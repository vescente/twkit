"""CSV under a workbook: will Tableau's text connector read the dates and numbers, or Null?"""
from __future__ import annotations

import csv
import io
import itertools
import os
import re
import zipfile

from . import safexml
from .extract import TYPE_SNIFF_SHARE, is_null_sentinel

SAMPLE_ROWS = 1024
EDGE_ROWS = SAMPLE_ROWS // 2
EXAMPLES = 3

LEADING = "leading empty"
MIXED = "mixed format"
TEXT_NUMBERS = "numbers as text"

_KIND = {"date": "date", "datetime": "date", "real": "number", "integer": "number"}
_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_DATE = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./]\d{1,2}[./]\d{2,4})"
                   r"([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?$")


def _is_number(v: str) -> bool:
    return bool(_NUMBER.match(v))


def _shape(v: str) -> str:
    """Value shape: any run of digits -> 9."""
    return re.sub(r"\d+", "9", v)


def _separator(raw: str) -> str:
    if raw in ("", None):
        return ","
    if raw.lower() in ("tab", "\\t"):
        return "\t"
    return raw[0]


def _attr_value(raw: str) -> str:
    """A capability attribute value comes quoted: `"\t"` -> `\t`."""
    return (raw or "").strip().strip('"')


def _relations(ds, conn_names: set, direct_conn):
    """CSV relations: by named connection (federated) or children of the textscan connection..."""
    found: dict = {}
    for rel in ds.iter("relation"):
        if rel.get("type") not in (None, "table"):
            continue
        owner = rel.get("connection")
        if owner in conn_names or (direct_conn is not None and rel.getparent() is direct_conn):
            key = rel.get("name") or rel.get("table") or ""
            if key not in found or (found[key].find("columns") is None
                                    and rel.find("columns") is not None):
                found[key] = rel
    return list(found.values())


def _declared(ds, rel) -> tuple[dict, dict]:
    """Declared column types of a file: CSV column name -> Tableau type."""
    types: dict = {}
    fmt: dict = {}
    cols = rel.find("columns")
    if cols is not None:
        fmt = {"sep": cols.get("separator"), "header": cols.get("header"),
               "charset": cols.get("character-set")}
        for c in cols.findall("column"):
            if c.get("name") and c.get("datatype"):
                types.setdefault(c.get("name"), c.get("datatype").lower())
    parent = f"[{rel.get('name')}]"
    for mr in ds.iter("metadata-record"):
        if (mr.findtext("parent-name") or "") != parent:
            continue
        if mr.get("class") == "capability":
            for a in mr.iter("attribute"):
                if a.get("name") == "field-delimiter" and not fmt.get("sep"):
                    fmt["sep"] = _attr_value(a.text)
                if a.get("name") == "header-row" and not fmt.get("header"):
                    fmt["header"] = "yes" if _attr_value(a.text) == "true" else "no"
        elif mr.get("class") == "column":
            name, lt = mr.findtext("remote-name"), (mr.findtext("local-type") or "").lower()
            if name and lt:
                types.setdefault(name, lt)
    remote_of: dict = {}
    for m in ds.iter("map"):
        val = m.get("value") or ""
        if val.startswith(parent + "."):
            remote_of[m.get("key")] = val[len(parent) + 1:].strip("[]")
    for c in ds.findall("column"):
        local, dt = c.get("name") or "", (c.get("datatype") or "").lower()
        remote = remote_of.get(local)
        if remote and dt:
            types.setdefault(remote, dt)
    return types, fmt


def csv_sources(path: str) -> list[dict]:
    """CSV sources of a workbook: file name, location, format and declared column types."""
    root = safexml.from_twbx(path)
    out = []
    seen = set()
    for ds in root.iter("datasource"):
        ex = ds.find("extract")
        from_extract = ex is not None and (ex.get("enabled") or "true") == "true"
        conns = []
        for c in ds.iter("connection"):
            if c.get("class") != "textscan":
                continue
            parent = c.getparent()
            if parent is not None and parent.tag == "named-connection":
                conns.append((c, {parent.get("name")}, None))
            else:
                conns.append((c, set(), c))
        for conn, names, direct_conn in conns:
            for rel in _relations(ds, names, direct_conn) or [None]:
                fn = conn.get("filename") or ""
                key = (ds.get("name"), fn, rel.get("name") if rel is not None else "")
                if not fn or key in seen:
                    continue
                seen.add(key)
                types, fmt = _declared(ds, rel) if rel is not None else ({}, {})
                out.append({"file": fn, "catalog": conn.get("directory") or "",
                            "source": ds.get("caption") or ds.get("name") or "",
                            "types": types, "format": fmt, "extract": from_extract})
    return out


def _read_csv(book: str, src: dict) -> tuple[str | None, str]:
    """CSV text: from the package, else from disk (connection directory, then next to the workbook)."""
    fn = src["file"]
    if book.lower().endswith(".twbx"):
        with zipfile.ZipFile(book) as z:
            hits = [n for n in z.namelist() if os.path.basename(n).lower() == fn.lower()]
            if hits:
                hits.sort(key=len)
                return _decode(z.read(hits[0]), src), f"package:{hits[0]}"
    for cand in (os.path.join(src["catalog"], fn) if src["catalog"] else "",
                 os.path.join(os.path.dirname(os.path.abspath(book)), fn)):
        if cand and os.path.isfile(cand):
            with open(cand, "rb") as f:
                return _decode(f.read(), src), cand
    return None, ""


def _decode(raw: bytes, src: dict) -> str:
    cs = (src["format"].get("charset") or "utf-8").lower()
    if cs in ("utf-8", "utf8"):
        cs = "utf-8-sig"
    try:
        return raw.decode(cs, errors="replace")
    except LookupError:
        return raw.decode("utf-8-sig", errors="replace")


class _Col:
    __slots__ = ("name", "kind", "origin", "first", "filled", "shapes", "bad", "bad_n",
                 "values")

    def __init__(self, name, kind, origin):
        self.name, self.kind, self.origin = name, kind, origin
        self.first = None
        self.filled = 0
        self.shapes: dict = {}
        self.bad: list = []
        self.bad_n = 0
        self.values: list = []


def scan_csv(text: str, types: dict | None = None, sep: str = ",",
             header: bool = True, file: str = "") -> dict:
    """Check CSV text against the declared types."""
    types = types or {}
    rd = csv.reader(io.StringIO(text), delimiter=sep)
    first_row = next(rd, None)
    if first_row is None:
        return {"row_count": 0, "column_count": 0, "findings": []}
    if header:
        names = [h.strip() for h in first_row]
        rows_iter = rd
    else:
        names = [f"F{i + 1}" for i in range(len(first_row))]
        rows_iter = itertools.chain([first_row], rd)

    cols: list[_Col | None] = []
    for n in names:
        dt = (types.get(n) or "").lower()
        if dt:
            kind = _KIND.get(dt)
            cols.append(_Col(n, kind, "book") if kind else None)
        else:
            cols.append(_Col(n, "?", "content"))

    nrows = 0
    for i, row in enumerate(rows_iter, start=1):
        nrows = i
        for j, c in enumerate(cols):
            if c is None:
                continue
            v = row[j].strip() if j < len(row) else ""
            if not v or is_null_sentinel(v):
                continue
            c.filled += 1
            if c.first is None:
                c.first = i
            if c.kind == "?":
                if len(c.values) < 5000:
                    c.values.append(v)
                c.shapes.setdefault(_shape(v), [0, v, i])[0] += 1
                if not _is_number(v):
                    c.bad_n += 1
                    if len(c.bad) < EXAMPLES:
                        c.bad.append((i, v))
            elif c.kind == "date":
                c.shapes.setdefault(_shape(v), [0, v, i])[0] += 1
            elif not _is_number(v):
                c.bad_n += 1
                if len(c.bad) < EXAMPLES:
                    c.bad.append((i, v))

    findings = []
    for c in cols:
        if c is None or not c.filled:
            continue
        if c.kind == "?":
            vals = c.values
            if sum(1 for v in vals if _DATE.match(v)) >= TYPE_SNIFF_SHARE * len(vals):
                c.kind = "date"
            elif sum(1 for v in vals if _is_number(v)) >= TYPE_SNIFF_SHARE * len(vals):
                c.kind = "number"
            else:
                continue
        findings += _judge(c, nrows, file)
    return {"row_count": nrows, "column_count": len(names), "findings": findings}


def _judge(c: _Col, nrows: int, file: str) -> list[dict]:
    out = []
    base = {"file": file, "column": c.name, "type": c.kind, "type_from": c.origin,
            "first_filled": c.first, "row_count": nrows}
    where = f"{file} · {c.name}" if file else c.name
    if c.first and c.first > EDGE_ROWS:
        hard = c.first > SAMPLE_ROWS
        out.append({**base, "class": LEADING, "level": "error" if hard else "warn",
                    "examples": [f"first filled value: data row {c.first} of {nrows}"],
                    "what": (f"{where}: first value in row {c.first}, but Tableau infers CSV types "
                            f"from the first {SAMPLE_ROWS} rows: "
                            + ("the whole column becomes Null" if hard else
                               "close to the sample edge, whether it is read is not checked")
                            + "; move rows with values to the top of the file")})
    if c.kind == "date" and len(c.shapes) > 1:
        ranked = sorted(c.shapes.values(), key=lambda s: (-s[0], s[2]))
        ex = [f"{s[1]!r} x{s[0]} (row {s[2]})" for s in ranked[:EXAMPLES]]
        out.append({**base, "class": MIXED, "level": "error", "format_count": len(ranked),
                    "examples": ex,
                    "what": (f"{where}: {len(ranked)} date formats in one column ("
                            + ", ".join(ex[:2]) + "); values in the other formats are read as Null; "
                            "use one format, e.g. YYYY-MM-DD 00:00:00")})
    if c.kind == "number" and c.bad_n:
        ex = [f"{v!r} (row {i})" for i, v in c.bad]
        out.append({**base, "class": TEXT_NUMBERS, "level": "error", "non_numbers": c.bad_n,
                    "examples": ex,
                    "what": (f"{where}: {c.bad_n} of {c.filled} values are not numbers ("
                            + ", ".join(ex[:2]) + "); in a numeric field Tableau reads them as Null")})
    return out


def check_workbook(path: str) -> dict:
    """Check every CSV source of a workbook."""
    srcs = csv_sources(path)
    if not srcs:
        return {"verdict": "no CSV sources", "file_count": 0, "findings": [],
                "not_checked": []}
    live = [s for s in srcs if not s["extract"]]
    if not live:
        return {"verdict": f"CSV {len(srcs)}, all read from the extract; "
                           f"the text connector is not involved",
                "file_count": len(srcs), "findings": [], "not_checked": []}
    findings, gaps, checked = [], [], 0
    for s in live:
        text, where = _read_csv(path, s)
        if text is None:
            gaps.append(f"CSV {s['file']} found neither in the package nor on disk; "
                        f"dates and numbers not checked")
            continue
        fmt = s["format"]
        header = (fmt.get("header") or "yes").lower() not in ("no", "false")
        try:
            res = scan_csv(text, s["types"], _separator(fmt.get("sep") or ""), header,
                           s["file"])
        except csv.Error as exc:
            gaps.append(f"CSV {s['file']} could not be parsed ({exc}); dates and numbers not checked")
            continue
        checked += 1
        for f in res["findings"]:
            f["where"] = where
        findings += res["findings"]
    hard = [f for f in findings if f["level"] == "error"]
    soft = [f for f in findings if f["level"] != "error"]
    verdict = (f"CSV checked {checked} of {len(live)}: "
               + (f"Tableau reads Null: {len(hard)}" if hard else "clean")
               + (f", at the sample edge: {len(soft)}" if soft else ""))
    return {"verdict": verdict, "file_count": len(live), "checked": checked,
            "findings": findings, "not_checked": gaps}

"""A workbook passport: what each page shows, what each sheet computes, by which formula."""
from __future__ import annotations

import os
import re

from . import safexml

_DERIV = {
    "none": "", "sum": "SUM", "cnt": "COUNT", "cntd": "COUNTD", "ctd": "COUNTD",
    "avg": "AVG",
    "min": "MIN", "max": "MAX", "med": "MEDIAN", "attr": "ATTR", "usr": "",
    "stdev": "STDEV", "var": "VAR",
    "tyr": "year", "tqr": "quarter", "tmn": "month", "twk": "week",
    "tdy": "day", "thr": "hour", "qyr": "year", "qqr": "quarter", "qmn": "month",
    "pcto": "% of total", "cum": "running total", "pctd": "% difference",
    "dif": "difference", "rank": "rank", "wsum": "moving sum",
}

_SERVICE = {
    "[:Measure Names]": "Measure Names",
    "[Multiple Values]": "Measure Values",
}


def _plain(token: str, caps: dict) -> str:
    """Shelf reference -> readable name: `[ds].[sum:GGR:qk]` -> `SUM(GGR)`."""
    token = (token or "").strip()
    if not token:
        return ""
    token = re.sub(r"^\[(?:federated|excel|textscan|mysql|hyper)\.[^\]]*\]\.", "", token)
    if token in _SERVICE:
        return _SERVICE[token]
    m = re.match(r"^\[([a-z]+):(.+?):([a-z]{2})(?::\d+)?\]$", token)
    if not m:
        name = token.strip("[]")
        return caps.get(name, name)
    deriv, field, _ = m.groups()
    name = caps.get(field, field)
    label = _DERIV.get(deriv, deriv)
    if not label:
        return name
    if label.isupper():
        return f"{label}({name})"
    return f"{name} ({label})"


_MEASURE_DERIV = {"sum", "cnt", "cntd", "ctd", "avg", "min", "max", "med",
                  "attr", "usr", "stdev", "var", "pcto", "cum", "wsum"}


def _shelf(text: str, caps: dict) -> list:
    """Shelf (`rows`/`cols`) -> `[(caption, role)]`; the role comes from the instance prefix."""
    if not text:
        return []
    out = []
    for t in re.findall(r"\[[^\]]+\]\.\[[^\]]+\]|\[[^\]]+\]", text):
        if t.startswith("[federated") and "].[" not in t:
            continue
        m = re.search(r"\[([a-z]+):", t)
        role = "measure" if m and m.group(1) in _MEASURE_DERIV else "dimension"
        label = _plain(t, caps)
        if label and (label, role) not in out:
            out.append((label, role))
    return out


def _readable_formula(formula: str, caps: dict) -> str:
    """`[Calculation_...]` and `[Parameters].[...]` in a formula -> captions."""
    def sub(m):
        name = m.group(1)
        return "[" + caps.get(name, name) + "]"
    txt = re.sub(r"\[([^\]\[]+)\]", sub, formula or "")
    txt = txt.replace("&#13;&#10;", "\n").replace("\r\n", "\n")
    return re.sub(r"[ \t]+", " ", txt).strip()


def _params(root) -> list:
    out = []
    for ds in root.findall("./datasources/datasource"):
        if ds.get("name") != "Parameters":
            continue
        for c in ds.findall("column"):
            members = [m.get("alias") or (m.get("value") or "").strip('"')
                       for m in c.findall(".//member")]
            out.append({
                "label": c.get("caption") or (c.get("name") or "").strip("[]"),
                "type": c.get("param-domain-type") or "",
                "value": (c.get("value") or "").strip('"'),
                "options": members,
            })
    return out


def _source(root) -> dict:
    for ds in root.findall("./datasources/datasource"):
        if ds.get("name") == "Parameters":
            continue
        conn = ds.find("connection")
        if conn is None:
            continue
        nc = conn.find(".//named-connection/connection")
        rel = conn.find("relation")
        kind = nc.get("class") if nc is not None else "?"
        info = {"class": kind,
                "server": (nc.get("server") if nc is not None else "") or "",
                "database": (nc.get("dbname") if nc is not None else "") or "",
                "extract": ds.find("extract") is not None}
        if rel is not None and rel.get("type") == "text" and (rel.text or "").strip():
            info["custom sql"] = True
            info["tables"] = sorted(set(re.findall(
                r"\b(?:FROM|JOIN)\s+([a-z_]+\.[a-zA-Z_][\w]*)", rel.text)))
        elif rel is not None:
            info["table"] = rel.get("table") or rel.get("name") or ""
        return info
    return {}


def _sheets(root, caps: dict) -> dict:
    out = {}
    for ws in root.iter("worksheet"):
        name = ws.get("name")
        if not name:
            continue
        marks = sorted({m.get("class") for m in ws.iter("mark") if m.get("class")})
        rows = _shelf((ws.findtext(".//rows") or ""), caps)
        cols = _shelf((ws.findtext(".//cols") or ""), caps)
        filters, topn = [], ""
        for f in ws.iter("filter"):
            fld = _plain(f.get("column") or "", caps)
            end = f.find(".//groupfilter[@function='end']")
            if end is not None:
                order = f.find(".//groupfilter[@function='order']")
                expr = (order if order is not None else end).get("expression") or ""
                topn = f"top {end.get('count')} by " + _plain(expr, caps)
            if fld and fld not in filters:
                filters.append(fld)
        title = ws.findtext("layout-options/title//run") or ""
        enc = {}
        for pane in ws.iter("pane"):
            for e in pane.findall("encodings/*"):
                if e.get("column"):
                    enc.setdefault(e.tag, _plain(e.get("column"), caps))
        out[name] = {"marks": marks, "rows": rows, "columns": cols,
                     "filters": filters, "top": topn, "label": title.strip(),
                     "encodings": enc, "pages": []}
    return out


def _pages(root, caps: dict, sheets: dict) -> list:
    pages = []
    order = [w.get("name") for w in root.iter("window") if w.get("class") == "dashboard"]
    dashes = {d.get("name"): d for d in root.iter("dashboard")}
    for nm in order + [n for n in dashes if n not in order]:
        dash = dashes.get(nm)
        if dash is None:
            continue
        on_page, ctrl = [], []
        for z in dash.iter("zone"):
            kind = z.get("type-v2") or ""
            if z.get("name") and kind not in ("filter", "paramctrl"):
                if z.get("name") in sheets and z.get("name") not in on_page:
                    on_page.append(z.get("name"))
            if kind == "paramctrl":
                ctrl.append(_param_caption(root, z.get("param") or ""))
            elif kind == "filter":
                ctrl.append(_plain(z.get("param") or "", caps))
        for s in on_page:
            sheets[s]["pages"].append(nm)
        pages.append({"page": nm, "sheets": on_page,
                      "controls": [c for c in dict.fromkeys(ctrl) if c]})
    return pages


def _param_caption(root, ref: str) -> str:
    name = ref.split("].[")[-1].strip("[]")
    for c in root.iter("column"):
        if (c.get("name") or "").strip("[]") == name and c.get("param-domain-type"):
            return c.get("caption") or name
    return name


def _calcs(root, caps: dict) -> list:
    seen, out = set(), []
    for ds in root.findall("./datasources/datasource"):
        if ds.get("name") == "Parameters":
            continue
        for c in ds.findall("column"):
            calc = c.find("calculation")
            if calc is None or not calc.get("formula"):
                continue
            name = (c.get("name") or "").strip("[]")
            if name in seen:
                continue
            seen.add(name)
            out.append({"field": c.get("caption") or name,
                        "formula": _readable_formula(calc.get("formula"), caps),
                        "format": c.get("default-format") or ""})
    return sorted(out, key=lambda x: (x["field"].startswith("_"), x["field"].lower()))


def passport(book_path: str) -> dict:
    """Parse a workbook into a structure: source, pages, sheets, formulas."""
    from .edit import field_index

    root = safexml.from_twbx(book_path) if book_path.lower().endswith(".twbx") \
        else safexml.from_file(book_path)
    caps = field_index(root)
    for c in root.iter("column"):
        if c.get("param-domain-type") and c.get("caption"):
            caps.setdefault((c.get("name") or "").strip("[]"), c.get("caption"))
    sheets = _sheets(root, caps)
    pages = _pages(root, caps, sheets)
    return {"book": os.path.splitext(os.path.basename(book_path))[0],
            "source": _source(root),
            "parameters": _params(root),
            "pages": pages,
            "sheets": sheets,
            "formulas": _calcs(root, caps)}


_TECH = ("_", "Calculation_")


def _human(label: str) -> str:
    """Hide helper names such as `_measure`."""
    return "selected metric" if label.startswith("_") else label


def _what(name: str, s: dict) -> str:
    """Sheet -> one readable line: what it shows."""
    forms = [f for f in s["marks"] if f != "Automatic"]
    shelf = s["rows"] + s["columns"]
    dims = list(dict.fromkeys(_human(l) for l, r in shelf
                              if r == "dimension" and l != "Measure Names"))
    meas = list(dict.fromkeys(_human(l) for l, r in shelf if r == "measure"))
    if any(l == "Measure Names" for l, _ in shelf):
        return "metric table by: " + (", ".join(dims) or "-")
    if forms and forms[0] in ("Bar", "Line", "Area") and dims:
        forma = {"Bar": "bars", "Line": "line", "Area": "area"}[forms[0]]
        return f"{forma} by '{dims[0]}'" + (": " + ", ".join(meas) if meas else "")
    if dims:
        return "breakdown by '" + "', '".join(dims) + "'" + \
               (": " + ", ".join(meas) if meas else "")
    if meas:
        return "number: " + ", ".join(meas)
    txt = s["encodings"].get("text")
    if txt and "Measure Values" not in txt:
        return "number: " + _human(txt)
    return ""


def _metrics(p: dict) -> list:
    """Report metrics: only what is visible on pages, no helper fields."""
    shown = set()
    for s in p["sheets"].values():
        if not s["pages"]:
            continue
        labels = [l for l, _ in s["rows"] + s["columns"]]
        for f in labels + list(s["encodings"].values()):
            shown.add(re.sub(r"^[A-Z]+\((.*)\)$", r"\1", f))
    out = []
    for c in p["formulas"]:
        nm, f = c["field"], c["formula"]
        if nm.startswith(_TECH):
            continue
        if "[Parameters]." in f and f.lstrip().upper().startswith(("CASE", "IF")):
            continue
        if shown and nm not in shown and not any(nm in x for x in shown):
            continue
        out.append(c)
    return out


def render(p: dict, *, description: str = "", shots: dict = None) -> str:
    """Workbook passport -> markdown description for colleagues."""
    shots = shots or {}
    L = [f"# {p['book']}", ""]
    L += [description.strip() or "> _Report description._", ""]

    L += ["## Report sections", ""]
    for i, pg in enumerate(p["pages"], 1):
        L += [f"### Section {i}: {pg['page']}", ""]
        if shots.get(pg["page"]):
            L += [f"![{pg['page']}]({shots[pg['page']]})", ""]
        for s in pg["sheets"]:
            what = _what(s, p["sheets"][s])
            if s.startswith(_TECH) or not what:
                continue
            L.append(f"- **{s}** — {what}")
        if pg["controls"]:
            L += ["- **Filters and switchers:** " + ", ".join(pg["controls"])]
        L.append("")

    metrics = _metrics(p)
    if metrics:
        L += ["## Metrics", "", "| metric | how it is computed |", "|---|---|"]
        for c in metrics:
            f = c["formula"].replace("|", "\\|").replace("\n", " ")
            L.append(f"| {c['field']} | `{f}` |")
        L.append("")

    switches = [pr for pr in p["parameters"] if pr["options"]]
    if switches:
        L += ["## Switchable options", "", "| switcher | values |", "|---|---|"]
        for pr in switches:
            L.append(f"| {pr['label']} | {', '.join(pr['options'])} |")
        L.append("")

    L += ["---", "", "_Data source: ClickHouse._", ""]
    return "\n".join(L)


def _src_line(src: dict) -> str:
    if not src:
        return "source not determined"
    if src.get("custom sql"):
        t = ", ".join(f"`{x}`" for x in src.get("tables", []))
        return "ClickHouse, query over tables " + (t or "")
    if src.get("table"):
        return f"table `{src['table']}`"
    return src.get("class", "source") + (f" `{src.get('server','')}`" if src.get("server") else "")


_KEEP = "## Report sections"


def keep_description(md_path: str) -> str:
    """Keep the human-written description paragraph from the previous version."""
    if not os.path.exists(md_path):
        return ""
    txt = open(md_path, encoding="utf-8").read()
    body = txt.split(_KEEP)[0]
    body = re.sub(r"^#[^\n]*\n", "", body).strip()
    return "" if body.startswith(">") else body


def build_all(workbooks_dir: str, out_dir: str = "") -> dict:
    """Build a document per workbook in a directory plus an index."""
    import glob

    out_dir = out_dir or os.path.join(workbooks_dir, "_ai", "reports")
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for book in sorted(glob.glob(os.path.join(workbooks_dir, "*.twbx"))):
        name = os.path.splitext(os.path.basename(book))[0]
        md_path = os.path.join(out_dir, name.replace(" ", "_") + ".md")
        p = passport(book)
        shots = {}
        for pg in p["pages"]:
            f = os.path.join(out_dir, "shots", name, pg["page"] + ".png")
            if os.path.exists(f):
                shots[pg["page"]] = os.path.relpath(f, out_dir)
        was = keep_description(md_path)
        text = render(p, description=was, shots=shots)
        open(md_path, "w", encoding="utf-8").write(text)
        gist = was.strip().split("\n")[0].strip() if was else ""
        made.append({"report": name, "section_count": len(p["pages"]),
                     "screenshot_count": len(shots), "about": gist.rstrip("."),
                     "document": os.path.basename(md_path)})

    idx = ["# Tableau reports", "",
           "What each report is and what it consists of.", "",
           "| report | about | sections |", "|---|---|---:|"]
    for m in made:
        idx.append(f"| [{m['report']}]({m['document']}) | {m['about']} | {m['section_count']} |")
    idx.append("")
    open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8").write("\n".join(idx))
    return {"catalog": out_dir, "report_count": len(made), "documents": made}

"""A linter for Tableau workbooks (`.twb` / `.twbx`)."""
from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from . import safexml

ERROR, WARN, INFO = "error", "warn", "info"


@dataclass
class Violation:
    rule: str
    severity: str
    message: str
    where: str = ""
    fix: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "severity": self.severity, "message": self.message,
                "where": self.where, "fix": self.fix}

    def __str__(self) -> str:
        head = f"[{self.severity.upper():5s}] {self.rule}  {self.message}"
        tail = f"\n         where: {self.where}" if self.where else ""
        tail += f"\n         fix: {self.fix}" if self.fix else ""
        return head + tail


@dataclass
class Book:
    """A parsed workbook: raw .twb text, the tree and (for .twbx) the archive members."""
    path: str
    raw: bytes
    root: Any
    is_twbx: bool
    archive: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.raw.decode("utf-8", "replace")


def load(path: str) -> Book:
    if path.lower().endswith(".twbx"):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            inner = [n for n in names if n.lower().endswith(".twb")]
            if not inner:
                raise ValueError(f"no .twb inside {path}")
            raw = z.read(inner[0])
        return Book(path, raw, safexml.from_bytes(raw), True, names)
    with open(path, "rb") as f:
        raw = f.read()
    return Book(path, raw, safexml.from_bytes(raw), False)


def r01_header(b: Book) -> list[Violation]:
    """Symptom: "This file is not in a recognizable format"."""
    out = []
    head = b.text[:400]
    decl = re.match(r"<\?xml[^>]*\?>", head)
    if not decl:
        return [Violation("R01", ERROR, "no XML declaration on the first line",
                          fix="safexml.serialize writes it; rebuild through Book.save")]
    if "encoding='utf-8'" not in decl.group(0) and 'encoding="utf-8"' not in decl.group(0):
        out.append(Violation("R01", ERROR,
                             f"encoding not lowercase: {decl.group(0)}",
                             fix="use encoding='utf-8' (as Tableau writes it)"))
    after = b.text[decl.end():]
    m = re.search(r"<workbook\b", after)
    if m and not re.match(r"\s*(<!--.*?-->\s*)*$", after[:m.start()], re.S):
        out.append(Violation("R01", ERROR, "something other than comments between the declaration and <workbook>",
                             where=repr(after[:m.start()][:120])))
    if m and after[:m.start()] and not after[:m.start()].rstrip().endswith("-->"):
        pass
    if m and "\n<workbook" not in after[:m.end()] and "\r\n<workbook" not in after[:m.end()]:
        out.append(Violation("R01", ERROR, "<workbook> does not start a line (glued to a comment)",
                             fix="add a newline before <workbook"))
    return out


_HASH = re.compile(r"^#.*#$", re.S)


def _params(b: Book):
    for col in b.root.iter("column"):
        if col.get("param-domain-type"):
            yield col


def r02_date_params(b: Book) -> list[Violation]:
    """Symptom: "Exception changing string '2026-07-01' to integer: Error parsing number"."""
    out = []
    for col in _params(b):
        if col.get("datatype") not in ("date", "datetime"):
            continue
        name = col.get("caption") or col.get("name")
        v = (col.get("value") or "").strip()
        if v and not _HASH.match(v):
            out.append(Violation("R02", ERROR, f"date parameter without #...#: value={v!r}",
                                 where=f"parameter {name}", fix="wrap in #...#"))
        rng = col.find("range")
        if rng is not None:
            for attr in ("min", "max"):
                rv = (rng.get(attr) or "").strip()
                if rv and not _HASH.match(rv):
                    out.append(Violation("R02", ERROR, f"range bound {attr}={rv!r} without #...#",
                                         where=f"parameter {name}", fix="wrap in #...#"))
        for m in col.iter("member"):
            mv = (m.get("value") or "").strip()
            if mv and not _HASH.match(mv):
                out.append(Violation("R02", ERROR, f"list member {mv!r} without #...#",
                                     where=f"parameter {name}", fix="wrap in #...#"))
        calc = col.find("calculation")
        if calc is not None:
            fv = (calc.get("formula") or "").strip()
            if fv and re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", fv):
                out.append(Violation("R02", ERROR, f"formula={fv!r} without #...#",
                                     where=f"parameter {name}", fix="wrap in #...#"))
    return out


def r03_string_params(b: Book) -> list[Violation]:
    """A string parameter must be type="nominal"."""
    out = []
    for col in _params(b):
        if col.get("datatype") == "string" and col.get("type") != "nominal":
            out.append(Violation("R03", ERROR,
                                 f'string parameter type="{col.get("type")}", "nominal" required',
                                 where=f"parameter {col.get('caption') or col.get('name')}"))
    return out


_AGG_PREFIX = ("sum", "avg", "stdev", "var", "median", "sum-agg")


def r04_boolean_calcs(b: Book) -> list[Violation]:
    """Symptom: a switcher filter computes wrong totals."""
    out = []
    bool_calcs: dict[str, str] = {}
    for col in b.root.iter("column"):
        if col.find("calculation") is None or col.get("datatype") != "boolean":
            continue
        raw_name = (col.get("name") or "").strip("[]")
        bool_calcs[raw_name] = col.get("caption") or raw_name
        if col.get("role") == "measure":
            out.append(Violation("R04", WARN,
                                 'boolean calculation with role="measure"',
                                 where=f"{bool_calcs[raw_name]}",
                                 fix='role="dimension" type="nominal"'))
    if not bool_calcs:
        return out
    txt = b.text
    for raw_name, cap in bool_calcs.items():
        for agg in _AGG_PREFIX:
            if f"[{agg}:{raw_name}:" in txt:
                out.append(Violation("R04", ERROR,
                                     f"an aggregated reference [{agg}:...] to a boolean calculation"
                                     f": {agg.upper()} over TRUE/FALSE gives wrong numbers",
                                     where=cap,
                                     fix='make the field role="dimension" type="nominal" and rebuild'))
                break
    return out


def r05_measure_names(b: Book) -> list[Violation]:
    """Symptom: "The field '[:Measure Names]' ... does not exist in your database"."""
    on_shelf = False
    for tag in ("rows", "cols"):
        for e in b.root.iter(tag):
            if e.text and ":Measure Names" in e.text:
                on_shelf = True
    if not on_shelf:
        return []
    declared = any((c.get("name") or "") == "[:Measure Names]" for c in b.root.iter("column"))
    if declared:
        return []
    return [Violation("R05", WARN, "[:Measure Names] on a shelf but the column is not declared",
                      fix="<column datatype='string' name='[:Measure Names]' "
                          "role='dimension' type='nominal'/> to the data source")]


def r06_mysql_connection(b: Book) -> list[Violation]:
    """Symptom: "Unable to connect to the MySQL server... Check that the server is running"."""
    out = []
    has_extract = any((e.get("enabled") or "true") == "true"
                      for e in b.root.iter("extract"))
    for c in b.root.iter("connection"):
        if c.get("class") != "mysql":
            continue
        where = f"connection server={c.get('server')}"
        if has_extract:
            out.append(Violation("R06", INFO,
                                 "connection without prompt/oauth, but the workbook runs on "
                                 "an extract; opening is not affected, a refresh will ask", where=where))
            continue
        if c.get("workgroup-auth-mode") != "prompt":
            out.append(Violation("R06", ERROR,
                                 f'workgroup-auth-mode="{c.get("workgroup-auth-mode")}" instead of "prompt"',
                                 where=where, fix="Tableau will not ask for a password: Unable to connect"))
        if c.get("server-oauth") is None:
            out.append(Violation("R06", ERROR, "no server-oauth attribute", where=where))
        if not (c.get("username") or "").strip():
            out.append(Violation("R06", ERROR, "empty username", where=where,
                                 fix="without a user name Tableau shows no password dialog"))
        if not (c.get("port") or "").strip():
            out.append(Violation("R06", WARN, "no port given (3306 expected)", where=where))
    return out


def r07_extract_packed(b: Book) -> list[Violation]:
    """Symptom: the workbook opens but has no data (empty sheets)."""
    out = []
    refs: list[str] = []
    for c in b.root.iter("connection"):
        if c.get("class") != "hyper":
            continue
        p = c.get("dbname") or c.get("filename") or ""
        if "tableau-temp" in p.replace("\\", "/"):
            continue
        if p:
            refs.append(p)
    if not refs:
        orphan = [n for n in b.archive if n.lower().endswith(".hyper")] if b.is_twbx else []
        return [Violation("R07", WARN,
                          f".hyper in the archive but no relation points to it: {n}",
                          where=n,
                          fix="extract.drop_packaged_extracts(): the file is unreachable "
                              "dead weight in the package")
                for n in orphan]
    if not b.is_twbx:
        return [Violation("R07", WARN, "the workbook references an extract but is saved as .twb",
                          where=", ".join(refs),
                          fix="deliver a .twbx, otherwise the extract does not travel with the file")]
    packed = [n for n in b.archive if n.lower().endswith(".hyper")]
    if not packed:
        near = any(os.path.exists(os.path.join(os.path.dirname(b.path),
                                               os.path.basename(r))) for r in refs)
        out.append(Violation("R07", ERROR if near else WARN,
                             ".hyper is not packed in the archive"
                             + (" (the file sits next to it: not packed)" if near
                                else " and not found next to it (template or broken reference)"),
                             where=", ".join(refs),
                             fix="put it into Data/Extracts/ inside the .twbx"))
        return out
    for n in packed:
        if not n.startswith("Data/"):
            out.append(Violation("R07", ERROR, f"extract outside Data/: {n}",
                                 fix="Data/Extracts/<file> inside the .twbx"))
    names = {os.path.basename(n) for n in packed}
    for r in refs:
        if os.path.basename(r) not in names:
            out.append(Violation("R07", ERROR,
                                 f"a relation references {os.path.basename(r)}, which is not in the archive",
                                 where=r))
    return out


def r08_extension(b: Book) -> list[Violation]:
    """Project rule: workbooks are saved as .twbx."""
    if b.path.lower().endswith(".twbx"):
        return []
    return [Violation("R08", WARN, f"extension {os.path.splitext(b.path)[1]}; the project rule is .twbx",
                      fix="style.out_path() forces .twbx")]


def r09_stale_columns(b: Book, db: str = "", table: str = "") -> list[Violation]:
    """Symptom: the workbook opens and shows NOTHING, with no error."""
    if not db or not table:
        return []
    try:
        from twkit import schema as SC
        live = {f["name"] for f in SC.fetch_schema(db, table, use_cache=False)}
    except Exception as exc:
        return [Violation("R09", INFO, f"live schema unavailable, check skipped: "
                                       f"{type(exc).__name__}")]
    used = set()
    for col in b.root.iter("column"):
        if col.find("calculation") is None and not col.get("param-domain-type"):
            used.add((col.get("name") or "").strip("[]"))
    stale = sorted(c for c in used
                   if c and c not in live and not c.startswith("Calculation_")
                   and not c.startswith(":") and c != "Multiple Values")
    return [Violation("R09", ERROR, f"reference to a missing column {c!r} in {db}.{table}",
                      fix="refresh the cached schema (table_schema refresh=True) and rebuild")
            for c in stale]


def r10_xsd(b: Book) -> list[Violation]:
    """XSD validation against the vendored Tableau schema: informational only."""
    try:
        from .xsd import validate
        res = validate(b.root)
    except Exception as exc:
        return [Violation("R10", INFO, f"XSD check unavailable: {type(exc).__name__}")]
    if not res["available"]:
        return [Violation("R10", INFO, "XSD schema not found, check skipped")]
    errs = list(res["errors"])
    if not errs:
        return []
    known = [e for e in errs if "_.fcp." in e]
    other = [e for e in errs if "_.fcp." not in e]
    fatal = [e for e in other if "Element 'column', attribute 'name'" in e and "pattern" in e]
    other = [e for e in other if e not in fatal]
    out = []
    for e in fatal[:5]:
        m = re.search(r"The value '([^']*)'", e)
        out.append(Violation("R10", ERROR,
                             f"column declared with an unbracketed name: {m.group(1) if m else e[:80]!r}; "
                             f"Tableau will not load the workbook (DOM loader)",
                             fix="write column names in brackets `[name]` with role/type; "
                                 "do not copy `<connection><columns>` into the declarations"))
    if known:
        out.append(Violation("R10", INFO,
                             f"{len(known)} XSD notes about feature control (_.fcp.*); "
                             f"Tableau's own workbooks have them too"))
    out += [Violation("R10", INFO, f"XSD: {e}",
                      fix="check the construct by eye; the schema does not know it") for e in other[:10]]
    if len(other) > 10:
        out.append(Violation("R10", INFO, f"...and {len(other) - 10} more XSD notes"))
    return out


def _worksheets(b: Book):
    """Only real sheets, from `<worksheets>`."""
    for holder in b.root.iter("worksheets"):
        for w in holder.findall("worksheet"):
            yield w


def _shelf_text(w, tag: str) -> str:
    return " ".join((e.text or "") for e in w.iter(tag)).strip()


def r11_sheet_without_breakdown(b: Book) -> list[Violation]:
    """A Measure Names sheet whose opposite shelf is empty: a single totals row."""
    out = []
    for w in _worksheets(b):
        rows, cols = _shelf_text(w, "rows"), _shelf_text(w, "cols")
        for a, other, side in ((rows, cols, "rows"), (cols, rows, "columns")):
            if ":Measure Names" in a and not other:
                out.append(Violation("R11", INFO,
                                     f"no breakdown: Measure Names on {side}, "
                                     f"the opposite shelf is empty: a single totals row",
                                     where=f"sheet {w.get('name')}",
                                     fix="if a breakdown was intended, it is missing"))
    return out


def r12_orphan_sheets(b: Book) -> list[Violation]:
    """A sheet that is on no dashboard."""
    dashboards = list(b.root.iter("dashboard"))
    if not dashboards:
        return []
    on_board = {z.get("name") for d in dashboards for z in d.iter("zone") if z.get("name")}
    orphans = sorted(w.get("name") for w in _worksheets(b)
                     if w.get("name") and w.get("name") not in on_board)
    if not orphans:
        return []
    return [Violation("R12", INFO,
                      f"sheets on no dashboard: {len(orphans)} ({', '.join(orphans[:5])}"
                      f"{'…' if len(orphans) > 5 else ''})",
                      fix="missing from worksheet_names, or a helper sheet")]


_SIMPSON = re.compile(r"\b(SUM|AVG)\s*\(\s*(\[[^\]]+\]|\w+)\s*/", re.I)


def r13_simpson(b: Book) -> list[Violation]:
    """A share computed as an average of ratios instead of from sums (Simpson's paradox)."""
    out = []
    for c in b.root.iter("column"):
        calc = c.find("calculation")
        if calc is None:
            continue
        f = calc.get("formula") or ""
        m = _SIMPSON.search(f)
        if m:
            out.append(Violation("R13", ERROR,
                                 f"share as an average of ratios ({m.group(1).upper()}(a/b)): "
                                 f"Simpson's paradox, the number is wrong",
                                 where=c.get("caption") or (c.get("name") or ""),
                                 fix="compute from sums: SUM([a]) / SUM([b])"))
    return out


def r41_param_ref_by_caption(b: Book) -> list[Violation]:
    """A parameter referenced by CAPTION instead of name."""
    names, caps = set(), {}
    for c in b.root.iter("column"):
        if c.get("param-domain-type"):
            nm = (c.get("name") or "").strip("[]")
            names.add(nm)
            if c.get("caption"):
                caps[c.get("caption")] = nm
    bad = sorted({x for x in re.findall(r"\[Parameters\]\.\[([^\]]+)\]", b.text)
                  if x not in names and x in caps})
    if not bad:
        return []
    return [Violation("R41", ERROR,
                      f"a formula references a parameter by caption instead of name: "
                      f"{', '.join(bad[:6])}",
                      fix="write [Parameters].[<name>] (edit._param_ref) and rebuild the sheet")]


def r14_unused_params(b: Book) -> list[Violation]:
    """A parameter that no formula references: a dead control."""
    txt = b.text
    dead = []
    for c in b.root.iter("column"):
        if not c.get("param-domain-type"):
            continue
        internal = (c.get("name") or "").strip("[]")
        if not internal:
            continue
        if f"[Parameters].[{internal}]" not in txt:
            dead.append(c.get("caption") or internal)
    dead = sorted(set(dead))
    if not dead:
        return []
    return [Violation("R14", WARN,
                      f"parameters used by no formula: {', '.join(dead[:8])}"
                      f"{'…' if len(dead) > 8 else ''}",
                      fix="the control has no effect: remove it or wire it in")]


def r15_orphan_filters(b: Book) -> list[Violation]:
    """A filter on a field the sheet does not have: filters silently or not at all."""
    SERVICE = ("[Action ", "[Tooltip ", "[Highlight ", "[Exclusions ", "[Set ")
    shared_deps: set[str] = set()
    for sv in b.root.iter("shared-view"):
        shared_deps |= {(c.get("name") or "") for c in sv.iter("column")}
        shared_deps |= {(ci.get("name") or "") for ci in sv.iter("column-instance")}

    out = []
    for w in _worksheets(b):
        deps = {(c.get("name") or "") for c in w.iter("column")}
        deps |= {(ci.get("name") or "") for ci in w.iter("column-instance")}
        deps |= shared_deps
        for fl in w.iter("filter"):
            col = fl.get("column") or ""
            m = re.search(r"\]\.(\[.+\])$", col)
            if not m:
                continue
            field = m.group(1)
            if field.startswith(SERVICE) or ":Measure Names" in field:
                continue
            if field not in deps:
                out.append(Violation("R15", ERROR,
                                     f"filter on {field}, which is not among the sheet fields",
                                     where=f"sheet {w.get('name')}",
                                     fix="the field is not declared in datasource-dependencies; "
                                         "the filter will not work"))
        for ss in w.iter("shelf-sort-v2"):
            for attr in ("dimension-to-sort", "measure-to-sort-by"):
                m = re.search(r"\]\.(\[.+\])$", ss.get(attr) or "")
                if m and m.group(1) not in deps and not m.group(1).startswith(SERVICE):
                    out.append(Violation("R15", ERROR,
                                         f"sort ({attr}) by {m.group(1)}, which is not "
                                         f"among the sheet fields",
                                         where=f"sheet {w.get('name')}",
                                         fix="Tableau opens the workbook with a warning dialog; "
                                             "sort by a field on the sheet"))
    return out


def r16_zone_geometry(b: Book) -> list[Violation]:
    """A zone extends beyond the canvas."""
    out = []
    LIMIT = 100000
    for d in b.root.iter("dashboard"):
        for z in d.iter("zone"):
            if not z.get("w"):
                continue
            x, y = int(z.get("x") or 0), int(z.get("y") or 0)
            w, h = int(z.get("w") or 0), int(z.get("h") or 0)
            if x < 0 or y < 0 or x + w > LIMIT or y + h > LIMIT:
                label = z.get("name") or z.get("type-v2") or z.get("param") or z.get("id") or "?"
                out.append(Violation("R16", WARN,
                                     f"zone beyond the canvas: {label} ({x},{y},{w}x{h})",
                                     where=f"dashboard {d.get('name')}",
                                     fix="part of the content will not be visible"))
    return out


def r17_automatic_marks(b: Book) -> list[Violation]:
    """`mark class="Automatic"`: Tableau chose the form, not us."""
    auto = 0
    total = 0
    for w in _worksheets(b):
        for m in w.iter("mark"):
            total += 1
            if m.get("class") == "Automatic":
                auto += 1
    if not auto:
        return []
    return [Violation("R17", WARN,
                      f"Automatic marks: {auto} of {total}; Tableau chose the form",
                      fix="set mark_type deliberately; task-to-form table in docs/DESIGN_KB.md section 3")]


def r18_no_comparison_base(b: Book) -> list[Violation]:
    """No baseline in the workbook: no reference lines and no deltas."""
    reflines = len(list(b.root.iter("reference-line")))
    deltas = b.text.count("↑") + b.text.count("▲")
    if reflines or deltas:
        return []
    return [Violation("R18", INFO,
                      "no reference lines and no arrow deltas: "
                      "numbers have no baseline",
                      fix="blocks delta_vs_prior / add_shared_axis_line")]


def r19_dual_axis(b: Book) -> list[Violation]:
    """Two measures of different scale on one axis."""
    n = len(re.findall(r"<axis-dual\b|\bdual-axis\b", b.text))
    if not n:
        return []
    return [Violation("R19", ERROR, f"dual axes: {n}",
                      fix="different scales: two charts sharing the X axis")]


def r20_metric_canon(b: Book) -> list[Violation]:
    """Metric formulas against the canon (`twkit/canon.py`)."""
    try:
        from . import canon as CANON
        findings = CANON.check_workbook(b.path)
    except Exception as exc:
        return [Violation("R20", INFO, f"canon unavailable: {type(exc).__name__}")]
    sev = {"error": ERROR, "warn": WARN}
    return [Violation("R20", sev.get(f.severity, WARN),
                      f"{f.metric}: {f.message}", fix=f"canon: {f.canon}")
            for f in findings]


def r21_stale_thumbnail(b: Book) -> list[Violation]:
    """The workbook carries previews but its data changed: the file shows a foreign picture."""
    thumbs = b.root.findall(".//thumbnails/thumbnail")
    if not thumbs:
        return []
    from .book import MARK
    generated = MARK in b.text
    if not generated:
        return []
    names = ", ".join((t.get("name") or "?") for t in thumbs[:4])
    return [Violation("R21", WARN,
                      f"our built workbook carries {len(thumbs)} previews ({names}); "
                      f"probably inherited from the source workbook",
                      fix="preview.strip_thumbnails(root) when porting; our own previews "
                          "appear after saving from Tableau")]


def r22_zone_too_narrow(b: Book) -> list[Violation]:
    """A sheet zone narrower than its first column: it can show nothing."""
    from . import layoutmodel as LM

    caps = {(c.get("name") or "").strip("[]"): c.get("caption")
            for c in b.root.iter("column") if c.get("caption")}
    wsn = b.root.find("worksheets")
    sheets = {w.get("name"): w for w in (list(wsn) if wsn is not None else [])}

    def label(ref: str) -> str:
        parts = re.findall(r"\[([^\]]+)\]", ref)
        if not parts:
            return ref
        last = parts[-1]
        bits = last.split(":")
        core = bits[1] if len(bits) >= 3 else last
        return (caps.get(core) or caps.get(last) or core).replace("_", " ")

    out = []
    for dash in b.root.iter("dashboard"):
        model = LM.build(dash)
        for zone in model.sheets():
            ws = sheets.get(zone.name)
            if ws is None:
                continue
            cols = [label(c) for c in LM.shelf_fields(ws, "cols") if ":Measure Names" not in c]
            if not cols:
                continue
            pt, family, _ = LM.sheet_font(ws)
            need = LM.text_width(cols[0], pt, family)
            if need and zone.w * 2 < need:
                out.append(Violation(
                    "R22", WARN,
                    f"sheet '{zone.name}' on '{model.name}' is collapsed: zone {zone.w:.0f} px, "
                    f"first column '{cols[0]}' needs {need:.0f} px",
                    where=model.name,
                    fix="widen the zone, or remove the sheet if it is a helper"))
    return out


def r23_duplicate_zone_id(b: Book) -> list[Violation]:
    """Symptom: "Unable to complete action"."""
    out = []
    dashes = b.root.find("dashboards")
    if dashes is None:
        return []
    for dash in dashes.findall("dashboard"):
        for layout, holder in (("default", dash.find("zones")),
                               ("phone", dash.find("devicelayouts"))):
            if holder is None:
                continue
            seen: dict = {}
            for z in holder.iter("zone"):
                zid = z.get("id")
                if not zid:
                    continue
                seen[zid] = seen.get(zid, 0) + 1
            dupes = sorted(i for i, c in seen.items() if c > 1)
            if dupes:
                out.append(Violation(
                    "R23", INFO,
                    f"duplicate zone ids in the {layout} layout: {', '.join(dupes)}",
                    where=f"dashboard {dash.get('name')}",
                    fix="give a copied zone a new id (max over the WHOLE "
                        "dashboard + 1), otherwise Internal Error 2805CF18"))
    return out


def r28_column_drift(b: Book) -> list[Violation]:
    """Symptom: the left control column jumps between pages."""
    from . import edit as ED

    roles: dict = {}
    xs, ws = [], []
    for dash in b.root.iter("dashboard"):
        for z in ED.left_column(dash):
            r = ED._rect(z)
            xs.append(r[0])
            ws.append(r[2])
            roles.setdefault(ED._role(z), []).append((dash.get("name"), r))
    out = []
    if len(xs) > 1:
        for key, col in (("left edge", xs), ("width", ws)):
            d = max(col) - min(col)
            if d > 400:
                out.append(Violation(
                    "R28", INFO,
                    f"{key} of the left column drifts between pages: spread {d} "
                    f"({min(col)}…{max(col)})",
                    fix="edit.align_left_column: align to the minimum width"))
    for role, items in sorted(roles.items()):
        if len(items) < 2:
            continue
        for i, key in ((1, "top"), (3, "height")):
            col = [r[i] for _n, r in items]
            d = max(col) - min(col)
            if d > 400:
                worst = max(items, key=lambda it: it[1][i])[0]
                out.append(Violation(
                    "R28", INFO,
                    f"{key} of column '{role}' drifts: spread {d} over {len(items)} pages",
                    where=f"worst: '{worst}'",
                    fix="edit.align_left_column: align within the container role"))
    return out


def r_format_attr(b) -> list:
    """`<format attr=...>` with a name outside the Tableau schema."""
    from twkit.edit import FORMAT_ATTRS, format_attr_hint
    bad = sorted({f.get("attr") for f in b.root.iter("format")
                  if f.get("attr") and f.get("attr") not in FORMAT_ATTRS})
    if not bad:
        return []
    named = [f"{a} → {format_attr_hint(a) or '?'}" for a in bad]
    fixable = [a for a in bad if format_attr_hint(a)]
    return [Violation("R31", ERROR,
                      f"format attribute outside the schema: {', '.join(named)}; Tableau will NOT open the workbook",
                      fix=("edit.fix_format_attrs(root) renames the known ones"
                           if fixable else "edit.strip_invalid_formats(root)"))]


_ORDERED_TAGS = {
    "filter", "slices", "aggregation", "calcs-on-densified-marks",
    "shelf-sorts", "perspective", "datasource-dependencies", "datasources",
    "default-sorts", "field-sort-info", "style", "layout", "semantic-values",
    "date-options", "column", "column-instance", "extract", "aliases",
    "customized-label", "customized-tooltip", "encodings", "mark", "panes",
    "rows", "cols", "zones", "zone",
}


def r29_element_order(b: Book) -> list[Violation]:
    """Symptom: Tableau refuses to open the workbook ("Errors occurred while trying to load the workbook")."""
    import re as _re
    out = []
    for v in r10_xsd(b):
        if "SCHEMAV_ELEMENT_CONTENT" not in v.message:
            continue
        m = _re.search(r"Element '([^']+)': This element is not expected", v.message)
        if not m or m.group(1) not in _ORDERED_TAGS:
            continue
        out.append(Violation("R29", ERROR,
                             f"<{m.group(1)}> is out of order; Tableau will NOT open the workbook",
                             where=v.message.split("ERROR")[0].strip(": "),
                             fix="edit.insert_in_order(parent, node, _VIEW_ORDER/_DS_ORDER)"))
    return out[:5]


_TABLE_FUNCS = ("RUNNING_SUM", "RUNNING_AVG", "RUNNING_MIN", "RUNNING_MAX",
                "RUNNING_COUNT", "WINDOW_SUM", "WINDOW_AVG", "WINDOW_MIN",
                "WINDOW_MAX", "WINDOW_COUNT", "WINDOW_MEDIAN", "WINDOW_STDEV",
                "WINDOW_VAR", "WINDOW_CORR", "WINDOW_COVAR", "WINDOW_PERCENTILE",
                "LOOKUP", "TOTAL", "RANK", "RANK_DENSE", "RANK_UNIQUE",
                "RANK_MODIFIED", "RANK_PERCENTILE", "INDEX", "SIZE", "FIRST",
                "LAST", "PREVIOUS_VALUE")


def _uses_table_func(formula: str) -> bool:
    """Strip field references first: field names can look like function names."""
    from .edit import bare_formula
    up = bare_formula(formula).upper()
    return any(re.search(rf"\b{f}\s*\(", up) for f in _TABLE_FUNCS)


def r30_table_calc_direction(b: Book) -> list[Violation]:
    """Symptom: the sheet draws, the number is WRONG, and nobody notices."""
    out = []
    for col in b.root.iter("column"):
        calc = col.find("calculation")
        if calc is None or calc.get("class") != "tableau":
            continue
        if not _uses_table_func(calc.get("formula")):
            continue
        if calc.find("table-calc") is not None:
            continue
        name = col.get("caption") or (col.get("name") or "").strip("[]")
        out.append(Violation("R30", ERROR,
                             f"table calculation {name!r} without a direction; "
                             f"Tableau computes across the table",
                             where=(calc.get("formula") or "")[:110],
                             fix="edit.table_calc(caption, kind=…, field=…, direction='down')"))
    return out[:5]


def r31_table_calc_drift(b: Book) -> list[Violation]:
    """Symptom: the field was fixed but a sheet still computes the old way."""
    src: dict = {}
    for ds in b.root.findall("./datasources/datasource"):
        for col in ds.findall("column"):
            calc = col.find("calculation")
            if calc is None:
                continue
            tc = calc.find("table-calc")
            src[(ds.get("name"), col.get("name"))] = (
                None if tc is None else (tc.get("ordering-type"), tc.get("ordering-field")))
    out, seen = [], {}
    for ws in b.root.iter("worksheet"):
        for dep in ws.iter("datasource-dependencies"):
            for col in dep.findall("column"):
                key = (dep.get("datasource"), col.get("name"))
                if key not in src:
                    continue
                calc = col.find("calculation")
                tc = calc.find("table-calc") if calc is not None else None
                mine = None if tc is None else (tc.get("ordering-type"), tc.get("ordering-field"))
                name = col.get("caption") or (col.get("name") or "").strip("[]")
                if (src[key] is None) != (mine is None):
                    where = "in the source, not in the sheet" if mine is None else \
                            "in the sheet, not in the source"
                    out.append(Violation("R31", ERROR,
                                         f"the direction of {name!r} is not everywhere "
                                         f"({where}); sheet {ws.get('name')!r} computes differently",
                                         fix="edit.table_calc(...) writes every declaration"))
                elif mine is not None:
                    seen.setdefault((key, name), set()).add(mine)
    for (key, name), variants in seen.items():
        if len(variants) > 1:
            out.append(Violation("R31", WARN,
                                 f"field {name!r} computes differently on different sheets: "
                                 f"{sorted(map(str, variants))}; Tableau allows it, "
                                 f"working workbooks do not do it",
                                 fix="compare Compute Using across sheets"))
    return out[:5]


_MANIFEST_GATES = {
    ("filter", "period-type-v2"): "ISO8601PeriodTypes",
}
_MANIFEST_ELEMENT_GATES = {
    "shelf-sorts": "IntuitiveSorting",
    "computed-sort": "SortTagCleanup",
    "manual-sort": "SortTagCleanup",
}


def r32_manifest_gate(b: Book) -> list[Violation]:
    """Symptom: Tableau refuses to open the workbook ("attribute ... is not declared")."""
    man = b.root.find(".//document-format-change-manifest")
    have = {c.tag for c in man} if man is not None else set()
    out = []
    for (tag, attr), entry in _MANIFEST_GATES.items():
        if not any(e.get(attr) is not None for e in b.root.iter(tag)):
            continue
        if entry in have:
            continue
        out.append(Violation("R32", ERROR,
                             f"<{tag} {attr}=...> is present but <{entry}/> is missing from the "
                             f"format manifest; Tableau will NOT open the workbook",
                             where="document-format-change-manifest",
                             fix=f"edit.ensure_manifest(root, '{entry}')"))
    for tag, entry in _MANIFEST_ELEMENT_GATES.items():
        if entry in have:
            continue
        sheets = sorted({ws.get("name") or "" for ws in b.root.iter("worksheet")
                         for e in ws.iter(tag) if e.getparent() is not None
                         and e.getparent().tag == "view"})
        if sheets:
            out.append(Violation("R32", ERROR,
                                 f"<{tag}> on sheets {', '.join(sheets[:5])} but <{entry}/> is missing "
                                 f"from the format manifest; Tableau will NOT open the "
                                 f"workbook (\"no declaration found for element '{tag}'\")",
                                 where="document-format-change-manifest",
                                 fix=f"edit.ensure_manifest(root, '{entry}') — "
                                     f"sort_by_measure/order_measures add it"))
    for ws in b.root.iter("worksheet"):
        for e in ws.iter("shelf-sort-v2"):
            m = e.get("measure-to-sort-by") or ""
            if m.endswith(":nk]"):
                out.append(Violation("R32", WARN,
                                     f"sheet '{ws.get('name')}': a sort by measure references "
                                     f"dimension {m.split('].[')[-1]}; the order will not "
                                     f"follow the measure",
                                     where=ws.get("name") or "",
                                     fix="edit.sort_by_measure(..., by=<measure>); the measure is "
                                         "looked up with role='measure'"))
    return out


def r40_ds_style_encoding(b: Book) -> list[Violation]:
    """A source-style color map that Tableau will not apply."""
    out = []
    for ds in b.root.iter("datasource"):
        st = ds.find("style")
        if st is None:
            continue
        declared = {ci.get("name") for ci in ds.findall("column-instance")}
        for e in st.iter("encoding"):
            fld = e.get("field") or ""
            if fld.startswith("[") and "].[" in fld:
                out.append(Violation("R40", ERROR,
                                     f"color map for {fld[:60]} is written with a data source "
                                     f"prefix; Tableau will not apply it",
                                     where=ds.get("name") or "",
                                     fix="in the source style the field is `[none:X:nk]` without `[ds].`"))
            elif (e.get("type") == "palette" and re.match(r"^\[\w+:.+:\w+\]$", fld)
                  and fld not in declared):
                out.append(Violation("R40", WARN,
                                     f"color map for {fld[:60]}: the instance is not declared in "
                                     f"the source; Tableau uses the default palette",
                                     where=ds.get("name") or "",
                                     fix="add a `<column-instance>` with this name to the source"))
    return out


def r33_opens_on_worksheet(b: Book) -> list[Violation]:
    """Symptom: the workbook opens on a sheet instead of a dashboard."""
    wins = b.root.find("windows")
    if wins is None:
        return []
    ws = list(wins.findall("window"))
    dash = [w for w in ws if w.get("class") == "dashboard"]
    if not dash or not ws:
        return []
    if ws[0].get("class") == "dashboard":
        return []
    if any(w.get("maximized") == "true" for w in dash):
        return []
    sheets = [w for w in ws if w.get("class") == "worksheet"]
    return [Violation("R33", WARN,
                      f"the workbook opens on sheet {ws[0].get('name')!r}, not on a "
                      f"dashboard ({len(dash)}); sheet tabs {len(sheets)}",
                      where="windows",
                      fix="edit.finish_windows(root): dashboard first and maximized, "
                          "dashboard sheets hidden")]


def _formula_is_aggregate(formula: str) -> bool:
    """An aggregate at the top level of a formula."""
    from .fields import is_aggregate
    return is_aggregate(formula)


def r34_double_aggregation(b: Book) -> list[Violation]:
    """Aggregate over an aggregate: `[sum:X:qk]` where formula `X` already has SUM."""
    calc: dict[str, str] = {}
    for col in b.root.iter("column"):
        c = col.find("calculation")
        if c is None:
            continue
        name = (col.get("name") or "").strip("[]")
        if name:
            calc[name] = c.get("formula") or ""

    out: list[Violation] = []
    seen: set = set()
    for ws in b.root.iter("worksheet"):
        for el in list(ws.iter("encodings")) + list(ws.iter("rows")) + list(ws.iter("cols")):
            refs = [el.get("column")] if el.get("column") else []
            for kid in el:
                if kid.get("column"):
                    refs.append(kid.get("column"))
            if el.tag in ("rows", "cols") and el.text:
                refs.append(el.text)
            for ref in refs:
                m = re.search(r"\[(sum|avg|cnt|ctd|min|max|med|total):([^:\]]+):", str(ref))
                if not m:
                    continue
                field = m.group(2)
                formula = calc.get(field)
                if not formula or not _formula_is_aggregate(formula):
                    continue
                key = (ws.get("name"), field)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Violation(
                    "R34", ERROR,
                    f"sheet {ws.get('name')!r}: {m.group(1).upper()} over field "
                    f"{field!r}, which is already an aggregate; Tableau will not draw the sheet",
                    where=f"worksheet/{ws.get('name')}",
                    fix="reference an aggregated calculation as [usr:...] "
                        "(derivation=\"User\")"))
    return out


_DEFAULT_NAME = re.compile(
    r"^(Calculation_\d+|\u0420\u0430\u0441\u0447\u0435\u0442\s*\d+|Sheet\s*\d+|\u041b\u0438\u0441\u0442\s*\d+|"
    r"\u0414\u0430\u0448\u0431\u043e\u0440\u0434\s*\d+|Dashboard\s*\d+)$")
_COPY_TRACE = re.compile(r"\(copy\)|\(\u043a\u043e\u043f\u0438\u044f\)|\s\(\d+\)$|_\d{13,}$")


def r35_naming_and_folders(b: Book) -> list[Violation]:
    """Naming and data pane folders (docs/NAMING_RULES.md)."""
    out: list[Violation] = []

    foldered: set[str] = set()
    folder_names: set[str] = set()
    for holder in b.root.iter("folders-common"):
        for folder in holder.findall("folder"):
            folder_names.add(folder.get("name") or "")
            for item in folder.findall("folder-item"):
                foldered.add((item.get("name") or "").strip("[]"))

    calcs, fields_total, loose = [], 0, []
    for ds in b.root.iter("datasource"):
        if ds.get("name") == "Parameters":
            continue
        for col in ds.findall("column"):
            name = (col.get("name") or "").strip("[]")
            if not name:
                continue
            fields_total += 1
            if col.find("calculation") is None:
                continue
            if col.get("param-domain-type"):
                continue
            calcs.append(name)
            if name not in foldered and not name.startswith("_"):
                loose.append(col.get("caption") or name)

    if loose:
        out.append(Violation(
            "R35", WARN,
            f"calculated fields outside the Calcs folder: {len(loose)} "
            f"({', '.join(sorted(set(loose))[:5])}{'…' if len(set(loose)) > 5 else ''})",
            fix="B.calc_folders(editor) as the last build step (docs/NAMING_RULES.md section 1)"))

    if fields_total >= 10 and not folder_names:
        out.append(Violation(
            "R35", WARN, f"data pane without folders with {fields_total} fields",
            fix="B.auto_folders(editor, fields) + B.calc_folders(editor)"))

    bad_names = sorted({n for n in calcs if _DEFAULT_NAME.match(n)})
    if bad_names:
        out.append(Violation(
            "R35", WARN,
            f"Tableau default field names: {len(bad_names)} "
            f"({', '.join(bad_names[:4])}{'…' if len(bad_names) > 4 else ''})",
            fix="give a business name: Title Case, no Calculation_... (docs/NAMING_RULES.md section 2)"))

    copied = sorted({n for n in calcs
                     if _COPY_TRACE.search(n) and not _DEFAULT_NAME.match(n)})
    if copied:
        out.append(Violation(
            "R35", WARN,
            f"copy traces in field names: {len(copied)} "
            f"({', '.join(copied[:4])}{'…' if len(copied) > 4 else ''})",
            fix="rename; for period variants use P1/P2/Δ suffixes, not (copy)"))

    sheet_copies = sorted({(w.get("name") or "") for w in _worksheets(b)
                           if _COPY_TRACE.search(w.get("name") or "")
                           or _DEFAULT_NAME.match(w.get("name") or "")})
    if sheet_copies:
        out.append(Violation(
            "R35", WARN,
            f"sheets with a default name or a copy trace: {len(sheet_copies)} "
            f"({', '.join(sheet_copies[:4])}{'…' if len(sheet_copies) > 4 else ''})",
            fix="name a sheet after what it shows; a period variant is a parameter, "
                "not a sheet copy (docs/NAMING_RULES.md section 3)"))
    return out


def r36_device_layout_drift(b: Book) -> list[Violation]:
    """A phone layout references a sheet no longer on the page."""
    out: list[Violation] = []
    for dash in b.root.iter("dashboard"):
        holder = dash.find("devicelayouts")
        zones = dash.find("zones")
        if holder is None or zones is None:
            continue
        base = {z.get("name") for z in zones.iter("zone") if z.get("name")}
        for layout in holder.findall("devicelayout"):
            got = {z.get("name") for z in layout.iter("zone") if z.get("name")}
            dangling = sorted(got - base)
            if not dangling:
                continue
            manual = (layout.get("auto-generated") or "").lower() == "false"
            out.append(Violation(
                "R36", ERROR if manual else WARN,
                f"layout '{layout.get('name')}' of dashboard '{dash.get('name')}' "
                f"references sheets not on the page: {', '.join(dangling[:3])}"
                f"{'…' if len(dangling) > 3 else ''}",
                where=f"dashboard {dash.get('name')}",
                fix=("the layout is no longer auto-generated; Tableau does NOT fix it, edit it"
                     if manual else
                     "open the workbook in Desktop once before publishing; "
                     "Tableau rebuilds the layout")))
    return out


def r37_gradient_on_plain_measure(b: Book) -> list[Violation]:
    """A color gradient on a measure that is not a delta: the color means nothing."""
    def bare_name(enc) -> str:
        f = (enc.get("field") or "").split("].")[-1].strip("[]")
        if f.startswith("usr:") and f.endswith(":qk"):
            f = f[4:-3].replace("\\%", "%")
        return f

    out: list[Violation] = []
    for ws in b.root.iter("worksheet"):
        name = ws.get("name") or ""
        encs = [e for sr in ws.findall("table/style/style-rule")
                if sr.get("element") == "mark"
                for e in sr.findall("encoding") if e.get("attr") == "color"]
        if not any(bare_name(e).endswith(" Δ") for e in encs):
            continue
        for enc in encs:
            bare = bare_name(enc)
            if (bare.endswith(" Δ") or bare == "Multiple Values"
                    or bare.startswith("Calculation_")):
                continue
            pal = enc.find("color-palette")
            tones = [c.text for c in pal.findall("color")] if pal is not None else []
            mono = bool(tones) and (len(set(tones)) == 1
                                    or (enc.get("num-steps") == "2" and tones[0] == tones[-1]))
            if mono or enc.get("num-steps") == "1":
                continue
            if enc.get("palette") or len(set(tones)) > 1:
                out.append(Violation(
                    "R37", WARN,
                    f"color gradient on measure '{bare}', which is not a delta; "
                    f"the color encodes nothing",
                    where=f"sheet {name}",
                    fix=("give the measure a single-tone palette: "
                         "type='custom-interpolated', a color-palette with an empty name "
                         "and one tone; keep color for deltas only")))
    return out


def r38_label_color_overridden(b) -> list:
    """A color encoding on a text mark overrides the `fontcolor` of label lines."""
    out = []
    for ws in b.root.iter("worksheet"):
        for pane in ws.iter("pane"):
            mark = pane.find("mark")
            if mark is None or mark.get("class") != "Text":
                continue
            enc = pane.find("encodings")
            if enc is None or enc.find("color") is None:
                continue
            label = pane.find("customized-label")
            if label is None:
                continue
            tinted = [r for r in label.iter("run") if r.get("fontcolor")]
            if not tinted:
                continue
            out.append(Violation(
                "R38", WARN,
                f"label line colors will not apply: the text mark has a color "
                f"encoding that colors the whole label ({len(tinted)} lines with fontcolor)",
                where=f"sheet {ws.get('name')}",
                fix="remove <color> from encodings and color by line, "
                    "or drop fontcolor and accept a single-color card"))
    return out


def r42_caption_collision(b) -> list:
    """Two different fields of one data source share a caption."""
    out = []
    for ds in b.root.iter("datasource"):
        parent = ds.getparent()
        if ds.get("name") == "Parameters" or parent is None or parent.tag != "datasources":
            continue
        by: dict = {}
        for c in ds.findall("column"):
            if c.get("caption") and c.get("name") and \
                    not c.get("name").startswith("[__tableau_internal_object_id__]"):
                by.setdefault(c.get("caption"), set()).add(c.get("name"))
        for cap, names in sorted(by.items()):
            if len(names) > 1:
                out.append(Violation(
                    "R42", ERROR,
                    f"caption '{cap}' names {len(names)} different fields: a reference by caption "
                    f"binds to one of them, often the wrong one",
                    where=f"data source {ds.get('caption') or ds.get('name')}",
                    fix="give each field its own caption (an invisible suffix is enough)"))
    return out


RULES = [r01_header, r02_date_params, r03_string_params, r04_boolean_calcs,
         r05_measure_names, r06_mysql_connection, r07_extract_packed,
         r08_extension, r10_xsd,
         r11_sheet_without_breakdown, r12_orphan_sheets, r13_simpson,
         r14_unused_params, r15_orphan_filters, r16_zone_geometry,
         r17_automatic_marks, r18_no_comparison_base, r19_dual_axis,
         r20_metric_canon, r21_stale_thumbnail, r22_zone_too_narrow,
         r23_duplicate_zone_id, r28_column_drift, r29_element_order,
         r30_table_calc_direction, r31_table_calc_drift, r32_manifest_gate,
         r33_opens_on_worksheet, r34_double_aggregation,
         r35_naming_and_folders, r36_device_layout_drift, r40_ds_style_encoding,
         r37_gradient_on_plain_measure, r38_label_color_overridden,
         r41_param_ref_by_caption, r42_caption_collision, r_format_attr]


def lint(path: str, db: str = "", table: str = "") -> list[Violation]:
    """Lint a workbook."""
    if not os.path.exists(path):
        return [Violation("R00", ERROR, f"file not found: {path}")]
    try:
        book = load(path)
    except Exception as exc:
        return [Violation("R00", ERROR, f"workbook does not parse: {type(exc).__name__}: {exc}")]
    out: list[Violation] = []
    for rule in RULES:
        try:
            out.extend(rule(book))
        except Exception as exc:
            out.append(Violation(rule.__name__[:3].upper(), INFO,
                                 f"rule crashed: {type(exc).__name__}: {exc}"))
    out.extend(r09_stale_columns(book, db, table))
    order = {ERROR: 0, WARN: 1, INFO: 2}
    return sorted(out, key=lambda v: (order[v.severity], v.rule))


def counts(violations: list[Violation]) -> dict[str, int]:
    return {s: sum(1 for v in violations if v.severity == s) for s in (ERROR, WARN, INFO)}


def format_report(violations: list[Violation], path: str = "") -> str:
    c = counts(violations)
    head = f"{os.path.basename(path)}: " if path else ""
    if not violations:
        return f"{head}clean: 0 violations"
    body = "\n".join(str(v) for v in violations)
    return (f"{head}errors {c[ERROR]}, warnings {c[WARN]}, info {c[INFO]}\n"
            f"{body}")


def assert_clean(path: str, db: str = "", table: str = "", strict: bool = False) -> list[Violation]:
    """End-of-build check: prints the report, fails on error (and on warn when strict)."""
    v = lint(path, db, table)
    print(format_report(v, path))
    c = counts(v)
    if c[ERROR] or (strict and c[WARN]):
        raise SystemExit(f"LINTER: the workbook is not fit for delivery ({c[ERROR]} errors, {c[WARN]} warnings)")
    return v

"""Field expressions on shelves (`SUM(sales)`, `MONTH(date)`, `country`) and their sheet instances."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from lxml import etree

from . import edit as ED

FUNCS = {
    "SUM": ("Sum", "qk"), "AVG": ("Avg", "qk"), "COUNT": ("Count", "qk"),
    "COUNTD": ("CountD", "qk"), "MIN": ("Min", "qk"), "MAX": ("Max", "qk"),
    "MEDIAN": ("Median", "qk"), "ATTR": ("Attribute", "nk"), "AGG": ("User", "qk"),
    "YEAR": ("Year", "ok"), "QUARTER": ("Quarter", "ok"), "MONTH": ("Month", "ok"),
    "WEEK": ("Week", "ok"), "WEEKDAY": ("Weekday", "ok"), "DAY": ("Day", "ok"),
    "MY": ("MY", "ok"), "MDY": ("MDY", "ok"),
    "YEARTRUNC": ("Year-Trunc", "qk"), "QUARTERTRUNC": ("Quarter-Trunc", "qk"),
    "MONTHTRUNC": ("Month-Trunc", "qk"), "WEEKTRUNC": ("Week-Trunc", "qk"),
    "DAYTRUNC": ("Day-Trunc", "qk"),
}
KIND_TYPE = {"nk": "nominal", "ok": "ordinal", "qk": "quantitative"}
_CALL = re.compile(r"^\s*([A-Za-z_]+)\s*\(\s*(.+?)\s*\)\s*$")
_PARAM = re.compile(r"^\[?Parameters\]?\.\[(.+)\]$")


def find_by(parent, tag: str, attr: str, value: str, deep: bool = False):
    """The first `tag` child (or descendant) whose `attr` equals `value`; no XPath from data."""
    for el in (parent.iter(tag) if deep else parent.iterfind(tag)):
        if el.get(attr) == value:
            return el
    return None


@dataclass(frozen=True)
class Field:
    name: str
    caption: str
    role: str
    datatype: str
    type: str
    formula: str = ""
    datasource: str = ""

    @property
    def aggregated(self) -> bool:
        return bool(self.formula) and is_aggregate(self.formula)

    @property
    def is_date(self) -> bool:
        return self.datatype in ("date", "datetime")


@dataclass(frozen=True)
class Placed:
    ref: str
    instance: str
    field: Field
    derivation: str

    @property
    def discrete(self) -> bool:
        return self.instance.endswith((":nk]", ":ok]"))


def _role_type(datatype: str) -> tuple[str, str]:
    if datatype in ("real", "integer"):
        return "measure", "quantitative"
    if datatype in ("date", "datetime"):
        return "dimension", "ordinal"
    return "dimension", "nominal"


def fields(root, datasource: str = "") -> dict:
    """Every field of the data sources by name and by caption."""
    out = {}
    for ds in root.find("datasources").findall("datasource"):
        dsn = ds.get("name") or ""
        if dsn == "Parameters" or (datasource and dsn != datasource):
            continue
        for c in ds.findall("column"):
            name = (c.get("name") or "").strip("[]")
            if not name or name.startswith(("__tableau", ":")) or c.get("datatype") == "table":
                continue
            calc = c.find("calculation")
            dt = c.get("datatype") or "string"
            role, typ = _role_type(dt)
            f = Field(name, c.get("caption") or name, c.get("role") or role, dt,
                      c.get("type") or typ,
                      (calc.get("formula") or "") if calc is not None else "", dsn)
            for key in (name, f.caption):
                out.setdefault(key, f)
        for col in ds.iter("column"):
            if col.getparent() is not None and col.getparent().tag == "columns":
                _raw(out, col.get("name") or "", col.get("datatype") or "string", dsn)
        for rec in ds.iter("metadata-record"):
            if rec.get("class") == "column":
                _raw(out, (rec.findtext("local-name") or "").strip("[]"),
                     rec.findtext("local-type") or "string", dsn)
    return out


def _raw(out: dict, name: str, datatype: str, datasource: str) -> None:
    if name and name not in out and not name.startswith(("__tableau", ":")):
        role, typ = _role_type(datatype)
        out[name] = Field(name, name, role, datatype, typ, "", datasource)


def find(root, name: str, datasource: str = "") -> Field | None:
    return fields(root, datasource).get((name or "").strip().strip("[]"))


def parse(root, expr: str, datasource: str = "") -> tuple[str, Field]:
    """`SUM(sales)` -> ("SUM", Field sales); a field whose name has brackets wins over a call."""
    text = (expr or "").strip()
    known = fields(root, datasource)
    bare = text.strip("[]")
    if bare in known:
        return "", known[bare]
    m = _CALL.match(text)
    if m:
        func = m.group(1).upper()
        if func not in FUNCS:
            raise ValueError(f"unknown function {m.group(1)}() in {expr!r}; "
                             f"use one of {', '.join(FUNCS)}")
        inner = m.group(2).strip().strip("[]")
        if inner in known:
            return func, known[inner]
        raise ValueError(f"no field {inner!r} in the workbook (from {expr!r})")
    raise ValueError(f"no field {bare!r} in the workbook")


def derivation(func: str, f: Field) -> tuple[str, str]:
    """Derivation and instance kind: an explicit function, or what a bare field means.

    A bare measure is summed (an aggregate calculation stays as it is); a bare date is the exact
    date, never guessed from its name: ask for MONTH(x) or MONTHTRUNC(x) explicitly.
    """
    if func:
        return FUNCS[func]
    if f.role == "measure":
        return ("User", "qk") if f.aggregated else ("Sum", "qk")
    if f.is_date:
        return "None", "qk" if f.type == "quantitative" else "ok"
    return "None", "ok" if f.type in ("ordinal", "quantitative") else "nk"


def sheet_datasource(root, ws) -> str:
    return ED._ds_name(ws)


def place(root, ws, expr: str, func: str = "") -> Placed:
    """Declare the field of `expr` and its instance on sheet `ws`."""
    fn, f = parse(root, expr, sheet_datasource(root, ws))
    deriv, kind = derivation(func or fn, f)
    declare(ws, f)
    ref, inst = ED._instance_ref(root, ws, f.name, deriv, kind=kind)
    return Placed(ref, inst, f, deriv)


_REF = re.compile(r"(?<![\].])\[([^\[\]]+)\](?!\.)")
_PARAM_REF = re.compile(r"\[Parameters\]\.\[([^\[\]]+)\]")


def declare(ws, f: Field, seen: set | None = None) -> None:
    """The field's `<column>` in the sheet's dependencies, as its data source declares it; a
    calculation brings the fields and parameters its formula reads, as Tableau writes them."""
    dep = find_by(ws, "datasource-dependencies", "datasource", ED._ds_name(ws), deep=True)
    if dep is None or any(c.get("name") == f"[{f.name}]" for c in dep.findall("column")):
        return
    seen = seen if seen is not None else set()
    seen.add(f.name)
    if f.formula:
        root = ws.getroottree().getroot()
        for name in _PARAM_REF.findall(f.formula):
            p = param(root, name)
            if p is not None:
                bind_parameter(ws, p)
        known = fields(root, f.datasource)
        for tok in _REF.findall(f.formula):
            g = known.get(tok)
            if g is not None and g.name not in seen:
                declare(ws, g, seen)
    src = None
    for ds in ws.getroottree().getroot().find("datasources").findall("datasource"):
        if ds.get("name") == f.datasource:
            src = next((c for c in ds.findall("column")
                        if c.get("name") == f"[{f.name}]"), None)
    if src is not None:
        dep.insert(0, copy.deepcopy(src))
        return
    col = etree.Element("column")
    for k, v in (("datatype", f.datatype), ("name", f"[{f.name}]"), ("role", f.role),
                 ("type", f.type)):
        col.set(k, v)
    dep.insert(0, col)


def shelf(refs: list) -> str:
    """Shelf expression as Tableau writes it: dimensions nest with `/`, measures stack with `+`,
    the two groups cross with `*`."""
    dims = [p.ref for p in refs if p.discrete]
    meas = [p.ref for p in refs if not p.discrete]

    def group(items, op):
        if not items:
            return ""
        return items[0] if len(items) == 1 else "(" + f" {op} ".join(items) + ")"

    d, m = group(dims, "/"), group(meas, "+")
    if d and m:
        return f"({d} * {m})"
    return d or m


def bind_parameter(ws, param_col) -> None:
    """The Parameters source and this parameter in a sheet's dependencies."""
    view = ws.find("table/view")
    dss = view.find("datasources")
    if not any(d.get("name") == "Parameters" for d in dss):
        d = etree.Element("datasource")
        d.set("caption", "Parameters")
        d.set("name", "Parameters")
        dss.insert(0, d)
    dep = view.find("datasource-dependencies[@datasource='Parameters']")
    if dep is None:
        dep = etree.Element("datasource-dependencies")
        dep.set("datasource", "Parameters")
        first = view.find("datasource-dependencies")
        if first is not None:
            first.addprevious(dep)
        else:
            from . import order as ORD
            ED.insert_in_order(view, dep, list(ORD.VIEW_ORDER))
    if not any(c.get("name") == param_col.get("name") for c in dep.findall("column")):
        dep.append(copy.deepcopy(param_col))


def param(root, caption: str):
    """The parameter column whose caption or name is `caption`."""
    p = _PARAM.match(caption or "")
    key = p.group(1) if p else (caption or "").strip("[]")
    ds = next((d for d in root.find("datasources").findall("datasource")
               if d.get("name") == "Parameters"), None)
    if ds is None:
        return None
    for c in ds.findall("column"):
        if key in ((c.get("caption") or ""), (c.get("name") or "").strip("[]")):
            return c
    return None


def reference(root, expr: str, datasource: str = "") -> str:
    """`[ds].[instance]` of an expression, without declaring anything."""
    func, f = parse(root, expr, datasource)
    deriv, kind = derivation(func, f)
    return f"[{f.datasource}].[{ED._DERIV_PREFIX.get(deriv, deriv.lower())}:{f.name}:{kind}]"


_AGGREGATES = ("SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN", "ATTR", "STDEV",
               "STDEVP", "VAR", "VARP", "PERCENTILE", "CORR", "COVAR", "COVARP", "COLLECT",
               "TOTAL", "INDEX", "SIZE", "FIRST", "LAST", "LOOKUP", "PREVIOUS_VALUE",
               "RANK", "RANK_DENSE", "RANK_MODIFIED", "RANK_PERCENTILE", "RANK_UNIQUE")
_AGG_CALL = re.compile(r"\b(" + "|".join(_AGGREGATES) + r"|WINDOW_\w+|RUNNING_\w+|SCRIPT_\w+)"
                       r"\s*\(", re.I)


def _strip_formula(formula: str) -> str:
    """The formula without comments, strings, field references and LOD blocks."""
    out = re.sub(r"//[^\n]*", " ", formula or "")
    out = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", " ", out)
    out = re.sub(r"\[[^\]]*\]", " ", out)
    while True:
        new = re.sub(r"\{[^{}]*\}", " 0 ", out)
        if new == out:
            return out
        out = new


def _args_at_top(text: str, start: int) -> int:
    """Commas at the top level of the call whose `(` is at `start`."""
    depth, commas = 0, 0
    for ch in text[start:]:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return commas
        elif ch == "," and depth == 1:
            commas += 1
    return commas


def is_aggregate(formula: str) -> bool:
    """Does the formula aggregate outside LOD braces? `{FIXED [u]: SUM(x)}` is row-level;
    `MIN(a, b)` with two arguments is a row-level comparison."""
    text = _strip_formula(formula)
    for m in _AGG_CALL.finditer(text):
        if m.group(1).upper() in ("MIN", "MAX") and _args_at_top(text, m.end() - 1) > 0:
            continue
        return True
    return False

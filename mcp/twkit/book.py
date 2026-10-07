"""A workbook being built: the document, its data sources, calculations, parameters and sheets.

`Book` is a thin session over module functions; every change is made on `book.root`.
"""
from __future__ import annotations

import copy
import os
import random
import re

from lxml import etree

from . import edit as ED
from . import order as ORD
from . import safexml

USER_NS = "http://www.tableausoftware.com/xml/user"
VERSION = "18.1"
SOURCE_BUILD = "2025.3.1 (20253.25.1210.1815)"
MARK = "built by twkit"
MANIFEST = ("AnimationOnByDefault", "MarkAnimation", "ObjectModelEncapsulateLegacy",
            "ObjectModelTableType", "SchemaViewerObjectModel", "SheetIdentifierTracking",
            "WindowsPersistSimpleIdentifiers")
WORKBOOK_ORDER = ("document-format-change-manifest", "repository-location", "preferences",
                  "style-theme", "style", "local-data", "datasources", "datasource-relationships",
                  "mapsources", "shared-views", "actions", "worksheets", "dashboards", "windows",
                  "datagraph", "thumbnails", "external")
_WS_CARDS = (("left", [("pages",), ("filters",), ("marks",)]),
             ("top", [("columns",), ("rows",), ("title",)]))


def tableau_id(n: int = 28) -> str:
    """A random lowercase identifier as Tableau writes after `federated.` or `textscan.`."""
    return "".join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(n))


def calc_name() -> str:
    return "Calculation_" + str(random.randint(10 ** 18, 10 ** 19 - 1))


def child(parent, tag: str, order=WORKBOOK_ORDER):
    """The child `tag` of `parent`, created in its place when missing."""
    node = parent.find(tag)
    if node is None:
        node = etree.Element(tag)
        ED.insert_in_order(parent, node, list(order))
    return node


def skeleton():
    """An empty workbook as Tableau Desktop starts one."""
    root = etree.Element("workbook", nsmap={"user": USER_NS})
    for k, v in (("original-version", VERSION), ("source-build", SOURCE_BUILD),
                 ("source-platform", "mac"), ("version", VERSION)):
        root.set(k, v)
    man = etree.SubElement(root, "document-format-change-manifest")
    for m in MANIFEST:
        etree.SubElement(man, m)
    prefs = etree.SubElement(root, "preferences")
    for name, value in (("ui.encoding.shelf.height", "24"), ("ui.shelf.height", "26")):
        p = etree.SubElement(prefs, "preference")
        p.set("name", name)
        p.set("value", value)
    etree.SubElement(root, "datasources")
    etree.SubElement(root, "windows")
    tree = etree.ElementTree(root)
    root.addprevious(etree.Comment(f" build {SOURCE_BUILD.split('(')[1].rstrip(')')} "))
    root.addprevious(etree.Comment(f" {MARK} "))
    return tree.getroot()


class Book:
    """The workbook in memory. `Book()` starts an empty one, `Book.open(path)` reads a file."""

    def __init__(self, root=None, path: str = ""):
        self.root = skeleton() if root is None else root
        self.path = path
        self.members: dict = {}

    @classmethod
    def open(cls, path: str) -> "Book":
        b = cls(safexml.from_twbx(str(path)), str(path))
        if str(path).lower().endswith(".twbx"):
            import zipfile
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    if not n.lower().endswith(".twb"):
                        b.members[n] = (os.path.abspath(str(path)), n)
        return b

    open_existing = open

    # data sources -----------------------------------------------------------------

    @property
    def datasources(self):
        return child(self.root, "datasources")

    @property
    def datasource(self):
        """The main data source: the first one that is not Parameters."""
        return next((d for d in self.datasources.findall("datasource")
                     if d.get("name") != "Parameters"), None)

    @property
    def parameters(self):
        ds = next((d for d in self.datasources.findall("datasource")
                   if d.get("name") == "Parameters"), None)
        if ds is None:
            ds = etree.Element("datasource")
            for k, v in (("hasconnection", "false"), ("inline", "true"),
                         ("name", "Parameters"), ("version", VERSION)):
                ds.set(k, v)
            etree.SubElement(ds, "aliases").set("enabled", "yes")
            self.datasources.insert(0, ds)
        return ds

    # calculations and parameters ---------------------------------------------------

    def _formula(self, formula: str) -> str:
        """Parameters and calculations referenced by caption become their internal names."""
        def param(m):
            p = _param_by_caption(self.root, m.group(1))
            return f"[Parameters].{p.get('name')}" if p is not None else m.group(0)
        out = re.sub(r"\[Parameters\]\.\[([^\]]+)\]", param, formula or "")
        ds = self.datasource
        if ds is None:
            return out
        names = {(c.get("name") or "") for c in ds.findall("column")}
        names |= {f"[{c.get('name')}]" for c in ds.iter("column")
                  if c.getparent() is not None and c.getparent().tag == "columns"}
        calcs = {f"[{c.get('caption')}]": c.get("name") for c in ds.findall("column")
                 if c.find("calculation") is not None and c.get("caption")}

        def calc(m):
            tok = m.group(0)
            if tok in names or tok not in calcs:
                return tok
            return calcs[tok]

        parts = re.split(r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")", out)
        return "".join(p if i % 2 else re.sub(r"(?<!\])(?<!\.)\[[^\[\]]+\](?!\.)", calc, p)
                       for i, p in enumerate(parts))

    def add_calculated_field(self, field_name: str, formula: str, datatype: str = "real",
                             role: str | None = None, field_type: str | None = None,
                             table_calc=None, default_format: str = "",
                             internal_name: str | None = None) -> str:
        ds = self.datasource
        if ds is None:
            raise ValueError("connect a data source before adding calculations")
        for c in ds.findall("column"):
            if ((c.get("caption") or (c.get("name") or "").strip("[]")) == field_name
                    and not (c.get("name") or "").startswith("[__tableau_internal_object_id__]")):
                raise ValueError(f"the caption {field_name!r} is already taken by "
                                 f"{c.get('name')} (lint R42)")
        if internal_name and any(c.get("name") == f"[{internal_name.strip('[]')}]"
                                 for c in ds.findall("column")):
            raise ValueError(f"internal name {internal_name!r} is already taken")
        formula = self._formula(formula)
        from .fields import is_aggregate
        if role is None:
            role = "measure" if (datatype in ("real", "integer")
                                 or is_aggregate(formula)) else "dimension"
        if field_type is None:
            field_type = ("quantitative" if role == "measure"
                          else "ordinal" if datatype in ("date", "datetime") else "nominal")
        col = etree.Element("column")
        for key, val in (("caption", field_name), ("datatype", datatype),
                         ("default-format", default_format),
                         ("name", f"[{(internal_name or calc_name()).strip('[]')}]"),
                         ("role", role), ("type", field_type)):
            if val:
                col.set(key, val)
        calc = etree.SubElement(col, "calculation")
        calc.set("class", "tableau")
        calc.set("formula", formula)
        if table_calc:
            tc = etree.SubElement(calc, "table-calc")
            spec = table_calc if isinstance(table_calc, dict) else {"ordering-type": table_calc}
            for k, v in spec.items():
                tc.set(k.replace("_", "-"), str(v))
        ED.insert_in_order(ds, col, list(ORD.DATASOURCE_ORDER))
        return f"Added calculated field {field_name!r} as {col.get('name')}"

    def remove_calculated_field(self, field_name: str) -> str:
        ds = self.datasource
        col = next((c for c in (ds.findall("column") if ds is not None else [])
                    if c.find("calculation") is not None
                    and field_name in (c.get("caption"), (c.get("name") or "").strip("[]"))),
                   None)
        if col is None:
            return f"No calculated field {field_name!r}"
        name = col.get("name")
        users = sorted({ws.get("name") for ws in self.root.iter("worksheet")
                        for ci in ws.iter("column-instance") if ci.get("column") == name})
        if users:
            return (f"{field_name!r} is used on {', '.join(users)}; remove it from those sheets "
                    f"first (edit_remove_field)")
        bare = name.strip("[]")
        other = sorted({_where(el) for el in self.root.iter()
                        if isinstance(el.tag, str) and el is not col
                        and col not in el.iterancestors()
                        and any(bare in v for v in el.attrib.values())})
        if other:
            return (f"{field_name!r} is still referenced ({', '.join(other[:5])}); "
                    f"remove those references first")
        ds.remove(col)
        return f"Removed calculated field {field_name!r}"

    def add_parameter(self, name: str, datatype: str = "real", default_value: str = "0",
                      domain_type: str = "range", min_value: str = "", max_value: str = "",
                      granularity: str = "", allowed_values: list | None = None,
                      default_format: str = "", internal_name: str | None = None,
                      alias: str | None = None, allowed_aliases: dict | None = None) -> str:
        ds = self.parameters
        if _param_by_caption(self.root, name) is not None:
            raise ValueError(f"parameter {name!r} already exists")
        taken = {c.get("name") for c in ds.findall("column")}
        if internal_name:
            pname = f"[{internal_name.strip('[]')}]"
        else:
            n = 1
            while f"[Parameter {n}]" in taken:
                n += 1
            pname = f"[Parameter {n}]"
        lit = ED.param_literal(datatype, default_value)
        col = etree.SubElement(ds, "column")
        kind = "nominal" if datatype in ("string", "boolean") else "quantitative"
        for key, val in (("alias", alias), ("caption", name), ("datatype", datatype),
                         ("default-format", default_format), ("name", pname),
                         ("param-domain-type", domain_type), ("role", "measure"),
                         ("type", kind), ("value", lit)):
            if val:
                col.set(key, val)
        calc = etree.SubElement(col, "calculation")
        calc.set("class", "tableau")
        calc.set("formula", lit)
        if domain_type == "range":
            rng = etree.SubElement(col, "range")
            for k, v in (("granularity", granularity), ("max", max_value), ("min", min_value)):
                if str(v) != "":
                    rng.set(k, ED.param_literal(datatype, v) if datatype in ("date", "datetime")
                            else str(v))
        elif domain_type == "list":
            values = [str(v) for v in (allowed_values or [default_value])]
            if allowed_aliases:
                al = etree.SubElement(col, "aliases")
                for v in values:
                    if v in allowed_aliases:
                        a = etree.SubElement(al, "alias")
                        a.set("key", ED.param_literal(datatype, v))
                        a.set("value", str(allowed_aliases[v]))
            mem = etree.SubElement(col, "members")
            for v in values:
                m = etree.SubElement(mem, "member")
                if allowed_aliases and v in allowed_aliases:
                    m.set("alias", str(allowed_aliases[v]))
                m.set("value", ED.param_literal(datatype, v))
        return f"Added parameter {name!r} as {pname}"

    # sheets ----------------------------------------------------------------------------

    def sheet(self, name: str):
        ws = ED._sheet(self.root, name)
        if ws is None:
            raise ValueError(f"no worksheet {name!r}; sheets: {', '.join(self.list_worksheets())}")
        return ws

    _find_worksheet = sheet

    def add_worksheet(self, worksheet_name: str) -> str:
        if ED._sheet(self.root, worksheet_name) is not None:
            raise ValueError(f"worksheet {worksheet_name!r} already exists")
        wss = child(self.root, "worksheets")
        ws = etree.SubElement(wss, "worksheet")
        ws.set("name", worksheet_name)
        table = etree.SubElement(ws, "table")
        view = etree.SubElement(table, "view")
        etree.SubElement(view, "datasources")
        etree.SubElement(view, "aggregation").set("value", "true")
        etree.SubElement(table, "style")
        pane = etree.SubElement(etree.SubElement(table, "panes"), "pane")
        pane.set("selection-relaxation-option", "selection-relaxation-allow")
        etree.SubElement(etree.SubElement(pane, "view"), "breakdown").set("value", "auto")
        etree.SubElement(pane, "mark").set("class", "Automatic")
        etree.SubElement(table, "rows")
        etree.SubElement(table, "cols")
        etree.SubElement(ws, "simple-id").set("uuid", ED.new_uuid())
        _worksheet_window(self.root, worksheet_name)
        return f"Added worksheet {worksheet_name!r}"

    def clone_worksheet(self, source_worksheet: str, target_worksheet: str) -> str:
        src = self.sheet(source_worksheet)
        if ED._sheet(self.root, target_worksheet) is not None:
            raise ValueError(f"worksheet {target_worksheet!r} already exists")
        ws = copy.deepcopy(src)
        ws.set("name", target_worksheet)
        sid = ws.find("simple-id")
        if sid is not None:
            sid.set("uuid", ED.new_uuid())
        src.addnext(ws)
        _worksheet_window(self.root, target_worksheet)
        return f"Cloned {source_worksheet!r} to {target_worksheet!r}"

    def set_worksheet_caption(self, worksheet_name: str, caption: str) -> str:
        ws = self.sheet(worksheet_name)
        lo = ws.find("layout-options")
        if lo is None:
            lo = etree.Element("layout-options")
            ws.insert(0, lo)
        for old in lo.findall("caption"):
            lo.remove(old)
        cap = etree.Element("caption")
        etree.SubElement(etree.SubElement(cap, "formatted-text"), "run").text = caption
        title = lo.find("title")
        if title is not None:
            title.addnext(cap)
        else:
            lo.insert(0, cap)
        return f"Caption of {worksheet_name!r} set"

    def set_worksheet_hidden(self, worksheet_name: str, hidden: bool = True) -> str:
        self.sheet(worksheet_name)
        win = next((w for w in child(self.root, "windows").findall("window")
                    if w.get("class") == "worksheet" and w.get("name") == worksheet_name), None)
        if win is None:
            win = _worksheet_window(self.root, worksheet_name)
        if hidden:
            win.set("hidden", "true")
        elif "hidden" in win.attrib:
            del win.attrib["hidden"]
        return f"{worksheet_name!r} {'hidden' if hidden else 'shown'}"

    # reading ----------------------------------------------------------------------------

    def list_worksheets(self) -> list:
        return [w.get("name") for w in self.root.iter("worksheet")]

    def list_dashboards(self) -> list:
        out = []
        for d in self.root.iter("dashboard"):
            sheets = list(dict.fromkeys(z.get("name") for z in d.iter("zone")
                                        if z.get("name") and not z.get("type-v2")))
            out.append({"name": d.get("name"), "worksheets": sheets})
        return out

    def list_fields(self) -> str:
        from . import fields as F
        lines = []
        seen = set()
        for f in F.fields(self.root).values():
            if f.name in seen:
                continue
            seen.add(f.name)
            kind = "calc" if f.formula else "field"
            lines.append(f"{f.caption} [{f.role}, {f.datatype}, {kind}]"
                         + (f" = {f.formula}" if f.formula else ""))
        for p in self.parameters.findall("column") if self._has_parameters() else []:
            lines.append(f"{p.get('caption')} [parameter, {p.get('datatype')}] = {p.get('value')}")
        return "\n".join(lines)

    def _has_parameters(self) -> bool:
        return any(d.get("name") == "Parameters" for d in self.datasources.findall("datasource"))

    # writing ----------------------------------------------------------------------------

    def save(self, output_path: str, validate: bool = False) -> str:
        """Write a .twbx: the workbook plus packaged data files."""
        out = str(output_path)
        if not out.lower().endswith(".twbx"):
            raise ValueError("save as .twbx only (law 5)")
        ORD.normalize_workbook(self.root)
        ORD.normalize_views(self.root)
        if validate:
            from . import xsd
            res = xsd.validate(self.root)
            if not res["ok"]:
                raise ValueError("schema errors: " + "; ".join(res["errors"][:5]))
        stem = os.path.splitext(os.path.basename(out))[0]
        safexml.write_twbx(self.root, out, f"{stem}.twb", self.members)
        self.path = out
        return out

    def validate_schema(self) -> dict:
        from . import xsd
        return xsd.validate(self.root)

    # building, delegated ------------------------------------------------------------------

    def set_csv_connection(self, *a, **k):
        from . import conn
        return conn.csv(self, *a, **k)

    def set_hyper_connection(self, *a, **k):
        from . import conn
        return conn.hyper(self, *a, **k)

    def set_mysql_connection(self, *a, **k):
        from . import conn
        return conn.mysql(self, *a, **k)

    def configure_chart(self, *a, **k):
        from . import sheet
        return sheet.configure(self, *a, **k)

    def configure_dual_axis(self, *a, **k):
        from . import sheet
        return sheet.dual_axis(self, *a, **k)

    def configure_worksheet_style(self, *a, **k):
        from . import sheet
        return sheet.style(self, *a, **k)

    def add_reference_line(self, *a, **k):
        from . import sheet
        return sheet.reference_line(self, *a, **k)

    def add_dashboard(self, *a, **k):
        from . import dash
        return dash.add(self, *a, **k)

    def add_dashboard_action(self, *a, **k):
        from . import dash
        return dash.action(self, *a, **k)


def _where(el) -> str:
    """A short human pointer to an element: its tag and the nearest named ancestor."""
    named = next((a for a in el.iterancestors() if a.get("name")
                  and a.tag in ("worksheet", "dashboard", "datasource", "column")), None)
    owner = f"{named.tag} {named.get('caption') or named.get('name')}" if named is not None else ""
    return f"{el.tag} in {owner}" if owner else el.tag


def _param_by_caption(root, caption: str):
    for ds in root.find("datasources").findall("datasource"):
        if ds.get("name") != "Parameters":
            continue
        for c in ds.findall("column"):
            if caption in (c.get("caption"), (c.get("name") or "").strip("[]")):
                return c
    return None


def _worksheet_window(root, name: str):
    wins = child(root, "windows")
    for w in wins.findall("window"):
        if w.get("class") == "worksheet" and w.get("name") == name:
            return w
    win = etree.Element("window")
    win.set("class", "worksheet")
    win.set("name", name)
    cards = etree.SubElement(win, "cards")
    for edge, strips in _WS_CARDS:
        e = etree.SubElement(cards, "edge")
        e.set("name", edge)
        if edge == "left":
            s = etree.SubElement(e, "strip")
            s.set("size", "160")
            for (card,) in strips:
                etree.SubElement(s, "card").set("type", card)
        else:
            for (card,) in strips:
                s = etree.SubElement(e, "strip")
                s.set("size", "2147483647")
                etree.SubElement(s, "card").set("type", card)
    for edge in ("right", "bottom"):
        etree.SubElement(cards, "edge").set("name", edge)
    etree.SubElement(win, "viewpoint")
    etree.SubElement(win, "simple-id").set("uuid", ED.new_uuid())
    dash_win = next((w for w in wins.findall("window") if w.get("class") == "dashboard"), None)
    if dash_win is not None:
        dash_win.addprevious(win)
    else:
        wins.append(win)
    return win

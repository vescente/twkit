"""A worksheet's chart: mark, shelves, encodings, filters, sorts, axes, labels, maps and style."""
from __future__ import annotations

import re

from lxml import etree

from . import edit as ED
from . import fields as F
from . import order as ORD

MARKS = {"Automatic": "Automatic", "Bar": "Bar", "Line": "Line", "Area": "Area",
         "Circle": "Circle", "Square": "Square", "Shape": "Shape", "Text": "Text",
         "Pie": "Pie", "Tree Map": "Square", "Treemap": "Square", "Map": "Multipolygon",
         "Polygon": "Polygon", "Gantt Bar": "GanttBar"}
PANE_ORDER = ["view", "mark", "mark-sizing", "encodings", "reference-line",
              "customized-tooltip", "customized-label", "style"]
TABLE_ORDER = ["view", "style", "panes", "rows", "cols", "subtotals", "tooltip-style",
               "show-full-range"]
_FIELD_IN_TEXT = re.compile(r"<([^<>]+)>")
_LATLON = ("[Latitude (generated)]", "[Longitude (generated)]")
_COUNTRY_ROLE = "[Country].[Name]"
_NEEDS_COUNTRY = ("[State].[Name]", "[County].[Name]", "[City].[Name]", "[ZipCode].[Name]")


# sheet skeleton ------------------------------------------------------------------------

def _reset(ws) -> None:
    """Clear what a previous chart left; titles, captions and identity stay."""
    table = ws.find("table")
    view = table.find("view")
    for el in list(view):
        if el.tag not in ("datasources", "aggregation"):
            view.remove(el)
    for d in list(view.find("datasources")):
        view.find("datasources").remove(d)
    style = table.find("style")
    for el in list(style):
        style.remove(el)
    for tag in ("subtotals", "tooltip-style", "show-full-range"):
        for el in table.findall(tag):
            table.remove(el)
    panes = table.find("panes")
    for p in list(panes):
        panes.remove(p)
    _pane(panes, "Automatic")
    for tag in ("rows", "cols"):
        table.find(tag).text = None


def _pane(panes, mark: str, pid: str = "", axis: tuple = ()):
    pane = etree.SubElement(panes, "pane")
    if pid:
        pane.set("id", pid)
    pane.set("selection-relaxation-option", "selection-relaxation-allow")
    if axis:
        pane.set(axis[0], axis[1])
    etree.SubElement(etree.SubElement(pane, "view"), "breakdown").set("value", "auto")
    etree.SubElement(pane, "mark").set("class", mark)
    return pane


def _bind(ws, ds) -> str:
    view = ws.find("table/view")
    dss = view.find("datasources")
    name = ds.get("name")
    if not any(d.get("name") == name for d in dss):
        d = etree.SubElement(dss, "datasource")
        if ds.get("caption"):
            d.set("caption", ds.get("caption"))
        d.set("name", name)
    if F.find_by(view, "datasource-dependencies", "datasource", name) is None:
        dep = etree.Element("datasource-dependencies")
        dep.set("datasource", name)
        ED.insert_in_order(view, dep, list(ORD.VIEW_ORDER))
    return name


def _source(book, key: str, explicit: bool = False):
    """The data source named or captioned `key`; the main one when `key` is empty or stale."""
    for d in book.datasources.findall("datasource"):
        if d.get("name") != "Parameters" and key and key in (d.get("name"), d.get("caption")):
            return d
    if explicit:
        raise ValueError(f"no data source {key!r} in the workbook")
    if book.datasource is None:
        raise ValueError("connect a data source before configuring charts")
    return book.datasource


def _encode(pane, tag: str, ref: str) -> None:
    enc = pane.find("encodings")
    if enc is None:
        enc = etree.Element("encodings")
        ED.insert_in_order(pane, enc, PANE_ORDER)
    if not any(e.tag == tag and e.get("column") == ref for e in enc):
        etree.SubElement(enc, tag).set("column", ref)


def _mark_style(pane, **formats) -> None:
    style = pane.find("style")
    if style is None:
        style = etree.Element("style")
        ED.insert_in_order(pane, style, PANE_ORDER)
    rule = next((r for r in style.findall("style-rule") if r.get("element") == "mark"), None)
    if rule is None:
        rule = etree.SubElement(style, "style-rule")
        rule.set("element", "mark")
    for attr, value in formats.items():
        attr = attr.replace("_", "-")
        old = next((f for f in rule.findall("format") if f.get("attr") == attr), None)
        if old is None:
            old = etree.SubElement(rule, "format")
            old.set("attr", attr)
        old.set("value", str(value))


def _table_rule(ws, element: str):
    return ED._style_rule(ws.find("table"), element)


def _format(rule, attr: str, value, field: str = "", scope: str = "") -> None:
    for f in rule.findall("format"):
        if f.get("attr") == attr and (f.get("field") or "") == field \
                and (f.get("scope") or "") == scope:
            f.set("value", str(value))
            return
    f = etree.SubElement(rule, "format")
    f.set("attr", attr)
    if field:
        f.set("field", field)
    if scope:
        f.set("scope", scope)
    f.set("value", str(value))


def _as_list(v) -> list:
    if v is None or v == "":
        return []
    return [v] if isinstance(v, str) else list(v)


def _shelf_text(items: list) -> str:
    """`items` are `(ref, discrete)`; see `fields.shelf`."""
    dims = [r for r, d in items if d]
    meas = [r for r, d in items if not d]

    def group(xs, op):
        return "" if not xs else xs[0] if len(xs) == 1 else "(" + f" {op} ".join(xs) + ")"

    d, m = group(dims, "/"), group(meas, "+")
    return f"({d} * {m})" if d and m else d or m


# filters and sorts -----------------------------------------------------------------------

def _member(f: F.Field, value) -> str:
    v = str(value)
    if f.datatype in ("string",) or (f.formula and f.datatype == "string"):
        return '"' + v.replace('"', '""') + '"'
    if f.is_date:
        return ED._date_literal(v)
    if f.datatype == "boolean":
        return v.lower()
    return v


def _values_filter(root, ws, field: str, values: list) -> str:
    p = F.place(root, ws, field, func="")
    if p.field.role == "measure":
        p = F.place(root, ws, field, func="ATTR")
    view = ws.find("table/view")
    ED._replace_filter(view, p.ref)
    filt = etree.Element("filter")
    filt.set("class", "categorical")
    filt.set("column", p.ref)
    members = [_member(p.field, v) for v in values]
    top = etree.SubElement(filt, "groupfilter")
    if len(members) == 1:
        top.set("function", "member")
        top.set("level", p.instance)
        top.set("member", members[0])
    else:
        top.set("function", "union")
        for m in members:
            g = etree.SubElement(top, "groupfilter")
            g.set("function", "member")
            g.set("level", p.instance)
            g.set("member", m)
    top.set(ED._u("ui-domain"), "database")
    top.set(ED._u("ui-enumeration"), "inclusive")
    top.set(ED._u("ui-marker"), "enumerate")
    ED.insert_in_order(view, filt, list(ORD.VIEW_ORDER))
    _slice(view, p.ref)
    return p.ref


def _slice(view, ref: str) -> None:
    sl = view.find("slices")
    if sl is None:
        sl = etree.Element("slices")
        ED.insert_in_order(view, sl, list(ORD.VIEW_ORDER))
    if not any((c.text or "") == ref for c in sl.findall("column")):
        etree.SubElement(sl, "column").text = ref


def _order_expr(root, ws, by: str) -> str:
    """`SUM(sales)` -> `SUM([sales])`; an aggregate calculation stands by its own name."""
    func, f = F.parse(root, by, F.sheet_datasource(root, ws))
    if not func:
        return f"[{f.name}]" if aggregated(root, f) else f"SUM([{f.name}])"
    return f"{func}([{f.name}])"


def _measure_filter(root, ws, field: str, low, high) -> str:
    p = F.place(root, ws, field)
    view = ws.find("table/view")
    ED._replace_filter(view, p.ref)
    filt = etree.Element("filter")
    filt.set("class", "quantitative")
    filt.set("column", p.ref)
    filt.set("included-values", "in-range")
    if low not in (None, ""):
        etree.SubElement(filt, "min").text = str(low)
    if high not in (None, ""):
        etree.SubElement(filt, "max").text = str(high)
    ED.insert_in_order(view, filt, list(ORD.VIEW_ORDER))
    return p.ref


def _filters(root, ws, specs: list) -> None:
    name = ws.get("name")
    for spec in specs or []:
        col = spec.get("column") or spec.get("field")
        if not col:
            raise ValueError(f"filter without a field (`column`): {spec}")
        col = col.strip()
        if "top" in spec:
            got = ED.top_n_filter(root, name, col.strip("[]"),
                                  _order_expr(root, ws, spec.get("by") or ""),
                                  spec["top"], spec.get("direction") or "desc")
            if not got.get("ok"):
                raise ValueError(f"top filter on {col}: {got.get('why')}")
        elif spec.get("type") == "quantitative" or "min" in spec or "max" in spec:
            _, f = F.parse(root, col, F.sheet_datasource(root, ws))
            if f.role == "measure":
                _measure_filter(root, ws, col, spec.get("min"), spec.get("max"))
            else:
                got = ED.range_filter(root, name, f.name, spec.get("min"), spec.get("max"))
                if not got.get("ok"):
                    raise ValueError(f"range filter on {col}: {got.get('why')}")
        elif "values" in spec:
            _values_filter(root, ws, col, _as_list(spec["values"]))
        else:
            raise ValueError(f"filter {spec}: give values, top/by or min/max")


def aggregated(root, f: F.Field, seen=None) -> bool:
    """An aggregate formula, or one that refers to an aggregate calculation."""
    if not f.formula:
        return False
    if F.is_aggregate(f.formula):
        return True
    seen = seen or set()
    allf = F.fields(root)
    for tok in re.findall(r"\[([^\[\]]+)\]", f.formula):
        g = allf.get(tok)
        if g is not None and g.formula and g.name not in seen:
            seen.add(g.name)
            if aggregated(root, g, seen):
                return True
    return False


def _place(root, ws, expr: str, func: str = "") -> F.Placed:
    fn, f = F.parse(root, expr, F.sheet_datasource(root, ws))
    if not (func or fn) and f.role == "measure" and aggregated(root, f):
        func = "AGG"
    return F.place(root, ws, expr, func=func or fn)


def _sort(root, ws, expr: str, placed_rows: list, placed_cols: list, measures: list) -> None:
    fn, f = F.parse(root, expr, F.sheet_datasource(root, ws))
    dims = [p for p in placed_rows + placed_cols if p.discrete]
    if fn or f.role == "measure" or not dims or f.name not in {p.field.name for p in dims}:
        if not dims:
            raise ValueError("sort_descending needs a dimension on rows or columns")
        if not fn and f.role == "measure" and aggregated(root, f):
            fn = "AGG"
        dim, by, deriv = dims[-1], f, F.derivation(fn, f)[0]
    else:
        dim = next(p for p in dims if p.field.name == f.name)
        if not measures:
            raise ValueError(f"sort_descending={expr!r}: no measure to sort by")
        by, deriv = measures[0].field, measures[0].derivation
    got = ED.sort_by_measure(root, ws.get("name"), dim.field.name, by.name, "desc",
                             derivation=deriv)
    if not got.get("ok"):
        raise ValueError(f"sort_descending: {got.get('why')}")


# the chart ------------------------------------------------------------------------------

def configure(book, worksheet_name: str, mark_type: str = "Automatic",
              columns: list | None = None, rows: list | None = None, color: str | None = None,
              size: str | None = None, label: str | None = None, detail=None,
              wedge_size: str | None = None, sort_descending: str | None = None,
              tooltip=None, filters: list | None = None, geographic_field: str | None = None,
              measure_values: list | None = None, mark_sizing_off: bool = False,
              axis_fixed_range: dict | None = None, customized_label: str | None = None,
              color_map: dict | None = None, text_format: dict | None = None,
              label_extra: list | None = None, map_country: str | None = None,
              datasource: str = "") -> str:
    """Build the chart of a worksheet from shelves and encodings; replaces what was there.

    The sheet keeps the data source it is bound to; `datasource` (name or caption) picks another.
    """
    root = book.root
    if mark_type not in MARKS:
        raise ValueError(f"unknown mark_type {mark_type!r}; use one of {', '.join(MARKS)}")
    mark = MARKS[mark_type]
    if wedge_size and mark != "Pie":
        raise ValueError("wedge_size is for mark_type='Pie'")
    if text_format and not (label or measure_values or mark == "Text"):
        raise ValueError("text_format formats text and labels; this chart has none")
    ws = book.sheet(worksheet_name)
    ds = _source(book, datasource or ED._ds_name(ws), explicit=bool(datasource))
    _reset(ws)
    dsn = _bind(ws, ds)
    table = ws.find("table")
    pane = table.find("panes/pane")

    rows_p = [_place(root, ws, e) for e in _as_list(rows)]
    cols_p = [_place(root, ws, e) for e in _as_list(columns)]
    if measure_values:
        rows_p = [p for p in rows_p if p.discrete]
        cols_p = [p for p in cols_p if p.discrete]
    rows_items = [(p.ref, p.discrete) for p in rows_p]
    cols_items = [(p.ref, p.discrete) for p in cols_p]
    measures = [p for p in rows_p + cols_p if not p.discrete]

    if measure_values:
        mv = [_place(root, ws, m) for m in measure_values]
        names = f"[{dsn}].[:Measure Names]"
        if ds.find("column[@name='[:Measure Names]']") is None:
            c = etree.Element("column")
            for k, v in (("datatype", "string"), ("name", "[:Measure Names]"),
                         ("role", "dimension"), ("type", "nominal")):
                c.set(k, v)
            ED.insert_in_order(ds, c, list(ORD.DATASOURCE_ORDER))
        filt = etree.Element("filter")
        filt.set("class", "categorical")
        filt.set("column", names)
        union = etree.SubElement(filt, "groupfilter")
        union.set("function", "union")
        union.set(ED._u("ui-domain"), "database")
        union.set(ED._u("ui-enumeration"), "inclusive")
        union.set(ED._u("ui-marker"), "enumerate")
        for p in mv:
            g = etree.SubElement(union, "groupfilter")
            g.set("function", "member")
            g.set("level", "[:Measure Names]")
            g.set("member", f'"{p.ref}"')
        ED.insert_in_order(table.find("view"), filt, list(ORD.VIEW_ORDER))
        cols_items.append((names, True))
        _encode(pane, "text", f"[{dsn}].[Multiple Values]")
        measures += mv

    geo = None
    if geographic_field:
        geo = _map(book, ws, geographic_field, map_country, mark)
        mark = "Circle" if mark == "Circle" else "Multipolygon"
        rows_items.append((f"[{dsn}].{_LATLON[0]}", False))
        cols_items.append((f"[{dsn}].{_LATLON[1]}", False))
        if mark == "Multipolygon":
            _encode(pane, "geometry", f"[{dsn}].[Geometry (generated)]")
        pane.attrib.pop("selection-relaxation-option", None)

    table.find("rows").text = _shelf_text(rows_items) or None
    table.find("cols").text = _shelf_text(cols_items) or None
    pane.find("mark").set("class", mark)
    if mark == "Pie":
        pane.attrib.pop("selection-relaxation-option", None)

    color_p = None
    if color:
        color_p = _place(root, ws, color)
        _encode(pane, "color", color_p.ref)
    if size:
        p = _place(root, ws, size)
        _encode(pane, "size", p.ref)
        measures.append(p)
    if wedge_size:
        p = _place(root, ws, wedge_size)
        _encode(pane, "wedge-size", p.ref)
        measures.append(p)
    text_p = []
    for e in _as_list(label) + _as_list(label_extra):
        p = _place(root, ws, e)
        _encode(pane, "text", p.ref)
        text_p.append(p)
    if text_p:
        _mark_style(pane, mark_labels_show="true", mark_labels_cull="true")
    for e in _as_list(detail):
        _encode(pane, "lod", _place(root, ws, e).ref)
    if geo:
        for ref in geo:
            _encode(pane, "lod", ref)
    for e in _as_list(tooltip):
        fn, f = F.parse(root, e, dsn)
        p = _place(root, ws, e, func="" if fn or f.role == "measure" else "ATTR")
        _encode(pane, "tooltip", p.ref)
    if mark == "Pie":
        _mark_style(pane, size="1.8")
    if mark_sizing_off:
        ms = etree.Element("mark-sizing")
        ms.set("mark-sizing-setting", "marks-scaling-off")
        ED.insert_in_order(pane, ms, PANE_ORDER)

    _filters(root, ws, filters)
    if sort_descending:
        _sort(root, ws, sort_descending, rows_p, cols_p, measures + text_p)
    if axis_fixed_range:
        _axis_range(root, ws, axis_fixed_range, rows_p, cols_p)
    if customized_label:
        _custom_label(root, ws, pane, customized_label)
    if text_format:
        _text_format(root, ws, text_format, text_p + measures)
    if color_map:
        if color_p is None or not color_p.discrete:
            raise ValueError("color_map needs a dimension on color")
        _color_map(book, color_p, color_map)
    return f"Configured {worksheet_name!r} as {mark_type}"


def _map(book, ws, geo_field: str, country: str | None, mark: str) -> list:
    """Geographic roles and context of a map; returns the detail references."""
    from .schema import infer_geo_role
    root = book.root
    if mark not in ("Automatic", "Multipolygon", "Circle"):
        raise ValueError(f"a map needs mark_type Automatic, Map or Circle, not {mark}")
    ds = F.find_by(book.datasources, "datasource", "name", ED._ds_name(ws))
    _, f = F.parse(root, geo_field, ds.get("name"))
    col = F.find_by(ds, "column", "name", f"[{f.name}]")
    role = col.get("semantic-role") if col is not None else None
    if not role:
        role = infer_geo_role(f.name, f.datatype)
        if not role:
            raise ValueError(f"{geo_field!r} has no geographic role; set semantic_role")
        if col is not None:
            col.set("semantic-role", role)
    country_col = next((c for c in ds.findall("column")
                        if c.get("semantic-role") == _COUNTRY_ROLE
                        and c.get("name") != f"[{f.name}]"), None)
    if role in _NEEDS_COUNTRY and country_col is None and not country:
        raise ValueError(f"{geo_field!r} ({role}) needs a country context: a country column "
                         f"with a geographic role, or map_country")
    if country:
        sv = ds.find("semantic-values")
        if sv is None:
            sv = etree.Element("semantic-values")
            ED.insert_in_order(ds, sv, list(ORD.DATASOURCE_ORDER))
        for old in list(sv):
            if old.get("key") == _COUNTRY_ROLE:
                sv.remove(old)
        v = etree.SubElement(sv, "semantic-value")
        v.set("key", _COUNTRY_ROLE)
        v.set("value", f'"{country}"')
    refs = [F.place(root, ws, f.name).ref]
    if country_col is not None:
        refs.append(F.place(root, ws, country_col.get("name").strip("[]")).ref)
    view = ws.find("table/view")
    if view.find("mapsources") is None:
        ms = etree.Element("mapsources")
        etree.SubElement(ms, "mapsource").set("name", "Tableau")
        ED.insert_in_order(view, ms, list(ORD.VIEW_ORDER))
    from .book import child
    wms = child(root, "mapsources")
    if wms.find("mapsource") is None:
        etree.SubElement(wms, "mapsource").set("name", "Tableau")
    return refs


def _axis_range(root, ws, spec: dict, rows_p: list, cols_p: list) -> None:
    scope = spec.get("scope")
    if spec.get("field"):
        p = _place(root, ws, spec["field"])
        on = "rows" if any(q.ref == p.ref for q in rows_p) else \
            "cols" if any(q.ref == p.ref for q in cols_p) else ""
        if not on:
            raise ValueError(f"axis_fixed_range: {spec['field']!r} is not an axis of this sheet")
        scope = scope or on
    else:
        pool = rows_p if scope == "rows" else cols_p if scope == "cols" else rows_p + cols_p
        p = next((q for q in pool if not q.discrete), None)
        if p is None:
            raise ValueError("axis_fixed_range: no measure axis on the sheet")
        scope = scope or ("rows" if p in rows_p else "cols")
    rule = _table_rule(ws, "axis")
    enc = etree.SubElement(rule, "encoding")
    for k, v in (("attr", "space"), ("class", "0"), ("field", p.ref),
                 ("field-type", "quantitative"), ("max", spec.get("max")),
                 ("min", spec.get("min")), ("range-type", "fixed"), ("scope", scope),
                 ("type", "space")):
        if v is not None:
            enc.set(k, str(v))


def _custom_label(root, ws, pane, template: str) -> None:
    on_sheet = {ci.get("name") for ci in ws.iter("column-instance")}
    used = {e.get("column") for e in pane.iter() if e.get("column")}
    ft = etree.Element("formatted-text")
    pos = 0
    for m in _FIELD_IN_TEXT.finditer(template):
        if m.start() > pos:
            etree.SubElement(ft, "run").text = template[pos:m.start()]
        try:
            fn, f = F.parse(root, m.group(1), F.sheet_datasource(root, ws))
        except ValueError as exc:
            raise ValueError(f"customized_label: {exc}") from None
        deriv, kind = F.derivation(fn, f)
        inst = f"[{ED._DERIV_PREFIX.get(deriv, deriv.lower())}:{f.name}:{kind}]"
        ref = f"[{F.sheet_datasource(root, ws)}].{inst}"
        if inst not in on_sheet or ref not in used:
            raise ValueError(f"customized_label: <{m.group(1)}> is not on this sheet; "
                             f"put it on label or label_extra first")
        for part in ("<", ref, ">"):
            etree.SubElement(ft, "run").text = part
        pos = m.end()
    if pos < len(template):
        etree.SubElement(ft, "run").text = template[pos:]
    cl = etree.Element("customized-label")
    cl.append(ft)
    ED.insert_in_order(pane, cl, PANE_ORDER)


def _text_format(root, ws, spec: dict, placed: list) -> None:
    refs = {p.ref for p in placed}
    rule = _table_rule(ws, "cell")
    for expr, mask in spec.items():
        p = _place(root, ws, expr)
        if p.ref not in refs:
            raise ValueError(f"text_format: {expr!r} is not on the sheet's text")
        _format(rule, "text-format", mask, field=p.ref)


def _color_map(book, p: F.Placed, mapping: dict) -> None:
    """Fixed colors of a dimension's values; the palette lives in the data source."""
    ds = F.find_by(book.datasources, "datasource", "name", p.ref[1:].split("].", 1)[0])
    if F.find_by(ds, "column-instance", "name", p.instance) is None:
        ci = etree.Element("column-instance")
        for k, v in (("column", f"[{p.field.name}]"), ("derivation", p.derivation),
                     ("name", p.instance), ("pivot", "key"),
                     ("type", F.KIND_TYPE[p.instance.rsplit(':', 1)[1][:2]])):
            ci.set(k, v)
        ED.insert_in_order(ds, ci, list(ORD.DATASOURCE_ORDER))
    style = ds.find("style")
    if style is None:
        style = etree.Element("style")
        ED.insert_in_order(ds, style, list(ORD.DATASOURCE_ORDER))
    rule = next((r for r in style.findall("style-rule") if r.get("element") == "mark"), None)
    if rule is None:
        rule = etree.SubElement(style, "style-rule")
        rule.set("element", "mark")
    for old in rule.findall("encoding"):
        if old.get("attr") == "color" and old.get("field") == p.instance:
            rule.remove(old)
    enc = etree.SubElement(rule, "encoding")
    enc.set("attr", "color")
    enc.set("field", p.instance)
    enc.set("type", "palette")
    for value, colour in mapping.items():
        m = etree.SubElement(enc, "map")
        m.set("to", colour)
        etree.SubElement(m, "bucket").text = _member(p.field, value)


# dual axis, style, reference lines ---------------------------------------------------------

def dual_axis(book, worksheet_name: str, mark_type_1: str = "Bar", mark_type_2: str = "Line",
              columns: list | None = None, rows: list | None = None,
              dual_axis_shelf: str = "rows", color_1: str | None = None,
              size_1: str | None = None, label_1: str | None = None, detail_1: str | None = None,
              color_2: str | None = None, size_2: str | None = None, label_2: str | None = None,
              detail_2: str | None = None, synchronized: bool = True,
              sort_descending: str | None = None, filters: list | None = None,
              show_labels: bool = True, hide_axes: bool = False, hide_zeroline: bool = False,
              mark_color_1: str | None = None, mark_color_2: str | None = None,
              color_map_1: dict | None = None, datasource: str = "") -> str:
    """Two measures on one shelf drawn on a shared (or dual) axis with their own marks."""
    for m in (mark_type_1, mark_type_2):
        if m not in MARKS:
            raise ValueError(f"unknown mark type {m!r}")
    shelf = "rows" if dual_axis_shelf == "rows" else "cols"
    dual = _as_list(rows if shelf == "rows" else columns)
    other = _as_list(columns if shelf == "rows" else rows)
    root = book.root
    configure(book, worksheet_name, mark_type="Automatic", rows=None, columns=None,
              datasource=datasource)
    ws = book.sheet(worksheet_name)
    table = ws.find("table")
    dual_p = [_place(root, ws, e) for e in dual]
    meas = [p for p in dual_p if not p.discrete]
    if len(meas) != 2:
        raise ValueError(f"a dual axis needs exactly two measures on {shelf}, got {len(meas)}")
    other_p = [_place(root, ws, e) for e in other]
    table.find(shelf).text = _shelf_text([(p.ref, p.discrete) for p in dual_p])
    table.find("cols" if shelf == "rows" else "rows").text = (
        _shelf_text([(p.ref, p.discrete) for p in other_p]) or None)
    panes = table.find("panes")
    for p in list(panes):
        panes.remove(p)
    base = _pane(panes, "Automatic")
    _mark_style(base, mark_labels_cull="true", mark_labels_show=str(show_labels).lower())
    axis_attr = "y-axis-name" if shelf == "rows" else "x-axis-name"
    specs = ((mark_type_1, color_1, size_1, label_1, detail_1, mark_color_1),
             (mark_type_2, color_2, size_2, label_2, detail_2, mark_color_2))
    color_ps = []
    for i, (p, (mk, col, sz, lab, det, solid)) in enumerate(zip(meas, specs), start=1):
        pane = _pane(panes, MARKS[mk], str(i), (axis_attr, p.ref))
        cp = None
        if col:
            cp = _place(root, ws, col)
            _encode(pane, "color", cp.ref)
        color_ps.append(cp)
        if sz:
            _encode(pane, "size", _place(root, ws, sz).ref)
        if lab:
            _encode(pane, "text", _place(root, ws, lab).ref)
        if det:
            _encode(pane, "lod", _place(root, ws, det).ref)
        fmts = {"mark_labels_show": str(show_labels).lower(), "mark_labels_cull": "true"}
        if solid:
            fmts["mark_color"] = solid
        _mark_style(pane, **fmts)
    rule = _table_rule(ws, "axis")
    for cls, p in ((1, meas[0]), (0, meas[1])):
        enc = etree.SubElement(rule, "encoding")
        for k, v in (("attr", "space"), ("class", str(cls)), ("field", p.ref),
                     ("field-type", "quantitative"), ("fold", "true"), ("scope", shelf),
                     ("synchronized", "true" if synchronized else None), ("type", "space")):
            if v is not None:
                enc.set(k, v)
    if hide_axes:
        _format(_table_rule(ws, "axis"), "display", "false")
    if hide_zeroline:
        z = _table_rule(ws, "zeroline")
        _format(z, "line-visibility", "off")
    _filters(root, ws, filters)
    if sort_descending:
        _sort(root, ws, sort_descending, other_p if shelf == "cols" else [],
              other_p if shelf == "rows" else [], meas)
    if color_map_1:
        if color_ps[0] is None or not color_ps[0].discrete:
            raise ValueError("color_map_1 needs a dimension on color_1")
        _color_map(book, color_ps[0], color_map_1)
    return f"Configured {worksheet_name!r} as a dual axis ({mark_type_1} + {mark_type_2})"


def style(book, worksheet_name: str, background_color: str | None = None,
          hide_axes: bool = False, hide_gridlines: bool = False, hide_zeroline: bool = False,
          hide_borders: bool = False, hide_band_color: bool = False,
          hide_row_label: str | None = None, hide_col_field_labels: bool = False,
          hide_row_field_labels: bool = False, disable_tooltip: bool = False,
          label_formats: list | None = None, cell_formats: list | None = None,
          header_formats: list | None = None) -> str:
    """Sheet-level formatting: background, axes, grid, borders, bands, field labels, fonts."""
    ws = book.sheet(worksheet_name)
    if background_color:
        _format(_table_rule(ws, "table"), "background-color", background_color)
    if hide_axes:
        _format(_table_rule(ws, "axis"), "display", "false")
    if hide_gridlines:
        _format(_table_rule(ws, "gridline"), "line-visibility", "off")
    if hide_zeroline:
        z = _table_rule(ws, "zeroline")
        _format(z, "line-visibility", "off")
        _format(z, "stroke-size", "0")
    if hide_borders:
        for el in ("header", "pane"):
            r = _table_rule(ws, el)
            _format(r, "border-width", "0")
            _format(r, "border-style", "none")
    if hide_band_color:
        _format(_table_rule(ws, "pane"), "band-color", "#00000000")
    if hide_row_label:
        ED.hide_header(book.root, worksheet_name, hide_row_label)
    for flag, scope in ((hide_col_field_labels, "cols"), (hide_row_field_labels, "rows")):
        if flag:
            _format(_table_rule(ws, "worksheet"), "display-field-labels", "false", scope=scope)
    for element, items in (("label", label_formats), ("cell", cell_formats),
                           ("header", header_formats)):
        for item in items or []:
            for attr, value in item.items():
                _format(_table_rule(ws, element), attr, value)
    if disable_tooltip:
        table = ws.find("table")
        ts = table.find("tooltip-style")
        if ts is None:
            ts = etree.Element("tooltip-style")
            ED.insert_in_order(table, ts, TABLE_ORDER)
        ts.set("tooltip-mode", "none")
    return f"Styled {worksheet_name!r}"


def reference_line(book, worksheet_name: str, *, axis_field: str, value_field: str,
                   scope: str = "per-pane", formula: str = "average", label_type: str = "value",
                   tooltip: str = "", pane_index: int = 0) -> str:
    """A reference line on a measure axis: average, max, min, median, sum, total.

    `tooltip` is accepted and not written: Tableau refuses a file whose reference line carries
    `tooltip` or `tooltip-type`.
    """
    root = book.root
    ws = book.sheet(worksheet_name)
    if scope not in ("per-pane", "per-table", "per-cell"):
        raise ValueError(f"scope {scope!r}: use per-pane, per-table or per-cell")
    axis = _place(root, ws, axis_field)
    value = _place(root, ws, value_field)
    panes = ws.findall("table/panes/pane")
    if not panes:
        raise ValueError("the sheet has no panes; configure the chart first")
    pane = panes[min(pane_index, len(panes) - 1)]
    taken = {r.get("id") for r in ws.iter("reference-line")}
    n = 0
    while f"refline{n}" in taken:
        n += 1
    rl = etree.Element("reference-line")
    for k, v in (("axis-column", axis.ref), ("enable-instant-analytics", "true"),
                 ("formula", formula), ("id", f"refline{n}"), ("label-type", label_type),
                 ("probability", "95"), ("scope", scope), ("value-column", value.ref),
                 ("z-order", "1")):
        rl.set(k, v)
    ED.insert_in_order(pane, rl, PANE_ORDER)
    return f"Added a {formula} reference line to {worksheet_name!r}"

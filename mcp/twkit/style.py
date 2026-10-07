"""House style — EXTRACTED from 25 of the owner's working books, not invented."""
from . import fields as F

FILE_EXT = ".twbx"


def out_path(name: str, out_dir: str = "") -> str:
    """Output path for a workbook (.twbx)."""
    import os as _os
    base = name[:-5] if name.endswith(".twbx") else (name[:-4] if name.endswith(".twb") else name)
    return _os.path.join(out_dir, base + FILE_EXT) if out_dir else base + FILE_EXT


PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    "#a0cbe8", "#ffbe7d", "#8cd17d", "#86bcb6", "#f1ce63",
    "#d37295", "#fabfd2", "#b6992d", "#499894", "#79706e",
]
SERIES = PALETTE[0]
ACCENT = PALETTE[1]
NEGATIVE = PALETTE[2]
NEUTRAL = "#bab0ac"

BAND_COLOR = "#eef1f3"
SURFACE = "#ffffff"
TRANSPARENT = "#00000000"

FMT = {
    "pct1":      "p0.0%",
    "pct2":      "p0.00%",
    "pct0":      "p0%",
    "int":       "n#,##0;-#,##0",
    "dec1":      "n#,##0.0;-#,##0.0",
    "eur":       'c"€ "#,##0;"€ "-#,##0',
    "thousands": "n#,##0,K;-#,##0,K",
    "eur_k":     'c"€ "#,##0,K;"€ "-#,##0,K',
    "eur_m":     'c"€ "#,##0,,M;"€ "-#,##0,,M',
    "eur_fin":   'c"€ "#,##0;("€ "#,##0)',
    "eur_fin_k": 'c"€ "#,##0,K;("€ "#,##0,K)',
    "eur_fin_b": 'c"€ "#,##0,,,B;("€ "#,##0,,,B)',
    "delta_arrow": "*↑ #,##0.0%;↓ #,##0.0%; ",
    "delta_sign":  "*+0.0%;-0.0%",
    "date":      "*dd.mm.yyyy",
    "date_long": "*d mmmm yyyy",
    "date_mmm":  "*dd mmm yyyy",
}

FONT_SIZES = {"kpi": "22", "title": "16", "label": "11", "body": "10"}

SIZING = "range"
SIZE_RANGE = {"minwidth": 1100, "maxwidth": 3200, "minheight": 800, "maxheight": 1900}

PARAM_DATE_FROM = "p_start_dt"
PARAM_DATE_TO = "p_end_dt"
PARAM_PERIOD = "p_period_granuality"
PARAM_DIM = "p_dim{}"
PARAM_METRIC = "p_metric"

PERIOD_VALUES = ["day", "week", "month", "quarter", "year"]
NO_DIM = " "


def date_range_params(editor, start: str, end: str) -> None:
    """The p_start_dt / p_end_dt date parameter pair."""
    editor.add_parameter(PARAM_DATE_FROM, datatype="date", domain_type="any",
                         default_value=start, default_format=FMT["date"])
    editor.add_parameter(PARAM_DATE_TO, datatype="date", domain_type="any",
                         default_value=end, default_format=FMT["date"])


def period_param(editor, default: str = "day") -> None:
    """Date granularity switcher parameter."""
    editor.add_parameter(PARAM_PERIOD, datatype="string", domain_type="list",
                         default_value=default, allowed_values=PERIOD_VALUES)


def dim_param(editor, idx: int, dims: list[str], default: str = NO_DIM) -> str:
    """Dimension switcher parameter p_dimN."""
    name = PARAM_DIM.format(idx)
    editor.add_parameter(name, datatype="string", domain_type="list",
                         default_value=default, allowed_values=[NO_DIM] + dims)
    return name


def switcher(param: str, mapping: dict[str, str], default: str = "NULL") -> str:
    """Switcher formula: IF [Parameters].[p] = 'X' THEN <expr> ELSEIF ..."""
    items = list(mapping.items())
    head = f"IF [Parameters].[{param}] = '{items[0][0]}' THEN {items[0][1]}"
    mid = "".join(f"\nELSEIF [Parameters].[{param}] = '{k}' THEN {v}" for k, v in items[1:])
    return f"{head}{mid}\nELSE {default}\nEND"


def period_trunc(field: str, param: str = PARAM_PERIOD) -> str:
    """DATETRUNC by the selected granularity, companion of period_param."""
    return f"DATE(DATETRUNC([Parameters].[{param}], [{field}]))"


def date_filter(field: str) -> str:
    """Boolean filter on the date parameter pair (goes on the Filters shelf)."""
    return (f"[{field}] >= [Parameters].[{PARAM_DATE_FROM}] "
            f"AND [{field}] <= [Parameters].[{PARAM_DATE_TO}]")


def control_panel(params: list[str], filters: list[dict] | None = None,
                  width: int = 260) -> dict:
    """Left control panel: parameters on top, filters below."""
    children: list[dict] = [
        {"type": "paramctrl", "parameter": p, "fixed_size": 62} for p in params
    ]
    for f in filters or []:
        children.append({"type": "filter", **f, "fixed_size": 90})
    children.append({"type": "empty"})
    return {"type": "container", "direction": "vertical",
            "fixed_size": width, "style": {"background-color": SURFACE},
            "children": children}


FILTER_CARD = {"background-color": "#f5f1f0", "border-color": "#d7b5a6",
               "border-width": "2", "border-style": "solid"}
TITLE_BLUE = "#011993"
SUBTOTAL_BG = "#f0f3fa"


def filter_cards(editor, sheet: str, titles: dict[str, str] | None = None) -> int:
    """Filter cards on a sheet: border, background, own title."""
    from lxml import etree

    ws = editor.sheet(sheet)
    table = ws.find("table")
    if table is None:
        return 0
    holder = table.find("style")
    if holder is None:
        holder = etree.SubElement(table, "style")
    rule = next((r for r in holder.findall("style-rule")
                 if r.get("element") == "quick-filter"), None)
    if rule is None:
        rule = etree.SubElement(holder, "style-rule")
        rule.set("element", "quick-filter")
    for field, caption in (titles or {}).items():
        try:
            ref = F.reference(editor.root, field)
        except Exception:
            continue
        fmt = etree.SubElement(rule, "format")
        fmt.set("attr", "title")
        fmt.set("field", ref)
        fmt.set("value", caption)
        ft = etree.SubElement(fmt, "formatted-text")
        etree.SubElement(ft, "run").text = caption
    for attr, value in FILTER_CARD.items():
        fmt = etree.SubElement(rule, "format")
        fmt.set("attr", attr)
        fmt.set("value", value)
    return len(rule.findall("format"))


def period_title(editor, sheet: str, pairs: list[tuple[str, str]],
                 *, label: str = "", color: str = TITLE_BLUE, size: str = "10") -> None:
    """Dynamic sheet title 'date - date vs date - date' from parameters."""
    from lxml import etree

    ws = editor.sheet(sheet)
    opts = ws.find("layout-options")
    if opts is None:
        opts = etree.Element("layout-options")
        ws.insert(0, opts)
    old = opts.find("title")
    if old is not None:
        opts.remove(old)
    title = etree.SubElement(opts, "title")
    ft = etree.SubElement(title, "formatted-text")

    def run(text: str, *, tone: str = "", bold: bool = False) -> None:
        r = etree.SubElement(ft, "run")
        r.set("fontcolor", tone or color)
        r.set("fontname", "Tableau Bold" if bold else "Tableau Medium")
        r.set("fontsize", size)
        r.text = text

    if label:
        run(label + "   ", tone="#000000", bold=True)
    for i, (start, end) in enumerate(pairs):
        run("   vs   " if i else "")
        run("<")
        run(f"[Parameters].[{start}]")
        run("> - <")
        run(f"[Parameters].[{end}]")
        run(">")


def value_color(editor, sheet: str) -> bool:
    """Table text color by the value itself (`[Multiple Values]`)."""
    from lxml import etree

    ws = editor.sheet(sheet)
    pane = ws.find("table/panes/pane")
    if pane is None:
        return False
    ds_name = ""
    for ds in ws.iter("datasource"):
        if (ds.get("name") or "").startswith("federated."):
            ds_name = ds.get("name")
            break
    if not ds_name:
        return False
    enc = pane.find("encodings")
    if enc is None:
        enc = etree.SubElement(pane, "encodings")
    if enc.find("color") is not None:
        return True
    color = etree.Element("color")
    color.set("column", f"[{ds_name}].[Multiple Values]")
    enc.insert(0, color)
    return True


PARAM_CARD = {"background-color": "#f5f1f0", "border-color": "#d7b5a6",
              "border-width": "2", "border-style": "solid"}

_DASH_ORDER = ("layout-options", "repository-location", "style", "size", "datasources",
               "datasource-dependencies", "zones", "devicelayouts", "simple-id")


def param_cards(editor, dashboard: str) -> int:
    """Parameter control cards on a page: border and background."""
    from lxml import etree

    dash = next((d for d in editor.root.iter("dashboard")
                 if d.get("name") == dashboard), None)
    if dash is None:
        return 0
    holder = dash.find("style")
    if holder is None:
        holder = etree.Element("style")
        rank = {t: i for i, t in enumerate(_DASH_ORDER)}
        after = next((c for c in dash if rank.get(c.tag, len(_DASH_ORDER))
                      > rank["style"]), None)
        if after is not None:
            after.addprevious(holder)
        else:
            dash.append(holder)
    rule = next((r for r in holder.findall("style-rule")
                 if r.get("element") == "parameter-ctrl"), None)
    if rule is None:
        rule = etree.SubElement(holder, "style-rule")
        rule.set("element", "parameter-ctrl")
    for attr, value in PARAM_CARD.items():
        fmt = etree.SubElement(rule, "format")
        fmt.set("attr", attr)
        fmt.set("value", value)
    return len(rule.findall("format"))


TREND_COLORS = {"Up": "#4a7ba7", "Down": "#b0564f", "Flat": "#8a8a8a"}

MEASURE_COLORS = {"P1": "#4a7ba7", "P2": "#4a7ba7",
                  "Δ": "#4f8a5b", "Δ %": "#c4813c"}

DELTA_TREND = {"Up": "#4f8a5b", "Down": "#c4813c", "Flat": "#8a8a8a"}

DELTA_INK = "#8a5a52"

PAGE_BG = "#f7f5f3"

BAND_WARM = "#f6f1ef"


def trend_color(editor, sheet: str, field: str = "",
                colors: dict[str, str] | None = None) -> bool:
    """Table text color by delta direction (`field`) or by value."""
    from lxml import etree

    ws = editor.sheet(sheet)
    pane = ws.find("table/panes/pane")
    if pane is None:
        return False
    ds_name = ""
    for ds in ws.iter("datasource"):
        if (ds.get("name") or "").startswith("federated."):
            ds_name = ds.get("name")
            break
    if not ds_name:
        return False
    if field:
        try:
            ref = F.reference(editor.root, field)
        except Exception:
            return False
    else:
        ref = f"[{ds_name}].[Multiple Values]"
    enc = pane.find("encodings")
    if enc is None:
        enc = etree.SubElement(pane, "encodings")
    if enc.find("color") is not None:
        return True
    color = etree.Element("color")
    color.set("column", ref)
    enc.insert(0, color)

    if not (field and colors):
        return True
    ds = next((d for d in editor.root.iter("datasource")
               if d.get("name") == ds_name), None)
    if ds is None:
        return True
    holder = ds.find("style")
    if holder is None:
        holder = etree.Element("style")
        after = next((ds.find(t) for t in ("semantic-values", "date-options",
                                           "default-date-format", "default-sorts",
                                           "object-graph")
                      if ds.find(t) is not None), None)
        if after is not None:
            after.addprevious(holder)
        else:
            ds.append(holder)
    rule = next((r for r in holder.findall("style-rule")
                 if r.get("element") == "mark"), None)
    if rule is None:
        rule = etree.SubElement(holder, "style-rule")
        rule.set("element", "mark")
    holders = [rule]
    ws_table = ws.find("table")
    if ws_table is not None:
        ws_style = ws_table.find("style")
        if ws_style is None:
            ws_style = etree.SubElement(ws_table, "style")
        ws_rule = next((r for r in ws_style.findall("style-rule")
                        if r.get("element") == "mark"), None)
        if ws_rule is None:
            ws_rule = etree.SubElement(ws_style, "style-rule")
            ws_rule.set("element", "mark")
        holders.append(ws_rule)
    for target in holders:
        if any(e.get("field") == ref for e in target.findall("encoding")):
            continue
        enc_el = etree.SubElement(target, "encoding")
        enc_el.set("attr", "color")
        enc_el.set("field", ref)
        enc_el.set("type", "palette")
        for bucket, hexc in colors.items():
            m = etree.SubElement(enc_el, "map")
            m.set("to", hexc)
            etree.SubElement(m, "bucket").text = f'"{bucket}"'
    return True


def field_colors(editor, sheet: str, colors: dict[str, str]) -> int:
    """Text color for individual measures of a table."""
    from lxml import etree

    ws = editor.sheet(sheet)
    table = ws.find("table")
    if table is None:
        return 0
    ds_name = ""
    for ds in ws.iter("datasource"):
        if (ds.get("name") or "").startswith("federated."):
            ds_name = ds.get("name")
            break
    if not ds_name:
        return 0
    by_caption = {}
    for col in editor.root.iter("column"):
        cap = col.get("caption")
        if cap and col.find("calculation") is not None:
            by_caption.setdefault(cap, (col.get("name") or "").strip("[]"))

    holder = table.find("style")
    if holder is None:
        holder = etree.SubElement(table, "style")
    rule = next((r for r in holder.findall("style-rule")
                 if r.get("element") == "cell"), None)
    if rule is None:
        rule = etree.SubElement(holder, "style-rule")
        rule.set("element", "cell")
    done = 0
    for caption, hexc in colors.items():
        inner = by_caption.get(caption)
        if not inner:
            continue
        fmt = etree.SubElement(rule, "format")
        fmt.set("attr", "color")
        fmt.set("field", f"[{ds_name}].[usr:{inner}:qk]")
        fmt.set("value", hexc)
        done += 1
    return done


def measure_colors(editor, sheet: str, colors: dict[str, str]) -> int:
    """Color by table columns: `[:Measure Names]` on the color shelf."""
    from lxml import etree

    ws = editor.sheet(sheet)
    table = ws.find("table")
    if table is None:
        return 0
    ds_name = ""
    for ds in ws.iter("datasource"):
        if (ds.get("name") or "").startswith("federated."):
            ds_name = ds.get("name")
            break
    if not ds_name:
        return 0
    by_caption = {}
    for col in editor.root.iter("column"):
        cap = col.get("caption")
        if cap and col.find("calculation") is not None:
            by_caption.setdefault(cap, (col.get("name") or "").strip("[]"))

    pane = table.find("panes/pane")
    if pane is None:
        return 0
    enc = pane.find("encodings")
    if enc is None:
        enc = etree.SubElement(pane, "encodings")
    if enc.find("color") is None:
        color = etree.Element("color")
        color.set("column", f"[{ds_name}].[:Measure Names]")
        enc.insert(0, color)

    targets = []
    holder = table.find("style")
    if holder is None:
        holder = etree.SubElement(table, "style")
    targets.append(holder)
    ds_el = next((d for d in editor.root.iter("datasource")
                  if d.get("name") == ds_name), None)
    if ds_el is not None:
        ds_style = ds_el.find("style")
        if ds_style is None:
            ds_style = etree.Element("style")
            after = next((ds_el.find(t) for t in ("semantic-values", "date-options",
                                                  "default-date-format", "object-graph")
                          if ds_el.find(t) is not None), None)
            if after is not None:
                after.addprevious(ds_style)
            else:
                ds_el.append(ds_style)
        targets.append(ds_style)

    done = 0
    for holder_el in targets:
        rule = next((r for r in holder_el.findall("style-rule")
                     if r.get("element") == "mark"), None)
        if rule is None:
            rule = etree.SubElement(holder_el, "style-rule")
            rule.set("element", "mark")
        if any(e.get("attr") == "color" for e in rule.findall("encoding")):
            continue
        enc_el = etree.SubElement(rule, "encoding")
        enc_el.set("attr", "color")
        enc_el.set("field", f"[{ds_name}].[:Measure Names]")
        enc_el.set("type", "palette")
        for caption, hexc in colors.items():
            inner = by_caption.get(caption)
            if not inner:
                continue
            m = etree.SubElement(enc_el, "map")
            m.set("to", hexc)
            etree.SubElement(m, "bucket").text = f'"[{ds_name}].[usr:{inner}:qk]"'
            done += 1
    return done


def table_grid(editor, sheet: str, *, font_size: str = "9",
               band_color: str = BAND_WARM, hide_row_label: str = "") -> None:
    """Table grid: no borders, zebra rows, no field labels."""
    editor.configure_worksheet_style(
        sheet,
        background_color=SURFACE,
        hide_gridlines=True,
        hide_band_color=False,
        hide_col_field_labels=True,
        hide_row_field_labels=True,
        cell_formats=[{"border-style": "none"}, {"border-width": "0"},
                      {"font-size": font_size}],
        header_formats=[{"border-style": "none"}, {"border-width": "0"},
                        {"font-size": font_size}],
        label_formats=[{"font-size": font_size}],
        hide_row_label=hide_row_label or None,
    )
    if band_color:
        row_bands(editor.sheet(sheet), band_color)

    ws = editor.sheet(sheet)
    table = ws.find("table")
    holder = table.find("style") if table is not None else None
    for rule in (holder.findall("style-rule") if holder is not None else []):
        seen = {}
        for fmt in list(rule.findall("format")):
            if fmt.get("field"):
                continue
            key = fmt.get("attr")
            if key in seen:
                rule.remove(seen[key])
            seen[key] = fmt


def _table_rule(ws, element: str):
    """`<style-rule element=…>` of a worksheet table, created when missing."""
    from lxml import etree as _et
    tbl = ws.find("table")
    if tbl is None:
        return None
    st = tbl.find("style")
    if st is None:
        st = _et.Element("style")
        panes = tbl.find("panes")
        (panes.addprevious(st) if panes is not None else tbl.append(st))
    rule = next((r for r in st.findall("style-rule") if r.get("element") == element), None)
    if rule is None:
        rule = _et.SubElement(st, "style-rule")
        rule.set("element", element)
    return rule


def row_bands(ws, color: str = BAND_WARM, size: str = "1") -> None:
    """Zebra rows on a text table."""
    from lxml import etree as _et
    for element, attr, value in (("header", "band-color", color),
                                 ("pane", "band-color", color),
                                 ("table", "band-size", size)):
        rule = _table_rule(ws, element)
        if rule is None:
            return
        for f in list(rule.findall("format")):
            if f.get("attr") == attr and f.get("scope") == "rows" and not f.get("field"):
                rule.remove(f)
        fmt = _et.SubElement(rule, "format")
        fmt.set("attr", attr)
        fmt.set("scope", "rows")
        fmt.set("value", value)


def uniform_type(ws, size: str = "10", family: str = "Tableau Book") -> None:
    """One font family and size for cells, headers and labels of a text table."""
    from lxml import etree as _et
    for element in ("cell", "header", "label"):
        rule = _table_rule(ws, element)
        if rule is None:
            return
        for f in list(rule.findall("format")):
            if f.get("attr") in ("font-size", "font-family") and not f.get("field"):
                rule.remove(f)
        for attr, value in (("font-size", size), ("font-family", family)):
            fmt = _et.Element("format")
            fmt.set("attr", attr)
            fmt.set("value", value)
            rule.insert(0, fmt)


def style_sheet(editor, name: str, *, bands: bool = False) -> None:
    """Uniform sheet look: quiet grid, no borders; bands only for tables."""
    editor.configure_worksheet_style(
        name,
        background_color=SURFACE,
        hide_gridlines=True,
        hide_borders=True,
        hide_band_color=not bands,
        hide_col_field_labels=True,
        hide_row_field_labels=True,
    )


def apply_sizing(editor, mode: str = SIZING, rng: dict | None = None) -> None:
    """A dashboard that stretches with the window."""
    editor.dashboard_sizing = mode
    editor.dashboard_size_range = rng or SIZE_RANGE

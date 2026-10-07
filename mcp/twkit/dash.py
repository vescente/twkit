"""Dashboards: a layout tree becomes zones; controls, legends and actions."""
from __future__ import annotations

import copy
import json
import os

from lxml import etree

from . import edit as ED
from . import fields as F
from . import order as ORD

UNITS = 100000
NODES = ("container", "horizontal", "vertical", "worksheet", "text", "title", "paramctrl",
         "filter", "color", "empty", "blank")
TEXT_COLOR = "#111e29"
_NO_BORDER = {"border-color": "#000000", "border-style": "none", "border-width": "0"}
_CONTROL_BG = {"background-color": "#ffffff"}
_ZONE_ORDER = ["formatted-text", "layout-cache", "zone", "button", "zone-style"]
# A sheet's fit on a page: how its zone scales (height, width), and Entire View in the viewpoint.
_CACHE = {"entire-view": ("scalable", "scalable"), "fit-width": ("cell", "scalable"),
          "fit-height": ("scalable", "cell")}
_DASH_ORDER = ["layout-options", "repository-location", "style", "size", "datasources",
               "datasource-dependencies", "zones", "devicelayouts", "simple-id"]


def _preset(layout: str, names: list) -> dict:
    sheet = [{"type": "worksheet", "name": n, "weight": 1} for n in names]
    if layout in ("auto", "vertical"):
        return {"type": "container", "direction": "vertical", "children": sheet}
    if layout == "horizontal":
        return {"type": "container", "direction": "horizontal", "children": sheet}
    if layout == "grid-2x2":
        rows = [sheet[i:i + 2] for i in range(0, len(sheet), 2)]
        return {"type": "container", "direction": "vertical", "children": [
            {"type": "container", "direction": "horizontal", "weight": 1, "children": r}
            for r in rows]}
    if os.path.exists(layout):
        from .conn import safe_source
        layout = safe_source(layout, (".json", ".yaml", ".yml"))
        with open(layout, encoding="utf-8") as f:
            if layout.lower().endswith((".yaml", ".yml")):
                import yaml
                return yaml.safe_load(f)
            return json.load(f)
    raise ValueError(f"layout {layout!r}: use auto, vertical, horizontal, grid-2x2, a dict "
                     f"or a JSON/YAML file")


def _check(node: dict, sheets: set, path: str = "layout") -> None:
    kind = node.get("type")
    if kind not in NODES:
        raise ValueError(f"unknown layout node type {kind!r} at {path}; use one of "
                         f"{', '.join(NODES)}")
    if kind == "worksheet" and node.get("name") not in sheets:
        raise ValueError(f"{path}: no worksheet {node.get('name')!r} in the workbook")
    if kind in ("filter", "color") and node.get("worksheet") not in sheets:
        raise ValueError(f"{path}: {kind} needs an existing worksheet, "
                         f"got {node.get('worksheet')!r}")
    for i, ch in enumerate(node.get("children") or []):
        _check(ch, sheets, f"{path}.children[{i}]")


class _Ids:
    def __init__(self, start: int = 3):
        self.n = start - 1

    def __call__(self) -> str:
        self.n += 1
        return str(self.n)


def _style(zone, fmt: dict) -> None:
    st = zone.find("zone-style")
    if st is None:
        st = etree.Element("zone-style")
        ED.insert_in_order(zone, st, _ZONE_ORDER)
    for attr, value in fmt.items():
        f = etree.SubElement(st, "format")
        f.set("attr", attr)
        f.set("value", value)


def _box(z, x: int, y: int, w: int, h: int) -> None:
    for k, v in (("x", x), ("y", y), ("w", w), ("h", h)):
        z.set(k, str(int(v)))


def _split(children: list, extent: int, px_total: int) -> list:
    """Sizes along the flow: fixed children keep their pixels, the rest share by weight."""
    fixed = [round(int(c["fixed_size"]) * UNITS / px_total) if c.get("fixed_size") else None
             for c in children]
    free = max(0, extent - sum(f for f in fixed if f))
    weights = [float(c.get("weight", 1) or 1) if f is None else 0 for c, f in zip(children, fixed)]
    total = sum(weights) or 1
    sizes, acc, given = [], 0.0, 0
    for f, wt in zip(fixed, weights):
        if f is not None:
            sizes.append(f)
            continue
        acc += free * wt / total
        sizes.append(round(acc) - given)
        given = round(acc)
    return sizes


class _Builder:
    def __init__(self, book, dash, width: int, height: int):
        self.book, self.root, self.dash = book, book.root, dash
        self.width, self.height = width, height
        self.ids = _Ids()
        self.fits = []

    def zone(self, node: dict, x: int, y: int, w: int, h: int):
        kind = node["type"]
        z = etree.Element("zone")
        z.set("id", self.ids())
        _box(z, x, y, w, h)
        if node.get("fixed_size"):
            z.set("fixed-size", str(int(node["fixed_size"])))
            z.set("is-fixed", "true")
        if kind in ("container", "horizontal", "vertical"):
            direction = node.get("direction") or ("horizontal" if kind == "horizontal"
                                                   else "vertical")
            horiz = direction.startswith("h")
            z.set("type-v2", "layout-flow")
            z.set("param", "horz" if horiz else "vert")
            kids = node.get("children") or []
            extent = w if horiz else h
            sizes = _split(kids, extent, self.width if horiz else self.height)
            pos = x if horiz else y
            for ch, s in zip(kids, sizes):
                if horiz:
                    z.append(self.zone(ch, pos, y, s, h))
                else:
                    z.append(self.zone(ch, x, pos, w, s))
                pos += s
        elif kind == "worksheet":
            z.set("name", node["name"])
            z.set("show-title", "true" if node.get("show_title") else "false")
            if node.get("fit"):
                mode = ED.fit_value(node["fit"])
                cache = _CACHE.get(mode)
                if cache:
                    lc = etree.Element("layout-cache")
                    lc.set("type-h", cache[0])
                    lc.set("type-w", cache[1])
                    ED.insert_in_order(z, lc, _ZONE_ORDER)
                if mode == "entire-view":
                    self.fits.append(node["name"])
        elif kind == "text":
            z.set("type-v2", "text")
            z.set("forceUpdate", "true")
            ft = etree.Element("formatted-text")
            run = etree.SubElement(ft, "run")
            if node.get("bold"):
                run.set("bold", "true")
            run.set("fontalignment", str(node.get("align", "1")))
            run.set("fontcolor", node.get("color") or TEXT_COLOR)
            run.set("fontsize", str(node.get("font_size") or 12))
            run.text = str(node.get("text") or "").replace("\n", "Æ\n")
            ED.insert_in_order(z, ft, _ZONE_ORDER)
        elif kind == "title":
            z.set("type-v2", "title")
        elif kind == "paramctrl":
            p = F.param(self.root, node.get("parameter") or "")
            if p is None:
                raise ValueError(f"paramctrl: no parameter {node.get('parameter')!r}")
            z.set("type-v2", "paramctrl")
            z.set("param", f"[Parameters].{p.get('name')}")
            if node.get("mode"):
                z.set("mode", node["mode"])
            self._depend_param(p)
        elif kind == "filter":
            ref = self._filter_ref(node["worksheet"], node.get("field") or "")
            z.set("type-v2", "filter")
            z.set("name", node["worksheet"])
            z.set("mode", node.get("mode") or "checkdropdown")
            z.set("values", "database")
            z.set("param", ref)
        elif kind == "color":
            ref = self._color_ref(node["worksheet"], node.get("field") or "")
            z.set("type-v2", "color")
            z.set("name", node["worksheet"])
            z.set("param", ref)
        else:
            z.set("type-v2", "empty")
        _style(z, dict(_NO_BORDER, **(_CONTROL_BG if kind in ("paramctrl", "filter") else {})))
        return z

    def _deps(self, dsn: str):
        dss = self.dash.find("datasources")
        if dss is None:
            dss = etree.Element("datasources")
            ED.insert_in_order(self.dash, dss, _DASH_ORDER)
        if not any(d.get("name") == dsn for d in dss):
            d = etree.SubElement(dss, "datasource")
            src = next((s for s in self.book.datasources.findall("datasource")
                        if s.get("name") == dsn), None)
            cap = "Parameters" if dsn == "Parameters" else (src.get("caption") if src is not None
                                                            else None)
            if cap:
                d.set("caption", cap)
            d.set("name", dsn)
            if dsn == "Parameters":
                dss.insert(0, d)
        dep = F.find_by(self.dash, "datasource-dependencies", "datasource", dsn)
        if dep is None:
            dep = etree.Element("datasource-dependencies")
            dep.set("datasource", dsn)
            ED.insert_in_order(self.dash, dep, _DASH_ORDER)
            if dsn == "Parameters":
                first = self.dash.find("datasource-dependencies")
                if first is not dep:
                    first.addprevious(dep)
        return dep

    def _depend_param(self, p) -> None:
        dep = self._deps("Parameters")
        if not any(c.get("name") == p.get("name") for c in dep.findall("column")):
            dep.append(copy.deepcopy(p))

    def _depend_field(self, ws, ref: str) -> None:
        dsn = ref[1:].split("].", 1)[0]
        inst = "[" + ref.split("].[", 1)[1]
        wdep = F.find_by(ws, "datasource-dependencies", "datasource", dsn, deep=True)
        dep = self._deps(dsn)
        ci = next((c for c in wdep.findall("column-instance") if c.get("name") == inst), None)
        if ci is None:
            return
        col = next((c for c in wdep.findall("column") if c.get("name") == ci.get("column")), None)
        if col is not None and F.find_by(dep, "column", "name", col.get("name")) is None:
            dep.insert(0, copy.deepcopy(col))
        if F.find_by(dep, "column-instance", "name", inst) is None:
            dep.append(copy.deepcopy(ci))

    def _filter_ref(self, sheet: str, field: str) -> str:
        ws = self.book.sheet(sheet)
        view = ws.find("table/view")
        if not field:
            filt = next((f for f in view.findall("filter")), None)
            if filt is None:
                raise ValueError(f"filter zone on {sheet!r}: name a field, the sheet has no filter")
            ref = filt.get("column")
        else:
            p = F.place(self.root, ws, field)
            ref = p.ref
            if not any(f.get("column") == ref for f in view.findall("filter")):
                ED.apply_filter(self.root, [sheet], p.field.name, derivation=p.derivation,
                                kind=p.instance.rsplit(":", 1)[1][:2])
                ref = next((f.get("column") for f in view.findall("filter")
                            if ED._base_name(f.get("column") or "") == p.field.name), ref)
        self._depend_field(ws, ref)
        return ref

    def _color_ref(self, sheet: str, field: str) -> str:
        ws = self.book.sheet(sheet)
        colors = [e.get("column") for e in ws.iter("color") if e.get("column")]
        if field:
            p = F.place(self.root, ws, field)
            ref = p.ref
        elif colors:
            ref = colors[0]
        else:
            raise ValueError(f"color legend on {sheet!r}: the sheet has no color field")
        self._depend_field(ws, ref)
        return ref


def add(book, dashboard_name: str, width: int = 1200, height: int = 800,
        layout="auto", worksheet_names: list | None = None) -> str:
    """A dashboard from a layout: a preset name, a dict tree or a JSON/YAML file."""
    from .book import child
    root = book.root
    if any(d.get("name") == dashboard_name for d in root.iter("dashboard")):
        raise ValueError(f"dashboard {dashboard_name!r} already exists")
    sheets = set(book.list_worksheets())
    names = list(worksheet_names or [])
    missing = [n for n in names if n not in sheets]
    if missing:
        raise ValueError(f"no worksheets {missing} in the workbook")
    tree = layout if isinstance(layout, dict) else _preset(str(layout), names or sorted(sheets))
    _check(tree, sheets)
    dash = etree.SubElement(child(root, "dashboards"), "dashboard")
    dash.set("name", dashboard_name)
    etree.SubElement(dash, "style")
    size = etree.SubElement(dash, "size")
    mode = getattr(book, "dashboard_sizing", "fixed") or "fixed"
    if mode == "range":
        rng = dict(getattr(book, "dashboard_size_range", None) or {})
        for k in ("maxheight", "maxwidth", "minheight", "minwidth"):
            if k in rng:
                size.set(k, str(rng[k]))
    elif mode == "fixed":
        for k, v in (("maxheight", height), ("maxwidth", width), ("minheight", height),
                     ("minwidth", width)):
            size.set(k, str(int(v)))
    size.set("sizing-mode", mode)
    zones = etree.SubElement(dash, "zones")
    b = _Builder(book, dash, int(width), int(height))
    zones.append(b.zone(tree, 0, 0, UNITS, UNITS))
    etree.SubElement(dash, "simple-id").set("uuid", ED.new_uuid())
    for el in list(dash):
        dash.remove(el)
        ED.insert_in_order(dash, el, _DASH_ORDER)
    placed = list(dict.fromkeys(z.get("name") for z in zones.iter("zone")
                                if z.get("name") and not z.get("type-v2")))
    _window(root, dashboard_name, placed, set(b.fits))
    return f"Added dashboard {dashboard_name!r} with {len(placed)} sheets"


def _window(root, name: str, sheets: list, entire: set) -> None:
    """The dashboard's window; on a page a sheet's Entire View lives in its viewpoint here."""
    from .book import child
    wins = child(root, "windows")
    win = etree.SubElement(wins, "window")
    win.set("class", "dashboard")
    win.set("name", name)
    vps = etree.SubElement(win, "viewpoints")
    for s in sheets:
        vp = etree.SubElement(vps, "viewpoint")
        vp.set("name", s)
        if s in entire:
            etree.SubElement(vp, "zoom").set("type", "entire-view")
    etree.SubElement(win, "active").set("id", "-1")
    etree.SubElement(win, "simple-id").set("uuid", ED.new_uuid())


def action(book, dashboard_name: str, action_type: str, source_sheet: str,
           target_sheet: str = "", fields: list | None = None, event_type: str = "on-select",
           caption: str = "", url: str = "", source_field: str = "", target_parameter: str = "",
           aggregation: str = "attr", clear_behavior: str = "keep-current",
           clear_value: str = "") -> str:
    """A dashboard action: filter, highlight, url or parameter."""
    from .book import child
    root = book.root
    dash = next((d for d in root.iter("dashboard") if d.get("name") == dashboard_name), None)
    if dash is None:
        raise ValueError(f"no dashboard {dashboard_name!r}")
    on_dash = [z.get("name") for z in dash.iter("zone") if z.get("name") and not z.get("type-v2")]
    if source_sheet not in on_dash:
        raise ValueError(f"{source_sheet!r} is not on {dashboard_name!r}")
    if target_sheet and target_sheet not in on_dash:
        raise ValueError(f"{target_sheet!r} is not on {dashboard_name!r}")
    acts = child(root, "actions")
    n = len(acts) + 1
    while any(a.get("name") == f"[Action{n}]" for a in acts):
        n += 1
    name = f"[Action{n}]"
    others = sorted(set(on_dash) - {target_sheet}) if target_sheet else []
    ws = book.sheet(source_sheet)

    def source(el):
        s = etree.SubElement(el, "source")
        s.set("dashboard", dashboard_name)
        s.set("type", "sheet")
        s.set("worksheet", source_sheet)

    kind = action_type.lower()
    if kind == "filter":
        a = etree.SubElement(acts, "action")
        a.set("caption", caption or f"Filter Action {n}")
        a.set("name", name)
        act = etree.SubElement(a, "activation")
        act.set("auto-clear", "true")
        act.set("type", event_type)
        source(a)
        if fields:
            from urllib.parse import quote
            dsn = F.sheet_datasource(root, ws)
            names = [F.parse(root, f, dsn)[1].name for f in fields]
            link = etree.SubElement(a, "link")
            link.set("caption", a.get("caption"))
            link.set("delimiter", ",")
            link.set("escape", "\\")
            link.set("expression", f"tsl:{dashboard_name}?" + "&".join(
                f"{quote(f'[{dsn}].[{n}]', safe='')}~s0=<[{dsn}].[{n}]~na>" for n in names))
            link.set("include-null", "true")
            link.set("multi-select", "true")
            link.set("url-escape", "true")
        cmd = etree.SubElement(a, "command")
        cmd.set("command", "tsc:tsl-filter")
        if others:
            etree.SubElement(cmd, "param", name="exclude", value=",".join(others))
        if not fields:
            etree.SubElement(cmd, "param", name="special-fields", value="all")
        etree.SubElement(cmd, "param", name="target", value=dashboard_name)
    elif kind == "highlight":
        a = etree.SubElement(acts, "action")
        a.set("caption", caption or f"Highlight Action {n}")
        a.set("name", name)
        act = etree.SubElement(a, "activation")
        act.set("auto-clear", "true")
        act.set("type", event_type)
        source(a)
        cmd = etree.SubElement(a, "command")
        cmd.set("command", "tsc:brush")
        if others:
            etree.SubElement(cmd, "param", name="exclude", value=",".join(others))
        if fields:
            etree.SubElement(cmd, "param", name="field-captions", value=",".join(fields))
        etree.SubElement(cmd, "param", name="target", value=dashboard_name)
    elif kind == "url":
        if not url:
            raise ValueError("a url action needs `url`")
        a = etree.SubElement(acts, "action")
        a.set("caption", caption or f"URL Action {n}")
        a.set("name", name)
        act = etree.SubElement(a, "activation")
        act.set("auto-clear", "true")
        act.set("type", event_type)
        source(a)
        link = etree.SubElement(a, "link")
        link.set("caption", caption or url)
        link.set("expression", url)
    elif kind == "parameter":
        p = F.param(root, target_parameter)
        if p is None:
            raise ValueError(f"no parameter {target_parameter!r}")
        sp = F.place(root, ws, source_field)
        a = etree.SubElement(acts, "edit-parameter-action")
        a.set("caption", caption or f"Parameter Action {n}")
        a.set("name", name)
        etree.SubElement(a, "activation").set("type", event_type)
        source(a)
        etree.SubElement(a, "agg-type").set("type", aggregation)
        co = etree.SubElement(a, "clear-option")
        co.set("type", "do-nothing" if clear_behavior == "keep-current" else clear_behavior)
        if clear_value:
            co.set("value", clear_value)
        params = etree.SubElement(a, "params")
        etree.SubElement(params, "param", name="source-field", value=sp.ref)
        # Tableau loads a parameter action only when the manifest declares the feature.
        ED.ensure_format_flags(root, ("ParameterAction", "ParameterActionClearSelection"))
        etree.SubElement(params, "param", name="target-parameter",
                         value=f"[Parameters].{p.get('name')}")
    else:
        raise ValueError(f"action_type {action_type!r}: use filter, highlight, url or parameter")
    return f"Added {kind} action {name} to {dashboard_name!r}"

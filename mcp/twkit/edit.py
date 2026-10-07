"""Editing an EXISTING workbook: operations that do not care which report it is."""
from __future__ import annotations

import copy
import difflib
import math
import re
import uuid

from lxml import etree

REF_ATTRS = {
    "column": ("name",), "column-instance": ("column", "name"),
    "format": ("field",), "filter": ("column",), "groupfilter": ("level", "member"),
    "zone": ("param",), "card": ("param",), "order": ("field",),
    "table-calc": ("ordering-field",), "field-sort-custom-order": ("field",),
    "folder-item": ("name",), "color": ("column",), "text": ("column",),
    "tooltip": ("column",), "size": ("column",), "shape": ("column",),
    "encoding": ("column", "field"), "slice": ("column",),
    "manual-sort": ("column",), "sort": ("column",),
}


_VIEW_ORDER = ["datasources", "map-sources", "datasource-dependencies", "filter",
               "sort", "manual-sort", "computed-sort", "natural-sort",
               "alphabetic-sort", "perspective", "shelf-sorts",
               "hide-sort-controls", "slices", "aggregation",
               "calcs-on-densified-marks"]

_DS_ORDER = ["repository-location", "connection", "utility-dimensions", "dimensions",
             "overridable-settings", "aliases", "column", "column-instance", "group",
             "mapped-images", "drill-paths", "folders-common", "folders-parameters",
             "actions", "calculated-members", "extract", "layout", "style",
             "semantic-values", "date-options", "default-date-format", "default-sorts",
             "field-sort-info", "datasource-dependencies", "explainability",
             "datasource-filters", "analytic-model", "object-graph",
             "default-calendar-type"]


_PANE_ORDER = ["view", "mark", "mark-sizing", "encodings", "customized-tooltip",
               "customized-label", "style"]


FORMAT_ATTRS = {
    "animation-style", "col-width", "line-pattern", "map-snap-zoom", "reverse-palette",
    "animation-duration", "animation-on", "aspect", "auto-subtitle", "background-color", "band-color",
    "band-level", "band-size", "body-type", "border-color", "border-style", "border-width", "break-on-special",
    "cell", "cell-h", "cell-q", "cell-w", "color", "color-mode", "display", "display-field-labels", "div-level",
    "enabled", "fill-above", "fill-below", "fill-color", "font-family", "font-size", "font-style", "font-weight",
    "geo-area-type", "has-halo", "has-stroke", "height", "height-header", "in-tooltip", "line-end", "line-end-size",
    "line-interpolation", "line-pattern-only", "line-visibility", "map-style", "margin", "margin-bottom",
    "margin-left", "margin-right", "margin-top", "mark-color", "mark-labels-cull", "mark-labels-line-first",
    "mark-labels-line-last", "mark-labels-mode", "mark-labels-range-field", "mark-labels-range-max",
    "mark-labels-range-min", "mark-labels-range-scope", "mark-labels-show", "mark-line-pattern", "mark-markers-mode",
    "mark-transparency", "maxheight", "maxwidth", "minheight", "minwidth", "omit-on-special", "opacity",
    "padding", "padding-bottom", "padding-left", "padding-right", "padding-top", "palette", "render-fold-reversed",
    "rounding", "shape", "show-null-value-warning", "size", "stroke-color", "stroke-size", "subtitle",
    "text-align", "text-decoration", "text-format", "text-orientation", "tick-color", "title", "total-label",
    "vertical-align", "washout", "whisker-end", "whisker-stroke-color", "whisker-stroke-size", "width",
    "width-header", "wrap",
}


FORMAT_ATTR_FIX = {
    "font-color": "color",
    "fontcolor": "color",
    "text-color": "color",
    "fontsize": "font-size",
    "font-size-px": "font-size",
    "fontname": "font-family",
    "font-name": "font-family",
    "fontweight": "font-weight",
    "bold": "font-weight",
    "line-color": "stroke-color",
    "line-width": "stroke-size",
    "border-colour": "border-color",
    "background": "background-color",
    "bg-color": "background-color",
    "align": "text-align",
}


def format_attr_hint(attr: str) -> str:
    """Replacement for an unknown `attr`: the exact known fix, else the closest schema name."""
    fix = FORMAT_ATTR_FIX.get(attr)
    if fix:
        return fix
    near = difflib.get_close_matches(attr, sorted(FORMAT_ATTRS), n=1, cutoff=0.7)
    return near[0] if near else ""


def fix_format_attrs(root) -> dict:
    """Rename `<format attr=...>` values that have a known correct counterpart."""
    done = {}
    for f in root.iter("format"):
        a = f.get("attr")
        if a in FORMAT_ATTR_FIX:
            f.set("attr", FORMAT_ATTR_FIX[a])
            done[a] = FORMAT_ATTR_FIX[a]
    return {"renamed": done}


def strip_invalid_formats(root) -> dict:
    """Remove `<format>` elements whose attribute is not in the Tableau schema."""
    bad = []
    for f in list(root.iter("format")):
        a = f.get("attr")
        if a and a not in FORMAT_ATTRS:
            bad.append(a)
            f.getparent().remove(f)
    return {"removed": len(bad), "attributes": sorted(set(bad))}


def repair_node_order(root) -> dict:
    """Reorder node children per the schema where a builder appended them at the end."""
    fixed = 0
    for pane in root.iter("pane"):
        kids = [c for c in pane if isinstance(c.tag, str)]
        known = [c for c in kids if c.tag in _PANE_ORDER]
        want = sorted(known, key=lambda c: _PANE_ORDER.index(c.tag))
        if [c.tag for c in known] == [c.tag for c in want]:
            continue
        for c in known:
            pane.remove(c)
        for c in reversed(want):
            pane.insert(0, c)
        fixed += 1
    return {"panes_fixed": fixed}


def insert_in_order(parent, child, order: list):
    """Insert a node at its schema position instead of appending."""
    tag = child.tag
    if tag not in order:
        parent.append(child)
        return child
    rank = order.index(tag)
    for existing in parent:
        t = existing.tag
        if isinstance(t, str) and t in order and order.index(t) > rank:
            existing.addprevious(child)
            return child
    parent.append(child)
    return child


def new_uuid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def mentions(s: str, field: str) -> bool:
    """Whether the string references exactly this field, not another with a similar name."""
    if not s:
        return False
    return (f"[{field}]" in s or f":{field}:" in s or s == field
            or f"[{field} " in s)


def field_names(root, caption: str) -> set:
    """Field caption plus the internal column names carrying that caption: a shelf stores..."""
    return {caption} | {(c.get("name") or "").strip("[]") for c in root.iter("column")
                        if c.get("caption") == caption and c.get("name")}

def shelf_tokens(text: str) -> list:
    """Shelf references: `([ds].[a] / ([ds].[b] / [ds].[c]))` gives three tokens."""
    return re.findall(r"\[[^\[\]]+\]\.\[[^\[\]]+\]", text or "")


def rebuild_shelf(tokens: list) -> str:
    """Build a right-nested shelf as Tableau writes it: `(a / (b / c))`."""
    if not tokens:
        return ""
    out = tokens[-1]
    for tok in reversed(tokens[:-1]):
        out = f"({tok} / {out})"
    return out


def drop_fields(root, fields: list, keep_on_shelves: str = "") -> dict:
    """Remove fields from the workbook together with ALL references."""
    killed = replaced = 0
    if keep_on_shelves:
        for ws in root.iter("worksheet"):
            for tag in ("rows", "cols"):
                for shelf in ws.iter(tag):
                    text = (shelf.text or "").strip()
                    if not text or "+" in text:
                        continue
                    toks = shelf_tokens(text)
                    if not any(mentions(t, f) for t in toks for f in fields):
                        continue
                    has_keep = any(mentions(t, keep_on_shelves) for t in toks)
                    new = []
                    for t in toks:
                        if not any(mentions(t, f) for f in fields):
                            new.append(t)
                        elif not has_keep:
                            new.append(retype_ref(t, keep_on_shelves))
                            has_keep = True
                    shelf.text = rebuild_shelf(new)
                    replaced += 1

    for el in list(root.iter()):
        attrs = REF_ATTRS.get(el.tag)
        if not attrs:
            continue
        vals = [el.get(a) or "" for a in attrs]
        if not any(mentions(v, f) for v in vals for f in fields):
            continue
        par = el.getparent()
        if par is not None:
            par.remove(el)
            killed += 1
    killed += _drop_text_refs(root, fields)
    return {"refs_removed": killed, "shelves_with_axis_replaced": replaced}


def _drop_text_refs(root, fields: list) -> int:
    """References in element TEXT, which an attribute walk does not see."""
    removed = 0
    for tag in ("rows", "cols"):
        for shelf in list(root.iter(tag)):
            text = (shelf.text or "").strip()
            if not text or "+" in text or not any(mentions(text, f) for f in fields):
                continue
            toks = [t for t in shelf_tokens(text)
                    if not any(mentions(t, f) for f in fields)]
            shelf.text = rebuild_shelf(toks)
            removed += 1
    for el in list(root.iter()):
        if el.tag not in ("column", "field", "run", "bucket") or not el.text:
            continue
        if not any(mentions(el.text, f) for f in fields):
            continue
        par = el.getparent()
        if par is None:
            continue
        par.remove(el)
        removed += 1
        left = len(par.findall("field"))
        if (par.tag == "color-one-way" and left == 0) or \
           (par.tag == "drill-path" and left < 2):
            gp = par.getparent()
            if gp is not None:
                gp.remove(par)
    return removed


def retype_ref(token: str, field: str) -> str:
    """`[none:provider:ok]` becomes `[none:payment_system:nk]`, keeping the prefix."""
    return re.sub(r"\[(\w+):[^:\]]+:(\w+)\]", rf"[\1:{field}:nk]", token)


def rename_field(root, old: str, new: str) -> int:
    """Rename a field throughout the document."""
    from . import safexml
    blob = etree.tostring(root, encoding="unicode")
    if old not in blob:
        return 0
    n = blob.count(old)
    new_root = safexml.from_bytes(blob.replace(old, new).encode())
    par = root.getparent()
    if par is not None:
        par.replace(root, new_root)
    else:
        root.clear()
        for k, v in new_root.attrib.items():
            root.set(k, v)
        for child in list(new_root):
            root.append(child)
    return n


def set_formula(root, calc: str, formula: str) -> dict:
    """Replace a calculated field's formula as a whole."""
    want = calc.strip()
    touched = []
    for col in root.iter("column"):
        nm = (col.get("name") or "").strip("[]")
        cap = (col.get("caption") or "").strip()
        if nm != want and cap != want:
            continue
        node = col.find("calculation")
        if node is None:
            continue
        touched.append(node.get("formula") or "")
        node.set("formula", formula)
    if not touched:
        raise ValueError(f"calculated field {calc!r} is not in the workbook")
    return {"field": calc, "declarations_edited": len(touched),
            "before": touched[0][:120], "after": formula}


def rename_fields(root, mapping: dict) -> dict:
    """Rename SEVERAL fields at once, refusing dangerous pairs."""
    pairs = {str(k).strip("[]"): str(v).strip("[]") for k, v in mapping.items()}
    if not pairs:
        return {"field_count": 0, "replacements": 0}

    problems = []
    for a in pairs:
        for b in pairs:
            if a != b and a in b:
                problems.append(f"{a!r} is a substring of {b!r}")
    have = {(c.get("name") or "").strip("[]") for c in root.iter("column")}
    for old in pairs:
        if old not in have:
            problems.append(f"field {old!r} is not in the workbook")
    for old, new in pairs.items():
        if new in have and new != old:
            problems.append(f"name {new!r} is already taken")
    if problems:
        raise ValueError("rename rejected:\n  - " + "\n  - ".join(sorted(set(problems))))

    total = 0
    for old, new in pairs.items():
        total += rename_field(root, old, new)
    return {"field_count": len(pairs), "replacements": total}


def dependent_calcs(root, fields: list) -> list:
    """Calculations that read these fields, directly or through other calculations."""
    calcs = {}
    for col in root.iter("column"):
        calc = col.find("calculation")
        if calc is None or not calc.get("formula"):
            continue
        nm = (col.get("name") or "").strip("[]")
        if nm:
            calcs[nm] = calc.get("formula")

    bad, order = set(fields), []
    while True:
        found = [nm for nm, f in calcs.items()
                 if nm not in bad and any(mentions(f, b) for b in bad)]
        if not found:
            return order
        bad.update(found)
        order += sorted(found)


def drop_param_members(root, values: list, params: list = ()) -> dict:
    """Remove items from parameter value lists."""
    dropped = defaults = 0
    want = {v.strip('"') for v in values}
    only = {p.strip() for p in params}
    for c in root.iter("column"):
        if not c.get("param-domain-type"):
            continue
        if only and (c.get("caption") or "").strip() not in only:
            continue
        members = c.find("members")
        if members is None:
            continue
        for m in list(members):
            if (m.get("value") or "").strip('"') in want:
                members.remove(m)
                dropped += 1
        if (c.get("value") or "").strip('"') not in want:
            continue
        first = members.find("member")
        if first is None:
            continue
        c.set("value", first.get("value"))
        calc = c.find("calculation")
        if calc is not None:
            calc.set("formula", first.get("value"))
        defaults += 1
    return {"members_dropped": dropped, "defaults_reset": defaults}


_BRANCH_END = r"(?=\s*(?:WHEN\b|ELSEIF\b|ELSE\b|END\b))"


def drop_case_branches(root, values: list, calcs: list = ()) -> dict:
    """Remove branches for a value and items inside `IN (...)` from formulas."""
    touched = branches = in_items = 0
    only = {c.strip() for c in calcs}
    for col in root.iter("column"):
        if only and (col.get("caption") or "").strip() not in only:
            continue
        calc = col.find("calculation")
        if calc is None:
            continue
        f0 = f = calc.get("formula") or ""
        if not f:
            continue
        for v in values:
            q = re.escape(v)
            f, n = re.subn(rf"\s*WHEN\s+'{q}'\s+THEN\s+.*?{_BRANCH_END}", "", f, flags=re.S)
            branches += n
            f, n = re.subn(rf"\s*(?:ELSEIF|IF)\s+[^\n]*?=\s*'{q}'\s+THEN\s+.*?{_BRANCH_END}",
                           "", f, flags=re.S)
            branches += n
            f, n = re.subn(rf"'{q}'\s*,\s*", "", f)
            in_items += n
            f, n = re.subn(rf",\s*'{q}'(?=\s*\))", "", f)
            in_items += n
        if f.lstrip().startswith("ELSEIF"):
            f = f.replace("ELSEIF", "IF", 1)
        if f != f0:
            calc.set("formula", f)
            touched += 1
    return {"calcs_edited": touched,
            "branches_removed": branches, "in_items_removed": in_items}


def add_param_members(root, params: list, values: list) -> dict:
    """Append items to parameter value lists; pair of `drop_param_members`."""
    want = [v.strip('"') for v in values]
    want_params = {p.strip() for p in params}
    added = skipped = touched = 0
    for c in root.iter("column"):
        if not c.get("param-domain-type"):
            continue
        if want_params and (c.get("caption") or "").strip() not in want_params:
            continue
        members = c.find("members")
        if members is None:
            continue
        have = {(m.get("value") or "").strip('"') for m in members}
        before = added
        for v in want:
            if v in have:
                skipped += 1
                continue
            m = etree.SubElement(members, "member")
            m.set("value", f'"{v}"')
            added += 1
        if added > before:
            touched += 1
    return {"members_added": added, "skipped_existing": skipped,
            "declarations_edited": touched}


def add_case_branches(root, calcs: list, branches: dict) -> dict:
    """Append `WHEN 'x' THEN <expression>` branches to formulas; pair of `drop_case_branches`."""
    want_calcs = {c.strip() for c in calcs}
    touched = added = 0
    for col in root.iter("column"):
        if want_calcs and (col.get("caption") or "").strip() not in want_calcs:
            continue
        calc = col.find("calculation")
        if calc is None:
            continue
        f = calc.get("formula") or ""
        if "CASE" not in f or not f.rstrip().endswith("END"):
            continue
        tail = f.rstrip()[:-3].rstrip()
        grew = False
        for member, expr in branches.items():
            if re.search(rf"WHEN\s+'{re.escape(member)}'\s+THEN", f):
                continue
            tail += f"\nWHEN '{member}' THEN {expr}"
            added += 1
            grew = True
        if grew:
            calc.set("formula", tail + "\nEND")
            touched += 1
    return {"calcs_edited": touched, "branches_added": added}


def zone_hide_button(root, dashboard: str, hide: list, keep: list,
                     hidden: bool = True) -> dict:
    """Hide zones behind a hide/show button, freeing the space for their neighbours."""
    dash = None
    for d in root.findall(".//dashboards/dashboard"):
        if d.get("name") == dashboard:
            dash = d
            break
    if dash is None:
        raise ValueError(f"dashboard {dashboard!r} is not in the workbook")

    canvas = dash.find("zones")
    if canvas is None:
        raise ValueError(f"dashboard {dashboard!r} has no default layout")

    def _kind(v: str) -> str:
        return "" if (v or "").upper() in ("", "NONE") else v

    def _pick(spec: str):
        name, _, want = spec.partition(":")
        got = [z for z in canvas.iter("zone")
               if z.get("name") == name and _kind(z.get("type-v2")) == _kind(want)]
        if not got:
            raise ValueError(
                f"no zone {spec!r} on dashboard {dashboard!r}"
                + ("" if want else " (no sheet with that name is on the dashboard)"))
        if len(got) > 1:
            raise ValueError(f"zone {spec!r} on dashboard {dashboard!r} is not unique ({len(got)})")
        return got[0]

    picked = {spec: _pick(spec) for spec in list(keep) + list(hide)}
    members = [picked[s] for s in list(keep) + list(hide)]
    parent = members[0].getparent()
    if any(z.getparent() is not parent for z in members):
        raise ValueError("zones are in different containers; only siblings can be wrapped")

    ids = [int(z.get("id")) for z in root.iter("zone")
           if (z.get("id") or "").isdigit()]
    next_id = max(ids) + 1

    def rect(zs):
        x = min(int(z.get("x")) for z in zs)
        y = min(int(z.get("y")) for z in zs)
        w = max(int(z.get("x")) + int(z.get("w")) for z in zs) - x
        h = max(int(z.get("y")) + int(z.get("h")) for z in zs) - y
        return x, y, w, h

    at = list(parent).index(members[0])
    for z in members:
        at = min(at, list(parent).index(z))

    row = etree.Element("zone")
    x, y, w, h = rect(members)
    for k, v in (("h", h), ("id", next_id), ("layout-strategy-id", "distribute-evenly"),
                 ("param", "horz"), ("type-v2", "layout-flow"), ("w", w), ("x", x), ("y", y)):
        row.set(k, str(v))
    parent.insert(at, row)

    box = etree.SubElement(row, "zone")
    hx, hy, hw, hh = rect([picked[n] for n in hide])
    for k, v in (("h", hh), ("hidden-by-user", "true"), ("id", next_id + 1),
                 ("param", "horz"), ("type-v2", "layout-flow"),
                 ("w", hw), ("x", hx), ("y", hy)):
        box.set(k, str(v))

    for n in reversed(list(keep)):
        row.insert(0, picked[n])
    if not hidden:
        box.attrib.pop("hidden-by-user", None)
    for n in hide:
        z = picked[n]
        box.append(z)
        if hidden:
            z.set("hidden-by-user", "true")
            for kid in z.iter("zone"):
                kid.set("hidden-by-user", "true")

    manifest = root.find("document-format-change-manifest")
    if manifest is None:
        manifest = etree.Element("document-format-change-manifest")
        root.insert(0, manifest)
    have = {e.tag for e in manifest}
    for feature in ("BasicButtonObject", "CollapsiblePane", "ZoneVisibilityControl"):
        if feature not in have:
            etree.SubElement(manifest, feature)

    win = None
    for w in root.findall(".//windows/window"):
        if w.get("class") == "dashboard" and w.get("name") == dashboard:
            win = w
            break
    if win is None:
        raise ValueError(f"dashboard {dashboard!r} has no window; run edit_finish_windows first")
    sid = win.find("simple-id")
    if sid is None:
        sid = etree.SubElement(win, "simple-id")
    if not sid.get("uuid"):
        sid.set("uuid", "{%s}" % uuid.uuid4().__str__().upper())

    btn_id = next_id + 2
    btn = etree.SubElement(canvas, "zone")
    bw, bh = 1478, 2837
    anchor = picked[hide[0]]
    bx = int(anchor.get("x")) + int(anchor.get("w")) - bw
    for k, v in (("h", bh), ("id", btn_id), ("type-v2", "dashboard-object"),
                 ("w", bw), ("x", bx), ("y", hy + 184)):
        btn.set(k, str(v))
    b = etree.SubElement(btn, "button")
    b.set("action", "")
    if hidden:
        b.set("active-visual-state-index", "1")
    act = etree.SubElement(b, "toggle-action")
    act.text = ('tabdoc:toggle-button-click-action '
                f'window-id="{sid.get("uuid")}" zone-id="{btn_id}" '
                f'zone-ids=[{next_id + 1}]')
    etree.SubElement(b, "button-visual-state")
    etree.SubElement(b, "button-visual-state")

    return {"page": dashboard, "behind_button": list(hide),
            "stays_visible": list(keep), "container": next_id,
            "collapsed_container": next_id + 1, "button": btn_id,
            "start_state": "collapsed" if hidden else "expanded"}


def zone_title(root, dashboard: str, titles: dict, *,
               font_size: int = 11, color: str = "#1b1b1b") -> dict:
    """Custom title of a CONTROL on a dashboard: filter, parameter, legend."""
    dash = None
    for d in root.findall(".//dashboards/dashboard"):
        if d.get("name") == dashboard:
            dash = d
            break
    if dash is None:
        raise ValueError(f"dashboard {dashboard!r} is not in the workbook")
    canvas = dash.find("zones")
    if canvas is None:
        raise ValueError(f"dashboard {dashboard!r} has no default layout")

    by_id = {z.get("id"): z for z in canvas.iter("zone")}
    missing = [k for k in titles if str(k) not in by_id]
    if missing:
        raise ValueError(f"no zones on dashboard {dashboard!r}: {sorted(missing)}")

    done = {}
    for zid, title in titles.items():
        zone = by_id[str(zid)]
        old = zone.find("formatted-text")
        if old is not None:
            zone.remove(old)
        ft = etree.Element("formatted-text")
        zone.insert(0, ft)
        run = etree.SubElement(ft, "run")
        run.set("fontcolor", color)
        run.set("fontsize", str(font_size))
        run.text = title
        zone.set("custom-title", "true")
        done[str(zid)] = title
    return {"page": dashboard, "titled": done}


def zone_text(root, dashboard: str, text: str, *, zone_id: str = "",
              font_size: int = 11, color: str = "#1b1b1b") -> dict:
    """Rewrite the text of a dashboard's TEXT zone (note, legend, description)."""
    dash = None
    for d in root.findall(".//dashboards/dashboard"):
        if d.get("name") == dashboard:
            dash = d
            break
    if dash is None:
        raise ValueError(f"dashboard {dashboard!r} is not in the workbook")
    canvas = dash.find("zones")
    if canvas is None:
        raise ValueError(f"dashboard {dashboard!r} has no default layout")

    zones = [z for z in canvas.iter("zone") if z.get("type-v2") == "text"
             and (not zone_id or z.get("id") == str(zone_id))]
    if not zones:
        raise ValueError(f"no text zone on dashboard {dashboard!r}"
                         + (f" with id={zone_id}" if zone_id else ""))
    if len(zones) > 1:
        raise ValueError(f"several text zones on dashboard {dashboard!r} "
                         f"({', '.join(z.get('id') for z in zones)}); zone_id is required")
    zone = zones[0]

    old = zone.find("formatted-text")
    if old is not None:
        zone.remove(old)
    ft = etree.Element("formatted-text")
    zone.insert(0, ft)

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if i:
            br = etree.SubElement(ft, "run")
            br.text = "\u00c6\n"
        body, bold = (line[2:], True) if line.startswith("# ") else (line, False)
        if not body:
            continue
        run = etree.SubElement(ft, "run")
        run.set("fontcolor", color)
        run.set("fontsize", str(font_size))
        if bold:
            run.set("bold", "true")
        run.text = body
    return {"page": dashboard, "zone": zone.get("id"),
            "row_count": len(lines), "headings": sum(1 for l in lines if l.startswith("# "))}


def rename_worksheet(root, old: str, new: str) -> dict:
    """Rename a SHEET everywhere Tableau stores its name."""
    if not new or new == old:
        return {"renamed": 0}
    hits = {"worksheet": 0, "zone": 0, "viewpoint": 0, "window": 0, "action": 0}
    for ws in root.iter("worksheet"):
        if ws.get("name") == old:
            ws.set("name", new)
            hits["worksheet"] += 1
    for z in root.iter("zone"):
        if z.get("name") == old:
            z.set("name", new)
            hits["zone"] += 1
    for vp in root.iter("viewpoint"):
        if vp.get("name") == old:
            vp.set("name", new)
            hits["viewpoint"] += 1
    for w in root.iter("window"):
        if w.get("class") == "worksheet" and w.get("name") == old:
            w.set("name", new)
            hits["window"] += 1
    for act in root.iter("action"):
        for node in list(act.iter("source")) + list(act.iter("target")):
            if node.get("worksheet") == old:
                node.set("worksheet", new)
                hits["action"] += 1
    total = sum(hits.values())
    return {"renamed": total, **{k: v for k, v in hits.items() if v}}


def _drop_named(root, tag: str, name: str, win_class: str) -> dict:
    """Remove `<{tag} name=...>`, its window and all references to it."""
    hits = {tag: 0, "window": 0, "zone": 0, "viewpoint": 0, "action": 0}
    for parent in list(root.iter()):
        for el in list(parent):
            if el.tag == tag and el.get("name") == name:
                parent.remove(el)
                hits[tag] += 1
            elif el.tag == "window" and el.get("class") == win_class and el.get("name") == name:
                parent.remove(el)
                hits["window"] += 1
            elif el.tag == "zone" and el.get("name") == name:
                parent.remove(el)
                hits["zone"] += 1
            elif el.tag == "viewpoint" and el.get("name") == name:
                parent.remove(el)
                hits["viewpoint"] += 1
    for parent in list(root.iter("actions")):
        for act in list(parent):
            refs = [n.get("worksheet") for n in list(act.iter("source")) + list(act.iter("target"))]
            if name in refs:
                parent.remove(act)
                hits["action"] += 1
    return hits


def remove_worksheet(root, name: str) -> dict:
    """Delete a SHEET together with its window, dashboard zones and actions."""
    hits = _drop_named(root, "worksheet", name, "worksheet")
    if not hits["worksheet"]:
        raise ValueError(f"sheet {name!r} is not in the workbook")
    return {"deleted": sum(hits.values()), **{k: v for k, v in hits.items() if v}}


def remove_dashboard(root, name: str) -> dict:
    """Delete a DASHBOARD together with its window and actions."""
    hits = _drop_named(root, "dashboard", name, "dashboard")
    if not hits["dashboard"]:
        raise ValueError(f"dashboard {name!r} is not in the workbook")
    return {"deleted": sum(hits.values()), **{k: v for k, v in hits.items() if v}}


def rename_dashboard(root, old: str, new: str) -> dict:
    """Rename a DASHBOARD everywhere Tableau stores its name."""
    if not new or new == old:
        return {"renamed": 0}
    hits = {"dashboard": 0, "window": 0, "action": 0, "button": 0}
    for d in root.iter("dashboard"):
        if d.get("name") == old:
            d.set("name", new)
            hits["dashboard"] += 1
    for w in root.iter("window"):
        if w.get("class") == "dashboard" and w.get("name") == old:
            w.set("name", new)
            hits["window"] += 1
    for act in root.iter("action"):
        for node in act.iter():
            if node.get("dashboard") == old:
                node.set("dashboard", new)
                hits["action"] += 1
            if node.tag == "param" and node.get("name") in ("target", "source") \
                    and node.get("value") == old:
                node.set("value", new)
                hits["action"] += 1
    for cap in root.iter("caption"):
        if (cap.text or "").strip() == old:
            cap.text = new
            hits["button"] += 1
    total = sum(hits.values())
    return {"renamed": total, **{k: v for k, v in hits.items() if v}}


def finish_windows(root, first_dashboard: str = "") -> dict:
    """Bring the workbook to the state it is opened in: dashboard first and maximized, helper sheets hidden."""
    wins = root.find("windows")
    if wins is None:
        return {"order": 0, "hidden": 0, "why": "the workbook has no windows"}
    kids = list(wins)
    dash = [w for w in kids if w.get("class") == "dashboard"]
    if not dash:
        return {"order": 0, "hidden": 0, "why": "the workbook has no dashboards"}

    head = next((w for w in dash if w.get("name") == first_dashboard), dash[0])
    for w in dash:
        w.attrib.pop("maximized", None)
    head.set("maximized", "true")

    used = {z.get("name") for d in root.iter("dashboard") for z in d.iter("zone")
            if z.get("name")}
    hidden = 0
    for w in kids:
        if w.get("class") == "worksheet" and w.get("name") in used:
            if w.get("hidden") != "true":
                w.set("hidden", "true")
                hidden += 1

    order = [head] + [w for w in dash if w is not head] + \
            [w for w in kids if w.get("class") != "dashboard"]
    for w in kids:
        wins.remove(w)
    for w in order:
        wins.append(w)
    return {"first": head.get("name"), "order": len(order), "hidden": hidden}


def reorder_pages(root, order: list) -> dict:
    """TAB order in a workbook equals the `<window>` order, not the `<dashboard>` order."""
    wins = root.find("windows")
    if wins is None:
        return {"order": 0}
    kids = list(wins)
    by_name = {}
    for w in kids:
        if w.get("class") == "dashboard":
            by_name[w.get("name")] = w
    head = [by_name[n] for n in order if n in by_name]
    if not head:
        return {"order": 0, "why": "no dashboard found"}
    tail = [w for w in kids if w not in head]
    for w in kids:
        wins.remove(w)
    for w in head + tail:
        wins.append(w)
    dashes = root.find("dashboards")
    if dashes is not None:
        dkids = list(dashes)
        dmap = {d.get("name"): d for d in dkids}
        dhead = [dmap[n] for n in order if n in dmap]
        dtail = [d for d in dkids if d not in dhead]
        for d in dkids:
            dashes.remove(d)
        for d in dhead + dtail:
            dashes.append(d)
    return {"order": len(head), "tabs": [w.get("name") for w in head + tail
                                         if w.get("class") == "dashboard"]}


def set_caption(root, name: str, caption: str) -> int:
    """Caption of a field or parameter, what a person sees in the workbook."""
    fixed = 0
    for c in root.iter("column"):
        nm = (c.get("name") or "").strip("[]")
        if nm == name or (c.get("caption") or "") == name:
            c.set("caption", caption)
            fixed += 1
    return fixed


def dedupe_shelves(root) -> int:
    """A field standing twice on one shelf gives two identical columns on screen."""
    fixed = 0
    for ws in root.iter("worksheet"):
        for tag in ("rows", "cols"):
            for shelf in ws.iter(tag):
                text = (shelf.text or "").strip()
                if not text or "+" in text:
                    continue
                toks = shelf_tokens(text)
                uniq = list(dict.fromkeys(toks))
                if len(uniq) != len(toks):
                    shelf.text = rebuild_shelf(uniq)
                    fixed += 1
    return fixed


def sync_viewpoints(win, dash) -> int:
    """Bring a window's `<viewpoints>` in line with the sheets REALLY on the dashboard."""
    vps = win.find("viewpoints")
    if vps is None:
        return 0
    zones = dash.find("zones")
    on_dash = [z.get("name") for z in zones.iter("zone")
               if z.get("name") and z.get("type-v2") in (None, "")] if zones is not None else []
    zoom = {}
    for vp in list(vps):
        z = vp.find("zoom")
        zoom[vp.get("name")] = z.get("type") if z is not None else "entire-view"
        vps.remove(vp)
    for sheet in dict.fromkeys(on_dash):
        vp = etree.SubElement(vps, "viewpoint")
        vp.set("name", sheet)
        etree.SubElement(vp, "zoom").set("type", zoom.get(sheet, "entire-view"))
    return len(on_dash)


def strip_phone_layout(dash) -> bool:
    """Remove a dashboard's phone layout."""
    dl = dash.find("devicelayouts")
    if dl is None:
        return False
    dash.remove(dl)
    return True


def unique_zone_ids(dash) -> int:
    """Make repeated zone `id`s unique within a dashboard."""
    seen, fixed = set(), 0
    mx = max((int(z.get("id")) for z in dash.iter("zone")
              if (z.get("id") or "").isdigit()), default=0)
    for z in dash.iter("zone"):
        zid = z.get("id")
        if not zid:
            continue
        if zid in seen:
            mx += 1
            z.set("id", str(mx))
            fixed += 1
        else:
            seen.add(zid)
    return fixed


def clone_dashboard(root, source: str, name: str, sheet_map: dict) -> dict:
    """Copy a dashboard, remapping its sheets."""
    dashes, windows = root.find("dashboards"), root.find("windows")
    if any(d.get("name") == name for d in dashes.findall("dashboard")):
        return {}
    tpl = next((d for d in dashes.findall("dashboard")
                if d.get("name") == source), None)
    tpl_win = next((w for w in windows.findall("window")
                    if w.get("class") == "dashboard" and w.get("name") == source), None)
    if tpl is None or tpl_win is None:
        raise ValueError(f"no template dashboard {source}")

    dash = copy.deepcopy(tpl)
    dash.set("name", name)
    sid = dash.find("simple-id")
    if sid is not None:
        sid.set("uuid", new_uuid())
    for z in list(dash.iter("zone")):
        zn = z.get("name")
        if zn not in sheet_map:
            continue
        target = sheet_map[zn]
        if target and z.get("type-v2") != "color":
            z.set("name", target)
            cache = z.find("layout-cache")
            if cache is not None:
                z.remove(cache)
        else:
            z.getparent().remove(z)
    strip_phone_layout(dash)
    unique_zone_ids(dash)
    dashes.append(dash)

    win = copy.deepcopy(tpl_win)
    win.set("name", name)
    wid = new_uuid()
    wsid = win.find("simple-id")
    if wsid is not None:
        wsid.set("uuid", wid)
    sync_viewpoints(win, dash)
    windows.append(win)
    return {"page": name, "window_uuid": wid}


def window_uuid(root, dash_name: str) -> str:
    """uuid of a dashboard's window; a navigation button addresses the jump with it."""
    for w in root.find("windows").findall("window"):
        if w.get("class") == "dashboard" and w.get("name") == dash_name:
            sid = w.find("simple-id")
            if sid is not None:
                return sid.get("uuid") or ""
    return ""


def _is_nav_button(zone) -> bool:
    """Whether the zone is a NAVIGATION button, not hide/show or export."""
    b = zone.find("button")
    return b is not None and (b.get("action") or "").startswith("tabdoc:goto-sheet")


def add_nav_buttons(root, targets) -> int:
    """A button for each new dashboard, ON ALL dashboards of the workbook."""
    if not isinstance(targets, dict):
        targets = {n: window_uuid(root, n) for n in targets}
    targets = {n: u for n, u in targets.items() if u}
    added = 0
    for dash in root.find("dashboards").findall("dashboard"):
        zones = dash.find("zones")
        if zones is None:
            continue
        buttons = [z for z in zones.iter("zone") if _is_nav_button(z)]
        if not buttons:
            continue
        have = {b.findtext(".//caption") for b in buttons}
        anchor = sorted(buttons, key=lambda z: int(z.get("y") or 0))[-1]
        next_id = 1 + max((int(z.get("id") or 0) for z in dash.iter("zone")
                           if (z.get("id") or "").isdigit()), default=0)
        for nm, win_id in targets.items():
            if nm in have:
                continue
            nb = copy.deepcopy(anchor)
            nb.set("id", str(next_id))
            next_id += 1
            nid = nb.find("simple-id")
            if nid is not None:
                nid.set("uuid", new_uuid())
            nb.find("button").set("action",
                                  f'tabdoc:goto-sheet window-id="{win_id}"')
            for cap in nb.iter("caption"):
                cap.text = nm
            anchor.addnext(nb)
            anchor = nb
            added += 1
    return added


def nav_buttons_absent_reason(root, targets: list) -> str:
    """Why `add_nav_buttons` returned 0, in words rather than a bare zero."""
    dashes = root.find("dashboards")
    has_button = dashes is not None and any(_is_nav_button(z) for z in dashes.iter("zone"))
    if not has_button:
        return ("the workbook has no navigation button to copy; "
                "a pattern is placed by the navigation_button zone (add_dashboard)")
    no_window = [t for t in targets if not window_uuid(root, t)]
    if no_window:
        return f"dashboards {no_window} have no window; the button has nowhere to lead"
    return "buttons for these dashboards are already in place"


def put_controls_over(dash, anchor_sheet: str, param_refs: list,
                      height: int = 5200) -> str:
    """A strip of parameter controls ABOVE a sheet zone."""
    zones = dash.find("zones")
    if zones is None:
        return "the dashboard has no zones"
    table = next((z for z in zones.iter("zone")
                  if z.get("name") == anchor_sheet), None)
    if table is None:
        return f"no zone for sheet {anchor_sheet}"
    holder = table.getparent()
    if (holder.get("type-v2") or "") != "layout-basic":
        return f"the sheet sits in {holder.get('type-v2')}; insertion cancelled"
    if any(z.get("param") in param_refs for z in zones.iter("zone")):
        return "controls are already in place"

    x, y = int(table.get("x")), int(table.get("y"))
    w, h = int(table.get("w")), int(table.get("h"))
    nid = max((int(z.get("id")) for z in dash.iter("zone")
               if (z.get("id") or "").isdigit()), default=0)
    row = etree.Element("zone")
    nid += 1
    row.set("id", str(nid))
    row.set("type-v2", "layout-flow")
    row.set("param", "horz")
    for k, v in (("x", x), ("y", y), ("w", w), ("h", height)):
        row.set(k, str(v))
    cw = w // max(1, len(param_refs))
    for i, ref in enumerate(param_refs):
        nid += 1
        z = etree.SubElement(row, "zone")
        z.set("id", str(nid))
        z.set("type-v2", "paramctrl")
        z.set("param", ref)
        z.set("mode", "compact")
        for k, v in (("x", x + i * cw), ("y", y), ("w", cw), ("h", height)):
            z.set(k, str(v))
    table.addprevious(row)
    table.set("y", str(y + height))
    table.set("h", str(h - height))
    return f"strip of {len(param_refs)} controls above '{anchor_sheet}'"


def drop_zone_by_param(dash, ref: str, kind: str = "paramctrl") -> int:
    """Remove a control zone by its parameter reference."""
    killed = 0
    for z in list(dash.iter("zone")):
        if z.get("param") == ref and z.get("type-v2") == kind:
            z.getparent().remove(z)
            killed += 1
    return killed


def _wrap_once(value: str, mark: str) -> str:
    v = str(value)
    return v if len(v) >= 2 and v[0] == v[-1] == mark else f"{mark}{v}{mark}"


def param_literal(datatype: str, value: str) -> str:
    """Parameter value as Tableau writes it in `value` and in a formula."""
    v = str(value)
    if datatype == "string":
        if len(v) >= 2 and v[0] == v[-1] == '"':
            return v
        return '"' + v.replace('"', '""') + '"'
    if datatype in ("date", "datetime"):
        return _wrap_once(v, "#")
    return v


def set_param_value(root, caption: str, value: str, quote: str = "",
                    unpin_dynamic: bool = True) -> int:
    """Parameter value by caption."""
    fixed, unpinned = 0, 0
    for c in root.iter("column"):
        if (c.get("caption") or "") != caption or not c.get("param-domain-type"):
            continue
        val = _wrap_once(value, quote) if quote else param_literal(c.get("datatype"), value)
        c.set("value", val)
        calc = c.find("calculation")
        if calc is not None:
            calc.set("formula", val)
        if unpin_dynamic and c.get("default-value-field"):
            del c.attrib["default-value-field"]
            unpinned += 1
        fixed += 1
    if unpinned:
        print(f"  warning: '{caption}': default-value-field binding removed "
              f"({unpinned} declarations); otherwise the value is overwritten on open")
    return fixed


def retune_categorical_filter(root, field: str, values: list) -> int:
    """Rebuild the value enumeration of a filter."""
    fixed = 0
    for f in root.iter("filter"):
        if field not in (f.get("column") or ""):
            continue
        union = next((g for g in f.iter("groupfilter")
                      if g.get("function") == "union"), None)
        level = next((g.get("level") for g in f.iter("groupfilter")
                      if g.get("level")), f"[{field}]")
        top = f.find("groupfilter")
        if union is None:
            # one member or "all": Tableau writes a list of members as a union
            if top is None or top.get("function") not in ("member", "level-members"):
                continue
            union = etree.Element("groupfilter")
            union.set("function", "union")
            union.set(_u("ui-domain"), "database")
            union.set(_u("ui-enumeration"), "inclusive")
            union.set(_u("ui-marker"), "enumerate")
            f.replace(top, union)
        for g in list(union):
            union.remove(g)
        for v in values:
            g = etree.SubElement(union, "groupfilter")
            g.set("function", "member")
            g.set("level", level)
            g.set("member", f'"{v}"')
        fixed += 1
    return fixed


_REMOTE_TYPE = {"integer": "20", "real": "5", "date": "133",
                "datetime": "135", "boolean": "11", "string": "129"}
_AGG = {"integer": "Sum", "real": "Sum", "date": "Year",
        "datetime": "Year", "boolean": "Count", "string": "Count"}


_ROLE_BY_TYPE = {"string": ("dimension", "nominal"), "date": ("dimension", "ordinal"),
                 "datetime": ("dimension", "ordinal"), "boolean": ("dimension", "nominal"),
                 "integer": ("measure", "quantitative"), "real": ("measure", "quantitative")}


def sync_column_decls(ds, columns: list) -> dict:
    """Bring a datasource's `<column>` declarations in line with the new schema's columns."""
    want = {c["name"]: c["datatype"] for c in columns}
    have, dropped = set(), 0
    for col in list(ds.findall("column")):
        if col.find("calculation") is not None or col.get("param-domain-type"):
            continue
        if (col.get("name") or "").startswith("[:"):
            continue
        nm = (col.get("name") or "").strip("[]")
        if nm in want:
            have.add(nm)
        else:
            ds.remove(col)
            dropped += 1
    added = 0
    for name, dt in want.items():
        if name in have:
            continue
        role, ctype = _ROLE_BY_TYPE.get(dt, ("dimension", "nominal"))
        col = etree.Element("column")
        col.set("datatype", dt)
        col.set("name", f"[{name}]")
        col.set("role", role)
        col.set("type", ctype)
        insert_in_order(ds, col, _DS_ORDER)
        added += 1
    return {"added": added, "removed": dropped}


def _sync_object_graph(ds, cname: str, relation_name: str, sql: str) -> int:
    """Point the datasource's logical layer (`<object-graph>`) at the same Custom SQL."""
    og = ds.find("./object-graph")
    if og is None:
        og = etree.SubElement(ds, "object-graph")
    objs = og.find("./objects")
    if objs is None:
        objs = etree.SubElement(og, "objects")
    if len(objs) == 0:
        etree.SubElement(objs, "object")
    kept = list(objs)[:1]
    for el in list(objs):
        if el not in kept:
            objs.remove(el)
    if not kept:
        return 0
    obj = kept[0]
    obj.set("caption", ds.get("caption") or relation_name)
    if not (obj.get("id") or "").startswith("_"):
        obj.set("id", "_" + uuid.uuid4().hex.upper())
    for pr in list(obj.findall("properties")):
        obj.remove(pr)
    props = etree.SubElement(obj, "properties")
    props.set("context", "")
    rel = etree.SubElement(props, "relation")
    rel.set("connection", cname)
    rel.set("name", relation_name)
    rel.set("type", "text")
    rel.text = sql
    return 1


FOLDER_CANON = ("Fields", "Date", "Measures", "Calcs", "System")


def apply_folder_canon(root, *, datasource: str = "", dims: tuple = (),
                       dates: tuple = ()) -> dict:
    """Arrange a datasource's fields into the corpus's canonical folders."""
    from lxml import etree

    done = {}
    for ds in root.findall("./datasources/datasource"):
        name = ds.get("name") or ""
        if name == "Parameters" or ds.find("connection") is None:
            continue
        if datasource and datasource not in (ds.get("caption"), name):
            continue
        plan = {k: [] for k in FOLDER_CANON}
        for col in ds.findall("column"):
            raw = (col.get("name") or "").strip("[]")
            cap = col.get("caption") or raw
            if not raw or raw.startswith(":"):
                continue
            dtype = (col.get("datatype") or "").lower()
            if cap in dates or raw in dates or dtype in ("date", "datetime"):
                bucket = "Date"
            elif cap.startswith("_") or raw.startswith("_"):
                bucket = "System"
            elif col.find("calculation") is not None:
                bucket = "Calcs"
            elif cap in dims or raw in dims or dtype == "string":
                bucket = "Fields"
            else:
                bucket = "Measures"
            plan[bucket].append(raw)

        for old in ds.findall("folders-common") + ds.findall("folder"):
            ds.remove(old)
        common = etree.SubElement(ds, "folders-common")
        for fname in FOLDER_CANON:
            items = sorted(set(plan[fname]))
            if not items:
                continue
            f = etree.SubElement(common, "folder")
            f.set("name", fname)
            for it in items:
                fi = etree.SubElement(f, "folder-item")
                fi.set("name", f"[{it}]")
                fi.set("type", "field")
        done[ds.get("caption") or name] = {k: len(set(v)) for k, v in plan.items() if v}
    return done


def to_live_sql(root, sql: str, columns: list, *, server: str, port: str,
                dbname: str, username: str, driver: str = "mysql",
                relation_name: str = "Custom SQL Query",
                datasource: str = "") -> dict:
    """Switch the workbook's datasource to a LIVE connection with Custom SQL and drop the extract."""
    changed, graphs = 0, 0
    targets, seen = [], []
    for ds in root.findall("./datasources/datasource"):
        if ds.get("name") == "Parameters":
            continue
        if ds.find("connection") is None:
            continue
        seen.append(ds.get("caption") or ds.get("name"))
        if datasource and datasource not in (ds.get("caption"), ds.get("name")):
            continue
        targets.append(ds)
    if datasource and not targets:
        raise ValueError(
            f"datasource {datasource!r} is not in the workbook; available: {sorted(set(seen))}")

    for ds in targets:
        conn = ds.find("connection")
        cname = f"{driver}.{uuid.uuid4().hex[:26]}"

        for tag in ("named-connections", "relation", "metadata-records"):
            for el in conn.findall(tag):
                conn.remove(el)

        ncs = etree.SubElement(conn, "named-connections")
        nc = etree.SubElement(ncs, "named-connection")
        nc.set("caption", server)
        nc.set("name", cname)
        inner = etree.SubElement(nc, "connection")
        for k, v in (("class", driver), ("dbname", dbname), ("odbc-native-protocol", ""),
                     ("one-time-sql", ""), ("port", str(port)), ("server", server),
                     ("server-oauth", ""), ("source-charset", ""),
                     ("username", username), ("workgroup-auth-mode", "prompt")):
            inner.set(k, v)

        rel = etree.SubElement(conn, "relation")
        rel.set("connection", cname)
        rel.set("name", relation_name)
        rel.set("type", "text")
        rel.text = sql

        recs = etree.SubElement(conn, "metadata-records")
        for i, col in enumerate(columns):
            dt = col["datatype"]
            rec = etree.SubElement(recs, "metadata-record")
            rec.set("class", "column")
            for tag, text in (("remote-name", col["name"]),
                              ("remote-type", _REMOTE_TYPE.get(dt, "129")),
                              ("local-name", f"[{col['name']}]"),
                              ("parent-name", f"[{relation_name}]"),
                              ("remote-alias", col["name"]),
                              ("ordinal", str(i)),
                              ("local-type", dt),
                              ("aggregation", _AGG.get(dt, "Count")),
                              ("contains-null", "true")):
                etree.SubElement(rec, tag).text = text

        decls = sync_column_decls(ds, columns)
        graphs += _sync_object_graph(ds, cname, relation_name, sql)

        for ex in ds.findall("extract"):
            ds.remove(ex)
        changed += 1
    return {"sources_switched": changed, "schema_column_count": len(columns),
            "column_declarations": decls if targets else {},
            "object_graphs_rewritten": graphs,
            "workbook_sources": sorted(set(seen))}


def fit_to_extract(book_path: str, rename: dict = None,
                   fallback_dim: str = "") -> dict:
    """Bring the workbook's references in line with the columns of ITS OWN extract."""
    from . import safexml
    from .extract import schema_from_hyper
    import os
    import tempfile
    import zipfile

    with zipfile.ZipFile(book_path) as z:
        hy = [n for n in z.namelist() if n.endswith(".hyper")]
        if not hy:
            raise ValueError("the workbook has no extract")
        tmp = os.path.join(tempfile.gettempdir(), "twkit_fit.hyper")
        with open(tmp, "wb") as f:
            f.write(z.read(hy[0]))
    live = {c["name"] for c in schema_from_hyper(tmp)}

    root = safexml.from_twbx(book_path)
    report = {"extract_column_count": len(live), "renamed": {}, "removed": []}
    for old, new in (rename or {}).items():
        n = rename_field(root, old, new)
        if n:
            report["renamed"][f"{old} -> {new}"] = n
            root = safexml.from_bytes(etree.tostring(root))

    used = set()
    for col in root.iter("column"):
        if col.find("calculation") is not None or col.get("param-domain-type"):
            continue
        nm = (col.get("name") or "").strip("[]")
        if nm and not nm.startswith((":", "Calculation_", "__tableau", "Parameter ")):
            used.add(nm)
    missing = sorted(used - live)
    if missing:
        report["removed"] = missing
        report.update(drop_fields(root, missing, keep_on_shelves=fallback_dim))
        for rel in root.iter("relation"):
            cols = rel.find("columns")
            if cols is None:
                continue
            for c in list(cols):
                if c.get("name") not in live:
                    cols.remove(c)
            for i, c in enumerate(cols):
                c.set("ordinal", str(i))
        stale = 0
        for rec in list(root.iter("metadata-record")):
            rn = rec.findtext("remote-name") or ""
            if rn and rn not in live:
                rec.getparent().remove(rec)
                stale += 1
        report["metadata_records_dropped"] = stale
    return {"root": root, "report": report}


def field_index(root) -> dict:
    """All datasource fields: column name to caption, and caption to caption."""
    idx = {}
    for ds in root.find("datasources").findall("datasource"):
        if ds.get("name") == "Parameters":
            continue
        for c in ds.findall("column"):
            name = (c.get("name") or "").strip("[]")
            cap = c.get("caption") or name
            if not name:
                continue
            idx.setdefault(name, cap)
            idx.setdefault(cap, cap)
        for rec in ds.iter("metadata-record"):
            if rec.get("class") != "column":
                continue
            name = (rec.findtext("local-name") or "").strip("[]")
            if name and not name.startswith((":", "__tableau")):
                idx.setdefault(name, name)
    return idx


_AGG_FUNCS = ("SUM", "COUNTD", "COUNT", "AVG", "MIN", "MAX", "MEDIAN", "ATTR",
              "STDEV", "VAR", "PERCENTILE", "CORR", "COVAR", "TOTAL",
              "RANK", "RANK_UNIQUE", "RANK_DENSE", "WINDOW_SUM", "WINDOW_AVG",
              "RUNNING_SUM", "INDEX", "SIZE", "FIRST", "LAST")


def bare_formula(formula: str) -> str:
    """A formula without field references and string literals."""
    out = re.sub(r"\[[^\]]*\]", " ", formula or "")
    out = re.sub(r"'[^']*'", " ", out)
    return re.sub(r'"[^"]*"', " ", out)


def is_aggregated(formula: str) -> bool:
    """Whether a formula is already an aggregate; a second aggregate on top is forbidden."""
    if not formula:
        return False
    if "{" in formula and "}" in formula:
        return True
    up = bare_formula(formula).upper()
    return any(re.search(rf"\b{f}\s*\(", up) for f in _AGG_FUNCS)


def resolve_fields(root, tokens: list, default_agg: str = "SUM") -> dict:
    """Bring a field list to the form the sheet builder understands."""
    idx = field_index(root)
    roles, aggregated = {}, set()
    for ds in root.find("datasources").findall("datasource"):
        if ds.get("name") == "Parameters":
            continue
        for c in ds.findall("column"):
            cap = c.get("caption") or (c.get("name") or "").strip("[]")
            roles[cap] = c.get("role") or ""
            calc = c.find("calculation")
            if calc is not None and is_aggregated(calc.get("formula") or ""):
                aggregated.add(cap)
        for rec in ds.iter("metadata-record"):
            if rec.get("class") != "column":
                continue
            nm = (rec.findtext("local-name") or "").strip("[]")
            if not nm or nm in roles:
                continue
            roles[nm] = ("measure" if (rec.findtext("local-type") or "")
                         in ("real", "integer") else "dimension")
    out, missing = [], []
    for t in tokens:
        t = (t or "").strip()
        if not t:
            continue
        key = t.strip("[]")
        cap = idx.get(key)
        if cap is None:
            if "(" in t and ")" in t:
                out.append(t)
                continue
            missing.append(t)
            continue
        needs_agg = roles.get(cap) == "measure" and cap not in aggregated
        out.append(f"{default_agg}([{cap}])" if needs_agg else cap)
    return {"fields": out, "not_found": missing}


def _sheet(root, name: str):
    for ws in root.iter("worksheet"):
        if ws.get("name") == name:
            return ws
    return None


def _ds_name(ws) -> str:
    """The sheet's data source; Parameters, often listed first, is not one."""
    for d in ws.iterfind(".//view/datasources/datasource"):
        if d.get("name") != "Parameters":
            return d.get("name") or ""
    return ""


HEAT_RAMP = ["#f1f1f1", "#dce8e7", "#c7dfde", "#b4d6d4", "#a2cdcb", "#91c4c1",
             "#81bbb8", "#71b2af", "#63a9a6", "#55a09d", "#499894"]


HEAT_PALETTE = "tableau-blue-light"
HEAT_PALETTE_PCT = "red_green"


def heat_columns(root, sheet: str, *, mark: str = "Square", ramp: list = None,
                 palette: str = HEAT_PALETTE,
                 pct_palette: str = HEAT_PALETTE_PCT) -> dict:
    """Heat fill of a table-indicator's COLUMNS: color per measure separately."""
    ws = _sheet(root, sheet)
    if ws is None:
        return {"loaded": 0, "why": f"no sheet '{sheet}'"}
    ds = _ds_name(ws)
    if not ds:
        return {"loaded": 0, "why": "the sheet has no datasource"}

    measures = []
    for filt in ws.iter("filter"):
        if filt.get("column") != f"[{ds}].[:Measure Names]":
            continue
        for g in filt.iter("groupfilter"):
            mem = (g.get("member") or "").strip('"')
            if mem and mem not in measures:
                measures.append(mem)

    done = 0
    for pane in ws.iter("pane"):
        enc = pane.find("encodings")
        if enc is None or enc.find("color") is not None:
            continue
        m = pane.find("mark")
        if m is not None:
            m.set("class", mark)
        col = etree.Element("color")
        col.set("column", f"[{ds}].[Multiple Values]")
        col.set("separate-domains", "true")
        enc.insert(0, col)
        style = pane.find("style")
        if style is None:
            style = etree.SubElement(pane, "style")
        rule = next((r for r in style.findall("style-rule") if r.get("element") == "mark"), None)
        if rule is None:
            rule = etree.SubElement(style, "style-rule")
            rule.set("element", "mark")
        if not any(f.get("attr") == "mark-labels-show" for f in rule):
            f = etree.SubElement(rule, "format")
            f.set("attr", "mark-labels-show")
            f.set("value", "true")
        done += 1
    if done:
        # colour encodings live in the sheet's table style (corpus 18/18, reference
        # heat_separate_legends); a pane-level rule is not where the colour tools look
        table = ws.find("table")
        style = table.find("style")
        if style is None:
            style = etree.Element("style")
            insert_in_order(table, style, _TABLE_ORDER)
        st = next((r for r in style.findall("style-rule") if r.get("element") == "mark"), None)
        if st is None:
            st = etree.SubElement(style, "style-rule")
            st.set("element", "mark")
        have = {e.get("field") for e in st.findall("encoding")}
        umbrella = f"[{ds}].[Multiple Values]"
        if umbrella not in have:
            e = etree.SubElement(st, "encoding")
            e.set("attr", "color")
            e.set("field", umbrella)
            e.set("symmetric", "false")
            e.set("type", "custom-interpolated")
            pal = etree.SubElement(e, "color-palette")
            pal.set("custom", "true")
            pal.set("name", "")
            pal.set("type", "ordered-sequential")
            for c in (ramp or HEAT_RAMP):
                etree.SubElement(pal, "color").text = c
        for ref in measures:
            if ref in have:
                continue
            e = etree.SubElement(st, "encoding")
            e.set("attr", "color")
            e.set("field", ref)
            e.set("palette", pct_palette if ":pcto:" in ref or "pcto:" in ref else palette)
            e.set("type", "interpolated")
    return {"loaded": done, "sheet": sheet, "measure_count": len(measures)}


def dual_axis(root, sheet: str, column: str, *, derivation: str = "User",
              mark: str = "Line", color: str = "", labels: bool = False) -> dict:
    """Put a second measure ON THE SAME axis (combo: bars + line)."""
    ws = _sheet(root, sheet)
    if ws is None:
        return {"axis": 0, "why": f"no sheet '{sheet}'"}
    ds = _ds_name(ws)
    src = None
    for c in root.iter("column"):
        nm = (c.get("name") or "").strip("[]")
        if c.find("calculation") is None:
            continue
        if nm == column or (c.get("caption") or "") == column:
            src, column = c, nm
            break
    inst = f"[{'usr' if derivation == 'User' else derivation.lower()}:{column}:qk]"
    ref = f"[{ds}].{inst}"
    rows = ws.find(".//rows")
    if rows is None or not (rows.text or "").strip():
        return {"axis": 0, "why": "rows are empty, nothing to duplicate"}
    if ref in (rows.text or ""):
        return {"axis": 0, "why": "the measure is already on this axis"}

    dep = ws.find(f".//datasource-dependencies[@datasource='{ds}']")
    if dep is None:
        return {"axis": 0, "why": "no datasource-dependencies"}
    have = {c.get("name") for c in dep.findall("column")}
    if f"[{column}]" not in have:
        if src is None:
            return {"axis": 0, "why": f"no declaration of '{column}' in the workbook"}
        dep.insert(0, copy.deepcopy(src))
    calc = src.find("calculation") if src is not None else None
    if calc is not None:
        by_name = {(c.get("name") or "").strip("[]"): c for c in root.iter("column")
                   if c.get("name")}
        for used in set(re.findall(r"\[([^\]\[]+)\]", calc.get("formula") or "")):
            decl = by_name.get(used)
            if decl is not None and f"[{used}]" not in {c.get("name")
                                                       for c in dep.findall("column")}:
                dep.insert(0, copy.deepcopy(decl))
    if not any(ci.get("name") == inst for ci in dep.findall("column-instance")):
        ci = etree.SubElement(dep, "column-instance")
        ci.set("column", f"[{column}]")
        ci.set("derivation", derivation)
        ci.set("name", inst)
        ci.set("pivot", "key")
        ci.set("type", "quantitative")

    base_ref = rows.text.strip()
    rows.text = f"({base_ref} + {ref})"

    panes = ws.find(".//panes")
    template = panes.find("pane")
    if "id" in template.attrib:
        del template.attrib["id"]

    names_ref = f"[{ds}].[:Measure Names]"
    for pane in (template,):
        enc0 = pane.find("encodings")
        if enc0 is None:
            enc0 = etree.Element("encodings")
            insert_in_order(pane, enc0, _PANE_ORDER)
        if not any(c.tag == "color" for c in enc0):
            c = etree.SubElement(enc0, "color")
            c.set("column", names_ref)

    left = copy.deepcopy(template)
    left.set("id", "1")
    left.set("y-axis-name", base_ref)

    right = copy.deepcopy(template)
    right.set("id", "2")
    right.set("y-axis-name", ref)
    m = right.find("mark")
    if m is not None:
        m.set("class", mark)
    enc = right.find("encodings")
    if enc is not None and not labels:
        for t in enc.findall("text"):
            enc.remove(t)
    elif enc is not None:
        for t in enc.findall("text"):
            t.set("column", ref)
    for st in right.iter("style-rule"):
        if st.get("element") != "mark":
            continue
        for f in list(st):
            if f.get("attr") in ("mark-labels-show", "mark-labels-cull") and not labels:
                st.remove(f)
        if color:
            f = etree.SubElement(st, "format")
            f.set("attr", "mark-color")
            f.set("value", color)
    panes.append(left)
    panes.append(right)

    for win in root.iter("window"):
        if win.get("class") != "worksheet" or win.get("name") != sheet:
            continue
        cards = win.find("cards")
        if cards is None:
            continue
        edge = next((e for e in cards.findall("edge") if e.get("name") == "right"), None)
        if edge is None:
            edge = etree.SubElement(cards, "edge")
            edge.set("name", "right")
        if not any(c.get("param") == names_ref for c in edge.iter("card")):
            strip = etree.SubElement(edge, "strip")
            strip.set("size", "160")
            card = etree.SubElement(strip, "card")
            card.set("pane-specification-id", "1")
            card.set("param", names_ref)
            card.set("type", "color")

    style = ws.find("table/style")
    if style is None:
        style = etree.Element("style")
        ws.find("table").insert(1, style)
    axis = next((r for r in style.findall("style-rule") if r.get("element") == "axis"), None)
    if axis is None:
        axis = etree.Element("style-rule")
        axis.set("element", "axis")
        style.insert(0, axis)
    if not any(e.get("attr") == "space" and e.get("field") == ref
               for e in axis.findall("encoding")):
        e = etree.Element("encoding")
        e.set("attr", "space")
        e.set("class", "0")
        e.set("field", ref)
        e.set("field-type", "quantitative")
        e.set("fold", "true")
        e.set("scope", "rows")
        e.set("type", "space")
        axis.insert(0, e)
    return {"axis": 1, "sheet": sheet, "measure": ref, "mark": mark, "pane_count": 3}


def _set_field_format(root, sheet: str, field_caption: str, attr: str, px: int, element: str) -> int:
    fixed = 0
    for ws in root.iter("worksheet"):
        if ws.get("name") != sheet:
            continue
        style = ws.find(".//table/style")
        if style is None:
            tbl = ws.find(".//table")
            if tbl is None:
                continue
            style = etree.SubElement(tbl, "style")
        rule = next((r for r in style.findall("style-rule")
                     if r.get("element") == element), None)
        if rule is None:
            rule = etree.SubElement(style, "style-rule")
            rule.set("element", element)
        names = field_names(root, field_caption)
        refs = []
        for tag in ("rows", "cols"):
            for shelf in ws.iter(tag):
                refs += [t for t in shelf_tokens(shelf.text or "")
                         if any(mentions(t, n) for n in names) or field_caption in t]
        if not refs:
            continue
        have = {f.get("field"): f for f in rule.findall("format")
                if f.get("attr") == attr}
        for ref in refs:
            fmt = have.get(ref)
            if fmt is None:
                fmt = etree.SubElement(rule, "format")
                fmt.set("attr", attr)
                fmt.set("field", ref)
            fmt.set("value", str(px))
            fixed += 1
    return fixed


def set_column_width(root, sheet: str, field_caption: str, px: int,
                     element: str = "header") -> int:
    """Column width of a sheet in pixels."""
    return _set_field_format(root, sheet, field_caption, "width", px, element)


def set_header_height(root, sheet: str, field_caption: str, px: int) -> int:
    """Height of a column header band in pixels: Tableau wraps the header text into the lines that fit."""
    return _set_field_format(root, sheet, field_caption, "height", px, "header")


def set_row_height(root, sheet: str, px: int) -> int:
    """Row height of a text table; Tableau does not wrap row labels in taller rows (checked).

    Written as Tableau does (corpus): a `cell` height on the innermost discrete row field."""
    ws = _sheet(root, sheet)
    refs = [r for r in re.findall(r"\[[^\]]+\]\.\[[^\]]+\]", ws.findtext("table/rows") or "")
            if re.search(r":(nk|ok)\]$", r)] if ws is not None else []
    if not refs:
        return 0
    bare = refs[-1].rsplit(".[", 1)[1][:-1].split(":")[1]
    cap = next((c.get("caption") or bare for c in root.iter("column") if c.get("name") == f"[{bare}]"), bare)
    return _set_field_format(root, sheet, cap, "height", px, "cell")


def _first_field(root, ws, shelf: str, discrete: bool = False) -> tuple | None:
    """`(caption, instance)` of the first field on a shelf; Measure Names is ':Measure Names'."""
    from . import frame as FR
    hidden = FR._hidden_headers(ws) if discrete else set()
    for ref in re.findall(r"\[[^\]]+\]\.\[[^\]]+\]", ws.findtext(f"table/{shelf}") or ""):
        inner = ref.rsplit(".[", 1)[1][:-1]
        if inner == ":Measure Names":
            return inner, inner
        if inner.count(":") < 2 or (discrete and (not inner.endswith((":nk", ":ok")) or
                                                  "[" + inner + "]" in hidden)):
            continue
        name = "[" + inner.split(":")[1] + "]"
        return next((c.get("caption") or name[1:-1] for c in root.iter("column")
                     if c.get("name") == name), name[1:-1]), inner
    return None


def _title_text(ws, name: str) -> str:
    node = ws.find(".//layout-options/title/formatted-text")
    if node is None:
        return name
    return "".join(r.text or "" for r in node.iter("run")).replace("<Sheet Name>", name)


def fit_tables_once(root, needs: dict) -> dict:
    """One pass of `fit_tables` against measured needs (`stylecritic.content_needs`).

    Header bands grow to the lines their headers wrap into, equal across tables side by side (a
    band already set counts too), and so do row heights, or the rows drift apart; a narrow table's first column widens so a one-line title takes
    two lines. Never shrinks a size."""
    from . import contentfit as CF
    from . import frame as FR
    from . import layoutmodel as LM
    sheets = {ws.get("name"): ws for ws in root.iter("worksheet")}
    want = {}
    for n, ws in ((n, sheets[n]) for n in needs if n in sheets):
        first = _first_field(root, ws, "cols")
        have = FR.head_height(ws, ["[" + first[1] + "]"]) if first else None
        want[n] = max(CF.header_px((needs.get(n) or {}).get("head_lines") or 0), int(have or 0))
    heads = {n: px for n, px in want.items() if px}
    rows_px = {n: int(FR.row_height(sheets[n]) or 0) for n in want}
    tall = {}
    for dash in root.iter("dashboard"):
        zones = {z.name: {"y": z.y, "h": z.h} for z in LM.build(dash).sheets() if z.name in sheets}
        for n, px in CF.equal_row_heights(zones, want).items():
            heads[n] = max(heads.get(n, 0), px)
        rows = {n: (needs.get(n) or {}).get("rows") for n in rows_px}
        for n, px in CF.equal_row_pitch(zones, rows_px, rows).items():
            tall[n] = max(tall.get(n, 0), px)
    out = {"header_px": {}, "title_px": {}, "row_px": {}}
    for n, px in tall.items():
        if px > rows_px.get(n, 0) and set_row_height(root, n, px):
            out["row_px"][n] = px
    for n, px in heads.items():
        first = _first_field(root, sheets[n], "cols")
        if first and px > (FR.head_height(sheets[n], ["[" + first[1] + "]"]) or 0) \
                and set_header_height(root, n, first[0], px):
            out["header_px"][n] = px
    for n, nd in needs.items():
        ws, cols = sheets.get(n), nd.get("cols") or []
        if ws is None or not cols or "\n" in _title_text(ws, n).strip() \
                or not CF.title_room_px(_title_text(ws, n), cols):
            continue
        first = _first_field(root, ws, "rows", discrete=True)
        if first is None:
            continue
        cap, inner = first
        px = CF.title_room_px(_title_text(ws, n), cols, None if inner == ":Measure Names" else cap)
        if px > (FR.xml_width(ws, "header", inner + "]") or 0) \
                and set_column_width(root, n, cap, px, element="header"):
            out["title_px"][n] = px
    return out


def fit_tables(path: str, passes: int = 3, out_dir: str = "") -> dict:
    """Text tables sized from what the frame measured, repeated until the measures settle.

    A wider column changes how headers wrap, so one pass can leave a stale decision: measure,
    apply, measure again, until a pass changes nothing (at most `passes`). Rewrites `path`."""
    from . import order as ORD
    from . import safexml
    from . import stylecritic as SC
    done = []
    for _ in range(passes):
        got = fit_tables_once(root := safexml.from_twbx(path), SC.content_needs(path, out_dir=out_dir))
        if not any(got.values()):
            return {"passes": len(done), "converged": True, "changes": done}
        ORD.normalize_workbook(root)
        safexml.to_twbx(path, root, path)
        done.append(got)
    return {"passes": len(done), "converged": False, "changes": done,
            "note": f"still changing after {passes} passes; run again or look at the frame"}


_LABEL_AFTER =("axis", "cell", "gridline", "header", "mark", "dropline", "refline", "label")


def hide_header(root, sheet: str, field_caption: str) -> int:
    """Hide a dimension's header on a shelf ("Show Header" off): the field stays a level of row detail but the..."""
    fixed = 0
    for ws in root.iter("worksheet"):
        if ws.get("name") != sheet:
            continue
        tbl = ws.find(".//table")
        if tbl is None:
            continue
        names = field_names(root, field_caption)
        refs = []
        for tag in ("rows", "cols"):
            for shelf in ws.iter(tag):
                refs += [(t, tag) for t in shelf_tokens(shelf.text or "")
                         if any(mentions(t, n) for n in names)]
        if not refs:
            continue
        style = tbl.find("style")
        if style is None:
            style = etree.Element("style")
            panes = tbl.find("panes")
            (panes.addprevious(style) if panes is not None else tbl.append(style))
        rule = next((r for r in style.findall("style-rule") if r.get("element") == "label"), None)
        if rule is None:
            rule = etree.Element("style-rule")
            rule.set("element", "label")
            later = next((r for r in style.findall("style-rule")
                          if r.get("element") not in _LABEL_AFTER), None)
            (later.addprevious(rule) if later is not None else style.append(rule))
        have = {f.get("field") for f in rule.findall("format") if f.get("attr") == "display"}
        for ref, tag in refs:
            if ref in have:
                continue
            fmt = etree.SubElement(rule, "format")
            fmt.set("attr", "display")
            fmt.set("field", ref)
            fmt.set("value", "false")
            fixed += 1
    return fixed

def set_number_format(root, field_caption: str, mask: str) -> int:
    """Number format of a field (`default-format`) across the whole workbook."""
    fixed = 0
    for c in root.iter("column"):
        if (c.get("caption") or "") != field_caption:
            continue
        c.set("default-format", mask)
        fixed += 1
    return fixed


def set_field_color(root, sheet: str, palette: str, mapping: dict = None) -> int:
    """Color palette of a sheet and, if needed, pinned colors for values."""
    fixed = 0
    for ws in root.iter("worksheet"):
        if ws.get("name") != sheet:
            continue
        for enc in ws.iter("color"):
            style = ws.find(".//style")
            if style is None:
                continue
            rule = etree.SubElement(style, "style-rule")
            rule.set("element", "mark")
            enc_el = etree.SubElement(rule, "encoding")
            enc_el.set("attr", "color")
            enc_el.set("field", enc.get("column") or "")
            enc_el.set("palette", palette)
            enc_el.set("type", "palette")
            for val, color in (mapping or {}).items():
                m = etree.SubElement(enc_el, "map")
                m.set("to", color)
                bucket = etree.SubElement(m, "bucket")
                bucket.text = f'"{val}"'
            fixed += 1
    return fixed


COLUMN_ITEM_PX = {"dashboard-object": 40, "paramctrl": 47, "filter": 58,
                  "text": 44, "empty": 5}

_CTL = ("paramctrl", "filter")
_NAV = ("dashboard-object",)

_ABS_PARENT = ("layout-basic", "zones")


def _parent_kind(zone) -> str:
    p = zone.getparent()
    if p is None:
        return ""
    return "zones" if p.tag == "zones" else (p.get("type-v2") or "")


def _rect(z) -> tuple:
    return tuple(int(z.get(k) or 0) for k in ("x", "y", "w", "h"))


def _kinds(z) -> dict:
    out: dict = {}
    for k in z.iter("zone"):
        t = k.get("type-v2") or "?"
        if t != "layout-flow":
            out[t] = out.get(t, 0) + 1
    return out


def _role(z) -> str:
    """Role of a column container."""
    k = _kinds(z)
    nav = any(k.get(t) for t in _NAV)
    ctl = any(k.get(t) for t in _CTL)
    return "buttons+controls" if nav and ctl else "buttons" if nav else "controls" if ctl else "other"


def left_column(dash, max_w: int = 32_000, max_x: int = 25_000) -> list:
    """Left-column containers whose coordinates can be set."""
    zones = dash.find("zones")
    if zones is None:
        return []
    out = []
    for z in zones.iter("zone"):
        if z.get("type-v2") != "layout-flow" or z.get("param") != "vert":
            continue
        x, _y, w, _h = _rect(z)
        if w <= 0 or w > max_w or x > max_x:
            continue
        if _parent_kind(z) not in _ABS_PARENT:
            continue
        if _role(z) == "other":
            continue
        out.append(z)
    return out


def _overlap(a: tuple, b: tuple) -> int:
    """Intersection area of two rectangles (0 means no overlap)."""
    dx = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    dy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return dx * dy if dx > 0 and dy > 0 else 0


def _mode(vals: list) -> int:
    """The most frequent value; on a tie, the smaller."""
    if not vals:
        return 0
    best, cnt = 0, -1
    for v in sorted(set(vals)):
        c = vals.count(v)
        if c > cnt:
            best, cnt = v, c
    return best


def column_report(root) -> dict:
    """Measure the left column on all dashboards: where it stands, what it consists of, what is declared."""
    pages: dict = {}
    xs, ws = [], []
    by_role: dict = {}
    for dash in root.iter("dashboard"):
        cols = left_column(dash)
        items = []
        for z in cols:
            r = _rect(z)
            xs.append(r[0])
            ws.append(r[2])
            role = _role(z)
            by_role.setdefault(role, []).append(r)
            kids = [k for k in z.iter("zone") if (k.get("type-v2") or "") in COLUMN_ITEM_PX]
            items.append({
                "id": z.get("id"), "role": role, "rect": r,
                "parent": _parent_kind(z), "kinds": _kinds(z),
                "sizes_declared": sum(1 for k in kids if k.get("is-fixed") == "true"),
                "item_count": len(kids),
            })
        pages[dash.get("name")] = items or [{"column": "not found"}]
    spread = {}
    if len(xs) > 1:
        spread["Δx"] = max(xs) - min(xs)
        spread["Δw"] = max(ws) - min(ws)
    for role, rects in sorted(by_role.items()):
        if len(rects) > 1:
            spread[f"Δy [{role}]"] = max(r[1] for r in rects) - min(r[1] for r in rects)
            spread[f"Δh [{role}]"] = max(r[3] for r in rects) - min(r[3] for r in rects)
    return {"pages": pages, "spread": spread}


def align_left_column(root, rect: tuple = None, heights: dict = None,
                      pin_children: bool = True, pages: list = None) -> dict:
    """Put the left column in ONE place on all dashboards and pin its items."""
    heights = dict(COLUMN_ITEM_PX, **(heights or {}))
    changed, refused, notes = [], [], []

    targets = []
    for dash in root.iter("dashboard"):
        name = dash.get("name")
        if pages and name not in pages:
            continue
        cols = left_column(dash)
        if not cols:
            refused.append(f"{name}: left column not found")
            continue
        targets += [(name, dash, z) for z in cols]
    if not targets:
        return {"changed": [], "refused": refused, "measured": column_report(root)}

    if rect and rect[0] is not None:
        col_x = rect[0]
    else:
        col_x = min(_rect(z)[0] for _n, _d, z in targets)
    col_w = rect[2] if rect and rect[2] is not None else \
        min(_rect(z)[2] for _n, _d, z in targets)

    vert: dict = {}
    roles: dict = {}
    for _n, _d, z in targets:
        roles.setdefault(_role(z), []).append(z)
    for role, zs in roles.items():
        y = rect[1] if rect and rect[1] is not None else _mode([_rect(z)[1] for z in zs])
        h = rect[3] if rect and rect[3] is not None else _mode([_rect(z)[3] for z in zs])
        vert[role] = (y, h)
        if len(zs) > 1:
            notes.append(f"role '{role}': {len(zs)} containers -> y={y}, h={h}")

    plan = {}
    for name, _d, z in targets:
        y, h = vert[_role(z)]
        plan[id(z)] = (col_x, y, col_w, h)

    was_all = {id(z): _rect(z) for _n, _d, z in targets}

    def sibling_rects(z, planned: bool):
        """Neighbour rectangles, in planned or in original form."""
        p = z.getparent()
        if p is None:
            return []
        out = []
        for s in p.findall("zone"):
            if s is z:
                continue
            r = (plan.get(id(s)) or _rect(s)) if planned else (was_all.get(id(s)) or _rect(s))
            if r[2] > 0 and r[3] > 0:
                out.append(r)
        return out

    for name, dash, z in targets:
        was = _rect(z)
        now = plan[id(z)]
        if now != was:
            sib = sibling_rects(z, planned=True)
            if [r for r in sib if _overlap(now, r) > 0] and \
                    not [r for r in sibling_rects(z, planned=False)
                         if _overlap(was, r) > 0]:
                only_h = (col_x, was[1], col_w, was[3])
                if [r for r in sib if _overlap(only_h, r) > 0]:
                    refused.append(f"{name}/{_role(z)}: the new rectangle would overlap a "
                                   f"neighbouring zone; rolled back")
                    now = was
                else:
                    refused.append(f"{name}/{_role(z)}: the vertical would overlap a neighbour; "
                                   f"aligned only the left edge and width")
                    now = only_h
                plan[id(z)] = now
        if now != was:
            for k, v in zip(("x", "y", "w", "h"), now):
                z.set(k, str(v))
            changed.append(f"{name}/{_role(z)}: {was} -> {now}")

        if not pin_children:
            continue
        kids = [k for k in z.iter("zone") if (k.get("type-v2") or "") in heights]
        want = sum(heights[k.get("type-v2")] for k in kids)
        size = dash.find(".//size")
        canvas_h = int((size.get("minheight") if size is not None else 0) or 800)
        room = int(z.get("h") or 0) / 100_000 * canvas_h
        if want > room:
            fits = int(room // max(1, len(kids)))
            notes.append(f"{name}/{_role(z)}: declared heights {want} px do not fit in "
                         f"{room:.0f} px; sizes not written; for {len(kids)} items "
                         f"{fits} px each fits")
            continue
        pinned = 0
        for k in kids:
            px = str(heights[k.get("type-v2")])
            if k.get("fixed-size") != px or k.get("is-fixed") != "true":
                k.set("fixed-size", px)
                k.set("is-fixed", "true")
                pinned += 1
        if pinned:
            changed.append(f"{name}/{_role(z)}: pinned {pinned} of {len(kids)}")

    return {"changed": changed, "refused": refused, "notes": notes,
            "measured": column_report(root)}


def stretch_zones(dash, scale_h: bool = True, scale_w: bool = True,
                  only: list = None) -> dict:
    """Stretch sheets to their zones instead of drawing at natural size."""
    want = set(only or [])
    fixed = 0
    for z in dash.iter("zone"):
        name = z.get("name")
        kind = (z.get("type-v2") or "NONE").upper()
        if not name or kind != "NONE":
            continue
        if want and name not in want:
            continue
        lc = z.find("layout-cache")
        if lc is None:
            lc = etree.Element("layout-cache")
            z.insert(0, lc)
        lc.set("type-h", "scalable" if scale_h else "cell")
        lc.set("type-w", "scalable" if scale_w else "cell")
        fixed += 1
    return {"zones_stretched": fixed}


def set_sheet_title(root, sheet: str, text: str = "", size: str = "10",
                    bold: bool = True, legend: dict | None = None) -> int:
    """Sheet TITLE with its own text and size; `legend` {label: color} adds a color-coded key line."""
    fixed = 0
    for ws in root.iter("worksheet"):
        if ws.get("name") != sheet:
            continue
        for old in ws.findall("layout-options"):
            ws.remove(old)
        lo = etree.Element("layout-options")
        title = etree.SubElement(lo, "title")
        ft = etree.SubElement(title, "formatted-text")
        lines = (text or sheet).split("\n")
        for i, line in enumerate(lines):
            for piece in ([line] + ([_LB] if i < len(lines) - 1 else [])):
                run = etree.SubElement(ft, "run")
                run.set("fontsize", str(size))
                if bold:
                    run.set("bold", "true")
                run.text = piece if piece.strip() else "\u00a0"
        if legend:
            run = etree.SubElement(ft, "run")
            run.set("fontsize", str(size))
            run.text = _LB
            for label, color in legend.items():
                for text, ink in (("\u25a0 ", color), (f"{label}   ", "#555555")):
                    run = etree.SubElement(ft, "run")
                    run.set("fontcolor", ink)
                    run.set("fontsize", "9")
                    run.text = text
        ws.insert(0, lo)
        fixed += 1
    return fixed


_LB = "Æ\n"


def kpi_tile(root, sheet: str, caption: str, *, value_size: str = "22",
             caption_size: str = "9", value_color: str = "#1f1f1f",
             caption_color: str = "#757575", bold: bool = True,
             caption_below: bool = True) -> dict:
    """KPI tile: a BIG number and a small caption in one mark label."""
    ws = _sheet(root, sheet)
    if ws is None:
        raise ValueError(f"sheet {sheet!r} is not in the workbook")
    ds = _ds_name(ws)
    made = 0
    for pane in ws.iter("pane"):
        enc = pane.find("encodings")
        ref = enc.find("text") if enc is not None else None
        if ref is None or not ref.get("column"):
            continue
        col = ref.get("column")
        if not col.startswith("["):
            col = f"[{ds}].{col}"
        for old in pane.findall("customized-label"):
            pane.remove(old)
        lab = etree.Element("customized-label")
        ft = etree.SubElement(lab, "formatted-text")

        def _cap():
            r = etree.SubElement(ft, "run")
            r.set("fontcolor", caption_color)
            r.set("fontsize", str(caption_size))
            r.text = caption

        def _val():
            r = etree.SubElement(ft, "run")
            if bold:
                r.set("bold", "true")
            r.set("fontcolor", value_color)
            r.set("fontsize", str(value_size))
            r.text = etree.CDATA(f"<{col}>")

        def _br():
            etree.SubElement(ft, "run").text = _LB

        if not caption:
            _val()
        elif caption_below:
            _val(); _br(); _cap()
        else:
            _cap(); _br(); _val()

        anchor = pane.find("customized-tooltip")
        if anchor is None:
            anchor = enc
        anchor.addnext(lab)
        made += 1
    return {"tile_count": made, "label": caption}


_CARD_STYLE = (
    ("cell",      (("text-align", None), ("vertical-align", "top"),
                   ("border-style", "none"), ("border-width", "0"))),
    ("label",     (("text-align", None),)),
    ("header",    (("font-size", "10"), ("font-weight", "bold"), ("color", "#4a6fa5"),
                   ("text-align", None), ("border-style", "none"), ("border-width", "0"))),
    ("pane",      (("background-color", "#ffffff"), ("border-color", "#e1e6ea"),
                   ("border-style", "solid"), ("border-width", "1"))),
    ("table",     (("background-color", "#00000000"),)),
    ("gridline",  (("line-visibility", "off"),)),
)


def text_card(root, sheet: str, column: str, lines: list, *,
              align: str = "left", divider: str = "#d4d4d4") -> dict:
    """Card sheet: a dimension on columns, metrics as lines of one label."""
    ws = _sheet(root, sheet)
    if ws is None:
        raise ValueError(f"sheet {sheet!r} is not in the workbook")
    if not lines:
        raise ValueError("at least one card line is required")
    ds = _ds_name(ws)
    table = ws.find("table")

    def _bare(name: str) -> str:
        return name[1:-1] if name.startswith("[") and name.endswith("]") else name

    col_ref, _ = _instance_ref(root, ws, _bare(column), "None")
    refs = [_instance_ref(root, ws, _bare(ln["field"]), ln.get("derivation", "User"))[0]
            for ln in lines]

    rows, cols = table.find("rows"), table.find("cols")
    if rows is None:
        rows = etree.SubElement(table, "rows")
    if cols is None:
        cols = etree.SubElement(table, "cols")
    rows.text = None
    cols.text = col_ref

    panes = table.find("panes")
    if panes is None:
        panes = etree.SubElement(table, "panes")
    for old in panes.findall("pane"):
        panes.remove(old)
    pane = etree.SubElement(panes, "pane")
    pane.set("selection-relaxation-option", "selection-relaxation-disallow")
    etree.SubElement(etree.SubElement(pane, "view"), "breakdown").set("value", "auto")
    etree.SubElement(pane, "mark").set("class", "Text")
    enc = etree.SubElement(pane, "encodings")
    for ref in refs:
        etree.SubElement(enc, "text").set("column", ref)

    label = etree.SubElement(pane, "customized-label")
    ft = etree.SubElement(label, "formatted-text")
    for i, (ln, ref) in enumerate(zip(lines, refs)):
        def _run(text):
            r = etree.SubElement(ft, "run")
            if ln.get("bold"):
                r.set("bold", "true")
            if ln.get("color"):
                r.set("fontcolor", ln["color"])
            if ln.get("size"):
                r.set("fontsize", str(ln["size"]))
            r.text = text
        if ln.get("caption"):
            _run(ln["caption"])
        nl = "" if i == len(lines) - 1 else "\n"
        if ln.get("suffix"):
            _run(f"<{ref}>")
            _run(str(ln["suffix"]) + nl)
        else:
            _run(f"<{ref}>" + nl)

    pst = etree.SubElement(pane, "style")
    mk = etree.SubElement(pst, "style-rule")
    mk.set("element", "mark")
    for attr, val in (("mark-labels-show", "true"), ("mark-labels-cull", "true")):
        f = etree.SubElement(mk, "format")
        f.set("attr", attr)
        f.set("value", val)

    for old in table.findall("style"):
        table.remove(old)
    st = etree.Element("style")
    for element, fmts in _CARD_STYLE:
        r = etree.SubElement(st, "style-rule")
        r.set("element", element)
        for attr, val in fmts:
            f = etree.SubElement(r, "format")
            f.set("attr", attr)
            f.set("value", align if val is None else val)
    r = etree.SubElement(st, "style-rule")
    r.set("element", "table-div")
    f = etree.SubElement(r, "format")
    f.set("attr", "line-visibility")
    f.set("scope", "rows")
    f.set("value", "off")
    for attr, val in (("line-visibility", "on" if divider else "off"),
                      ("stroke-color", divider or "#d4d4d4"),
                      ("stroke-size", "1"), ("line-pattern-only", "solid")):
        f = etree.SubElement(r, "format")
        f.set("attr", attr)
        f.set("scope", "cols")
        f.set("value", val)
    r = etree.SubElement(st, "style-rule")
    r.set("element", "worksheet")
    for scope in ("cols", "rows"):
        f = etree.SubElement(r, "format")
        f.set("attr", "display-field-labels")
        f.set("scope", scope)
        f.set("value", "false")
    view = table.find("view")
    table.insert(list(table).index(view) + 1 if view is not None else 0, st)

    return {"sheet": sheet, "dimension": col_ref, "line_count": len(lines),
            "text_measure_count": len(refs)}


def set_mark_color(root, sheet: str, color: str) -> int:
    """Solid mark color of a sheet (`mark-color`): color encodes the BLOCK, not the rank."""
    ws = _sheet(root, sheet)
    if ws is None:
        raise ValueError(f"sheet {sheet!r} is not in the workbook")
    done = 0
    for pane in ws.iter("pane"):
        st = pane.find("style")
        if st is None:
            st = etree.SubElement(pane, "style")
        rule = next((r for r in st.findall("style-rule") if r.get("element") == "mark"), None)
        if rule is None:
            rule = etree.SubElement(st, "style-rule")
            rule.set("element", "mark")
        f = next((x for x in rule if x.get("attr") == "mark-color"), None)
        if f is None:
            f = etree.SubElement(rule, "format")
            f.set("attr", "mark-color")
        f.set("value", color)
        done += 1
    return done


def show_zone_title(root, dashboard: str, sheets: list, show: bool = False) -> int:
    """Whether to show the sheet title in a dashboard zone (`show-title`)."""
    want = set(sheets)
    done = 0
    for dash in root.iter("dashboard"):
        if dash.get("name") != dashboard:
            continue
        for z in dash.iter("zone"):
            if z.get("name") in want:
                z.set("show-title", "true" if show else "false")
                done += 1
    return done


_DERIV_PREFIX = {"User": "usr", "Sum": "sum", "CountD": "ctd", "Count": "cnt",
                 "Avg": "avg", "Min": "min", "Max": "max", "None": "none",
                 "Attribute": "attr", "Median": "med", "InOut": "io",
                 "Year": "yr", "Quarter": "qr", "Month": "mn", "Day": "dy",
                 "Hour": "hr", "MY": "my", "MDY": "mdy", "Week": "wk", "Weekday": "wd",
                 "Quarter-Trunc": "tqr",
                 "Year-Trunc": "tyr", "Month-Trunc": "tmn",
                 "Week-Trunc": "twk", "Day-Trunc": "tdy"}


def _instance_ref(root, ws, column: str, derivation: str, kind: str = "",
                  role: str = ""):
    """Declare a field and its instance in a sheet, return `([ds].[inst], inst)`."""
    ds = _ds_name(ws)
    src = None
    for dsn in root.iter("datasource"):
        for c in dsn.findall("column"):
            nm = (c.get("name") or "").strip("[]")
            if role and c.get("role") and c.get("role") != role:
                continue
            if nm == column or (c.get("caption") or "") == column:
                if src is None or c.find("calculation") is not None:
                    src, column = c, nm
                if c.find("calculation") is not None:
                    break
        if src is not None and src.find("calculation") is not None:
            break
    if src is None:
        for c in root.iter("column"):
            if c.getparent() is not None and c.getparent().tag == "columns" \
                    and (c.get("name") or "") == column:
                dt = c.get("datatype") or "string"
                src = etree.Element("column")
                src.set("datatype", dt)
                src.set("name", f"[{column}]")
                src.set("role", "measure" if dt in ("real", "integer") else "dimension")
                src.set("type", "quantitative" if dt in ("real", "integer")
                        else ("ordinal" if dt in ("date", "datetime") else "nominal"))
                break
    kind = kind or {"nominal": "nk", "ordinal": "ok"}.get(
        (src.get("type") or "") if src is not None else "", "qk")
    inst = f"[{_DERIV_PREFIX.get(derivation, derivation.lower())}:{column}:{kind}]"
    dep = ws.find(f".//datasource-dependencies[@datasource='{ds}']")
    if dep is None:
        raise ValueError("the sheet has no datasource-dependencies")
    if f"[{column}]" not in {c.get("name") for c in dep.findall("column")}:
        if src is None:
            raise ValueError(f"no declaration of '{column}' in the workbook")
        dep.insert(0, copy.deepcopy(src))
    if not any(ci.get("name") == inst for ci in dep.findall("column-instance")):
        ci = etree.SubElement(dep, "column-instance")
        ci.set("column", f"[{column}]")
        ci.set("derivation", derivation)
        ci.set("name", inst)
        ci.set("pivot", "key")
        ci.set("type", {"nk": "nominal", "ok": "ordinal", "qk": "quantitative"}.get(
            kind, (src.get("type") if src is not None else None) or "quantitative"))
    return f"[{ds}].{inst}", inst


def add_measure(root, sheet: str, column: str, derivation: str = "Sum") -> dict:
    """Add a measure to the COLUMNS of a `Measure Names` table."""
    ws = _sheet(root, sheet)
    if ws is None:
        raise ValueError(f"sheet {sheet!r} is not in the workbook")
    ds = _ds_name(ws)
    ref, _ = _instance_ref(root, ws, column, derivation)
    for filt in ws.iter("filter"):
        if filt.get("column") != f"[{ds}].[:Measure Names]":
            continue
        union = filt.find("groupfilter")
        if union is None:
            continue
        member = f'"{ref}"'
        if any(g.get("member") == member for g in union.findall("groupfilter")):
            return {"added": 0, "why": "the measure is already in the columns", "measure": ref}
        g = etree.SubElement(union, "groupfilter")
        g.set("function", "member")
        g.set("level", "[:Measure Names]")
        g.set("member", member)
        return {"added": 1, "measure": ref}
    raise ValueError("the sheet has no [:Measure Names] filter; it is not a measure table")


def order_measures(root, sheet: str, columns: list, derivations: list = None) -> dict:
    """Column order of a measure table (`<manual-sort>` on `[:Measure Names]`)."""
    ws = _sheet(root, sheet)
    if ws is None:
        raise ValueError(f"sheet {sheet!r} is not in the workbook")
    ds = _ds_name(ws)
    derivations = derivations or ["Sum"] * len(columns)
    refs = [_instance_ref(root, ws, c, d)[0] for c, d in zip(columns, derivations)]

    for datasource in root.findall("./datasources/datasource"):
        if datasource.get("name") != ds:
            continue
        for old in datasource.findall("default-sorts"):
            datasource.remove(old)
        srt = etree.Element("default-sorts")
        ms = etree.SubElement(srt, "manual-sort")
        ms.set("column", "[:Measure Names]")
        ms.set("direction", "ASC")
        dic = etree.SubElement(ms, "dictionary")
        for r in refs:
            etree.SubElement(dic, "bucket").text = f'"{r}"'
        insert_in_order(datasource, srt, _DS_ORDER)
        ensure_format_flags(root, MANUAL_SORT_FLAGS)
    return {"ordered_column_count": len(refs), "order": refs}
    raise ValueError(f"datasource {ds} is not in the workbook")


def order_members(root, sheet: str, column: str, values: list,
                  derivation: str = "None") -> dict:
    """Order of a DIMENSION's values on a sheet (`<view><manual-sort>`), as the author set it."""
    ws = _sheet(root, sheet)
    if ws is None:
        raise ValueError(f"sheet {sheet!r} is not in the workbook")
    view = ws.find("table/view")
    ref, _ = _instance_ref(root, ws, column, derivation, role="dimension")
    for old in view.findall("manual-sort"):
        if old.get("column") == ref:
            view.remove(old)
    ms = etree.Element("manual-sort")
    ms.set("column", ref)
    ms.set("direction", "ASC")
    dic = etree.SubElement(ms, "dictionary")
    for v in dict.fromkeys(str(x) for x in values):
        etree.SubElement(dic, "bucket").text = f'"{v}"'
    insert_in_order(view, ms, _VIEW_ORDER)
    ensure_format_flags(root, MANUAL_SORT_FLAGS)
    return {"sheet": sheet, "field": ref, "order": list(dict.fromkeys(str(x) for x in values))}


_USER_NS = "http://www.tableausoftware.com/xml/user"


def _u(attr: str) -> str:
    return "{%s}%s" % (_USER_NS, attr)


def _quote_member(value: str) -> str:
    """Wrap a string filter value in quotes as Tableau expects."""
    v = str(value or "")
    if not v or v.startswith('"'):
        return v
    if v.lower() in ("true", "false", "%null%", "%all%"):
        return v
    try:
        float(v.replace(",", "."))
        return v
    except ValueError:
        return f'"{v}"'


def apply_filter(root, sheets: list, column: str, *, derivation: str = "None",
                 member: str = "", context: bool = False, kind: str = "") -> dict:
    """The same filter ON ALL listed sheets; `kind` (nk, ok, qk) keeps the instance the sheet has."""
    member = _quote_member(member)
    kind = kind or {"None": "nk", "Sum": "qk", "CountD": "qk"}.get(derivation, "nk")

    put = []
    for name in sheets:
        ws = _sheet(root, name)
        view = ws.find(".//view") if ws is not None else None
        if view is None:
            continue
        try:
            ref, inst = _instance_ref(root, ws, column, derivation, kind=kind)
        except ValueError:
            continue
        column = inst[1:-1].split(":")[1]
        if any(f.get("column") == ref for f in view.findall("filter")):
            continue

        filt = etree.Element("filter")
        filt.set("class", "categorical")
        filt.set("column", ref)
        if context:
            filt.set("context", "true")
        g = etree.SubElement(filt, "groupfilter")
        if member:
            g.set("function", "member")
            g.set("level", inst)
            g.set("member", member)
            g.set(_u("ui-domain"), "database")
            g.set(_u("ui-enumeration"), "inclusive")
        else:
            g.set("function", "level-members")
            g.set("level", inst)
            g.set(_u("ui-enumeration"), "all")
        g.set(_u("ui-marker"), "enumerate")

        insert_in_order(view, filt, _VIEW_ORDER)
        sl = view.find("slices")
        if sl is None:
            sl = etree.Element("slices")
            insert_in_order(view, sl, _VIEW_ORDER)
        if not any((c.text or "") == ref for c in sl.findall("column")):
            etree.SubElement(sl, "column").text = ref
        put.append(name)
    return {"sheet_count": len(put), "field": column, "sheets": put}


def add_control_column(dash, refs: list, *, width: int = 17800,
                       item_h: int = 5600) -> dict:
    """A control column on the RIGHT of a dashboard with a vertical flow."""
    zones = dash.find("zones")
    if zones is None:
        return {"column": 0, "why": "the dashboard has no zones"}
    body = zones.find("zone")
    if body is None or (body.get("type-v2") or "") != "layout-flow":
        return {"column": 0, "why": "the dashboard root is not a layout-flow"}
    if any((z.get("param") or "") in refs for z in zones.iter("zone")):
        return {"column": 0, "why": "controls are already in place"}

    nid = max((int(z.get("id")) for z in dash.iter("zone")
               if (z.get("id") or "").isdigit()), default=0)
    W, H = int(body.get("w")), int(body.get("h"))
    x0, y0 = int(body.get("x")), int(body.get("y"))
    left = W - width

    nid += 1
    row = etree.Element("zone")
    for k, v in (("id", nid), ("x", x0), ("y", y0), ("w", W), ("h", H)):
        row.set(k, str(v))
    row.set("type-v2", "layout-flow")
    row.set("param", "horz")

    body.addprevious(row)
    row.append(body)
    body.set("w", str(left))

    nid += 1
    col = etree.SubElement(row, "zone")
    for k, v in (("id", nid), ("x", x0 + left), ("y", y0), ("w", width), ("h", H)):
        col.set(k, str(v))
    col.set("type-v2", "layout-flow")
    col.set("param", "vert")

    for i, ref in enumerate(refs):
        nid += 1
        z = etree.SubElement(col, "zone")
        z.set("id", str(nid))
        sheet, _, field = ref.partition("|")
        if field:
            z.set("name", sheet)
            z.set("param", field)
            z.set("type-v2", "filter")
            z.set("mode", "checkdropdown")
        else:
            z.set("param", ref)
            z.set("type-v2", "paramctrl")
            z.set("mode", "compact")
        z.set("show-title", "true")
        for k, v in (("x", x0 + left), ("y", y0 + i * item_h),
                     ("w", width), ("h", item_h)):
            z.set(k, str(v))
    return {"column": 1, "control_count": len(refs), "width": width}


_ZONE_ORDER = ["formatted-text", "layout-cache", "zone", "flipboard-doc",
               "button", "add-in", "zone-style"]
_WINDOW_ORDER = ["cards", "viewpoint", "highlight", "simple-id"]

SHEET_FIT = {"stretch": "entire-view", "by width": "fit-width",
             "by height": "fit-height", "standard": ""}
_FIT_ALIASES = {"whole": "entire-view",
                "entire": "entire-view", "entire view": "entire-view", "entire-view": "entire-view",
                "fit width": "fit-width", "width": "fit-width", "fit-width": "fit-width",
                "fit height": "fit-height", "height": "fit-height", "fit-height": "fit-height",
                "normal": ""}


def fit_value(mode: str) -> str:
    """Fit mode to Tableau's `zoom type` value."""
    key = (mode or "").strip().lower()
    if key in SHEET_FIT:
        return SHEET_FIT[key]
    if key in _FIT_ALIASES:
        return _FIT_ALIASES[key]
    raise ValueError(f"unknown Fit mode {mode!r}: stretch/whole (Entire View), "
                     f"by width (Fit Width), by height (Fit Height), standard (Standard)")


def set_sheet_fit(root, sheets: list, mode: str = "stretch") -> int:
    """How a sheet fills its allotted space (`Fit` in Tableau)."""
    want = set(sheets)
    val = fit_value(mode)
    done = 0
    for win in root.iter("window"):
        if win.get("class") != "worksheet" or win.get("name") not in want:
            continue
        for old_vp in win.findall("viewpoint"):
            win.remove(old_vp)
        if val:
            vp = etree.Element("viewpoint")
            z = etree.SubElement(vp, "zoom")
            z.set("type", val)
            insert_in_order(win, vp, _WINDOW_ORDER)
        done += 1
    return done


MERGEABLE_STYLE = ("table", "gridline", "header", "pane", "cell", "label", "axis")


def dedupe_style_rules(root, sheets: list, elements: tuple = MERGEABLE_STYLE) -> dict:
    """Collapse repeated `<style-rule element=...>` of a sheet into one rule."""
    want = set(sheets)
    done = {}
    for ws in root.iter("worksheet"):
        if ws.get("name") not in want:
            continue
        st = ws.find("table/style")
        if st is None:
            continue
        merged = 0
        for el in elements:
            rules = [r for r in st.findall("style-rule")
                     if r.get("element") == el and r.get("scope") is None]
            if len(rules) < 2:
                continue
            keep = rules[0]
            have = {f.get("attr"): f for f in keep.findall("format")}
            for extra in rules[1:]:
                for f in extra.findall("format"):
                    tgt = have.get(f.get("attr"))
                    if tgt is None:
                        have[f.get("attr")] = etree.SubElement(keep, "format")
                        have[f.get("attr")].set("attr", f.get("attr"))
                        tgt = have[f.get("attr")]
                    tgt.set("value", f.get("value"))
                st.remove(extra)
                merged += 1
        if merged:
            done[ws.get("name")] = merged
    return done


DIVERGING_PALETTES = frozenset((
    "red_green_diverging_10_0", "orange_blue_diverging_10_0",
    "green_blue_diverging_10_0", "red_blue_diverging_10_0", "red_green",
))

PALETTE_STOPS = 24


def palette_stops(spec, stops: int = PALETTE_STOPS) -> list:
    """Palette stops from a short color description."""
    if isinstance(spec, str):
        spec = [spec]
    spec = list(spec)
    if len(spec) == 1 or len(set(spec)) == 1:
        return [spec[0]] * stops
    if len(spec) == 2:
        half = stops // 2
        return [spec[0]] * half + [spec[1]] * (stops - half)
    return interpolate_colors(spec, stops)


def interpolate_colors(stops: list, count: int) -> list:
    """Smooth gradient through the listed colors: `count` shades, interpolated in RGB."""
    def rgb(c):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

    pts = [rgb(c) for c in stops]
    out = []
    for i in range(count):
        t = i / (count - 1) * (len(pts) - 1)
        lo_i = min(int(t), len(pts) - 2)
        f = t - lo_i
        a, b = pts[lo_i], pts[lo_i + 1]
        out.append("#%02x%02x%02x" % tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3)))
    return out


def set_color_range(root, sheets: list, full_range: bool = True,
                    reversed_scale: bool = None) -> dict:
    """`Use Full Color Range` and `Reversed` on a sheet's colour encodings."""
    done, touched = {}, 0
    want = set(sheets)
    for ws in root.iter("worksheet"):
        if ws.get("name") not in want:
            continue
        n = 0
        for sr in ws.findall("table/style/style-rule"):
            if sr.get("element") != "mark":
                continue
            for e in sr.findall("encoding"):
                if e.get("attr") != "color":
                    continue
                e.set("symmetric", "false" if full_range else "true")
                if reversed_scale is not None:
                    if reversed_scale:
                        e.set("reverse", "true")
                    else:
                        e.attrib.pop("reverse", None)
                n += 1
        if n:
            done[ws.get("name")] = n
            touched += n
    return _say_untouched(root, want, done, {"sheets": len(done), "encodings": touched,
                                       "full_color_range": full_range,
                                       "reversed": reversed_scale})


def _say_untouched(root, want: set, done: dict, out: dict) -> dict:
    """Name the sheets where there was nothing to edit, instead of a quiet "sheets: 0"."""
    existing = {w.get("name") for w in root.iter("worksheet")}
    missing = sorted(want - existing)
    if missing:
        out["missing_sheets"] = missing
    skipped = sorted((want & existing) - set(done))
    if skipped:
        out["no_color_encoding"] = skipped
        out["why"] = ("the sheet has no color encoding of its own (default palette); "
                      "set a palette first: edit_copy_color_encoding / edit_sign_color")
    return out


def set_color_steps(root, sheets: list, steps: int = 2) -> dict:
    """Stepped color (`Stepped Color`): `num-steps` on a sheet's color encodings."""
    done = {}
    want = set(sheets)
    for ws in root.iter("worksheet"):
        if ws.get("name") not in want:
            continue
        n = 0
        for sr in ws.findall("table/style/style-rule"):
            if sr.get("element") != "mark":
                continue
            for e in sr.findall("encoding"):
                if e.get("attr") != "color":
                    continue
                if steps and steps > 1:
                    e.set("num-steps", str(steps))
                else:
                    e.attrib.pop("num-steps", None)
                n += 1
        if n:
            done[ws.get("name")] = n
    return _say_untouched(root, want, done, {"sheet_count": len(done), "steps": steps,
                                       "encodings_per_sheet": sorted(set(done.values()))})


def copy_color_encoding(root, donor: str, sheets: list) -> dict:
    """Copy coloring FROM A DONOR SHEET to other sheets, as is."""
    src = _sheet(root, donor)
    if src is None:
        return {"moved": 0, "why": f"no donor sheet '{donor}'"}
    src_ds = _ds_name(src)
    src_col = src.find("table/panes/pane/encodings/color")
    src_rule = next((r for r in src.findall("table/style/style-rule")
                     if r.get("element") == "mark" and r.findall("encoding")), None)
    if src_col is None or src_rule is None:
        return {"moved": 0, "why": f"'{donor}' has no coloring, nothing to copy"}

    def _retarget(node, ds):
        for el in node.iter():
            for key in ("column", "field"):
                v = el.get(key)
                if v and src_ds and src_ds in v:
                    el.set(key, v.replace(src_ds, ds))

    done = {}
    for ws in root.iter("worksheet"):
        name = ws.get("name")
        if name not in set(sheets) or name == donor:
            continue
        ds = _ds_name(ws)
        enc = ws.find("table/panes/pane/encodings")
        style = ws.find("table/style")
        if enc is None or style is None or not ds:
            continue

        col = enc.find("color")
        if col is None:
            col = etree.Element("color")
            enc.insert(0, col)
        for k, v in src_col.attrib.items():
            col.set(k, v)
        _retarget(col, ds)

        rule = None
        for r in style.findall("style-rule"):
            if r.get("element") != "mark":
                continue
            if r.findall("encoding"):
                for old in r.findall("encoding"):
                    if old.get("attr") == "color":
                        r.remove(old)
                rule = r
        if rule is None:
            rule = etree.SubElement(style, "style-rule")
            rule.set("element", "mark")
        n = 0
        for e in src_rule.findall("encoding"):
            if e.get("attr") != "color":
                continue
            copy_e = copy.deepcopy(e)
            _retarget(copy_e, ds)
            rule.append(copy_e)
            n += 1
        done[name] = n
    return {"moved": len(done), "donor": donor, "encodings_per_sheet": sorted(set(done.values()))}


def sign_color(root, sheets: list, measures: dict) -> dict:
    """Text color in a measure table BY THE SIGN of the value, with its own scale per measure."""
    bad = {k: v for k, v in measures.items()
           if not isinstance(v, str) or not v.strip() or v.strip().startswith("#")}
    if bad:
        raise ValueError(f"sign_color expects a palette NAME per measure, not a color: {bad}. "
                         "Example: red_green_diverging_10_0 (by sign), Just black (constant)")
    done = {}
    want = set(sheets)
    for ws in root.iter("worksheet"):
        if ws.get("name") not in want:
            continue
        ds = _ds_name(ws)
        if not ds:
            continue
        enc = ws.find("table/panes/pane/encodings")
        if enc is None:
            continue
        col = enc.find("color")
        if col is None:
            col = etree.Element("color")
            enc.insert(0, col)
        col.set("column", f"[{ds}].[Multiple Values]")
        col.set("separate-domains", "true")

        style = ws.find("table/style")
        if style is None:
            continue
        rule = None
        for sr in style.findall("style-rule"):
            if sr.get("element") != "mark":
                continue
            for old in sr.findall("encoding"):
                if old.get("attr") == "color":
                    sr.remove(old)
                    rule = sr
        if rule is None:
            rule = etree.SubElement(style, "style-rule")
            rule.set("element", "mark")

        base = etree.SubElement(rule, "encoding")
        base.set("attr", "color")
        base.set("field", f"[{ds}].[Multiple Values]")
        base.set("symmetric", "false")
        base.set("type", "custom-interpolated")
        bpal = etree.SubElement(base, "color-palette")
        bpal.set("custom", "true"); bpal.set("name", ""); bpal.set("type", "ordered-diverging")
        for tone in ("#d9d9d9", "#d9d9d9", "#d9d9d9"):
            etree.SubElement(bpal, "color").text = tone

        made = 0
        for name, spec in measures.items():
            e = etree.SubElement(rule, "encoding")
            e.set("attr", "color")
            e.set("field", f"[{ds}].[{name}]")
            e.set("type", "interpolated")
            e.set("palette", spec.strip())
            if spec.strip() in DIVERGING_PALETTES:
                e.set("center", "0")
            made += 1
        done[ws.get("name")] = made
    return done


def parse_sign_color_spec(text: str) -> dict:
    """`column:palette, ...` to `{column: palette}`: the input of `edit_sign_color`."""
    spec = {}
    for item in (text or "").split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, palette = item.rpartition(":")
        if palette.strip().startswith("#"):
            raise ValueError(f"'{item}': a color instead of a palette name; at measure level "
                             "only a name works (red_green_diverging_10_0, Just black)")
        if not sep or not name.strip() or not palette.strip():
            raise ValueError(f"'{item}': expected `column:palette`, "
                             "for example sum:profit:qk:red_green_diverging_10_0")
        spec[name.strip()] = palette.strip()
    return spec


def transpose_flow(root, dashboard: str, zone_id, gap_item: str = "") -> dict:
    """Transpose a container's grid: N columns of M items becomes M rows of N items."""
    dash = next((d for d in root.iter("dashboard") if d.get("name") == dashboard), None)
    if dash is None:
        raise ValueError(f"dashboard {dashboard!r} is not in the workbook")
    outer = next((z for z in dash.iter("zone") if z.get("id") == str(zone_id)), None)
    if outer is None:
        raise ValueError(f"zone {zone_id} is not on dashboard {dashboard!r}")
    if outer.get("type-v2") != "layout-flow":
        return {"expanded": 0, "why": "the zone is not a layout-flow"}
    cols = outer.findall("zone")
    if not cols or any(c.get("type-v2") != "layout-flow" for c in cols):
        return {"expanded": 0, "why": "not all children are containers"}
    sizes = {len(c.findall("zone")) for c in cols}
    if len(sizes) != 1:
        return {"expanded": 0, "why": f"columns have different item counts: {sorted(sizes)}"}
    depth = sizes.pop()
    if depth < 2:
        return {"expanded": 0, "why": "a column has fewer than two items; nothing to transpose"}

    inner_param = cols[0].get("param")
    outer_param = outer.get("param")
    used = {int(z.get("id")) for z in dash.iter("zone") if z.get("id")}
    next_id = max(used) + 1

    grid = [col.findall("zone") for col in cols]
    rows = []
    for k in range(depth):
        row = etree.Element("zone")
        row.set("id", str(next_id)); next_id += 1
        row.set("type-v2", "layout-flow")
        row.set("param", outer_param)
        if grid[0][k].get("fixed-size"):
            row.set("fixed-size", grid[0][k].get("fixed-size"))
            row.set("is-fixed", "true")
        for col, items in zip(cols, grid):
            item = items[k]
            col.remove(item)
            item.attrib.pop("fixed-size", None)
            item.attrib.pop("is-fixed", None)
            row.append(item)
        rows.append(row)

    dropped = []
    for col in cols:
        st = col.find("zone-style")
        fmt = {f.get("attr"): f.get("value") for f in st.findall("format")} if st is not None else {}
        dropped.append({"id": col.get("id"),
                        "background": fmt.get("background-color", "-")})
        outer.remove(col)
    outer.set("param", inner_param)
    for row in rows:
        insert_in_order(outer, row, _ZONE_ORDER)
    return {"expanded": depth, "rows": [r.get("id") for r in rows],
            "columns_removed": dropped}


def set_zone_fit(root, dashboard: str, sheets: list, mode: str = "stretch") -> int:
    """How a sheet fills its ZONE on a DASHBOARD."""
    want = set(sheets)
    val = fit_value(mode)
    done = 0
    for win in root.iter("window"):
        if win.get("class") != "dashboard" or win.get("name") != dashboard:
            continue
        for vp in win.iter("viewpoint"):
            if vp.get("name") not in want:
                continue
            for old in vp.findall("zoom"):
                vp.remove(old)
            if val:
                etree.SubElement(vp, "zoom").set("type", val)
            done += 1
    return done


KPI_CARD = {"border-color": "#000000", "border-style": "none", "border-width": "0",
            "margin": "4", "padding": "12", "background-color": "#f6f6f4"}


def set_zone_style(root, dashboard: str, sheets: list, fmt: dict,
                   controls: bool = False) -> int:
    """Zone styling on a dashboard: background, border, padding (`<zone-style>`)."""
    want = set(sheets)
    done = 0
    for dash in root.iter("dashboard"):
        if dash.get("name") != dashboard:
            continue
        for z in dash.iter("zone"):
            if z.get("name") not in want:
                continue
            if not controls and (z.get("type-v2") or "NONE") != "NONE":
                continue
            st = z.find("zone-style")
            if st is None:
                st = etree.Element("zone-style")
                insert_in_order(z, st, _ZONE_ORDER)
            have = {f.get("attr"): f for f in st.findall("format")}
            for attr, val in fmt.items():
                f = have.get(attr)
                if f is None:
                    f = etree.SubElement(st, "format")
                    f.set("attr", attr)
                f.set("value", val)
            done += 1
    return done


ROW_HEADER_FLOOR_PX = 68


def fit_column_width(root, sheet: str, field_caption: str, labels: list,
                     max_px: int = 400, element: str = "header") -> dict:
    """Pick a column width so that labels STAY DISTINCT.

    The narrowest such width, but never below the full labels or `ROW_HEADER_FLOOR_PX`
    (what Tableau keeps when it shrinks row headers), whichever is less."""
    from . import dryrun as DR
    from . import layoutmodel as LM

    labels = [str(x) for x in labels if str(x)]
    if not labels:
        return {"verdict": "no labels given; nothing to fit against", "width": 0}

    ws = next((w for w in root.iter("worksheet") if w.get("name") == sheet), None)
    if ws is None:
        return {"verdict": f"no sheet '{sheet}' in the workbook", "width": 0}
    pt, family, _ = LM.sheet_font(ws)

    def clashes_at(px: float) -> list:
        return DR.indistinct_after_truncation(
            labels, max(1.0, px - DR.CELL_PADDING_PX), pt, family)

    full = int(math.ceil(max(LM.text_width(s, pt, family) for s in labels)
                         + DR.CELL_PADDING_PX))
    if not clashes_at(1.0):
        return {"verdict": "labels are distinct at any width; no edit needed",
                "width": 0}
    if full > max_px:
        return {"verdict": f"{full} px needed, {max_px} allowed; labels become "
                           f"distinct only beyond the limit. Raise max_px or "
                           f"move the differing part to the start of the label",
                "width": 0, "needed": full, "limit": max_px}

    lo, hi = 0, full
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if clashes_at(float(mid)):
            lo = mid
        else:
            hi = mid
    px = max(hi, min(full, ROW_HEADER_FLOOR_PX))
    n = set_column_width(root, sheet, field_caption, px, element)
    if not n:
        return {"verdict": f"field '{field_caption}' not found on the sheet's shelves; "
                           f"width not applied", "width": px}
    return {"verdict": f"width {px} px; labels are distinct ({len(clashes_at(px - 1))} "
                       f"disputed pairs would remain at {px - 1} px)",
            "width": px, "refs": n}


def set_grand_total(root, sheet: str, rows: bool = True, cols: bool = False,
                    on_top: bool = True, on_left: bool = False) -> dict:
    """A TOTAL row/column in a table (grand total)."""
    done = []
    for ws in root.iter("worksheet"):
        if ws.get("name") != sheet:
            continue
        for tag, want, side_attr, side in (("rows", rows, "onTop", on_top),
                                           ("cols", cols, "onLeft", on_left)):
            if not want:
                continue
            for shelf in ws.iter(tag):
                shelf.set("total", "true")
                if side:
                    shelf.set(side_attr, "true")
                else:
                    shelf.attrib.pop(side_attr, None)
                done.append(tag)
    if not done:
        return {"verdict": f"no sheet '{sheet}' in the workbook or it has no shelves",
                "shelf_count": 0}
    where = " and ".join(sorted(set(done)))
    place = (" (top)" if rows and on_top else "") + (" (left)" if cols and on_left else "")
    return {"verdict": f"total enabled on shelf {where}{place}", "shelf_count": len(done)}


def set_mark_labels(root, sheets: list, show: bool = False) -> int:
    """Whether to show mark labels (`mark-labels-show`) on these sheets."""
    want = set(sheets)
    done = 0
    for ws in root.iter("worksheet"):
        if ws.get("name") not in want:
            continue
        hit = False
        for fmt in ws.iter("format"):
            if fmt.get("attr") == "mark-labels-show":
                fmt.set("value", "true" if show else "false")
                hit = True
        if hit:
            done += 1
    return done


def line_end_labels(root, sheets: list) -> int:
    """Labels on a line's end only (`mark-labels-mode='line-ends'`, first point off), as in the corpus (54 uses,..."""
    want = set(sheets)
    done = 0
    for ws in root.iter("worksheet"):
        if ws.get("name") not in want:
            continue
        hit = False
        for show in [f for f in ws.iter("format") if f.get("attr") == "mark-labels-show"]:
            rule = show.getparent()
            show.set("value", "true")
            have = {f.get("attr"): f for f in rule.findall("format")}
            for attr, val in (("mark-labels-mode", "line-ends"),
                              ("mark-labels-line-first", "false")):
                if attr in have:
                    have[attr].set("value", val)
                else:
                    el = etree.Element("format")
                    el.set("attr", attr)
                    el.set("value", val)
                    show.addprevious(el)
            hit = True
        done += hit
    return done


def _style_rule(tbl, element: str):
    style = tbl.find("style")
    if style is None:
        style = etree.Element("style")
        panes = tbl.find("panes")
        (panes.addprevious(style) if panes is not None else tbl.append(style))
    rule = next((r for r in style.findall("style-rule") if r.get("element") == element), None)
    if rule is None:
        rule = etree.Element("style-rule")
        rule.set("element", element)
        later = next((r for r in style.findall("style-rule")
                      if element == "label" and r.get("element") not in _LABEL_AFTER), None)
        (later.addprevious(rule) if later is not None else style.append(rule))
    return rule


def hide_axes(root, sheets: list) -> int:
    """Sparkline look: measure axes off (`axis` display false) and discrete headers off."""
    want = set(sheets)
    done = 0
    for ws in root.iter("worksheet"):
        tbl = ws.find(".//table")
        if ws.get("name") not in want or tbl is None:
            continue
        hit = False
        for tag in ("rows", "cols"):
            for shelf in ws.iter(tag):
                for ref in shelf_tokens(shelf.text or ""):
                    element = "axis" if ref.endswith(":qk]") else "label"
                    rule = _style_rule(tbl, element)
                    if any(f.get("attr") == "display" and f.get("field") == ref
                           for f in rule.findall("format")):
                        continue
                    fmt = etree.SubElement(rule, "format")
                    fmt.set("attr", "display")
                    if element == "axis":
                        fmt.set("class", "0")
                    fmt.set("field", ref)
                    if element == "axis":
                        fmt.set("scope", tag)
                    fmt.set("value", "false")
                    hit = True
        done += hit
    return done


def hide_axis_titles(root, sheets: list) -> int:
    """Remove axis titles (`<style-rule element="axis"><format attr="title" value=""/>`)."""
    want = set(sheets)
    done = 0
    for ws in root.iter("worksheet"):
        if ws.get("name") not in want:
            continue
        style = ws.find("table/style")
        if style is None:
            style = ws.find(".//style")
        if style is None:
            continue
        sr = next((x for x in style.findall("style-rule") if x.get("element") == "axis"), None)
        if sr is None:
            sr = etree.SubElement(style, "style-rule")
            sr.set("element", "axis")
        fmt = next((f for f in sr.findall("format") if f.get("attr") == "title"), None)
        if fmt is None:
            fmt = etree.SubElement(sr, "format")
            fmt.set("attr", "title")
        fmt.set("value", "")
        done += 1
    return done


def set_parameter_value(root, caption: str, value: str) -> int:
    """Set a parameter's value in ALL its declarations."""
    quoted = f'"{value}"'
    touched = 0
    for col in root.iter("column"):
        if not col.get("param-domain-type"):
            continue
        if col.get("caption") != caption and col.get("name") != f"[{caption}]":
            continue
        col.set("value", quoted if col.get("datatype") == "string" else value)
        calc = col.find("calculation")
        if calc is not None:
            calc.set("formula", quoted if col.get("datatype") == "string" else value)
        touched += 1
    return touched


def parameter_members(root, caption: str) -> list:
    """Allowed parameter values, so states need not be invented by hand."""
    for col in root.iter("column"):
        if not col.get("param-domain-type"):
            continue
        if col.get("caption") != caption and col.get("name") != f"[{caption}]":
            continue
        out = []
        for m in col.iter("member"):
            v = (m.get("value") or "").strip()
            out.append(v[1:-1] if v.startswith('"') and v.endswith('"') else v)
        if out:
            return out
    return []


def sheet_swap(root, param: str, mapping: dict, wide: list = None) -> dict:
    """Swap sheets by a parameter value."""
    if not mapping:
        return {"ok": False, "why": "nothing to swap: mapping is empty"}
    wide = set(wide or [])
    known = {ws.get("name") for ws in root.iter("worksheet")}
    missing = [s for s in mapping if s not in known]
    if missing:
        return {"ok": False, "why": f"no such sheets: {', '.join(missing)}"}

    ds = _main_datasource_name(root)
    made, filtered = [], []
    for sheet, value in mapping.items():
        calc = f"Swap {sheet}"
        _ensure_swap_calc(root, ds, calc, param, value)
        made.append(calc)
        _ensure_ds_dependency(root, sheet, ds)
        res = apply_filter(root, [sheet], calc, member='"show"')
        filtered += res.get("sheets", []) or [sheet]
        _ensure_param_dependency(root, sheet, param)

    vp = _ensure_viewpoints(root)
    for name in wide:
        _drop_fit(root, name)
    return {"ok": True, "calculations": made, "sheets_with_filter": sorted(set(filtered)),
            "viewpoints_added": vp, "without_fit": sorted(wide)}


def _main_datasource_name(root) -> str:
    for dsn in root.iter("datasource"):
        name = dsn.get("name") or ""
        if name and name != "Parameters":
            return name
    return ""


def _param_ref(root, param: str) -> str:
    """`[Parameters].[<NAME>]` from a parameter's caption or name."""
    p = param.strip()
    if p.startswith("[Parameters]."):
        p = p[len("[Parameters]."):]
    p = p.strip("[]")
    for dsn in root.iter("datasource"):
        if dsn.get("name") != "Parameters":
            continue
        for c in dsn.findall("column"):
            if c.get("name") == f"[{p}]":
                return f"[Parameters].[{p}]"
        for c in dsn.findall("column"):
            if c.get("caption") == p:
                return f"[Parameters].{c.get('name')}"
    return f"[Parameters].[{p}]"


def _ensure_swap_calc(root, ds: str, caption: str, param: str, value: str) -> None:
    formula = (f"IF {_param_ref(root, param)} = '{value}' THEN 'show' "
               f"ELSE 'hide' END")
    for dsn in root.iter("datasource"):
        if dsn.get("name") != ds:
            continue
        for col in dsn.findall("column"):
            if col.get("name") == f"[{caption}]":
                calc = col.find("calculation")
                if calc is not None:
                    calc.set("formula", formula)
                return
        col = etree.Element("column")
        col.set("caption", caption)
        col.set("datatype", "string")
        col.set("name", f"[{caption}]")
        col.set("role", "dimension")
        col.set("type", "nominal")
        calc = etree.SubElement(col, "calculation")
        calc.set("class", "tableau")
        calc.set("formula", formula)
        insert_in_order(dsn, col, _DS_ORDER)
        return


def _ensure_ds_dependency(root, sheet: str, ds: str) -> None:
    """A sheet's datasource-dependencies block."""
    for ws in root.iter("worksheet"):
        if ws.get("name") != sheet:
            continue
        view = ws.find("table/view")
        if view is None:
            return
        if view.find(f"datasource-dependencies[@datasource='{ds}']") is not None:
            return
        dep = etree.Element("datasource-dependencies")
        dep.set("datasource", ds)
        insert_in_order(view, dep, _VIEW_ORDER)
        return


def _ensure_param_dependency(root, sheet: str, param: str) -> None:
    """A copy of the parameter declaration in a sheet's dependencies: without it the formula does not resolve."""
    src = None
    for dsn in root.iter("datasource"):
        if dsn.get("name") != "Parameters":
            continue
        for col in dsn.findall("column"):
            if col.get("caption") == param or col.get("name") == f"[{param}]":
                src = col
    if src is None:
        return
    for ws in root.iter("worksheet"):
        if ws.get("name") != sheet:
            continue
        view = ws.find("table/view")
        if view is None:
            return
        for dep in view.findall("datasource-dependencies"):
            if dep.get("datasource") == "Parameters":
                if any(c.get("name") == src.get("name") for c in dep.findall("column")):
                    return
                dep.append(copy.deepcopy(src))
                return
        dep = etree.Element("datasource-dependencies")
        dep.set("datasource", "Parameters")
        dep.append(copy.deepcopy(src))
        insert_in_order(view, dep, _VIEW_ORDER)
        for dss in view.findall("datasources"):
            if not any(d.get("name") == "Parameters" for d in dss.findall("datasource")):
                d = etree.SubElement(dss, "datasource")
                d.set("name", "Parameters")
        return


def _ensure_viewpoints(root) -> int:
    """Each dashboard sheet zone needs its own viewpoint."""
    added = 0
    for dash in root.iter("dashboard"):
        names = {z.get("name") for z in dash.iter("zone") if z.get("name")}
        for win in root.findall("windows/window"):
            if win.get("class") != "dashboard" or win.get("name") != dash.get("name"):
                continue
            vps = win.find("viewpoints")
            if vps is None:
                vps = etree.Element("viewpoints")
                win.insert(0, vps)
            have = {v.get("name") for v in vps.findall("viewpoint")}
            for name in sorted(names - have):
                v = etree.SubElement(vps, "viewpoint")
                v.set("name", name)
                added += 1
    return added


def _drop_fit(root, sheet: str) -> None:
    for vps in root.iter("viewpoints"):
        for v in vps.findall("viewpoint"):
            if v.get("name") == sheet:
                for z in list(v.findall("zoom")):
                    v.remove(z)


_TC_DIRECTIONS = {
    "down": "Columns", "down by rows": "Columns", "table down": "Columns",
    "across": "Rows", "across by columns": "Rows", "table across": "Rows",
    "across in pane": "ColumnInPane",
    "pane": "Pane",
    "table": "Table",
    "cell": "CellInPane",
    "by field": "Field",
}

_TC_PROVEN = {"Columns": "accumulates down the rows; verified by screenshot",
              "Rows": "accumulates across the columns; verified by screenshot",
              "Field": "computes along the named field; present in the corpus (43 nodes)",
              "ColumnInPane": "corpus measurement (12 nodes), NOT verified by experiment",
              "Table": "corpus measurement (3 nodes), NOT verified by experiment",
              "Pane": "corpus measurement (2 nodes), NOT verified by experiment",
              "CellInPane": "corpus measurement (1 node), NOT verified by experiment"}

TABLE_CALCS = {
    "running total": (
        "RUNNING_SUM({x})", "real", "",
        "cumulative sum from the start of the dimension"),
    "% of total": (
        "{x} / TOTAL({x})", "real", "p0.0%",
        "share of the row in the sum along the direction of computation"),
    "rank": (
        "RANK({x})", "integer", "n#,##0",
        "place by descending value"),
    "difference from previous": (
        "ZN({x}) - LOOKUP(ZN({x}), -1)", "real", "",
        "absolute change against the adjacent row"),
    "% change from previous": (
        "(ZN({x}) - LOOKUP(ZN({x}), -1)) / ABS(LOOKUP(ZN({x}), -1))", "real", "p0.0%",
        "percentage change against the adjacent row"),
    "moving average": (
        "WINDOW_AVG({x}, -{w}, 0)", "real", "",
        "average over the current row and {w} previous"),
    "moving sum": (
        "WINDOW_SUM({x}, -{w}, 0)", "real", "",
        "sum over the current row and {w} previous"),
    "cumulative share": (
        "RUNNING_SUM({x}) / TOTAL({x})", "real", "p0.0%",
        "cumulative share, a Pareto curve"),
}

_TC_ALIASES = {
    "running_total": "running total", "running_sum": "running total",
    "pct_of_total": "% of total", "percent_of_total": "% of total",
    "difference": "difference from previous", "diff": "difference from previous",
    "pct_difference": "% change from previous", "pct_diff": "% change from previous",
    "moving_average": "moving average", "moving_avg": "moving average",
    "moving_sum": "moving sum",
    "pareto": "cumulative share", "running_pct": "cumulative share",
}


def _tc_source_expr(root, field: str, agg: str = "SUM") -> tuple:
    """Source measure expression for a table function: `([name], 'SUM([name])')`."""
    src, name = None, field.strip("[]")
    for c in root.iter("column"):
        nm = (c.get("name") or "").strip("[]")
        if nm == name or (c.get("caption") or "") == field:
            if src is None or c.find("calculation") is not None:
                src, name = c, nm
            if c.find("calculation") is not None:
                break
    if src is None:
        return None, ""
    calc = src.find("calculation")
    formula = calc.get("formula") if calc is not None else ""
    if calc is not None and is_aggregated(formula or ""):
        return src, f"[{name}]"
    if (src.get("role") or "") == "dimension":
        return src, f"[{name}]"
    return src, f"{agg}([{name}])"


def _tc_ordering_ref(root, ds: str, field: str) -> str:
    """`ordering-field` is a reference of the form `[datasource].[column]`."""
    if field.startswith("[") and "]." in field:
        return field
    name = field.strip("[]")
    for c in root.iter("column"):
        if (c.get("caption") or "") == field:
            name = (c.get("name") or "").strip("[]")
            break
    return f"[{ds}].[{name}]"


def _tc_column(root, ds: str, caption: str, formula: str, datatype: str,
               fmt: str, tc_attrs: dict):
    """Declare (or redeclare) a calculation field with a direction of computation."""
    for dsn in root.iter("datasource"):
        if dsn.get("name") != ds:
            continue
        col = None
        for c in dsn.findall("column"):
            if c.get("name") == f"[{caption}]" or c.get("caption") == caption:
                col = c
                break
        if col is None:
            col = etree.Element("column")
            col.set("name", f"[{caption}]")
            insert_in_order(dsn, col, _DS_ORDER)
        col.set("caption", caption)
        col.set("datatype", datatype)
        col.set("role", "measure")
        col.set("type", "ordinal" if datatype == "integer" else "quantitative")
        if fmt:
            col.set("default-format", fmt)
        for old in col.findall("calculation"):
            col.remove(old)
        calc = etree.Element("calculation")
        calc.set("class", "tableau")
        calc.set("formula", formula)
        tc = etree.SubElement(calc, "table-calc")
        for k, v in tc_attrs.items():
            tc.set(k, v)
        col.insert(0, calc)
        return col
    return None


def _tc_sync(root, ds: str, caption: str, src_col, sheets: list = None) -> dict:
    """Spread the field declaration across the copies in sheets."""
    touched, added = [], []
    want = set(sheets or [])
    for ws in root.iter("worksheet"):
        name = ws.get("name")
        dep = ws.find(f".//datasource-dependencies[@datasource='{ds}']")
        has = dep is not None and any(
            c.get("name") == f"[{caption}]" for c in dep.findall("column"))
        if not has and name not in want:
            continue
        if dep is None:
            _ensure_ds_dependency(root, name, ds)
            dep = ws.find(f".//datasource-dependencies[@datasource='{ds}']")
            if dep is None:
                continue
        for c in dep.findall("column"):
            if c.get("name") == f"[{caption}]":
                dep.remove(c)
        dep.insert(0, copy.deepcopy(src_col))
        (touched if has else added).append(name)
    return {"updated_in_sheets": sorted(touched), "added_to_sheets": sorted(added)}


def table_calc(root, caption: str, *, kind: str, field: str,
               direction: str = "down", ordering_field: str = "",
               window: int = 2, agg: str = "SUM", fmt: str = "",
               sheets: list = None) -> dict:
    """Create a table-calculation field with an EXPLICIT direction of computation."""
    key = _TC_ALIASES.get(kind.strip().lower(), kind.strip().lower())
    for k in TABLE_CALCS:
        if k.lower() == key:
            key = k
            break
    if key not in TABLE_CALCS:
        return {"ok": False, "why": f"no recipe {kind!r}",
                "recipes": sorted(TABLE_CALCS) + sorted(_TC_ALIASES)}

    ds = _main_datasource_name(root)
    if not ds:
        return {"ok": False, "why": "the workbook has no datasource"}

    src, expr = _tc_source_expr(root, field, agg)
    if src is None:
        return {"ok": False, "why": f"no field {field!r} in the workbook"}

    known = {ws.get("name") for ws in root.iter("worksheet")}
    unknown = [x for x in (sheets or []) if x not in known]
    if unknown:
        return {"ok": False, "why": f"no such sheets: {', '.join(unknown)}",
                "workbook_sheets": sorted(known)}

    order_type = _TC_DIRECTIONS.get(direction.strip().lower())
    if order_type is None:
        return {"ok": False, "why": f"no direction {direction!r}",
                "directions": sorted(set(_TC_DIRECTIONS))}

    tc_attrs = {}
    note = ""
    if ordering_field:
        if order_type != "Field":
            note = (f"direction {order_type} replaced with Field: "
                    f"computation field {ordering_field!r} is given")
        order_type = "Field"
        tc_attrs["ordering-field"] = _tc_ordering_ref(root, ds, ordering_field)
    elif order_type == "Field":
        return {"ok": False,
                "why": "direction 'by field' without ordering_field; "
                       "Tableau would compute across the table and the number would be wrong"}
    tc_attrs["ordering-type"] = order_type

    tpl, datatype, def_fmt, _ = TABLE_CALCS[key]
    formula = tpl.format(x=expr, w=int(window))
    fmt = fmt or def_fmt
    col = _tc_column(root, ds, caption, formula, datatype, fmt, tc_attrs)
    if col is None:
        return {"ok": False, "why": f"datasource {ds} is not in the workbook"}
    spread = _tc_sync(root, ds, caption, col, sheets)

    out = {"ok": True, "field": caption, "recipe": key, "formula": formula,
           "direction": order_type, "format": fmt or "(default)",
           "next": f"put on a sheet: place_field(sheet, '{caption}', "
                   f"shelf='text', derivation='User'); if the sheet is a MEASURE "
                   f"TABLE, use add_measure('{caption}', derivation='User')"}
    if ordering_field:
        out["by_field"] = tc_attrs["ordering-field"]
    if note:
        out["note"] = note
    out.update(spread)
    return out


_TABLE_ORDER = ["view", "style", "panes", "rows", "cols", "subtotals",
                "tooltip-style", "show-full-range"]

_SHELVES = {
    "rows": "rows",
    "cols": "cols", "columns": "cols",
    "text": "text", "label": "text",
    "color": "color",
    "size": "size",
    "detail": "lod", "lod": "lod",
    "tooltip": "tooltip",
}
_ONE_PER_PANE = {"text", "color", "size"}


def _shelf_node(ws, tag: str):
    table = ws.find("table")
    if table is None:
        return None
    node = table.find(tag)
    if node is None:
        node = etree.Element(tag)
        insert_in_order(table, node, _TABLE_ORDER)
    return node


def place_field(root, sheet: str, field: str, shelf: str = "rows",
                derivation: str = "Sum", separator: str = "") -> dict:
    """Put a field on a sheet shelf: rows, columns, text, color, size, detail, tooltip."""
    ws = _sheet(root, sheet)
    if ws is None:
        return {"ok": False, "why": f"no sheet {sheet!r} in the workbook",
                "workbook_sheets": sorted(w.get("name") for w in root.iter("worksheet"))}
    tag = _SHELVES.get(shelf.strip().lower())
    if tag is None:
        return {"ok": False, "why": f"no shelf {shelf!r}",
                "shelves": sorted(set(_SHELVES))}

    ds = _ds_name(ws)
    try:
        ref, _inst = _instance_ref(root, ws, field, derivation)
    except ValueError as exc:
        return {"ok": False, "why": str(exc)}

    if tag in ("rows", "cols"):
        node = _shelf_node(ws, tag)
        if node is None:
            return {"ok": False, "why": "the sheet has no <table>"}
        cur = (node.text or "").strip()
        if ref in cur:
            return {"ok": True, "set": 0, "why": "the field is already on this shelf",
                    "shelf": tag, "expression": cur}
        if "[:Measure Names]" in cur and not separator:
            return {"ok": False,
                    "why": "the shelf already has [:Measure Names]; this is a measure "
                           "table, a column is added via add_measure, not a shelf",
                    "shelf": tag, "expression": cur}
        sep = separator or ("/" if ref.endswith((":nk]", ":ok]")) else "+")
        node.text = f"({cur} {sep} {ref})" if cur else ref
        return {"ok": True, "set": 1, "shelf": tag, "separator": sep,
                "expression": node.text}

    panes = [p for p in ws.iter("pane")]
    if not panes:
        return {"ok": False, "why": "the sheet has no panes; nothing to encode"}
    n = 0
    for pane in panes:
        enc = pane.find("encodings")
        if enc is None:
            enc = etree.Element("encodings")
            insert_in_order(pane, enc, _PANE_ORDER)
        if any(c.get("column") == ref for c in enc.findall(tag)):
            continue
        if tag in _ONE_PER_PANE:
            for old in enc.findall(tag):
                enc.remove(old)
        e = etree.SubElement(enc, tag)
        e.set("column", ref)
        n += 1
    return {"ok": True, "set": n, "shelf": tag, "field": ref,
            "pane_count": len(panes)}


def swap_rows_cols(root, sheets: list = None) -> dict:
    """Swap rows and columns: the "Swap Rows and Columns" button (Ctrl+W)."""
    names = set(sheets or [])
    done, missing = [], [s for s in names
                         if s not in {w.get("name") for w in root.iter("worksheet")}]
    if missing:
        return {"ok": False, "why": f"no such sheets: {', '.join(missing)}"}
    for ws in root.iter("worksheet"):
        if names and ws.get("name") not in names:
            continue
        table = ws.find("table")
        if table is None:
            continue
        rows, cols = table.find("rows"), table.find("cols")
        if rows is None and cols is None:
            continue
        r_text = (rows.text or "") if rows is not None else ""
        c_text = (cols.text or "") if cols is not None else ""
        if not r_text.strip() and not c_text.strip():
            continue
        rows = rows if rows is not None else _shelf_node(ws, "rows")
        cols = cols if cols is not None else _shelf_node(ws, "cols")
        rows.text, cols.text = c_text, r_text

        r_attr = {"total": rows.get("total"), "side": rows.get("onTop")}
        c_attr = {"total": cols.get("total"), "side": cols.get("onLeft")}
        for node, attr, src in ((rows, "onTop", c_attr), (cols, "onLeft", r_attr)):
            for a in ("total", attr):
                if node.get(a) is not None:
                    del node.attrib[a]
            if src["total"] is not None:
                node.set("total", src["total"])
            if src["side"] is not None:
                node.set(attr, src["side"])

        flipped = 0
        for node in ws.iter():
            sc = node.get("scope")
            if sc == "rows":
                node.set("scope", "cols")
                flipped += 1
            elif sc == "cols":
                node.set("scope", "rows")
                flipped += 1
        done.append({"sheet": ws.get("name"), "rows": (rows.text or "")[:60],
                     "columns": (cols.text or "")[:60],
                     "formatting_moved": flipped})
    if not done:
        return {"ok": False, "why": "nothing to swap: shelves are empty"}
    return {"ok": True, "sheets_swapped": len(done), "sheets": done}


_DIRECTIONS = {"desc": "DESC", "descending": "DESC",
               "asc": "ASC", "ascending": "ASC"}


#     type: string and boolean give `nk`, integer, date and datetime give `ok`, real gives
_BY_TYPE = {"nominal": "nk", "ordinal": "ok", "quantitative": "qk"}
_BY_DATATYPE = {"string": "nk", "boolean": "nk", "integer": "ok",
                "date": "ok", "datetime": "ok", "real": "qk"}


def _instance_on_sheet(ws, ds: str, name: str) -> str:
    """Instance name of this field ALREADY declared on the sheet, if there is one."""
    dep = ws.find(f".//datasource-dependencies[@datasource='{ds}']")
    if dep is None:
        return ""
    shelves = " ".join((ws.findtext("table/rows") or "", ws.findtext("table/cols") or ""))
    found: list[str] = []
    for ci in dep.findall("column-instance"):
        inner = (ci.get("name") or "").strip("[]")
        parts = inner.split(":")
        base = ":".join(parts[1:-1]) if len(parts) >= 3 else inner
        if base == name:
            found.append(f"[{ds}].[{inner}]")
    if not found:
        return ""
    on_shelf = [f for f in found if f in shelves]
    plain = [f for f in found if "].[none:" in f]
    return (on_shelf or plain or found)[0]


def _dim_ref(root, ws, field: str, force: str = "") -> str:
    """A field reference as Tableau writes it: `[ds].[none:field:nk]`."""
    ds = _ds_name(ws)
    name, kind = field.strip("[]"), "nk"
    for c in root.iter("column"):
        anc = next(c.iterancestors("datasource"), None)
        if anc is not None and anc.get("name") == "Parameters":
            continue
        nm = (c.get("name") or "").strip("[]")
        if nm == name or (c.get("caption") or "") == field:
            name = nm
            kind = (_BY_TYPE.get(c.get("type") or "")
                    or _BY_DATATYPE.get(c.get("datatype") or "", "nk"))
            break
    if force:
        want = f"[{ds}].[none:{name}:{force}]"
        if _instance_on_sheet(ws, ds, name) != want:
            try:
                return _instance_ref(root, ws, name, "None", kind=force)[0]
            except ValueError:
                return want
        return want
    on_sheet = _instance_on_sheet(ws, ds, name)
    if on_sheet:
        return on_sheet
    return f"[{ds}].[none:{name}:{kind}]"


SORT_FLAGS = ("IntuitiveSorting", "IntuitiveSorting_SP2", "SortTagCleanup")
MANUAL_SORT_FLAGS = ("SortTagCleanup",)


def ensure_format_flags(root, flags) -> list:
    """Several format-manifest entries at once (via `ensure_manifest`), creating the manifest if needed and..."""
    if root.find(".//document-format-change-manifest") is None:
        root.insert(0, etree.Element("document-format-change-manifest"))
    added = [f for f in flags if ensure_manifest(root, f)]
    if added:
        man = root.find(".//document-format-change-manifest")
        kids = sorted(man, key=lambda c: c.tag)
        for c in list(man):
            man.remove(c)
        for c in kids:
            man.append(c)
    return added


def sort_by_measure(root, sheet: str, dimension: str, by: str,
                    direction: str = "desc", derivation: str = "") -> dict:
    """Sort a dimension BY A MEASURE: `<shelf-sorts><shelf-sort-v2>`.

    `derivation` (Sum, CountD, User...) names the aggregation; without it a calculation is
    taken as is (User) and a column is summed.
    """
    ws = _sheet(root, sheet)
    if ws is None:
        return {"ok": False, "why": f"no sheet {sheet!r} in the workbook",
                "workbook_sheets": sorted(w.get("name") for w in root.iter("worksheet"))}
    view = ws.find("table/view")
    if view is None:
        return {"ok": False, "why": "the sheet has no <view>"}
    d = _DIRECTIONS.get(direction.strip().lower())
    if d is None:
        return {"ok": False, "why": f"no direction {direction!r}",
                "directions": sorted(set(_DIRECTIONS))}

    col = _dim_ref(root, ws, dimension)
    try:
        if derivation:
            using, _ = _instance_ref(root, ws, by, derivation, kind="qk")
        else:
            using, _ = _instance_ref(root, ws, by, "User" if _is_calc(root, by) else "Sum",
                                     role="measure")
    except ValueError as exc:
        return {"ok": False, "why": str(exc)}

    dropped = 0
    for tag in ("computed-sort", "manual-sort", "natural-sort", "alphabetic-sort"):
        for old in view.findall(tag):
            if old.get("column") == col:
                view.remove(old)
                dropped += 1
    shelf_sorts = view.find("shelf-sorts")
    if shelf_sorts is None:
        shelf_sorts = etree.Element("shelf-sorts")
        insert_in_order(view, shelf_sorts, _VIEW_ORDER)
    for old in shelf_sorts.findall("shelf-sort-v2"):
        if old.get("dimension-to-sort") == col:
            shelf_sorts.remove(old)
            dropped += 1
    cols_text = ws.findtext("table/cols") or ""
    node = etree.SubElement(shelf_sorts, "shelf-sort-v2")
    node.set("dimension-to-sort", col)
    node.set("direction", d)
    node.set("is-on-innermost-dimension", "true")
    node.set("measure-to-sort-by", using)
    node.set("shelf", "columns" if col in cols_text else "rows")
    flags = ensure_format_flags(root, SORT_FLAGS)
    return {"ok": True, "sheet": sheet, "dimension": col, "by_measure": using,
            "direction": d, "shelf": node.get("shelf"),
            "previous_sorts_removed": dropped, "manifest_flags_added": flags}


def _is_calc(root, field: str) -> bool:
    for c in root.iter("column"):
        nm = (c.get("name") or "").strip("[]")
        if nm == field.strip("[]") or (c.get("caption") or "") == field:
            return c.find("calculation") is not None
    return False


def _order_expression(root, by: str) -> str:
    """Top-N sort expression by the INTERNAL name, as in the corpus: `SUM([Profit])` for a column,..."""
    b = by.strip()
    if re.match(r"^[A-Z_]+\(", b):
        return b
    key = b.strip("[]")
    cols = [c for ds in root.iter("datasource") if ds.get("name") != "Parameters"
            for c in ds.findall("column")]
    el = next((c for c in cols if c.get("caption") == key), None)
    if el is None:
        el = next((c for c in cols if (c.get("name") or "") == f"[{key}]"), None)
    if el is None:
        return f"[{key}]"
    from .fields import is_aggregate
    name = el.get("name")
    calc = el.find("calculation")
    if calc is not None and is_aggregate(calc.get("formula") or ""):
        return name
    return f"SUM({name})"

def top_n_filter(root, sheet: str, dimension: str, by: str, count,
                 direction: str = "desc") -> dict:
    """A "top-N by measure" filter."""
    ws = _sheet(root, sheet)
    if ws is None:
        return {"ok": False, "why": f"no sheet {sheet!r} in the workbook"}
    view = ws.find("table/view")
    if view is None:
        return {"ok": False, "why": "the sheet has no <view>"}
    d = _DIRECTIONS.get(direction.strip().lower())
    if d is None:
        return {"ok": False, "why": f"no direction {direction!r}",
                "directions": sorted(set(_DIRECTIONS))}

    col = _dim_ref(root, ws, dimension)
    level = "[" + col.split("].[", 1)[1]
    txt = str(count).strip()
    if txt.isdigit():
        cnt, kind = txt, "number"
    else:
        cnt = _param_ref(root, txt)
        kind = "parameter"
        if not any(c.get("caption") == txt.strip("[]") or
                   c.get("name") == f"[{txt.strip('[]')}]"
                   for dsn in root.iter("datasource")
                   if dsn.get("name") == "Parameters"
                   for c in dsn.findall("column")):
            return {"ok": False, "why": f"no parameter {txt!r} in the workbook; "
                                        f"the filter would silently not work"}
        _ensure_param_dependency(root, sheet, txt.strip("[]"))

    for old in view.findall("filter"):
        if old.get("column") == col:
            view.remove(old)

    filt = etree.Element("filter")
    filt.set("class", "categorical")
    filt.set("column", col)
    end = etree.SubElement(filt, "groupfilter")
    end.set("count", cnt)
    end.set("end", "top" if d == "DESC" else "bottom")
    end.set("function", "end")
    end.set("units", "records")
    end.set(_u("ui-marker"), "end")
    end.set(_u("ui-top-by-field"), "true")
    order = etree.SubElement(end, "groupfilter")
    order.set("direction", d)
    order.set("expression", _order_expression(root, by))
    order.set("function", "order")
    order.set(_u("ui-marker"), "order")
    lvl = etree.SubElement(order, "groupfilter")
    lvl.set("function", "level-members")
    lvl.set("level", level)
    lvl.set(_u("ui-enumeration"), "all")
    lvl.set(_u("ui-marker"), "enumerate")
    insert_in_order(view, filt, _VIEW_ORDER)
    return {"ok": True, "sheet": sheet, "dimension": col, "by_measure": by,
            "count": cnt, "depth_given_as": kind,
            "edge": "top" if d == "DESC" else "bottom"}


_PERIODS = {"day": "day", "week": "week", "month": "month",
            "quarter": "quarter", "year": "year"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(\s+\d{2}:\d{2}:\d{2})?$")


def _date_literal(v) -> str:
    """A date in a Tableau workbook is written IN HASHES: `#2026-01-31#`."""
    txt = str(v).strip()
    if _DATE_RE.match(txt):
        return f"#{txt}#"
    return txt


def _base_name(ref: str) -> str:
    """Field name inside a reference: `[ds].[none:Month:ok]` gives `Month`."""
    inner = ref.split("].[", 1)[1].rstrip("]") if "].[" in ref else ref.strip("[]")
    parts = inner.split(":")
    return ":".join(parts[1:-1]) if len(parts) >= 3 else inner


def _replace_filter(view, col: str) -> int:
    """Remove earlier filters ON THE SAME FIELD, comparing the name, not the whole reference."""
    want, dropped = _base_name(col), 0
    for old in view.findall("filter"):
        ref = old.get("column") or ""
        if ref == col or _base_name(ref) == want:
            view.remove(old)
            dropped += 1
    return dropped


def range_filter(root, sheet: str, field: str, low=None, high=None,
                 context: bool = False) -> dict:
    """A value-range filter (`class="quantitative"`)."""
    ws = _sheet(root, sheet)
    if ws is None:
        return {"ok": False, "why": f"no sheet {sheet!r} in the workbook"}
    view = ws.find("table/view")
    if view is None:
        return {"ok": False, "why": "the sheet has no <view>"}
    col = _dim_ref(root, ws, field, force="qk")
    dropped = _replace_filter(view, col)

    filt = etree.Element("filter")
    filt.set("class", "quantitative")
    filt.set("column", col)
    if context:
        filt.set("context", "true")
    filt.set("included-values", "in-range" if (low is not None or high is not None)
             else "all")
    if low is not None:
        etree.SubElement(filt, "min").text = _date_literal(low)
    if high is not None:
        etree.SubElement(filt, "max").text = _date_literal(high)
    insert_in_order(view, filt, _VIEW_ORDER)
    return {"ok": True, "sheet": sheet, "field": col,
            "from": _date_literal(low) if low is not None else "(no lower bound)",
            "to": _date_literal(high) if high is not None else "(no upper bound)",
            "in_context": bool(context), "previous_filters_removed": dropped}


def ensure_manifest(root, entry: str) -> bool:
    """Declare a format capability in `<document-format-change-manifest>`."""
    man = root.find(".//document-format-change-manifest")
    if man is None:
        return False
    if man.find(entry) is not None:
        return False
    node = etree.SubElement(man, entry)
    node.tail = "\n    "
    return True


def relative_date_filter(root, sheet: str, field: str, period: str = "month",
                         first: int = -5, last: int = 0,
                         include_future: bool = True,
                         context: bool = False) -> dict:
    """A "last N periods" filter (`class="relative-date"`)."""
    ws = _sheet(root, sheet)
    if ws is None:
        return {"ok": False, "why": f"no sheet {sheet!r} in the workbook"}
    view = ws.find("table/view")
    if view is None:
        return {"ok": False, "why": "the sheet has no <view>"}
    p = _PERIODS.get(str(period).strip().lower())
    if p is None:
        return {"ok": False, "why": f"no period {period!r}",
                "periods": sorted(set(_PERIODS))}
    if int(first) > int(last):
        return {"ok": False,
                "why": f"start ({first}) is after end ({last}); the window is empty"}

    col = _dim_ref(root, ws, field, force="qk")
    dropped = _replace_filter(view, col)
    filt = etree.Element("filter")
    filt.set("class", "relative-date")
    filt.set("column", col)
    if context:
        filt.set("context", "true")
    filt.set("first-period", str(int(first)))
    filt.set("include-future", "true" if include_future else "false")
    filt.set("include-null", "false")
    filt.set("last-period", str(int(last)))
    filt.set("period-type-v2", p)
    insert_in_order(view, filt, _VIEW_ORDER)
    added = ensure_manifest(root, "ISO8601PeriodTypes")
    out = {"ok": True, "sheet": sheet, "field": col, "period": p,
           "window": f"from {first} to {last}", "in_context": bool(context),
           "previous_filters_removed": dropped}
    if added:
        out["manifest"] = "ISO8601PeriodTypes added; without it the workbook would not open"
    return out


def set_filter_context(root, sheets: list, field: str = "", on: bool = True) -> dict:
    """Move filter(s) into CONTEXT: they are applied before the others."""
    known = {w.get("name") for w in root.iter("worksheet")}
    missing = [s for s in (sheets or []) if s not in known]
    if missing:
        return {"ok": False, "why": f"no such sheets: {', '.join(missing)}"}
    touched = []
    for ws in root.iter("worksheet"):
        if sheets and ws.get("name") not in sheets:
            continue
        view = ws.find("table/view")
        if view is None:
            continue
        want = _dim_ref(root, ws, field) if field else ""
        for filt in view.findall("filter"):
            col = filt.get("column") or ""
            if field and col != want and f":{field.strip('[]')}:" not in col:
                continue
            if on:
                filt.set("context", "true")
            elif filt.get("context") is not None:
                del filt.attrib["context"]
            touched.append({"sheet": ws.get("name"), "filter": col})
    if not touched:
        return {"ok": False, "why": "no such filter found; "
                                    "context would silently not be set"}
    return {"ok": True, "in_context" if on else "out_of_context": len(touched),
            "filters": touched}


_TIP_LABEL_COLOR = "#757575"
_TIP_BREAK = "\u00c6\n"


def _auto_ref(root, ws, field: str, derivation: str = "") -> str:
    """Field reference for substitution: a dimension as is, a measure with an aggregate."""
    bare = field.strip("[]")
    col = next((c for d in root.iter("datasource") for c in d.findall("column")
                if (c.get("name") or "").strip("[]") == bare or (c.get("caption") or "") == field), None)
    if col is None:
        # a raw field of a text/extract source is declared only in the relation's column list
        col = next((c for c in root.iter("column") if c.getparent() is not None
                    and c.getparent().tag == "columns" and c.get("name") == bare), None)
        if col is None:
            return ""
    role = col.get("role") or ("measure" if col.get("datatype") in ("real", "integer") else "dimension")
    if not derivation:
        if role == "dimension":
            derivation = "None"
        else:
            derivation = "User" if col.find("calculation") is not None else "Sum"
    if derivation == "None":
        return _dim_ref(root, ws, field)
    return _instance_ref(root, ws, field, derivation)[0]


def set_tooltip(root, sheet: str, lines: list, plain: bool = False) -> dict:
    """Build a sheet tooltip from "caption -> field" lines."""
    ws = _sheet(root, sheet)
    if ws is None:
        return {"ok": False, "why": f"no sheet {sheet!r} in the workbook",
                "workbook_sheets": sorted(w.get("name") for w in root.iter("worksheet"))}
    panes = list(ws.iter("pane"))
    if not panes:
        return {"ok": False, "why": "the sheet has no panes; nowhere to put a tooltip"}
    if not lines:
        return {"ok": False, "why": "nothing to show: no lines given"}

    runs, missing = [], []
    for item in lines:
        if item.get("text") is not None:
            runs.append(({}, str(item["text"])))
            runs.append(({}, _TIP_BREAK))
            continue
        field = item.get("field") or ""
        ref = _auto_ref(root, ws, field, item.get("derivation") or "")
        if not ref:
            missing.append(field)
            continue
        label = item.get("label")
        if label is None:
            label = field
        if label != "":
            runs.append(({} if plain else {"fontcolor": _TIP_LABEL_COLOR},
                         f"{label}:\t"))
        runs.append(({} if plain else {"bold": "true"}, f"<{ref}>"))
        runs.append(({}, _TIP_BREAK))
    if missing:
        return {"ok": False,
                "why": f"fields not in the workbook: {', '.join(missing)}; a line "
                       f"would vanish and the tooltip would look fine"}

    made = 0
    for pane in panes:
        for old in pane.findall("customized-tooltip"):
            pane.remove(old)
        tip = etree.Element("customized-tooltip")
        ft = etree.SubElement(tip, "formatted-text")
        for attrs, text in runs:
            run = etree.SubElement(ft, "run")
            for k, v in attrs.items():
                run.set(k, v)
            run.text = text
        insert_in_order(pane, tip, _PANE_ORDER)
        made += 1
    return {"ok": True, "sheet": sheet, "row_count": len(lines), "pane_count": made,
            "style": "plain" if plain else "house (grey caption, bold value)"}


_SHELF_TOKEN = re.compile(r"\[[^\]]*\](?:\.\[[^\]]*\])+|[()+/*]")


def _parse_shelf(text: str):
    """Parse a shelf expression into a tree: ('ref', text) | ('op', [children], [operations])."""
    tokens = _SHELF_TOKEN.findall(text or "")
    pos = [0]

    def expr():
        kids, ops = [term()], []
        while pos[0] < len(tokens) and tokens[pos[0]] in "+/*":
            ops.append(tokens[pos[0]])
            pos[0] += 1
            kids.append(term())
        return kids[0] if len(kids) == 1 and not ops else ("op", kids, ops)

    def term():
        if pos[0] >= len(tokens):
            return ("ref", "")
        tok = tokens[pos[0]]
        pos[0] += 1
        if tok == "(":
            node = expr()
            if pos[0] < len(tokens) and tokens[pos[0]] == ")":
                pos[0] += 1
            return node
        return ("ref", tok)

    return expr() if tokens else None


def _drop_ref(node, ref: str):
    """Remove a reference from the tree; a node with no children vanishes, with one it collapses."""
    if node is None:
        return None
    if node[0] == "ref":
        return None if node[1] == ref else node
    kids, ops = node[1], node[2]
    keep, keep_ops = [], []
    for i, k in enumerate(kids):
        got = _drop_ref(k, ref)
        if got is None:
            if i > 0 and keep_ops:
                keep_ops.pop()
            elif i < len(ops):
                ops = ops[:i] + ops[i + 1:]
            continue
        if keep:
            idx = min(len(keep) - 1, len(ops) - 1)
            keep_ops.append(ops[idx] if 0 <= idx < len(ops) else "/")
        keep.append(got)
    if not keep:
        return None
    if len(keep) == 1:
        return keep[0]
    return ("op", keep, keep_ops[:len(keep) - 1])


def _render_shelf(node) -> str:
    if node is None:
        return ""
    if node[0] == "ref":
        return node[1]
    parts = [_render_shelf(node[1][0])]
    for op, kid in zip(node[2], node[1][1:]):
        parts.append(f" {op} {_render_shelf(kid)}")
    return "(" + "".join(parts) + ")"


def remove_field(root, sheet: str, field: str, shelf: str = "") -> dict:
    """Take a field off a sheet shelf; the inverse of `place_field`."""
    ws = _sheet(root, sheet)
    if ws is None:
        return {"ok": False, "why": f"no sheet {sheet!r} in the workbook",
                "workbook_sheets": sorted(w.get("name") for w in root.iter("worksheet"))}
    tag = _SHELVES.get(shelf.strip().lower()) if shelf else ""
    if shelf and tag is None:
        return {"ok": False, "why": f"no shelf {shelf!r}",
                "shelves": sorted(set(_SHELVES))}

    ds = _ds_name(ws)
    name = field.strip("[]")
    for c in root.iter("column"):
        if (c.get("caption") or "") == field:
            name = (c.get("name") or "").strip("[]")
            break

    def matches(ref: str) -> bool:
        inner = ref.split("].[", 1)[1].rstrip("]") if "].[" in ref else ref.strip("[]")
        parts = inner.split(":")
        return (":".join(parts[1:-1]) if len(parts) >= 3 else inner) == name

    removed = []
    for want in (("rows", "cols") if not tag else (tag,)):
        if want not in ("rows", "cols"):
            continue
        node = ws.find(f"table/{want}")
        if node is None or not (node.text or "").strip():
            continue
        tree = _parse_shelf(node.text.strip())
        refs = []

        def collect(n):
            if n is None:
                return
            if n[0] == "ref":
                refs.append(n[1])
            else:
                for k in n[1]:
                    collect(k)

        collect(tree)
        for ref in [r for r in refs if matches(r)]:
            tree = _drop_ref(tree, ref)
            removed.append({"shelf": want, "field": ref})
        node.text = _render_shelf(tree)

    for pane in ws.iter("pane"):
        enc = pane.find("encodings")
        if enc is None:
            continue
        for child in list(enc):
            if tag and child.tag != tag:
                continue
            if not tag and child.tag not in _SHELVES.values():
                continue
            if matches(child.get("column") or ""):
                enc.remove(child)
                removed.append({"shelf": child.tag, "field": child.get("column")})
        if len(enc) == 0:
            pane.remove(enc)

    if not removed:
        return {"ok": False,
                "why": f"field {field!r} is not on these shelves; "
                       f"'removed 0' would read as success"}
    return {"ok": True, "sheet": sheet, "removed": len(removed), "what": removed}


def _member_literal(value, datatype: str = "") -> str:
    """A member value as Tableau writes it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if datatype in ("integer", "real") or text in ("true", "false"):
        return text
    return f'"{text}"'


def exclude_members(root, sheet: str, field: str, members: list,
                    datatype: str = "") -> dict:
    """Exclude specific dimension values: what right-click on a mark then **Exclude** does in Desktop (and the..."""
    ws = _sheet(root, sheet)
    if ws is None:
        raise ValueError(f"sheet {sheet!r} is not in the workbook")
    members = [m for m in (members or []) if m != "" and m is not None]
    if not members:
        return {"ok": False, "why": "no values given; "
                                    "'excluded 0' would read as success"}

    ds_name = _ds_name(ws)
    ref = _dim_ref(root, ws, field)
    level = "[" + ref.split("].[", 1)[1] if "].[" in ref else ref
    caption = field.strip("[]")
    group_name = f"Exclusions ({caption})"

    ds = None
    for cand in root.findall("./datasources/datasource"):
        if cand.get("name") == ds_name:
            ds = cand
            break
    if ds is None:
        raise ValueError(f"datasource {ds_name!r} is not in the workbook")

    for old in ds.findall("group"):
        if (old.get("name") or "").strip("[]") == group_name:
            ds.remove(old)
    group = etree.Element("group")
    group.set("hidden", "true")
    group.set("name", f"[{group_name}]")
    group.set("name-style", "unqualified")
    group.set("{%s}auto-column" % _USER_NS, "exclude")
    cj = etree.SubElement(group, "groupfilter")
    cj.set("function", "crossjoin")
    lm = etree.SubElement(cj, "groupfilter")
    lm.set("function", "level-members")
    lm.set("level", level)
    insert_in_order(ds, group, _DS_ORDER)

    view = ws.find(".//view")
    col = f"[{ds_name}].[{group_name}]"
    _replace_filter(view, col)

    filt = etree.Element("filter")
    filt.set("class", "categorical")
    filt.set("column", col)
    exc = etree.SubElement(filt, "groupfilter")
    exc.set("function", "except")
    for attr, val in (("ui-domain", "database"), ("ui-enumeration", "exclusive"),
                      ("ui-marker", "enumerate")):
        exc.set("{%s}%s" % (_USER_NS, attr), val)
    keep = etree.SubElement(exc, "groupfilter")
    keep.set("function", "crossjoin")
    keep_lm = etree.SubElement(keep, "groupfilter")
    keep_lm.set("function", "level-members")
    keep_lm.set("level", level)
    reorder = etree.SubElement(exc, "groupfilter")
    reorder.set("function", "reorder-dimensionality")
    inner = etree.SubElement(reorder, "groupfilter")
    inner.set("function", "crossjoin")
    holder = inner
    if len(members) > 1:
        holder = etree.SubElement(inner, "groupfilter")
        holder.set("function", "union")
    for value in members:
        mem = etree.SubElement(holder, "groupfilter")
        mem.set("function", "member")
        mem.set("level", level)
        mem.set("member", _member_literal(value, datatype))
    order = etree.SubElement(reorder, "order")
    etree.SubElement(order, "hierarchy").set("name", level)

    last = view.findall("filter")
    if last:
        last[-1].addnext(filt)
    else:
        view.insert(0, filt)

    slices = view.find("slices")
    if slices is None:
        slices = etree.SubElement(view, "slices")
    if not any((c.text or "") == col for c in slices.findall("column")):
        etree.SubElement(slices, "column").text = col

    return {"ok": True, "sheet": sheet, "field": caption,
            "excluded": len(members), "values": [str(m) for m in members],
            "group": group_name}


_PAGE_BORDER = {"border-color": "#e4e8e2", "border-style": "solid", "border-width": "1"}


def _page_zone_style(zone, fmt: dict):
    """Give a zone a `<zone-style>` with the listed formats."""
    st = zone.find("zone-style")
    if st is None:
        st = etree.Element("zone-style")
        insert_in_order(zone, st, _ZONE_ORDER)
    for attr, value in fmt.items():
        node = next((f for f in st.findall("format") if f.get("attr") == attr), None)
        if node is None:
            node = etree.SubElement(st, "format")
            node.set("attr", attr)
        node.set("value", value)


def _sheet_zone(name: str, zid: int, height: int = 0, fit_cache: bool = True):
    z = etree.Element("zone")
    z.set("id", str(zid))
    z.set("name", name)
    if height:
        z.set("fixed-size", str(height))
        z.set("is-fixed", "true")
    if fit_cache:
        cache = etree.SubElement(z, "layout-cache")
        cache.set("type-h", "fixed")
        cache.set("type-w", "fixed")
    _page_zone_style(z, dict(_PAGE_BORDER))
    return z


def _text_zone(zid: int, height: int, runs: list):
    """A dashboard text zone."""
    z = etree.Element("zone")
    z.set("id", str(zid))
    z.set("type-v2", "text")
    z.set("fixed-size", str(height))
    z.set("is-fixed", "true")
    z.set("forceUpdate", "true")
    ft = etree.Element("formatted-text")
    for item in runs:
        run = etree.SubElement(ft, "run")
        if item.get("bold"):
            run.set("bold", "true")
        if item.get("color"):
            run.set("fontcolor", item["color"])
        if item.get("size"):
            run.set("fontsize", str(item["size"]))
        run.text = item.get("text", "")
    insert_in_order(z, ft, _ZONE_ORDER)
    _page_zone_style(z, dict(_PAGE_BORDER))
    return z


def stack_page(root, dashboard: str, items: list, size: dict = None) -> dict:
    """Rebuild a dashboard into ONE vertical column: a long scrolling sheet."""
    dash = next((d for d in root.iter("dashboard") if d.get("name") == dashboard), None)
    if dash is None:
        raise ValueError(f"dashboard {dashboard!r} is not in the workbook")
    zones = dash.find("zones")
    if zones is None:
        raise ValueError(f"dashboard {dashboard!r} has no <zones>")
    outer = zones.find("zone")
    if outer is None:
        raise ValueError(f"dashboard {dashboard!r} has no root zone")
    outer.set("param", "vert")
    outer.set("type-v2", "layout-flow")

    kept = {z.get("id"): z for z in outer.findall("zone")}
    used = {int(z.get("id")) for z in dash.iter("zone") if z.get("id")}
    next_id = max(used) + 1 if used else 1

    built, taken = [], set()
    for item in items:
        kind = item.get("kind")
        h = int(item.get("h") or 0)
        if kind == "keep":
            zid = str(item["id"])
            if zid not in kept:
                raise ValueError(f"zone {zid} is not on dashboard {dashboard!r}")
            z = kept[zid]
            taken.add(zid)
            if h:
                z.set("fixed-size", str(h))
                z.set("is-fixed", "true")
            kids = z.findall("zone") if z.get("type-v2") == "layout-flow" else None
            built.append((z, int(z.get("fixed-size") or h or 100), kids))
        elif kind == "sheet":
            z = _sheet_zone(item["name"], next_id, h); next_id += 1
            built.append((z, h, None))
        elif kind == "row":
            z = etree.Element("zone")
            z.set("id", str(next_id)); next_id += 1
            z.set("type-v2", "layout-flow")
            z.set("param", "horz")
            z.set("layout-strategy-id", "distribute-evenly")
            z.set("fixed-size", str(h))
            z.set("is-fixed", "true")
            kids = []
            for entry in item["sheets"]:
                if isinstance(entry, str):
                    kid = _sheet_zone(entry, next_id)
                elif entry.get("kind") == "text":
                    kid = _text_zone(next_id, 0, entry.get("runs") or [])
                    kid.attrib.pop("fixed-size", None)
                    kid.attrib.pop("is-fixed", None)
                else:
                    kid = _sheet_zone(entry["name"], next_id)
                next_id += 1
                z.append(kid)
                kids.append(kid)
            built.append((z, h, kids))
        elif kind == "text":
            z = _text_zone(next_id, h, item.get("runs") or []); next_id += 1
            built.append((z, h, None))
        elif kind == "gap":
            z = etree.Element("zone")
            z.set("id", str(next_id)); next_id += 1
            z.set("type-v2", "empty")
            z.set("fixed-size", str(h))
            z.set("is-fixed", "true")
            built.append((z, h, None))
        else:
            raise ValueError(f"unknown block {kind!r}")

    dropped = [{"id": zid, "name": z.get("name") or z.get("type-v2") or "-"}
               for zid, z in kept.items() if zid not in taken]
    for z in outer.findall("zone"):
        outer.remove(z)

    ox, oy = int(outer.get("x") or 0), int(outer.get("y") or 0)
    ow, oh = int(outer.get("w") or 100000), int(outer.get("h") or 100000)
    total = sum(px for _, px, _ in built) or 1
    y = oy
    for i, (z, px, kids) in enumerate(built):
        zh = (oy + oh - y) if i == len(built) - 1 else max(1, round(oh * px / total))
        z.set("x", str(ox)); z.set("y", str(y))
        z.set("w", str(ow)); z.set("h", str(zh))
        if kids:
            kw = ow // len(kids)
            for i, kid in enumerate(kids):
                kid.set("x", str(ox + kw * i)); kid.set("y", str(y))
                kid.set("w", str(kw if i < len(kids) - 1 else ow - kw * i))
                kid.set("h", str(zh))
        y += zh
        insert_in_order(outer, z, _ZONE_ORDER)

    win = next((w for w in root.iter("window")
                if w.get("class") == "dashboard" and w.get("name") == dashboard), None)
    added = sync_viewpoints(win, dash) if win is not None else 0

    out = {"ok": True, "page": dashboard, "block_count": len(built),
           "height_px": total, "zones_removed": dropped, "viewpoints_added": added}
    if size:
        node = dash.find("size")
        if node is None:
            node = etree.Element("size")
            dash.insert(0, node)
        for attr in ("minwidth", "maxwidth", "minheight", "maxheight"):
            node.attrib.pop(attr, None)
            if size.get(attr):
                node.set(attr, str(size[attr]))
        node.set("sizing-mode", size.get("sizing-mode", "range"))
        out["size"] = dict(node.attrib)
    return out

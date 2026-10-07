"""Story points — a presentation of steps, each with its own caption and captured sheet."""
from __future__ import annotations

from lxml import etree

from . import style as S

NAV_HEIGHT = 125
NAV_TYPES = ("caption", "numbers", "dots", "arrows-only")


def add_story(editor, name: str, points: list[dict], *,
              title: str = "", nav_type: str = "caption",
              show_arrows: bool = True, caption_bg: str = "#c0c0c0") -> str:
    """Add a story (storyboard) built from steps."""
    if not points:
        raise ValueError("a story needs at least one step")
    if nav_type not in NAV_TYPES:
        raise ValueError(f"nav_type={nav_type!r}; available: {', '.join(NAV_TYPES)}")

    existing = {w.get("name") for holder in editor.root.iter("worksheets")
                for w in holder.findall("worksheet")}
    existing |= {d.get("name") for d in editor.root.iter("dashboard")}

    normalized = []
    for i, p in enumerate(points, 1):
        sheet = p.get("sheet") or ""
        caption = p.get("caption") or ""
        if not sheet:
            raise ValueError(f"step {i}: no sheet given")
        if sheet not in existing:
            raise ValueError(
                f"step {i}: sheet '{sheet}' is not in the workbook. Available: {', '.join(sorted(existing))}"
            )
        if not caption:
            raise ValueError(f"step {i} ({sheet}): no caption; a story is read through its captions")
        normalized.append((str(i), sheet, caption))

    dashboards = editor.root.find("dashboards")
    if dashboards is None:
        dashboards = etree.SubElement(editor.root, "dashboards")

    dash = etree.SubElement(dashboards, "dashboard")
    dash.set("name", name)
    dash.set("type", "storyboard")

    lo = etree.SubElement(dash, "layout-options")
    t = etree.SubElement(lo, "title")
    ft = etree.SubElement(t, "formatted-text")
    run = etree.SubElement(ft, "run")
    run.text = title or name

    st = etree.SubElement(dash, "style")
    rule = etree.SubElement(st, "style-rule")
    rule.set("element", "story-point-caption")
    fmt = etree.SubElement(rule, "format")
    fmt.set("attr", "background-color")
    fmt.set("value", caption_bg)

    size = etree.SubElement(dash, "size")
    size.set("sizing-mode", "range")
    size.set("minwidth", str(S.SIZE_RANGE["minwidth"]))
    size.set("minheight", str(S.SIZE_RANGE["minheight"]))

    zones = etree.SubElement(dash, "zones")
    outer = etree.SubElement(zones, "zone")
    _box(outer, "2", "layout-basic", 0, 0, 100000, 100000)

    flow = etree.SubElement(outer, "zone")
    _box(flow, "1", "layout-flow", 0, 0, 100000, 100000)
    flow.set("param", "vert")
    flow.set("removable", "false")

    title_zone = etree.SubElement(flow, "zone")
    _box(title_zone, "3", "title", 0, 0, 100000, 4453)

    nav = etree.SubElement(flow, "zone")
    _box(nav, "4", "flipboard-nav", 0, 4453, 100000, 16869)
    nav.set("fixed-size", str(NAV_HEIGHT))
    nav.set("is-fixed", "true")
    nav.set("paired-zone-id", "5")
    nav.set("removable", "false")

    board = etree.SubElement(flow, "zone")
    _box(board, "5", "flipboard", 0, 21322, 100000, 78678)
    board.set("paired-zone-id", "4")
    board.set("removable", "false")

    flip = etree.SubElement(board, "flipboard")
    flip.set("active-id", "1")
    flip.set("nav-type", nav_type)
    flip.set("show-nav-arrows", "true" if show_arrows else "false")
    sp = etree.SubElement(flip, "story-points")
    for pid, sheet, caption in normalized:
        point = etree.SubElement(sp, "story-point")
        point.set("caption", caption)
        point.set("captured-sheet", sheet)
        point.set("id", pid)

    _register_window(editor, name)
    return name


def _box(zone, zid: str, type_v2: str, x: int, y: int, w: int, h: int) -> None:
    zone.set("h", str(h))
    zone.set("id", zid)
    zone.set("type-v2", type_v2)
    zone.set("w", str(w))
    zone.set("x", str(x))
    zone.set("y", str(y))


def _register_window(editor, name: str) -> None:
    """A window with class="dashboard"; without it Tableau shows no story tab."""
    windows = editor.root.find("windows")
    if windows is None:
        windows = etree.SubElement(editor.root, "windows")
    if any(w.get("name") == name for w in windows.findall("window")):
        return
    win = etree.SubElement(windows, "window")
    win.set("class", "dashboard")
    win.set("name", name)
    etree.SubElement(win, "viewpoints")
    active = etree.SubElement(win, "active")
    active.set("id", "-1")


def flipboard_zone(points: list[dict], *, nav_type: str = "caption",
                   show_arrows: bool = True, nav_height: int = NAV_HEIGHT) -> list[dict]:
    """A flipboard as PART of a regular dashboard: cards with a switcher, not a whole story."""
    if not points:
        raise ValueError("a flipboard needs at least one step")
    if nav_type not in NAV_TYPES:
        raise ValueError(f"nav_type={nav_type!r}; available: {', '.join(NAV_TYPES)}")
    steps = []
    for i, p in enumerate(points, 1):
        sheet = p.get("sheet") or ""
        caption = p.get("caption") or ""
        if not sheet or not caption:
            raise ValueError(f"step {i}: 'sheet' and 'caption' are required")
        steps.append({"id": str(i), "sheet": sheet, "caption": caption})
    return [
        {"type": "empty", "fixed_size": nav_height, "_flipboard_nav": True},
        {"type": "empty", "weight": 3, "_flipboard": True,
         "_steps": steps, "_nav_type": nav_type, "_arrows": show_arrows},
    ]


def pair_flipboard_zones(editor, dashboard_name: str, spec_zones: list[dict]) -> bool:
    """Turn placeholder zones into a real flipboard after add_dashboard."""
    nav_spec = next((z for z in spec_zones if z.get("_flipboard_nav")), None)
    board_spec = next((z for z in spec_zones if z.get("_flipboard")), None)
    if not nav_spec or not board_spec:
        return False

    dash = next((d for d in editor.root.iter("dashboard")
                 if d.get("name") == dashboard_name), None)
    if dash is None:
        raise ValueError(f"dashboard '{dashboard_name}' does not exist; call add_dashboard first")

    empties = [z for z in dash.iter("zone") if (z.get("type-v2") or "") == "empty"]
    if len(empties) < 2:
        raise ValueError("the layout has no two adjacent placeholder zones for the flipboard")
    nav, board = empties[0], empties[1]

    nav.set("type-v2", "flipboard-nav")
    nav.set("is-fixed", "true")
    nav.set("fixed-size", str(nav_spec.get("fixed_size", NAV_HEIGHT)))
    nav.set("removable", "false")
    nav.set("paired-zone-id", board.get("id"))

    board.set("type-v2", "flipboard")
    board.set("removable", "false")
    board.set("paired-zone-id", nav.get("id"))

    flip = etree.SubElement(board, "flipboard")
    flip.set("active-id", "1")
    flip.set("nav-type", board_spec["_nav_type"])
    flip.set("show-nav-arrows", "true" if board_spec["_arrows"] else "false")
    sp = etree.SubElement(flip, "story-points")
    for st in board_spec["_steps"]:
        point = etree.SubElement(sp, "story-point")
        point.set("caption", st["caption"])
        point.set("captured-sheet", st["sheet"])
        point.set("id", st["id"])
    return True

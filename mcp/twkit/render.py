"""Channel: a TEXT snapshot of a page — the layout described instead of photographed."""
from __future__ import annotations

import os
import re

from . import layoutmodel as LM

CONTAINERS = ("layout-basic", "layout-flow")


OVERLAP_EPS = 0.02


def _kind(z) -> str:
    """What kind of zone this is."""
    k = z.get("type-v2") or z.get("type") or ""
    if k:
        return k
    return "worksheet" if z.get("name") else "empty"


class RZone:
    """A zone in pixels with its children."""

    __slots__ = ("id", "kind", "name", "x", "y", "w", "h", "hidden", "flow",
                 "children", "floating", "title", "param", "style", "scaled")

    def __init__(self, z, cw: int, ch: int, floating: bool = False):
        self.id = z.get("id") or "?"
        self.kind = _kind(z)
        self.name = z.get("name") or ""
        self.x = int(z.get("x") or 0) / LM.CANVAS * cw
        self.y = int(z.get("y") or 0) / LM.CANVAS * ch
        self.w = int(z.get("w") or 0) / LM.CANVAS * cw
        self.h = int(z.get("h") or 0) / LM.CANVAS * ch
        self.hidden = (z.get("hidden-by-user") or "") == "true"
        self.flow = z.get("param") or "" if self.kind == "layout-flow" else ""
        self.param = z.get("param") or ""
        self.scaled = (z.get("is-scaled") or "") == "1"
        st = z.get("show-title") or ""
        self.title = st != "false" if self.kind == "worksheet" else st == "true"
        self.floating = floating
        st = z.find("zone-style")
        self.style = {f.get("attr"): f.get("value")
                      for f in (st.iter("format") if st is not None else ())}
        self.children: list[RZone] = []

    @property
    def is_container(self) -> bool:
        return self.kind in CONTAINERS

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def label(self) -> str:
        """Short recognizable zone label for reports."""
        if self.name:
            what = {"filter": "filter", "color": "color legend",
                    "size": "size legend", "shape": "shape legend"}.get(
                        self.kind, "sheet")
            return f"{what} '{self.name}'"
        return {"layout-flow": f"row {self.flow or '?'}",
                "layout-basic": "container",
                "paramctrl": "parameter",
                "text": "text",
                "bitmap": "image",
                "dashboard-object": "button",
                "empty": "empty",
                "blank": "empty"}.get(self.kind, self.kind)


ALONG_AXIS = ("Line", "Area", "Shape", "Circle")

NOT_A_SHEET = ("filter", "color", "size", "shape", "legend", "paramctrl", "text",
               "bitmap", "dashboard-object", "empty", "blank")


def is_swapped(ws) -> bool:
    """A swapped sheet: it filters on the `Swap <sheet>` calculation written by `edit.sheet_swap`."""
    for f in ws.iter("filter"):
        col = f.get("column") or ""
        if re.search(r"\[(?:none:)?Swap [^\]]*\]", col):
            return True
    return False


def is_sheet(z) -> bool:
    """A zone where Tableau draws a sheet."""
    return bool(z.name) and z.kind not in NOT_A_SHEET and z.kind not in CONTAINERS


def _build_tree(dash, cw: int, ch: int) -> list[RZone]:
    """The dashboard zone tree."""
    zs = dash.find("zones")
    if zs is None:
        return []

    def make(z, floating: bool) -> RZone:
        node = RZone(z, cw, ch, floating)
        for kid in z:
            if kid.tag == "zone":
                node.children.append(make(kid, False))
        return node

    tops = [z for z in zs if z.tag == "zone"]
    base = max(tops, key=lambda z: int(z.get("w") or 0) * int(z.get("h") or 0),
               default=None)
    return [make(z, z is not base) for z in tops]


def _overlap(a: RZone, b: RZone) -> float:
    dx = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    dy = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return dx * dy if dx > 0 and dy > 0 else 0.0


def _covered(zones: list[RZone]) -> float:
    """Canvas area covered by sheets and controls."""
    return sum(z.area for z in zones if not z.is_container and z.kind != "empty")


def _fits_rows(h: float, pt: float) -> int:
    """How many table rows fit the zone height."""
    row = max(11.0, pt * 96 / 72 * 1.55)
    return max(0, int((h - 24) // row))


def _sheet_facts(ws, zone: RZone, st: dict | None) -> dict:
    """What a sheet will draw in its zone: form, dimensions, whether it fits."""
    pt, family, _ = LM.sheet_font(ws) if ws is not None else (LM.DEFAULT_FONT_PT,
                                                              LM.DEFAULT_FAMILY, False)
    out = {"sheet": zone.name, "zone": f"{zone.w:.0f}×{zone.h:.0f}",
           "mark": LM.mark_class(ws) if ws is not None else "?",
           "size_pt": pt}
    if ws is not None:
        out["rows"] = len(LM.shelf_fields(ws, "rows"))
        out["columns"] = len(LM.shelf_fields(ws, "cols"))
    if not st:
        return out
    cats = st.get("categories")
    if cats is not None:
        out["categories"] = cats
        fits = _fits_rows(zone.h, pt)
        out["fits"] = fits
        if cats > fits:
            out["truncation"] = f"{cats} categories, {fits} fit"
    if st.get("max_label"):
        out["max_label"] = st["max_label"]
        need = LM.text_width("x" * int(st["max_label"]), pt, family)
        out["label_px_needed"] = round(need)
    if st.get("spread"):
        out["spread"] = st["spread"]
    return out


def describe(path: str, page: str = "", stats: dict | None = None,
             width: int = 0, height: int = 0) -> dict:
    """A text snapshot of a workbook: zone tree in pixels and what each zone draws."""
    from .lint import load

    if not os.path.exists(path):
        return {"verdict": f"file not found: {path}", "pages": []}

    book = load(path)
    root = book.root
    wsn = root.find("worksheets")
    sheets = {w.get("name"): w for w in (list(wsn) if wsn is not None else [])}
    by_sheet = {s["sheet"]: s for s in (stats or {}).get("sheets", [])}
    skipped = set((stats or {}).get("skipped") or [])

    placed: set[str] = set()
    for dash in root.iter("dashboard"):
        zs = dash.find("zones")
        for z in (zs.iter("zone") if zs is not None else ()):
            if z.get("name") and _kind(z) not in CONTAINERS:
                placed.add(z.get("name"))

    pages, findings = [], []
    for dash in root.iter("dashboard"):
        name = dash.get("name") or "?"
        if page and name != page:
            continue
        cw, chh, mode = LM.dashboard_size(dash)
        cw, chh = width or cw, height or chh
        tree = _build_tree(dash, cw, chh)
        flat = [z for t in tree for z in t.walk()]

        page_findings = _findings(name, tree, flat, cw, chh, sheets,
                                  by_sheet, skipped, dash)
        findings += page_findings

        sheet_zones = [z for z in flat if is_sheet(z)]
        area = float(cw * chh) or 1.0
        pages.append({
            "page": name,
            "canvas": f"{cw}×{chh}",
            "mode": (f"{mode}: size not set, measured at a typical "
                      f"{LM.DEFAULT_SIZE[0]}×{LM.DEFAULT_SIZE[1]}"
                      if mode in ("automatic", "none") and not (width or height)
                      else mode),
            "tree": _tree_lines(tree),
            "zone_count": len(flat),
            "sheet_count": len(sheet_zones),
            "control_count": sum(1 for z in flat if z.kind in ("filter", "paramctrl")),
            "hidden_zones": sum(1 for z in flat if z.hidden),
            "area": {
                "sheets": round(sum(z.area for z in sheet_zones) / area, 2),
                "controls": round(sum(z.area for z in flat
                                      if z.kind in ("filter", "paramctrl")) / area, 2),
                "free": round(max(0.0, 1 - _covered(flat) / area), 2),
            },
            "decor": _decor(flat),
            "sheet_details": [
                _sheet_facts(sheets.get(z.name), z, by_sheet.get(z.name))
                for z in sheet_zones],
            "findings": page_findings,
        })

    off = [n for n in sheets if n not in placed]
    report = {
        "book": os.path.basename(path),
        "page_count": len(pages),
        "pages": pages,
        "findings": findings,
        "sheets_off_pages": off,
        "data": ("present" if by_sheet else
                   "no: geometry only (categories and labels not checked)"),
    }
    report["image"] = ("the workbook has no pages; nothing to look at" if not pages
                      else _verdict(findings, skipped, placed, bool(by_sheet)))
    report["verdict"] = ("no layout questions" if not findings else
                         f"findings: {len(findings)}")
    return report


def _toggles(dash) -> dict:
    """Hide/show buttons of a page: button id -> ids of the zones it controls."""
    out: dict[str, list[str]] = {}
    for z in dash.iter("zone"):
        act = z.find("button/toggle-action")
        if act is None:
            continue
        text = act.text or ""
        ids = re.findall(r"zone-ids=\[([^\]]*)\]", text)
        targets = [t.strip() for part in ids for t in part.split(",") if t.strip()]
        out[z.get("id") or "?"] = targets
    return out


def _decor(flat: list[RZone]) -> list[str]:
    """Page decoration: only the differences, not the full list."""
    out = []
    fills: dict[str, list[str]] = {}
    borders: list[str] = []
    for z in flat:
        bg = z.style.get("background-color")
        if bg and bg.lower() not in ("none", "#00000000"):
            fills.setdefault(bg, []).append(z.id)
        if (z.style.get("border-style") or "none") != "none":
            borders.append(z.id)
    for color, ids in sorted(fills.items()):
        out.append(f"fill {color}: zones {', '.join(ids[:8])}")
    if borders:
        out.append(f"border on zones: {', '.join(borders[:8])}")
    return out


def _findings(page: str, tree: list[RZone], flat: list[RZone], cw: int, ch: int,
              sheets: dict, by_sheet: dict, skipped: set, dash=None) -> list[dict]:
    out: list[dict] = []
    by_id = {z.id: z for z in flat}

    for parent in flat:
        if not parent.is_container:
            continue
        stacks: dict[tuple, list[RZone]] = {}
        for k in parent.children:
            if k.area <= 0:
                continue
            stacks.setdefault((round(k.x), round(k.y), round(k.w), round(k.h)),
                              []).append(k)
        for group in stacks.values():
            named = [z for z in group if z.name]
            if len(group) < 2 or len(named) < 2:
                continue
            out.append({
                "code": "V1", "level": "info", "page": page,
                "what": f"{len(named)} zones in one place "
                       f"({', '.join(z.label() for z in named[:6])}) — "
                       f"sheet swap; one is visible at a time",
                "fix": "not a defect; check the states with screenshot_param_states"})

    toggles = _toggles(dash) if dash is not None else {}
    controlled = {t for ids in toggles.values() for t in ids}
    hidden = [z for z in flat if z.hidden]
    if hidden:
        by_button = [z for z in hidden
                     if ({z.id} | {p.id for p in flat if z in list(p.walk())[1:]})
                     & controlled]
        named = sorted({z.label() for z in hidden if z.name})
        out.append({
            "code": "V4", "level": "info", "page": page,
            "what": f"hidden zones {len(hidden)} (button-controlled {len(by_button)})"
                   + (": " + ", ".join(named[:6]) if named else ""),
            "fix": "not a defect, but a screenshot will NOT show these zones"})

    for bid, targets in toggles.items():
        dead = [t for t in targets if t not in by_id]
        if dead:
            out.append({
                "code": "V7", "level": "error", "page": page,
                "what": f"button [{bid}] controls zones {', '.join(dead)} "
                       f"that are not on the page; clicking it does nothing",
                "fix": "point the button zone-ids at real zone ids"})

    seen_v3: set[str] = set()
    parent_of = {k.id: p for p in flat if p.is_container for k in p.children}
    swapped_note: set[str] = set()
    for z in flat:
        st = by_sheet.get(z.name)
        if not st or not is_sheet(z) or z.hidden or z.name in seen_v3:
            continue
        ws = sheets.get(z.name)
        if ws is not None and LM.mark_class(ws) in ALONG_AXIS:
            continue
        pt, family, _ = LM.sheet_font(ws) if ws is not None else (
            LM.DEFAULT_FONT_PT, LM.DEFAULT_FAMILY, False)
        h = z.h
        parent = parent_of.get(z.id)
        if ws is not None and is_swapped(ws) and parent is not None and parent.flow == "vert":
            h = parent.h
            swapped_note.add(parent.id)
        cats, fits = st.get("categories"), _fits_rows(h, pt)
        if cats and fits and cats > fits * 2:
            seen_v3.add(z.name)
            out.append({
                "code": "V3", "level": "warn", "page": page,
                "what": f"sheet '{z.name}': {cats} categories, {fits} fit in {h:.0f} px; "
                       f"less than half is visible"
                       + (" (swap: container height)" if h != z.h else ""),
                "fix": "limit top-N, enlarge the zone or change the dimension"})
    for pid in sorted(swapped_note):
        p = by_id[pid]
        names = [k.name for k in p.children if k.name]
        out.append({
            "code": "V8", "level": "info", "page": page,
            "what": f"sheet swap in container [{pid}] {p.w:.0f}x{p.h:.0f}: "
                   f"{', '.join(names[:8])}; one is visible, by parameter value",
            "fix": "not a defect; states via screenshot_param_states"})

    unchecked = sorted({z.name for z in flat if z.name in skipped})
    if unchecked:
        out.append({
            "code": "V5", "level": "warn", "page": page,
            "what": "skipped by the dry run (LOD/table calculation): "
                   + ", ".join(unchecked),
            "fix": "the model is silent on these sheets; look at a screenshot"})
    return out


def _verdict(findings: list[dict], skipped: set, placed: set, has_data: bool) -> str:
    """Whether a screenshot is needed."""
    hard = [f for f in findings if f["level"] == "error"]
    soft = [f for f in findings if f["level"] == "warn"]
    blind = sorted(skipped & placed)
    if hard:
        pg = sorted({f["page"] for f in hard})
        return (f"LOOK: {', '.join(pg)}: {hard[0]['what'][:90]}")
    if blind:
        return (f"look at the page with sheets {', '.join(blind[:3])}: the model "
                f"cannot compute their view (LOD/table calculations)")
    if soft:
        pg = sorted({f["page"] for f in soft})
        return f"optional: {', '.join(pg)}: {soft[0]['what'][:90]}"
    if not has_data:
        return ("no LAYOUT questions; data not checked, so categories and "
                "labels are unknown")
    return "no layout questions; no screenshot needed"


def _tree_lines(tree: list[RZone], depth: int = 0) -> list[str]:
    """Zone tree as lines: indent = nesting, sizes in pixels."""
    lines = []
    for z in sorted(tree, key=lambda z: (round(z.y), round(z.x))):
        mark = " HIDDEN" if z.hidden else ""
        mark += " floating" if z.floating else ""
        lines.append(f"{'  ' * depth}[{z.id}] {z.label()} {z.w:.0f}×{z.h:.0f} "
                     f"@{z.x:.0f},{z.y:.0f}{mark}")
        ctrl = [k for k in z.children if k.kind in ("filter", "paramctrl")]
        if len(ctrl) >= 3 and len(ctrl) == len(z.children):
            w = ", ".join(f"{c.w:.0f}×{c.h:.0f}" for c in ctrl[:1])
            lines.append(f"{'  ' * (depth + 1)}{len(ctrl)} controls of {w} "
                         f"(id {', '.join(c.id for c in ctrl)})")
            continue
        lines += _tree_lines(z.children, depth + 1)
    return lines


def format_report(r: dict) -> str:
    if not r.get("pages"):
        return f"Text snapshot: {r.get('verdict', 'no pages')}"
    lines = [f"Text snapshot - {r['book']}: {r['verdict']}",
             f"  data: {r['data']}"]
    for p in r["pages"]:
        a = p["area"]
        lines.append(f"\nPage '{p['page']}' - canvas {p['canvas']} ({p['mode']})"
                     f" - zones {p['zone_count']}, sheets {p['sheet_count']}, controls "
                     f"{p['control_count']}"
                     + (f", HIDDEN {p['hidden_zones']}" if p["hidden_zones"] else ""))
        lines.append(f"  area: sheets {a['sheets']:.0%} - controls "
                     f"{a['controls']:.0%} - free {a['free']:.0%}")
        lines += ["  " + t for t in p["tree"]]
        for d in p.get("decor") or []:
            lines.append("  decor: " + d)
        for s in p["sheet_details"]:
            bits = [f"{s['sheet']}: zone {s['zone']}, {s['mark']}"]
            if s.get("categories") is not None:
                bits.append(f"categories {s['categories']} (fit {s['fits']})")
            if s.get("max_label"):
                bits.append(f"label up to {s['max_label']} chars"
                            f" ~{s['label_px_needed']} px")
            if s.get("spread"):
                bits.append(f"spread x{s['spread']:,.0f}")
            lines.append("  · " + ", ".join(bits))
    for f in r["findings"]:
        lines.append(f"  {f['level'].upper():5s} {f['code']} [{f['page']}] {f['what']}")
    if r.get("sheets_off_pages"):
        lines.append(f"  sheets not on any page (nobody sees them): "
                     f"{', '.join(r['sheets_off_pages'][:8])}")
    lines.append(f"  SCREENSHOT: {r['image']}")
    return "\n".join(lines)


def _flat_map(path: str, page: str = "") -> dict:
    """Page -> {zone id: zone}."""
    from .lint import load

    root = load(path).root
    out: dict[str, dict] = {}
    for dash in root.iter("dashboard"):
        name = dash.get("name") or "?"
        if page and name != page:
            continue
        cw, ch, _ = LM.dashboard_size(dash)
        tree = _build_tree(dash, cw, ch)
        out[name] = {z.id: z for t in tree for z in t.walk()}
    return out


def diff(before: str, after: str, page: str = "", moved_px: float = 4.0) -> dict:
    """How the layout of `after` differs from `before`."""
    a, b = _flat_map(before, page), _flat_map(after, page)
    out: list[str] = []
    for name in sorted(set(a) | set(b)):
        if name not in a:
            out.append(f"page '{name}' ADDED ({len(b[name])} zones)")
            continue
        if name not in b:
            out.append(f"page '{name}' REMOVED")
            continue
        was, now = a[name], b[name]
        for zid in sorted(set(was) - set(now)):
            z = was[zid]
            out.append(f"'{name}': removed [{zid}] {z.label()} {z.w:.0f}x{z.h:.0f}")
        for zid in sorted(set(now) - set(was)):
            z = now[zid]
            out.append(f"'{name}': added [{zid}] {z.label()} {z.w:.0f}x{z.h:.0f} "
                       f"@{z.x:.0f},{z.y:.0f}")
        for zid in sorted(set(was) & set(now)):
            p, q = was[zid], now[zid]
            bits = []
            if abs(p.w - q.w) >= moved_px or abs(p.h - q.h) >= moved_px:
                bits.append(f"size {p.w:.0f}x{p.h:.0f} -> {q.w:.0f}x{q.h:.0f}")
            if abs(p.x - q.x) >= moved_px or abs(p.y - q.y) >= moved_px:
                bits.append(f"position @{p.x:.0f},{p.y:.0f} -> @{q.x:.0f},{q.y:.0f}")
            if p.hidden != q.hidden:
                bits.append("HIDDEN" if q.hidden else "shown")
            if p.name != q.name:
                bits.append(f"sheet '{p.name}' -> '{q.name}'")
            if p.style != q.style:
                changed = sorted(k for k in set(p.style) | set(q.style)
                                 if p.style.get(k) != q.style.get(k))
                bits.append("decor: " + ", ".join(
                    f"{k} {p.style.get(k, '—')}→{q.style.get(k, '—')}"
                    for k in changed[:3]))
            if bits:
                out.append(f"'{name}': [{zid}] {q.label()} — " + "; ".join(bits))
    return {"before": os.path.basename(before), "after": os.path.basename(after),
            "change_count": len(out), "what": out,
            "verdict": ("layout unchanged" if not out
                        else f"layout changes: {len(out)}")}


def format_diff(d: dict) -> str:
    lines = [f"Layout {d['before']} -> {d['after']}: {d['verdict']}"]
    lines += ["  " + t for t in d["what"][:60]]
    if len(d["what"]) > 60:
        lines.append(f"  ...and {len(d['what']) - 60} more")
    return "\n".join(lines)


def has_local_data(path: str, db: str = "", table: str = "") -> bool:
    """Whether statistics can be collected without network access."""
    if db and table:
        return True
    if not path.lower().endswith(".twbx"):
        return False
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.lower().endswith((".hyper", ".csv")) for n in z.namelist())
    except Exception:
        return False


def look(path: str, page: str = "", db: str = "", table: str = "",
         out_dir: str = "") -> dict:
    """Show a page through the cheapest channel that can answer."""
    from . import preview as PV

    stats = None
    if has_local_data(path, db, table):
        try:
            from .dryrun import visual_stats
            stats = visual_stats(path, db, table)
        except Exception:
            stats = None

    desc = describe(path, page, stats)
    th = PV.thumbs_state(path)
    out = {"book": os.path.basename(path), "page": page or "all",
           "previews": th["verdict"], "layout": desc["verdict"],
           "image": desc["image"], "images": []}
    if th.get("fresh") is not False:
        try:
            import tempfile
            thumbs = PV.extract_thumbnails(
                path, out_dir or os.path.join(tempfile.gettempdir(),
                                              "twkit_preview"))
        except Exception:
            thumbs = []
        want = [t for t in thumbs if not page or t.name == page]
        out["images"] = [t.path for t in (want or thumbs)]
        if out["images"]:
            out["image"] = (
                "not needed: the workbook holds a Tableau render; open the PNG "
                "with Read" if th.get("fresh") else
                "look at the embedded preview, REMEMBERING its freshness is unknown: "
                "compare with the zone tree below; if they differ, take a screenshot")
    out["report"] = format_report(desc)
    return out


def format_look(r: dict) -> str:
    lines = [f"Page '{r['page']}' - {r['book']}",
             f"  previews: {r['previews']}"]
    for p in r["images"]:
        lines.append(f"  · {p}")
    lines.append(r["report"])
    lines.append(f"  RESULT: {r['image']}")
    return "\n".join(lines)

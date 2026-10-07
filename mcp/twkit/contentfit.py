"""Sizes from content: text table columns, header bands, title room, and layout rows around them.

Pure functions: text and numbers in, pixels out. Callers apply the result with
`edit.set_column_width` / `edit.set_header_height`; the natural widths and header line counts come
from the frame (`stylecritic.content_needs`).

Layout functions work on the layout dicts of `dash.add` (`type`, `children`, `direction`, `fixed_size`)
annotated by the caller: `_h` content height, `_w` content width of a table, `_chart` a chart or a
container of charts only, `_lost` an empty zone that replaced a sheet without data.
"""
from __future__ import annotations

import re

from . import layoutmodel as LM

INVISIBLE = re.compile("[​‌⁠]")
AUTO_HEAD_PX = 90
HEAD_LINE_PX = 15.3
THREE_LINE_HEAD_PX = 52
TABLEAU_TAILS = [(r"(?i)\s+along\s+Table\b.*$", "")]


def tidy_caption(label: str, tails: list = ()) -> str:
    """Column header for a reader: Tableau's table calc tails and calc-name debris dropped.

    `tails` are the caller's own `(pattern, replacement)` pairs, applied after Tableau's."""
    t = str(label)
    for a, b in TABLEAU_TAILS + list(tails):
        t = re.sub(a, b, t)
    t = re.sub(r"(?<=[A-Za-z])_(?=[A-Za-z])", " ", t)
    t = re.sub(r"(?i)(?<=[a-z]{4})(?<!week)(?<!tier)(?<!level)(?<!month)\s+2$", "", t)
    t = " ".join(t.split())
    t = re.sub(r"\s*·\s*(?=·)", "", t).strip(" ·")
    return t[:1].upper() + t[1:] if t else str(label)


def two_line_px(text: str, pt: float = 10) -> float:
    """Width a header or title needs to fit in two lines, split at the best word gap."""
    w = INVISIBLE.sub("", text or "").split()
    cut = [max(LM.text_width(" ".join(w[:i]), pt), LM.text_width(" ".join(w[i:]), pt))
           for i in range(1, len(w))] or [LM.text_width(" ".join(w), pt)]
    return min(cut) * 1.1 + 12


def compact_mask(mask: str, magnitude: float) -> str:
    """A dense table shows thousands («€ 2,070K», not «€ 2,070,007») once values reach 100,000."""
    if magnitude < 1e5 or "%" in mask or re.search(r",K|,,", mask):
        return mask
    m = re.match(r'^[a-z]?("[^"]*")?', mask)
    pre = m.group(1) or ""
    return f"{'c' if pre else 'n'}{pre}#,##0,K;{pre}-#,##0,K"


def label_column_px(values, header: str, free: int | None = None, wide_from: int = 8) -> int | None:
    """Width of a dimension label column, or None to keep Tableau's automatic width.

    Short values: only a header that needs more than Tableau's ~90 px. Long values: the longest
    value up to 220 px, more of the free room when clipping would merge different labels, a little
    less (down to 180 px) when that keeps the row from scrolling and labels stay distinct.
    Distinct means after Tableau's truncation with the real font (`dryrun.truncate_to_px`)."""
    from . import dryrun as DR
    vals = set(values)

    def clash(px: float) -> bool:
        return bool(DR.indistinct_after_truncation(sorted(vals), px - DR.CELL_PADDING_PX, 10,
                                                   LM.DEFAULT_FAMILY))

    longest = max((len(v) for v in vals), default=0)
    head = two_line_px(header)
    val = max((LM.text_width(v, 10) for v in vals), default=0.0) * 1.1 + 14
    if longest <= wide_from:
        return int(max(head, val)) if head > AUTO_HEAD_PX else None
    cap = 220
    if free is not None:
        cap = free if 180 <= free < cap and not clash(free) else \
            max(cap, free if clash(cap) else min(400, free))
    return int(min(cap, max(val, head)))


def measure_cols_px(headers: list, values: list) -> float:
    """Width the measure columns of a table take: one width for all, the widest value or a
    header in two lines up to Tableau's automatic header width."""
    if not headers:
        return 85.0
    val = max((LM.text_width(t, 10, bold=True) for t in values), default=0.0) * 1.1 + 14
    head = min(float(AUTO_HEAD_PX), max(two_line_px(h) for h in headers))
    return len(headers) * max(50.0, val, head)


def measure_names_rows_px(captions: list) -> int | None:
    """Width of the Measure Names column when measures run down the rows, or None if auto fits."""
    caps = [INVISIBLE.sub("", c or "") for c in captions]
    if not caps:
        return None
    px = max(LM.text_width(t, 10) for t in caps) * 1.1 + 16
    return int(min(px, 320)) if px > AUTO_HEAD_PX else None


def measure_cell_px(headers: list, values: list, zone_w: float, used: float) -> tuple[int, int]:
    """Measure columns wide enough for every header in two lines, within the zone's room.

    Returns `(cell width or 0, header band height or 0)`: the band goes to three lines when two
    do not fit even at the widest the zone allows (corpus: header height 49-52 on Measure Names)."""
    heads = [two_line_px(h) for h in headers]
    if not heads or max(heads) <= AUTO_HEAD_PX:
        return 0, 0
    vals = [LM.text_width(t, 10, bold=True) * 1.1 + 12 for t in values]
    room = (zone_w - used - 16) / len(heads)
    w = max(max(vals, default=0), min(max(heads), room))
    return (int(w) if w > AUTO_HEAD_PX else 0,
            THREE_LINE_HEAD_PX if max(heads) > max(w, AUTO_HEAD_PX) + 2 else 0)


def header_px(lines: int) -> int:
    """Header band for the lines the longest header wraps into (3-4 lines; 2 is Tableau's own)."""
    return int(4 + HEAD_LINE_PX * min(lines, 4)) if 3 <= lines < 99 else 0


def title_room_px(title: str, cols: list, header: str | None = None) -> int:
    """Width of a narrow table's first column so its title wraps into two lines, or 0.

    In standard fit Tableau wraps a sheet title at the table width; `cols` are the natural
    column widths, `header` the first column's header (never narrower than it in two lines)."""
    gap = two_line_px(title, 15) - (sum(cols) + 12)
    if gap <= 6:
        return 0
    floor = [two_line_px(header)] if header else []
    return int(max(cols[0] + gap, *floor, AUTO_HEAD_PX))


def equal_row_heights(zones: dict, heights: dict) -> dict:
    """Header heights for tables side by side: the tallest in a row, or their rows drift apart.

    `zones` maps a sheet to its zone (`y`, `h`), `heights` to the header height it needs."""
    rows: dict = {}
    for name, z in zones.items():
        rows.setdefault((round(z["y"] / 4), round(z["h"] / 4)), []).append(name)
    out = {}
    for group in rows.values():
        px = max((heights.get(n, 0) for n in group), default=0)
        if px:
            out.update((n, px) for n in group)
    return out


def equal_row_pitch(zones: dict, heights: dict, rows: dict) -> dict:
    """Row heights for tables that start level and hold as many rows: the tallest, or rows drift.

    Zone heights may differ (the critic's R1 compares the same tables); `rows` maps a sheet to its
    row count, `heights` to its row height (0 when standard)."""
    groups: list = []
    for name in sorted((n for n in zones if n in heights), key=lambda n: zones[n]["y"]):
        g = next((g for g in groups if rows.get(g[0]) == rows.get(name)
                  and abs(zones[g[0]]["y"] - zones[name]["y"]) <= 4), None)
        g.append(name) if g is not None else groups.append([name])
    out = {}
    for group in groups:
        px = max(heights[n] for n in group)
        if px and len(group) > 1:
            out.update((n, px) for n in group)
    return out


def elastic(k: dict) -> bool:
    """A chart (or a container of charts only) can give up height; a table cannot."""
    return bool(k.get("_chart")) or (k.get("type") == "worksheet" and not k.get("_w"))


def min_h(k: dict) -> float:
    if k.get("type") == "container":
        hs = [min_h(c) for c in k.get("children") or [] if c.get("type") != "empty"]
        return (sum(hs) if k.get("direction") == "vertical" else max(hs)) if hs else 0.0
    if k.get("type") in ("text", "paramctrl"):
        return k.get("fixed_size") or k.get("_h") or 30
    return min(k.get("_h") or 160, 160)


def squeeze(k: dict, target: float) -> None:
    """Fit an elastic node into `target` px: charts in a stack shrink proportionally."""
    k["_h"] = target
    if k.get("type") != "container":
        return
    kids = k.get("children") or []
    if k.get("direction") == "horizontal":
        for c in kids:
            squeeze(c, target)
        return
    fixed = sum(c.get("fixed_size", 0) for c in kids if not elastic(c))
    el = [c for c in kids if elastic(c)]
    cur = sum(c.get("fixed_size") or c.get("_h") or 0 for c in el)
    room = target - fixed
    if not el or cur <= 0 or room >= cur:
        return
    for c in el:
        h = max(min_h(c), (c.get("fixed_size") or c.get("_h") or 0) * room / cur)
        if "fixed_size" in c:
            c["fixed_size"] = int(h)
        squeeze(c, h)


def squeeze_row(row: list) -> float | None:
    """Height of a horizontal row when tables keep their content height and charts give theirs
    up, or None when that saves under 40 px. Squeezes the charts in place."""
    solid = [k for k in row if k.get("type") not in ("empty", "text", "paramctrl")]
    hs = [k.get("_h", 0) for k in solid]
    content = [k for k in solid if not elastic(k)]
    el = [k for k in row if elastic(k)]
    if not (content and el and hs):
        return None
    target = max(max(k.get("_h", 0) for k in content), max(min_h(k) for k in el))
    if target >= max(hs) - 40:
        return None
    for k in el:
        squeeze(k, target)
    return target


def drop_orphan_heads(kids: list) -> None:
    """A section title whose sheets all came out empty goes with them (`None` marks a drop)."""
    idx = [i for i, k in enumerate(kids) if k]
    for j, i in enumerate(idx):
        if kids[i] is None or kids[i].get("type") != "text":
            continue
        body = []
        for i2 in idx[j + 1:]:
            if kids[i2] is not None and kids[i2].get("type") == "text":
                break
            body.append(i2)
        if body and all(kids[b] is not None and kids[b].get("type") == "empty" for b in body) \
                and any(kids[b].get("_lost") for b in body):
            for b in [i] + body:
                kids[b] = None


def row_overflow(kids: list, row_w: float) -> bool:
    """A table in a horizontal row needs 40+ px more than the width the row gives it."""
    real = [k for k in kids if k]
    if len(real) < 2:
        return False
    rest = row_w - sum(k.get("fixed_size", 0) for k in real)
    return any((k.get("_w") or 0) > (k.get("fixed_size") or rest) + 40 for k in real)


def balance(kids: list, widths: dict) -> None:
    """A table narrower than its columns takes width from a wide chart in the same row.

    `widths` maps a kid index to its width and is updated in place; a chart keeps 340 px."""
    for i, w in list(widths.items()):
        need = kids[i].get("_w") or 0
        if need <= w:
            continue
        for j in sorted(widths, key=lambda j: -widths[j]):
            if j == i or not elastic(kids[j]) or widths[j] <= 360:
                continue
            take = min(need - widths[i], widths[j] - 340)
            if take > 0:
                widths[i] += take
                widths[j] -= take
            if widths[i] >= need:
                break

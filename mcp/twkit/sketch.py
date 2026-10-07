"""Channel 2: sketch a sheet from REAL data — see every sheet without opening the book."""
from __future__ import annotations

import os
import re

INK = (51, 51, 51)
MUTED = (150, 150, 150)
GRID = (225, 225, 225)
BAR = (75, 120, 168)
SURFACE = (252, 252, 251)
STAMP = (200, 90, 70)

PAD = 8
DEFAULT_SIZE = (420, 260)


def _font(pt: int = 9, bold: bool = False):
    from PIL import ImageFont

    from .layoutmodel import _font_file
    path = _font_file("Arial", bold)
    px = max(7, int(round(pt * 96 / 72)))
    try:
        return ImageFont.truetype(path, px) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _tlen(draw, text, font) -> float:
    """Label width."""
    return draw.textlength(" ".join(str(text).split()), font=font)


def _fit(draw, text: str, width: float, font) -> str:
    """Truncate a label to a width with an ellipsis, as Tableau does."""
    text = " ".join(str(text).split())
    if _tlen(draw, text, font) <= width:
        return text
    ell = draw.textlength("…", font=font)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _tlen(draw, text[:mid], font) + ell <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


_CONTINUOUS_AXIS = re.compile(r"\[(?:tdy|tmn|tqr|tyr):[^\]]+:qk\]")


def continuous_axis(ws) -> bool:
    """Whether the sheet has a continuous axis (truncated date)."""
    if ws is None:
        return False
    for tag in ("rows", "cols"):
        for e in ws.iter(tag):
            if _CONTINUOUS_AXIS.search(e.text or ""):
                return True
    return False


def card_lines(ws) -> list:
    """Lines of a `customized-label`: [(text, size, bold, is_field), ...] per line."""
    if ws is None:
        return []
    lab = ws.find(".//pane/customized-label/formatted-text")
    if lab is None:
        return []
    seg_lines: list[list] = [[]]
    for run in lab.findall("run"):
        size = float(run.get("fontsize") or 9)
        bold = (run.get("bold") or "") == "true"
        text = (run.text or "").replace("\u00c6", "")
        for i, part in enumerate(text.split("\n")):
            if i:
                seg_lines.append([])
            if part:
                seg_lines[-1].append((part, size, bold))
    lines = []
    for segs in seg_lines:
        full = "".join(t for t, _, _ in segs)
        if not full:
            continue
        owner = []
        for t, sz, b in segs:
            owner += [(sz, b)] * len(t)
        ln, pos = [], 0
        for tok in re.split(r"(<\[[^>]*\]>)", full):
            if not tok:
                continue
            fmt = owner[pos:pos + len(tok)] or [(9.0, False)]
            pos += len(tok)
            is_field = tok.startswith("<[") and tok.endswith("]>")
            ln.append((tok, max(f[0] for f in fmt), any(f[1] for f in fmt), is_field))
        lines.append(ln)
    return [ln for ln in lines if ln]


def _draw_card(d, lines: list, values: list, x0, y0, w, h) -> list[str]:
    """Card: label runs with their sizes, fields in order from the dry-run row."""
    obs: list[str] = []
    y, k, widest = y0, 0, 0.0
    for ln in lines:
        x, line_h = x0, 0
        for text, size, bold, is_field in ln:
            if is_field:
                text = _cell(values[k]) if k < len(values) else "…"
                k += 1
            font = _font(int(round(size * 1.33)), bold)
            d.text((x, y), text, font=font, fill=INK if bold else MUTED)
            x += _tlen(d, text, font)
            line_h = max(line_h, int(size * 1.33) + 4)
        widest = max(widest, x - x0)
        y += line_h
    used = y - y0
    obs.append(f"card: {len(lines)} lines, text ~{used:.0f} px high, "
               f"~{widest:.0f} px wide")
    if used > h - y0 - 16:
        obs.append(f"DOES NOT FIT in height: {used:.0f} px in a {h - y0:.0f} px zone")
    if widest > w - 2 * PAD:
        obs.append(f"label wider than the zone: {widest:.0f} px of {w - 2 * PAD:.0f}")
    return obs


def sketch_sheet(rows: list, out_path: str, *, title: str = "",
                 kind: str = "bar", size: tuple[int, int] = DEFAULT_SIZE,
                 note: str = "", synthetic: bool = False,
                 label_width: float = 0.0, continuous: bool = False,
                 ndims: int = 0, card: list | None = None, ncols_dims: int = 0) -> dict:
    """Draw the sketch of one sheet."""
    from PIL import Image, ImageDraw

    w, h = max(160, int(size[0])), max(120, int(size[1]))
    img = Image.new("RGB", (w, h), SURFACE)
    d = ImageDraw.Draw(img)
    f_lbl, f_ttl = _font(9), _font(9, bold=True)

    top = PAD
    if title:
        d.text((PAD, top), _fit(d, title, w - 2 * PAD, f_ttl), font=f_ttl, fill=INK)
        top += 15

    observations: list[str] = []
    pairs = []
    for r in rows:
        if not r:
            continue
        label = str(r[0]) if len(r) > 1 else ""
        value = _num(r[-1])
        pairs.append((label, value))

    if not pairs:
        d.text((PAD, top), "no data", font=f_lbl, fill=MUTED)
        observations.append("the sheet is empty; nothing to draw")
    elif kind == "card" and card:
        first = next((r for r in rows if r), [])
        observations += _draw_card(d, card, list(first[ncols_dims:]), PAD, top, w, h)
    elif kind == "matrix":
        observations += _draw_matrix(d, rows, PAD, top, w, h, f_lbl,
                                     ndims=max(2, ndims), label_width=label_width)
    elif kind == "table":
        observations += _draw_table(d, rows, PAD, top, w, h, f_lbl,
                                   label_width=label_width)
    else:
        drawn = _draw_bars(d, pairs, PAD, top, w, h, f_lbl, label_width=label_width)
        if continuous:
            drawn = [o for o in drawn
                     if not o.startswith(("categories ", "labels clipped"))]
        observations += drawn
        if synthetic:
            observations.append("the sketch shows ROW COUNTS, not the metric "
                                "(the measure comes through Measure Names); "
                                "do not judge magnitudes from this sketch")

    stamp = "SKETCH - not Tableau"
    sw = d.textlength(stamp, font=f_lbl)
    d.text((w - sw - PAD, h - 14), stamp, font=f_lbl, fill=STAMP)
    if note:
        d.text((PAD, h - 14), _fit(d, note, w - sw - 3 * PAD, f_lbl), font=f_lbl, fill=MUTED)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    img.save(out_path)
    return {"file": out_path, "size": f"{w}x{h}", "observations": observations}


def _is_number(v) -> bool:
    """A drawable value: not None, NaN or infinity."""
    if v is None or isinstance(v, bool):
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))


def _draw_bars(d, pairs, x0, y0, w, h, font, label_width: float = 0.0) -> list[str]:
    """Horizontal bars: label on the left, bar on the right."""
    obs = []
    vals = [float(v) for _, v in pairs if _is_number(v)]
    if not vals:
        d.text((x0, y0), "values are not numeric", font=font, fill=MUTED)
        return ["the measure did not parse as a number; the form may be wrong"]

    lab_w = (min(label_width, w - 40) if label_width > 0
             else min(w * 0.42, max((_tlen(d, l, font) for l, _ in pairs),
                                    default=0) + 6))
    plot_x = x0 + lab_w + 6
    plot_w = w - plot_x - x0
    row_h = 14
    fits = max(1, int((h - y0 - 22) // row_h))
    shown = pairs[:fits]
    if len(pairs) > fits:
        obs.append(f"categories {len(pairs)}, {fits} fit; the rest scroll")

    from .dryrun import SPREAD_LIMIT
    hi = max(abs(v) for v in vals) or 1.0
    lo = min(abs(v) for v in vals if v) if any(vals) else 0.0
    if lo and hi / lo > SPREAD_LIMIT:
        obs.append(f"spread x{hi / lo:,.0f}: small bars merge with the axis")

    cut = 0
    for i, (label, value) in enumerate(shown):
        y = y0 + i * row_h
        short = _fit(d, str(label), lab_w - 4, font)
        if short != str(label):
            cut += 1
        d.text((x0, y), short, font=font, fill=INK)
        d.line([(plot_x, y + row_h - 2), (plot_x + plot_w, y + row_h - 2)], fill=GRID)
        if _is_number(value) and float(value):
            bar = max(1, int(plot_w * abs(float(value)) / hi))
            d.rectangle([plot_x, y + 2, plot_x + bar, y + row_h - 4], fill=BAR)
    if cut:
        obs.append(f"labels clipped: {cut} of {len(shown)}")
        seen, clash = {}, 0
        for label, _ in shown:
            s = _fit(d, str(label), lab_w - 4, font)
            if s in seen and seen[s] != label:
                clash += 1
            seen[s] = label
        if clash:
            obs.append(f"{clash} labels are INDISTINGUISHABLE after clipping; rows look identical")
    return obs


def _cell(value) -> str:
    """A number as Tableau will display it, not as SQL returned it."""
    if value is None:
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f != f:
        return ""
    a = abs(f)
    if a >= 1000:
        text = f"{f:,.0f}"
    elif a >= 1:
        text = f"{f:,.2f}".rstrip("0").rstrip(".")
    elif a == 0:
        text = "0"
    else:
        text = f"{f:.4f}".rstrip("0").rstrip(".")
    return text.replace(",", " ")


def _draw_table(d, rows, x0, y0, w, h, font, label_width: float = 0.0) -> list[str]:
    """Table: how many columns actually fit the zone width."""
    obs = []
    ncols = max(len(r) for r in rows)
    lab_w = min(label_width, w - 40) if label_width > 0 else 0.0
    col_w = ((w - 2 * x0 - lab_w) / max(1, ncols - 1) if lab_w and ncols > 1
             else (w - 2 * x0) / max(1, ncols))
    row_h = 13
    fits_rows = max(1, int((h - y0 - 22) // row_h))
    if col_w < 40:
        obs.append(f"{ncols} columns of {col_w:.0f} px: narrower than readable")
    for i, r in enumerate(rows[:fits_rows]):
        y = y0 + i * row_h
        for j, cell in enumerate(r[:ncols]):
            cw = lab_w if (lab_w and j == 0) else col_w
            cx = x0 + (0 if j == 0 else (lab_w or col_w) + (j - 1) * col_w
                       if lab_w else j * col_w)
            d.text((cx, y), _fit(d, _cell(cell), cw - 4, font), font=font, fill=INK)
        d.line([(x0, y + row_h - 1), (w - x0, y + row_h - 1)], fill=GRID)
    if len(rows) > fits_rows:
        obs.append(f"rows {len(rows)}, {fits_rows} fit")
    return obs


def _draw_matrix(d, rows, x0, y0, w, h, font, ndims: int = 2,
                 label_width: float = 0.0) -> list[str]:
    """Matrix: dimension x dimension, value as color."""
    obs = []
    r_keys, c_keys = [], []
    cells: dict = {}
    for r in rows:
        if len(r) <= ndims:
            continue
        rk, ck = str(r[0]), str(r[1])
        if rk not in cells:
            r_keys.append(rk)
        cells.setdefault(rk, {})[ck] = _num(r[ndims])
        if ck not in c_keys:
            c_keys.append(ck)
    if not r_keys or not c_keys:
        return ["could not build the matrix: no pair of dimensions in the rows"]

    def _key(v):
        try:
            return (0, float(v))
        except ValueError:
            return (1, 0.0)
    c_keys.sort(key=lambda v: (_key(v), v))
    r_keys.sort(key=lambda v: (_key(v), v))

    lab_w = (min(label_width, w * 0.4) if label_width > 0
             else min(w * 0.25,
                      max(_tlen(d, k, font) for k in r_keys) + 6))
    row_h = 13
    fits_rows = max(1, int((h - y0 - 30) // row_h))
    grid_w = w - x0 - lab_w - x0
    cell_w = grid_w / max(1, len(c_keys))
    fits_cols = len(c_keys) if cell_w >= 8 else max(1, int(grid_w // 8))
    if len(r_keys) > fits_rows:
        obs.append(f"rows {len(r_keys)}, {fits_rows} fit; "
                   f"the rest scroll")
    if fits_cols < len(c_keys):
        obs.append(f"{len(c_keys)} columns of {cell_w:.0f} px; "
                   f"about {fits_cols} visible")
    vals = [v for row in cells.values() for v in row.values() if _is_number(v)]
    hi = max((abs(v) for v in vals), default=0.0) or 1.0

    head_step = max(1, int(round(d.textlength("00", font=font) * 1.6 / max(1, cell_w))))
    for j, ck in enumerate(c_keys[:fits_cols]):
        if j % head_step:
            continue
        d.text((x0 + lab_w + j * cell_w, y0), _fit(d, ck, cell_w * head_step, font),
               font=font, fill=MUTED)
    if head_step > 1:
        obs.append(f"column labels thinned: every {head_step}th is printed "
                   f"(cell {cell_w:.0f} px)")
    top = y0 + row_h
    cut = 0
    for i, rk in enumerate(r_keys[:fits_rows]):
        y = top + i * row_h
        short = _fit(d, rk, lab_w - 4, font)
        cut += short != rk
        d.text((x0, y), short, font=font, fill=INK)
        for j, ck in enumerate(c_keys[:fits_cols]):
            v = cells.get(rk, {}).get(ck)
            if not _is_number(v):
                continue
            k = min(1.0, abs(float(v)) / hi)
            tone = (int(235 - 160 * k), int(240 - 120 * k), int(248 - 80 * k))
            d.rectangle([x0 + lab_w + j * cell_w, y,
                         x0 + lab_w + (j + 1) * cell_w - 1, y + row_h - 2], fill=tone)
    if cut:
        obs.append(f"row labels clipped: {cut} of {min(len(r_keys), fits_rows)}")
    obs.append(f"matrix {len(r_keys)}x{len(c_keys)}, cell "
               f"{cell_w:.0f}×{row_h} px")
    return obs


def sketch_workbook(path: str, out_dir: str = "", db: str = "",
                    table: str = "", limit: int = 40) -> dict:
    """Sketch EVERY sheet of a workbook from its real data."""
    import zipfile

    from . import dryrun as _DR
    from . import layoutmodel as LM
    from .dryrun import dry_run

    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(path)), "_sketch")
    results = dry_run(path, db, table, limit=limit, sample_rows=limit)

    stuck = [r.sheet for r in results if r.status == "skipped"]
    if stuck:
        relaxed = {r.sheet: r for r in dry_run(path, db, table, limit=limit,
                                               sample_rows=limit, relax=True)
                   if r.status == "ok"}
        results = [relaxed.get(r.sheet, r) if r.status == "skipped" else r
                   for r in results]
    if not any(r.status == "ok" for r in results):
        return {"verdict": "no data; no sketches built",
                "sheets": [r.as_dict() for r in results]}

    from . import safexml
    root = safexml.from_twbx(path)
    wsn = root.find("worksheets")
    sheets = {w.get("name"): w for w in (list(wsn) if wsn is not None else [])}
    zones: dict[str, tuple[int, int]] = {}
    for dash in root.iter("dashboard"):
        model = LM.build(dash)
        for z in model.sheets():
            if z.name not in zones:
                zones[z.name] = (int(z.w), int(z.h))

    made, notes = [], []
    for r in results:
        if r.status != "ok" or not r.sample:
            notes.append(f"{r.sheet}: {r.status} — {r.note[:60]}")
            continue
        ws = sheets.get(r.sheet)
        mark = LM.mark_class(ws) if ws is not None else "Automatic"
        card = card_lines(ws)
        kind = ("card" if card
                else "matrix" if mark in ("Square", "Heatmap") and len(r.dim_exprs) >= 2
                else "table" if (_DR._is_text_table(ws) if ws is not None else False)
                or (mark in ("Text", "Automatic") and len(r.dim_exprs) >= 2)
                else "bar")
        size = zones.get(r.sheet, DEFAULT_SIZE)
        out = os.path.join(out_dir, f"{r.sheet.replace('/', '_')}.png")
        note = f"{r.rows} rows - {mark}"
        if r.relaxed:
            note += " - SIMPLIFIED: " + r.relaxed
        if r.synthetic_measure:
            note += " - value = ROW COUNT (measure via Measure Names)"
        lab_px = 0.0
        if ws is not None:
            rows_el = ws.find(".//rows")
            toks = re.findall(r"\[[^\[\]]+\]\.\[[^\[\]]+\]",
                              (rows_el.text or "") if rows_el is not None else "")
            if toks:
                lab_px = LM.declared_width(ws, toks[0], element="header")
        res = sketch_sheet(r.sample, out, title=r.sheet, kind=kind, size=size,
                           note=note, synthetic=r.synthetic_measure,
                           card=card, ncols_dims=len(r.dim_exprs),
                           label_width=lab_px, continuous=continuous_axis(ws),
                           ndims=len(r.dim_exprs))
        if r.relaxed:
            res["observations"] = list(res["observations"]) + [
                "sheet drawn SIMPLIFIED (" + r.relaxed + "); judge the layout, "
                "not the magnitudes"]
        made.append({"sheet": r.sheet, "relaxed": r.relaxed, **res})

    problems = [f"{m['sheet']}: {o}" for m in made for o in m["observations"]]
    total = sum(1 for _ in results)
    simple = [m["sheet"] for m in made if m.get("relaxed")]
    return {
        "verdict": (f"sketches built {len(made)} of {total}"
                    + (f", simplified {len(simple)} (magnitudes NOT real)"
                       if simple else "")
                    + (f", NOT DRAWN {total - len(made)}: "
                       + ", ".join(n.split(":")[0] for n in notes[:4])
                       + "; nothing checked how these sheets look"
                       if total - len(made) else "")
                    + (f", with notes {len(problems)}" if problems else "")),
        "sketches": made, "notes": problems, "skipped": notes,
        "how_to_read": "open the PNG with Read; the SKETCH stamp means this is OUR "
                      "view model, not a Tableau render; a difference from a real "
                      "screenshot is a finding to investigate",
    }

"""View critic: what the frame DREW and where it reads badly."""
from __future__ import annotations

import json
import math
import os
import pathlib
import re
import tempfile

PX_PER_PT = 96.0 / 72.0
TEXT_PT = 9.0
TITLE_PT = 15.0

FEW_ROWS = 15
FEW_HIDDEN = 3
TITLE_LINES_WARN = 3
DRIFT_PX = 6
OVERFLOW_PX = 8
MAX_COLORS = 12
DE_CLOSE = 5.0
CONTRAST_MIN = 3.0
EMPTY_STRIP_PX = 120
EMPTY_STRIP_SHARE = 0.4
EMPTY_BAND_PX = 200
EMPTY_BAND_SHARE = 0.12
TINY_PT = 7.0

HEAD_CAP = 90
VALUE_CAP = 170

TEXT_FORMS = ("table", "mlist", "matrix")
SQUEEZE_FITS = ("fit-width", "entire-view")

ERROR, WARN, INFO = "error", "warn", "info"
CLASSES = ("clipped", "overlap", "drift", "color", "emptiness", "table")

FRAME_GAPS = (
    "PROBE_JS: per table cell: th/td/number, column, natural text width "
    "(Range), not only the cut counter and 3 samples",
    "PROBE_JS: sheet title: natural width and wrapped line count",
    "PROBE_JS: first table body row (y) and row pitch, for neighbour drift",
    "PROBE_JS: text boxes (overlaps), text and background colors, legend swatches, bar pitch",
    "font size: sheet title 15 px instead of 15 pt (20 px); cells 11 px instead of "
    "`label`/`cell` pt × 96/72",
    "column widths: equal instead of by values plus horizontal scroll (Standard); "
    "Tableau default row header width (about 68 px), "
    "not by the longest label",
    "Tableau wraps column headers (2 lines); the frame clips them",
    "mark labels: Tableau culls overlapping ones, the frame draws all",
)


CRITIC_JS = r"""(opts) => {
  opts = opts || {};
  const MAXS = opts.max_scale || 2.2, CAP = opts.cap_px || 170;
  const cv = document.querySelector('.canvas');
  if (!cv) return {error: 'no canvas'};
  const C = cv.getBoundingClientRect();
  const box = r => [Math.round(r.left - C.left), Math.round(r.top - C.top),
                    Math.round(r.width), Math.round(r.height)];
  const hex = s => {
    const m = (s || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x));
    if (p.length > 3 && p[3] < 0.5) return null;
    return '#' + p.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  };
  const inlineBg = e => !!(e.style && (e.style.background || e.style.backgroundColor));
  const bgOf = el => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      if (e instanceof SVGElement) continue;
      const b = hex(getComputedStyle(e).backgroundColor);
      if (b) return [b, inlineBg(e)];
    }
    return ['#ffffff', false];
  };
  const textW = el => { const rg = document.createRange(); rg.selectNodeContents(el);
                        return rg.getBoundingClientRect().width; };
  const lineW = el => {
    const it = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const rows = {};
    for (let n; (n = it.nextNode());) {
      if (!n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      for (const r of rg.getClientRects()) {
        const k = Math.round(r.top);
        rows[k] = [Math.min(r.left, (rows[k] || [r.left])[0]), Math.max(r.right, (rows[k] || [0, r.right])[1])];
      }
    }
    return Math.max(0, ...Object.values(rows).map(([a, b]) => b - a));
  };
  // trailing blank lines are a builder's padding, not title text: counting them feeds the padding back
  const bare = el => {
    const c = el.cloneNode(true);
    const blank = k => k.nodeType === 3 ? !k.textContent.replace(/[\s\u00a0]/g, '')
                                        : k.tagName === 'BR' || !k.textContent.replace(/[\s\u00a0]/g, '');
    for (let n = c; n && n.lastChild; ) {
      if (blank(n.lastChild)) { n.removeChild(n.lastChild); continue; }
      n = n.lastChild.nodeType === 1 ? n.lastChild : null;
    }
    return c;
  };
  const wrapLines = (el, px, width) => {
    const c = el.cloneNode(true);
    c.style.cssText = 'position:absolute;visibility:hidden;white-space:normal;overflow:visible;' +
      'text-overflow:clip;display:block;line-height:1.2;width:' + width + 'px;font-size:' + px + 'px';
    for (const k of c.querySelectorAll('*')) {
      if (!k.style.fontSize) k.style.fontSize = px + 'px';
      k.style.whiteSpace = 'normal';
    }
    document.body.appendChild(c);
    const h = c.getBoundingClientRect().height;
    c.remove();
    return Math.max(1, Math.round(h / (px * 1.2)));
  };
  const out = {canvas: [Math.round(C.width), Math.round(C.height)], zones: []};
  for (const z of cv.querySelectorAll('.zone[data-kind]')) {
    const zr = z.getBoundingClientRect();
    const it = {id: z.dataset.id || '', name: z.dataset.name || '', kind: z.dataset.kind || '',
                form: z.dataset.form || '', fit: z.dataset.fit || '', box: box(zr),
                sheet: z.classList.contains('sheet'), text: z.classList.contains('text'),
                floating: z.style.zIndex === '5', tables: [], lbls: [], ink: {}, marks: {},
                swatches: [], bars: null, content: null, empty: ''};
    const em = z.querySelector('.empty');
    if (em) it.empty = em.textContent.trim().slice(0, 120);
    const t = z.querySelector(':scope > .ttl');
    if (t) {
      const fs = parseFloat(getComputedStyle(t).fontSize);
      const px = (opts.title_px || {})[it.name] || fs;
      it.title = {text: t.innerText.trim().slice(0, 120), need: Math.ceil(textW(t)), width: t.clientWidth,
                  h: Math.round(t.getBoundingClientRect().height), fs, px,
                  lines: wrapLines(bare(t), px, t.clientWidth)};
    }
    for (const tb of z.querySelectorAll('table')) {
      const cols = [];
      let first = null, last = null, nbody = 0, rowh = 0;
      for (const tr of tb.rows) {
        const head = !!tr.querySelector('th') && !tr.querySelector('td');
        const rb = tr.getBoundingClientRect();
        if (!head) {
          nbody++;
          if (first === null) { first = Math.round(rb.top - C.top); rowh = rb.height; }
          last = Math.round(rb.bottom - C.top);
        }
        [...tr.cells].forEach((c, ci) => {
          const col = cols[ci] || (cols[ci] = {n: 0, num: 0, nat: 0, fs: 0, have: c.clientWidth, cells: []});
          const cs = getComputedStyle(c);
          const txt = c.textContent.trim();
          if (!txt) return;
          const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
          const fs = parseFloat(cs.fontSize);
          if (head) {
            const inner = c.querySelector('div');
            const clamped = !!inner && inner.scrollHeight > inner.clientHeight + 6;
            const hneed = Math.ceil((clamped ? Math.max(lineW(c), textW(c) + 12) : lineW(c)) + pad);
            col.head = {text: txt.slice(0, 80), need: hneed, fs, have: c.clientWidth}; return;
          }
          const need = Math.ceil(textW(c) + pad);
          col.n++; col.have = c.clientWidth; col.fs = col.fs || fs;
          if (c.classList.contains('num')) col.num++;
          col.nat = Math.max(col.nat, need);
          if (need * MAXS > Math.min(c.clientWidth, CAP) && col.cells.length < 150)
            col.cells.push([txt.slice(0, 80), need]);
        });
      }
      // column width: from the workbook style (`xml`) or by content (`auto`)
      [...tb.querySelectorAll('colgroup > col')].forEach((cg, ci) => {
        if (cols[ci]) { cols[ci].src = cg.dataset.src || ''; cols[ci].px = +cg.dataset.px || 0; }
      });
      const fv = tb.closest('.fitv');
      it.tables.push({box: box(tb.getBoundingClientRect()), cols, nbody, first, last,
                      rowh: Math.round(rowh * 10) / 10, natrh: fv ? +fv.dataset.natrh || 0 : 0});
    }
    let cb = null;
    const grow = r => { if (!r.width || !r.height) return;
      const l = Math.max(r.left, zr.left), tp = Math.max(r.top, zr.top),
            rt = Math.min(r.right, zr.right), bt = Math.min(r.bottom, zr.bottom);
      if (rt <= l || bt <= tp) return;
      cb = cb ? [Math.min(cb[0], l), Math.min(cb[1], tp), Math.max(cb[2], rt), Math.max(cb[3], bt)]
              : [l, tp, rt, bt]; };
    const leafs = [...z.querySelectorAll('*')].filter(e =>
      [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
    for (const e of leafs.slice(0, 1500)) {
      const r = e.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (!(t && (e === t || t.contains(e)))) grow(r);
      const cs = getComputedStyle(e);
      const svg = e instanceof SVGElement;
      const fg = svg ? (hex(cs.fill) || '#000000') : hex(cs.color);
      const [bg, bgOwn] = bgOf(svg ? e.closest('.zone') : e);
      const own = !!(e.style && e.style.color) || bgOwn || (svg && !!e.getAttribute('fill'));
      const key = fg + '|' + bg;
      const ink = it.ink[key] || (it.ink[key] = {n: 0, own: false, sample: e.textContent.trim().slice(0, 30),
                                                 fs: parseFloat(cs.fontSize)});
      ink.n++; ink.own = ink.own || own; ink.fs = Math.min(ink.fs, parseFloat(cs.fontSize));
      if (e.closest('table') || svg) continue;
      const cls = (e.getAttribute('class') || '');
      let vis = r;
      const rg = document.createRange(); rg.selectNodeContents(e);
      const tr_ = rg.getBoundingClientRect();
      if (tr_.width) {
        const l = Math.max(r.left, tr_.left), rt = Math.min(r.right, tr_.right);
        vis = {left: l, top: r.top, width: Math.max(0, rt - l), height: r.height};
      }
      const clamped = getComputedStyle(e).webkitLineClamp !== 'none';
      const cut = e.classList.contains('lbl') &&
        (clamped ? e.scrollHeight > e.clientHeight + 1 : e.scrollWidth > e.clientWidth + 1);
      if (it.lbls.length < 400)
        it.lbls.push({t: e.textContent.trim().slice(0, 60), cls, box: box(vis), cut,
                      fs: parseFloat(cs.fontSize)});
    }
    for (const m of z.querySelectorAll('svg, img, .fill, .vcol i, .col i, table tr')) grow(m.getBoundingClientRect());
    if (cb) it.content = [Math.round(cb[0] - C.left), Math.round(cb[1] - C.top),
                          Math.round(cb[2] - cb[0]), Math.round(cb[3] - cb[1])];
    const add = c => { if (c) it.marks[c] = (it.marks[c] || 0) + 1; };
    for (const m of z.querySelectorAll('.fill, .vcol i, .col i')) add(hex(getComputedStyle(m).backgroundColor));
    for (const m of z.querySelectorAll('svg rect, svg path, svg circle')) add(hex(getComputedStyle(m).fill));
    for (const m of z.querySelectorAll('svg polyline')) add(hex(getComputedStyle(m).stroke));
    for (const m of z.querySelectorAll('i')) {
      if (m.closest('.vcol, .col')) continue;
      const c = hex(getComputedStyle(m).backgroundColor);
      if (c) it.swatches.push(c);
    }
    const bars = [...z.querySelectorAll('.bar')];
    if (bars.length) {
      const hs = bars.map(b => b.getBoundingClientRect().height).sort((a, b) => a - b);
      const lab = z.querySelector('.blab');
      it.bars = {n: bars.length, pitch: Math.round(hs[Math.floor(hs.length / 2)] * 10) / 10,
                 fs: lab ? parseFloat(getComputedStyle(lab).fontSize) : 0};
    }
    out.zones.push(it);
  }
  return out;
}"""


def _page_file(page: dict) -> str:
    """HTML of a frame page: `file` when the frame returned it, else next to the image."""
    if page.get("file"):
        return page["file"]
    shot = page.get("image") or ""
    return shot[:-4] + ".html" if shot.endswith(".png") else ""


def deep_probe(page_file: str, opts: dict | None = None) -> dict:
    """Critic measurement of a frame page in the persistent frame Chrome (`twkit.cdp`)."""
    from . import cdp, frame
    url = pathlib.Path(os.path.abspath(page_file)).as_uri()
    m = frame.canvas_size(open(page_file, encoding="utf-8").read())
    w, h = (int(m.group(1)) + 40, int(m.group(2)) + 40) if m else (1600, 1200)
    with cdp.Tab() as t:
        t.open(url, w, h, "document.fonts.status === 'loaded' && "
                          "!!document.getElementById('probe-out')")
        return t.eval(f"({CRITIC_JS})({json.dumps(opts or {}, ensure_ascii=False)})") or {}


def probe(page_file: str, opts: dict | None = None) -> tuple:
    """`deep_probe` with one retry: a page measured too early in a busy Chrome reads as failed.

    Returns `(measurement, "")` or `(None, why)`."""
    err = ""
    for _ in range(2):
        try:
            d = deep_probe(page_file, opts)
        except Exception as exc:                                     # noqa: BLE001
            err = f"{type(exc).__name__}: {str(exc)[:80]}"
            continue
        if d and not d.get("error"):
            return d, ""
        err = (d or {}).get("error") or "empty measurement"
    return None, err


def _pt(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def sheet_style(ws) -> dict:
    """Sheet font sizes as Tableau applies them: `label` for headers, `cell` for values."""
    st = {"label_pt": TEXT_PT, "cell_pt": TEXT_PT, "title_pt": TITLE_PT, "head_lines": 2}
    if ws is None:
        return st
    for sr in ws.iter("style-rule"):
        el = sr.get("element")
        for f in sr.findall("format"):
            if el == "header" and f.get("attr") == "height" and _pt(f.get("value")):
                st["head_lines"] = max(st["head_lines"], int((_pt(f.get("value")) - 4) / 15.3))
            if f.get("attr") != "font-size" or f.get("field"):
                continue
            v = _pt(f.get("value"))
            if v and el in ("label", "cell"):
                st[f"{el}_pt"] = v
    node = ws.find(".//layout-options/title/formatted-text")
    if node is not None:
        sizes = [_pt(r.get("fontsize")) for r in node.iter("run")]
        sizes = [s for s in sizes if s]
        if sizes:
            st["title_pt"] = max(sizes)
    return st


def _sheets(root) -> dict:
    wsn = root.find("worksheets") if root is not None else None
    return {w.get("name"): w for w in (list(wsn) if wsn is not None else [])}


def _color_ref(ws) -> str:
    enc = ws.find(".//encodings/color") if ws is not None else None
    return (enc.get("column") or "") if enc is not None else ""


def _discrete(ref: str) -> bool:
    return bool(ref) and (":Measure Names" in ref or bool(re.search(r":(nk|ok)(:\d+)?\]$", ref)))


def _rgb(h: str) -> tuple:
    h = h.lstrip("#")[:6]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(h: str) -> float:
    r, g, b = (_lin(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast: (L1 + 0.05) / (L2 + 0.05)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _lab(h: str) -> tuple:
    r, g, b = (_lin(v) for v in _rgb(h))
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e(c1: str, c2: str) -> float:
    """CIEDE2000: how distinguishable two colors are (below 5: barely)."""
    L1, a1, b1 = _lab(c1)
    L2, a2, b2 = _lab(c2)
    cb = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(cb ** 7 / (cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1 = math.degrees(math.atan2(b1, a1p)) % 360
    h2 = math.degrees(math.atan2(b2, a2p)) % 360
    dl, dc = L2 - L1, c2p - c1p
    dh = 0.0 if c1p * c2p == 0 else (h2 - h1 - 360 if h2 - h1 > 180 else
                                     h2 - h1 + 360 if h2 - h1 < -180 else h2 - h1)
    dhh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    lb, cbp = (L1 + L2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hb = h1 + h2
    elif abs(h1 - h2) > 180:
        hb = (h1 + h2 + 360) / 2 if h1 + h2 < 360 else (h1 + h2 - 360) / 2
    else:
        hb = (h1 + h2) / 2
    t = (1 - 0.17 * math.cos(math.radians(hb - 30)) + 0.24 * math.cos(math.radians(2 * hb))
         + 0.32 * math.cos(math.radians(3 * hb + 6)) - 0.20 * math.cos(math.radians(4 * hb - 63)))
    dth = 30 * math.exp(-((hb - 275) / 25) ** 2)
    rc = 2 * math.sqrt(cbp ** 7 / (cbp ** 7 + 25 ** 7))
    sl = 1 + 0.015 * (lb - 50) ** 2 / math.sqrt(20 + (lb - 50) ** 2)
    sc, sh = 1 + 0.045 * cbp, 1 + 0.015 * cbp * t
    rt = -math.sin(math.radians(2 * dth)) * rc
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * (dc / sc) * (dhh / sh))


def _hsv(h: str) -> tuple:
    import colorsys
    return colorsys.rgb_to_hsv(*(v / 255 for v in _rgb(h)))


def achromatic(h: str) -> bool:
    """Greys, black and white are utility colors, not palette colors."""
    _h, s, v = _hsv(h)
    return s < 0.12 or v < 0.12


def house_colors() -> set:
    """House palette: Tableau 20 (`style.PALETTE`) plus anchor colors of the stock quantitative palettes."""
    from . import frame, style
    out = {c.lower() for c in style.PALETTE}
    for stops in getattr(frame, "TABLEAU_PALETTES", {}).values():
        out |= {c.lower() for c in stops}
    out |= {style.BAND_COLOR, getattr(style, "BAND_WARM", ""), "#f0f7fa", "#b4b4b4"}
    return {c for c in out if c}


RAINBOW_NAMES = re.compile(r"rainbow|spectral|hue|temperature|traffic|sunrise", re.I)


def rainbow(colors: list) -> bool:
    """Rainbow scale on a measure: anchors circle the hue wheel (3+ saturated, hue spread > 150 deg)."""
    sat = [c for c in colors if not achromatic(c)]
    if len(sat) < 3:
        return False
    hues = sorted(_hsv(c)[0] * 360 for c in sat)
    gaps = [b - a for a, b in zip(hues, hues[1:])] + [hues[0] + 360 - hues[-1]]
    span = 360 - max(gaps)
    mid = colors[len(colors) // 2]
    return span > 150 and not achromatic(mid) and _hsv(mid)[1] > 0.3


def _f(cls: str, code: str, level: str, page: str, sheet: str, what: str, proof: str,
       fix: str) -> dict:
    return {"class": cls, "code": code, "level": level, "page": page, "sheet": sheet,
            "what": what, "evidence": proof, "fix": fix}


def _short(text: str, have: float, need: float, char_px: float = 0.0) -> str:
    """What remains of a label in a column, plus an ellipsis."""
    if need <= have:
        return text
    per = char_px or need / max(len(text), 1)
    k = max(0, int(max(0.0, have - 8) / max(per, 0.1)))
    return text[:k].rstrip() + "…"


def _col_scale(col: dict, st: dict) -> float:
    """How much wider a column text is in Tableau than in the frame."""
    pt = st["cell_pt"] if col.get("num") and col["num"] >= col.get("n", 0) / 2 else st["label_pt"]
    fs = col.get("fs") or 11.0
    return max(0.5, pt * PX_PER_PT / fs)


def _is_num(col: dict) -> bool:
    return bool(col.get("num")) and col["num"] >= col.get("n", 0) / 2


def column_widths(cols: list, st: dict, zone_w: float, fit: str) -> tuple:
    """Column widths as Tableau assigns them -> (widths, overflow, squeezed)."""
    squeeze = fit in SQUEEZE_FITS
    nat = []
    for c in cols:
        if c.get("src") == "xml" and c.get("px"):
            nat.append(float(c["px"]))
            continue
        h = c.get("head") or {}
        head = h.get("need", 0) * st["label_pt"] * PX_PER_PT / (h.get("fs") or 11.0)
        nat.append(min(VALUE_CAP, max(c.get("nat", 0) * _col_scale(c, st), min(head, HEAD_CAP))))
    overflow = not squeeze and sum(nat) > zone_w + OVERFLOW_PX
    widths, squeezed = [], []
    for ci, c in enumerate(cols):
        row_head = not _is_num(c) and not any(_is_num(cc) for cc in cols[:ci])
        sq = squeeze or (overflow and row_head and c.get("src") != "xml")
        widths.append(float(c.get("have", 0)) if sq else nat[ci])
        squeezed.append(sq)
    return widths, overflow, squeezed, sum(nat)


def judge_table(page: str, z: dict, tb: dict, st: dict) -> list:
    """Clipping in a text table as Tableau draws it (`column_widths`)."""
    out = []
    name, fit = z.get("name", ""), z.get("fit", "standard")
    cols = [c for c in (tb.get("cols") or []) if c]
    if not cols:
        return out
    zone_w = (z.get("box") or [0, 0, 0, 0])[2] - 12
    widths, overflow, squeezed, total = column_widths(cols, st, zone_w, fit)
    if overflow:
        out.append(_f("clipped", "K5", WARN, page, name,
                      f"table wider than the zone by {total - zone_w:.0f} px: horizontal scroll",
                      f"columns {len(cols)}, need {total:.0f} px, zone {zone_w:.0f} px "
                      f"(Tableau size {st['label_pt']:g}/{st['cell_pt']:g} pt)",
                      "widen the zone, drop columns or fit width"))
    heads = []
    for ci, (c, have, sq) in enumerate(zip(cols, widths, squeezed)):
        s = _col_scale(c, st)
        cut = [(t, n * s) for t, n in (c.get("cells") or []) if n * s > have + 1]
        h = c.get("head")
        if h and h.get("text") and len(cols) > 1:
            hn = h["need"] * st["label_pt"] * PX_PER_PT / (h.get("fs") or 11.0)
            # one frame line rescaled to Tableau's size can still wrap into the allowed lines
            if hn > have + 2 and wrap_lines(h["text"], have - 10, st["label_pt"]) > st.get("head_lines", 2):
                heads.append((h["text"], _short(h["text"], have, hn)))
        if not cut:
            continue
        n = c.get("n", 0) or len(cut)
        if _is_num(c):
            t, need = cut[0]
            out.append(_f("clipped", "K1", ERROR, page, name,
                          f"numbers do not fit column {ci + 1}: '{t}' in {have:.0f} px "
                          f"(need {need:.0f}); Tableau shows ##### or a stub",
                          f"numbers clipped {len(cut)} of {n}; fit '{fit}'",
                          "widen the column or zone, or remove fit width"))
            continue
        uniq = dict(cut)
        per = sum(uniq.values()) / max(sum(len(t) for t in uniq), 1)
        short = {}
        for t, need in uniq.items():
            short.setdefault(_short(t, have, need, per), []).append(t)
        same = sum(len(v) for v in short.values() if len(v) > 1)
        share = len(cut) / max(n, 1)
        hard = sq or same > 0
        ex = ", ".join(f"'{t[:28]}' → '{_short(t, have, need, per)}'"
                       for t, need in list(uniq.items())[:3])
        why = ("column squeezed" if sq else
               f"{same} different labels became identical after clipping" if same else
               f"long labels beyond the column width cap ({share:.0%})")
        out.append(_f("clipped", "K2", ERROR if hard else WARN, page, name,
                      f"values of column {ci + 1} clipped: {len(cut)} of {n}: {why}",
                      ex + f"; column {have:.0f} px, fit '{fit}'",
                      "widen the column (edit_fit_column_width) or move the "
                      "distinguishing part of the label to the start"))
    if heads:
        ex = ", ".join(f"'{a[:30]}' → '{b}'" for a, b in heads[:4])
        out.append(_f("clipped", "K3", WARN, page, name,
                      f"column headers will be clipped: {len(heads)}",
                      ex, "shorten the measure caption or widen the column"))
    return out


def judge_zone(page: str, z: dict, st: dict, fr_zone: dict | None) -> list:
    """Findings of one zone: clipping, scrolling, overlap, emptiness, text color."""
    out = []
    name = z.get("name", "")
    form, fit = z.get("form", ""), z.get("fit", "standard")
    x, y, w, h = z.get("box") or [0, 0, 0, 0]
    if z.get("sheet") and z.get("empty"):
        note = z["empty"]
        if note == "no data" or note.startswith("empty"):
            out.append(_f("emptiness", "E1", WARN, page, name, "the sheet is empty: nothing in the zone",
                          f"frame: '{note}'; {w}x{h} px",
                          "check filters/period (the data channel decides whether it blocks)"))
    t = z.get("title")
    if t and t.get("lines", 1) >= TITLE_LINES_WARN:
        out.append(_f("clipped", "K4", WARN, page, name,
                      f"sheet title does not fit: {t['lines']} lines in a {w} px zone",
                      f"'{t['text'][:60]}' at {t.get('px', 0):.0f} px, width {t.get('width', 0)} px",
                      "shorten the title, widen the zone, or hide the title "
                      "(edit_show_zone_title) and caption the block with a text zone"))
    for tb in z.get("tables") or []:
        out += judge_table(page, z, tb, st)
    ov = (fr_zone or {}).get("overflow") or {}
    if ov:
        dy = ov.get("sh", 0) - ov.get("ch", 0)
        dx = ov.get("sw", 0) - ov.get("cw", 0)
        tbs = z.get("tables") or []
        if form in TEXT_FORMS and tbs and dy > OVERFLOW_PX and fit not in ("entire-view", "fit-height"):
            rowh = max(tbs[0].get("rowh") or 20, 1)
            hidden = math.ceil(dy / rowh)
            rows = sum(t_.get("nbody", 0) for t_ in tbs)
            if rows <= FEW_ROWS or hidden <= FEW_HIDDEN:
                out.append(_f("clipped", "K6", WARN, page, name,
                              f"scrolling for {hidden} of {rows} rows",
                              f"content {ov.get('sh')} px in a {ov.get('ch')} px zone",
                              "zone height by row count, or fit height"))
        elif z.get("text") and dy > OVERFLOW_PX:
            out.append(_f("clipped", "K7", WARN, page, name or f"text [{z.get('id')}]",
                          f"text does not fit the zone: {dy} px hidden",
                          f"content {ov.get('sh')} px in a {ov.get('ch')} px zone",
                          "enlarge the zone or shorten the text"))
        elif z.get("sheet") and form not in TEXT_FORMS and dx > max(OVERFLOW_PX, 0.03 * w):
            out.append(_f("clipped", "K7", WARN, page, name,
                          f"sheet wider than its zone by {dx} px",
                          f"content {ov.get('sw')} px in a {ov.get('cw')} px zone",
                          "widen the zone or shorten labels"))
    lbls = z.get("lbls") or []
    bl = [l_ for l_ in lbls if "blab" in (l_.get("cls") or "")]
    bars = z.get("bars")
    if bars and bars.get("n", 0) >= 2:
        lab_px = st["label_pt"] * PX_PER_PT
        if bars["pitch"] < lab_px * 0.95:
            out.append(_f("overlap", "P2", ERROR, page, name,
                          f"labels of {bars['n']} categories overlap",
                          f"bar pitch {bars['pitch']} px with label size {lab_px:.0f} px",
                          "top-N, a taller zone, or another dimension"))
        cut = [l_ for l_ in bl if l_.get("cut")]
        if cut:
            out.append(_f("clipped", "K2", WARN, page, name,
                          f"category labels clipped: {len(cut)} of {len(bl)}",
                          ", ".join(f"'{l_['t'][:30]}'" for l_ in cut[:3]),
                          "widen the zone or shorten labels"))
    if z.get("text"):
        worst = None
        for key, ink in (z.get("ink") or {}).items():
            fg, bg = key.split("|")
            if not (ink.get("own") and fg.startswith("#") and bg.startswith("#")):
                continue
            cr = contrast(fg, bg)
            if cr < CONTRAST_MIN and (worst is None or cr < worst[0]):
                worst = (cr, fg, bg, ink)
        if worst:
            cr, fg, bg, ink = worst
            out.append(_f("color", "C3", WARN, page, name or f"text [{z.get('id')}]",
                          f"text drowns in the background: contrast {cr:.1f} (need >= {CONTRAST_MIN:g})",
                          f"text {fg} on {bg}, '{ink.get('sample', '')}'",
                          "dark text on a light background or the reverse"))
    return out


def judge_strips(page: str, zones: list, sheets: dict) -> list:
    """An empty strip under a table, empty for the WHOLE row."""
    out = []
    for z in zones:
        tbs = [t for t in (z.get("tables") or []) if t.get("last")]
        if not (z.get("sheet") and z.get("form") in TEXT_FORMS and tbs
                and z.get("fit", "standard") == "standard"):
            continue
        x, y, w, h = z["box"]
        st = sheet_style(sheets.get(z.get("name")))
        last = max(t["last"] for t in tbs)
        first = min((t.get("first") or last) for t in tbs)
        fs = next((c.get("fs") for t in tbs for c in (t.get("cols") or []) if c and c.get("fs")),
                  11.0)
        bottom = first + (last - first) * max(1.0, st["cell_pt"] * PX_PER_PT / fs)
        for o in zones:
            ob, oc = o.get("box") or [0, 0, 0, 0], o.get("content")
            if o is z or not oc or abs(ob[1] - y) > 4 or abs(ob[3] - h) > 4:
                continue
            bottom = max(bottom, oc[1] + oc[3])
        strip = (y + h) - bottom
        if strip >= max(EMPTY_STRIP_PX, EMPTY_STRIP_SHARE * h):
            out.append(_f("emptiness", "E2", WARN, page, z.get("name", ""),
                          f"empty strip under the table {strip:.0f} px ({strip / max(h, 1):.0%} of the zone)",
                          f"rows {sum(t.get('nbody', 0) for t in tbs)}, zone {h} px; "
                          f"row neighbours do not extend lower",
                          "size the zone height by row count"))
    return out


SWATCH = re.compile(r"\s*[\u25a0\u25cf\u25b2\u25c6]\s*")


def judge_book_ink(page: str, name: str, ws) -> list:
    """Sheet text contrast by XML: text color against the sheet background."""
    if ws is None:
        return []
    hexes = lambda vals: [v.lower()[:7] for v in vals
                          if re.fullmatch(r"#[0-9a-fA-F]{6}(ff|FF)?", v or "")]
    fgs = hexes([f.get("value") for f in ws.iter("format") if f.get("attr") == "color"] +
                [r.get("fontcolor") for r in ws.iter("run") if not SWATCH.fullmatch(r.text or "")])
    bgs = hexes([f.get("value") for sr in ws.iter("style-rule")
                 if sr.get("element") in ("worksheet", "table", "pane", "cell")
                 for f in sr.findall("format") if f.get("attr") == "background-color"]) or ["#ffffff"]
    worst = min(((contrast(a, b), a, b) for a in set(fgs) for b in set(bgs)), default=None)
    if not worst or worst[0] >= CONTRAST_MIN:
        return []
    cr, fg, bg = worst
    return [_f("color", "C3", WARN, page, name,
               f"text drowns in the background: contrast {cr:.1f} (need >= {CONTRAST_MIN:g})",
               f"text {fg} on background {bg} (sheet style)",
               "dark text on a light background or the reverse")]


def judge_drift(page: str, zones: list) -> list:
    """Block drift: neighbouring tables of one row with equal row counts must start at the same height."""
    out = []
    cand = []
    for z in zones:
        tbs = [t for t in (z.get("tables") or []) if t.get("first") is not None]
        if not (z.get("sheet") and z.get("form") in TEXT_FORMS and tbs):
            continue
        tb = tbs[0]
        if (tb.get("nbody") or 0) < 1:
            continue
        x, y, w, h = z["box"]
        off = tb["first"] - y
        t = z.get("title")
        extra = 0.0
        if t:
            extra = t.get("lines", 1) * t.get("px", t.get("fs", 15)) * 1.2 - (t.get("h") or 0)
        cand.append({"z": z, "x": x, "y": y, "w": w, "n": tb["nbody"], "off": off + extra,
                     "rowh": tb.get("rowh") or 0, "lines": (t or {}).get("lines", 0)})
    cand.sort(key=lambda c: (c["y"], c["x"]))
    used = set()
    for i, a in enumerate(cand):
        if id(a["z"]) in used:
            continue
        group = [a]
        for b in cand[i + 1:]:
            last = group[-1]
            if abs(b["y"] - a["y"]) <= 4 and b["n"] == a["n"] and \
                    0 <= b["x"] - (last["x"] + last["w"]) <= 16:
                group.append(b)
        if len(group) < 2:
            continue
        used |= {id(g["z"]) for g in group}
        offs = [g["off"] for g in group]
        pitch = {round(g["rowh"]) for g in group}
        if max(offs) - min(offs) > DRIFT_PX or (max(pitch) - min(pitch) > 2 if pitch else False):
            low = max(group, key=lambda g: g["off"])
            why = (f"title '{(low['z'].get('title') or {}).get('text', '')[:40]}' "
                   f"in {low['lines']} lines" if low["lines"] > 1 else
                   "neighbours differ in header or fit")
            out.append(_f("drift", "R1", ERROR, page, low["z"].get("name", ""),
                          f"rows of neighbouring tables do not align: '{low['z'].get('name', '')}' "
                          f"lower by {max(offs) - min(offs):.0f} px",
                          f"row {', '.join(g['z'].get('name', '')[:24] for g in group)}: "
                          f"first row at {', '.join(f'{o:.0f}' for o in offs)} px from the zone top"
                          f", row pitch {sorted(pitch)}; cause: {why}",
                          "equal one-line titles for neighbours or one block title "
                          "as a text zone; equal headers and fit"))
    return out


def judge_floating(page: str, zones: list) -> list:
    """A floating zone over sheet labels: a button or legend covers data."""
    out = []
    for f in zones:
        if not f.get("floating") or not f.get("content"):
            continue
        fx, fy, fw, fh = f["content"]
        for z in zones:
            if z is f or z.get("floating") or not z.get("sheet"):
                continue
            hit = [l_ for l_ in z.get("lbls") or []
                   if min(fx + fw, l_["box"][0] + l_["box"][2]) - max(fx, l_["box"][0]) > 2 and
                   min(fy + fh, l_["box"][1] + l_["box"][3]) - max(fy, l_["box"][1]) > 2]
            if hit:
                out.append(_f("overlap", "P3", WARN, page, z.get("name", ""),
                              f"floating zone '{f.get('name') or f.get('kind')}' covers "
                              f"sheet labels: {len(hit)}",
                              f"zone [{f.get('id')}] {f['content']}; '{hit[0]['t'][:30]}'",
                              "move the floating zone or make room for it"))
    return out


def judge_colors(page: str, z: dict, ws) -> list:
    """Color in one zone: category count, indistinguishable pairs, off-palette, rainbow."""
    out = []
    name = z.get("name", "")
    ref = _color_ref(ws)
    marks = [c for c in (z.get("marks") or {}) if c]
    sw = list(dict.fromkeys(z.get("swatches") or []))
    if _discrete(ref) or (not ref and (len(sw) >= 2)):
        cats = sorted(set(marks) | set(sw))
        n_items = max(len(z.get("swatches") or []), len(cats))
        if n_items > MAX_COLORS:
            rep = len(z.get("swatches") or []) > len(set(z.get("swatches") or []))
            out.append(_f("color", "C1", WARN, page, name,
                          f"{n_items} color categories"
                          + ("; colors repeat" if rep else ""),
                          f"distinct colors {len(cats)}, legend items {len(z.get('swatches') or [])}",
                          "top-N plus Other, color only the main categories, or "
                          "put the dimension on an axis instead of color"))
        close = sorted((delta_e(a, b), a, b) for i, a in enumerate(cats) for b in cats[i + 1:]
                       if not (achromatic(a) and achromatic(b)))
        close = [c for c in close if c[0] < DE_CLOSE]
        if close:
            d, a, b = close[0]
            out.append(_f("color", "C2", WARN, page, name,
                          f"indistinguishable colors in one legend: {len(close)} pairs",
                          f"{a} and {b}: dE2000 {d:.1f} (< {DE_CLOSE})",
                          "separate the colors (different palette slots) or reduce categories"))
    return out


def judge_book_colors(root, sheets: dict, placed: set) -> list:
    """Workbook colors: off the house palette, and rainbow scales on measures (by XML)."""
    out = []
    if root is None:
        return out
    from . import frame
    house = house_colors()
    off: dict = {}
    for name, ws in sheets.items():
        if name not in placed:
            continue
        try:
            cmap = frame.color_map(root, ws) or {}
        except Exception:                                        # noqa: BLE001
            cmap = {}
        for c in cmap.values():
            c = (c or "").lower()[:7]
            if re.fullmatch(r"#[0-9a-f]{6}", c) and c not in house and not achromatic(c):
                off.setdefault(c, set()).add(name)
        for f in ws.iter("format"):
            if f.get("attr") == "mark-color":
                c = (f.get("value") or "").lower()[:7]
                if re.fullmatch(r"#[0-9a-f]{6}", c) and c not in house and not achromatic(c):
                    off.setdefault(c, set()).add(name)
        for enc in ws.iter("encoding"):
            if enc.get("attr") != "color":
                continue
            fld = enc.get("field") or ""
            if _discrete(fld):
                continue
            pal = enc.get("palette") or ""
            src = list(enc.iter("color")) or [c for cp in root.findall("preferences/color-palette")
                                              if pal and cp.get("name") == pal
                                              for c in cp.findall("color")]
            stops = [(c.text or "").strip().lower()[:7] for c in src]
            stops = [s for s in stops if re.fullmatch(r"#[0-9a-f]{6}", s)]
            if (stops and rainbow(stops)) or RAINBOW_NAMES.search(pal):
                out.append(_f("color", "C5", WARN, "", name,
                              "rainbow scale on a measure: the scale circles the hue wheel",
                              f"palette {pal or 'custom'}: {', '.join(stops[:6])}",
                              "a single-hue sequential scale (blue_10_0) or "
                              "a diverging scale through a neutral middle"))
                break
    if off:
        items = sorted(off.items(), key=lambda kv: -len(kv[1]))
        out.append(_f("color", "C4", WARN, "", ", ".join(sorted({s for _c, ss in items for s in ss}))[:80],
                      f"colors off the house palette: {len(off)}",
                      "; ".join(f"{c} ({', '.join(sorted(ss))[:40]})" for c, ss in items[:4]),
                      "Tableau 20 in slot order (docs/STYLE_GUIDE.md section 3); a custom color only "
                      "with meaning (good/bad) and a label"))
    return out


def judge_fonts(root, sheets: dict, placed: set) -> list:
    """Tiny font sizes in sheet styles and title/zone texts (by XML)."""
    tiny: dict = {}
    for name, ws in sheets.items():
        if name not in placed:
            continue
        for f in ws.iter("format"):
            if f.get("attr") == "font-size":
                v = _pt(f.get("value"))
                if v and v < TINY_PT:
                    tiny.setdefault(name, set()).add(v)
        for r in ws.iter("run"):
            v = _pt(r.get("fontsize"))
            if v and v < TINY_PT:
                tiny.setdefault(name, set()).add(v)
    for dash in (root.iter("dashboard") if root is not None else ()):
        for r in dash.iter("run"):
            v = _pt(r.get("fontsize"))
            if v and v < TINY_PT:
                tiny.setdefault(f"page '{dash.get('name')}'", set()).add(v)
    if not tiny:
        return []
    return [_f("emptiness", "E4", WARN, "", ", ".join(list(tiny)[:4]),
               f"font too small: {len(tiny)} places",
               "; ".join(f"{k}: {', '.join(f'{v:g}' for v in sorted(vs))} pt"
                         for k, vs in list(tiny.items())[:4]),
               f"at least {TINY_PT:g} pt; corpus footnotes use 8 pt")]


DELTA_CAPTION = re.compile(r"(?i)^\s*Δ|^\s*\+/-|% ?change|\bvs\b|\b(DoD|WoW|MoM|YoY)\b|% ?diff")


def _text_table(ws) -> bool:
    mark = ws.find(".//mark")
    cls = mark.get("class") if mark is not None else ""
    text = cls == "Text" or (cls == "Automatic" and ws.find(".//encodings/text") is not None)
    shelves = (ws.findtext("table/rows") or "") + (ws.findtext("table/cols") or "")
    return text and bool((ws.findtext("table/rows") or "").strip()) and ":qk]" not in shelves


def _shown_measures(ws) -> set:
    """Instance names the table prints: `Measure Names` filter members and text encodings."""
    out = set()
    for f in ws.iter("filter"):
        if (f.get("column") or "").endswith("[:Measure Names]"):
            out |= {m.get("member").strip('"').rsplit(".", 1)[-1]
                    for m in f.iter("groupfilter") if m.get("member")}
    for e in ws.iter("encodings"):
        for el in e:
            if el.get("column") and "[Multiple Values]" not in el.get("column"):
                out.add(el.get("column").rsplit(".", 1)[-1])
    return out


def _table_fonts(ws) -> tuple[set, set]:
    sizes, families = set(), set()
    for rule in ws.findall("table/style/style-rule"):
        if rule.get("element") not in ("cell", "header", "label"):
            continue
        seen = set()
        for f in rule.findall("format"):
            a = f.get("attr")
            if f.get("field") or a in seen or a not in ("font-size", "font-family"):
                continue
            seen.add(a)
            (sizes if a == "font-size" else families).add(f.get("value"))
    return sizes, families


def _delta_measures(ws) -> list:
    out, shown = [], _shown_measures(ws)
    for dep in ws.iter("datasource-dependencies"):
        cols = {c.get("name"): c for c in dep.findall("column")}
        for ci in dep.findall("column-instance"):
            c = cols.get(ci.get("column"))
            if ci.get("type") != "quantitative" or c is None or ci.get("name") not in shown:
                continue
            cap = re.sub("[\u200b\u2060]", "", c.get("caption") or c.get("name") or "")
            fmt = c.get("default-format") or ""
            if "↑" in fmt or "▲" in fmt or DELTA_CAPTION.search(cap):
                out.append(cap)
    return out


def judge_tables(root, sheets: dict, placed: set) -> list:
    """Three table rules by XML: one typography, zebra rows, deltas coloured by sign."""
    mixed, flat, grey = [], [], []
    for name, ws in sheets.items():
        if name not in placed or not _text_table(ws):
            continue
        sizes, families = _table_fonts(ws)
        if len(sizes) > 1 or len(families) > 1:
            mixed.append(f"{name}: {', '.join(sorted(sizes | families))}")
        if not any(f.get("attr") == "band-color" and f.get("scope") == "rows"
                   for f in ws.iter("format")):
            flat.append(name)
        deltas = _delta_measures(ws)
        if deltas and ws.find(".//encodings/color") is None:
            grey.append(f"{name}: {', '.join(dict.fromkeys(deltas))}")
    out = []
    if mixed:
        out.append(_f("table", "T1", WARN, "", mixed[0].split(":")[0],
                      f"mixed typography in tables: {len(mixed)} sheets",
                      "; ".join(mixed[:4]), "style.uniform_type: one family, size 10"))
    if flat:
        out.append(_f("table", "T2", WARN, "", flat[0],
                      f"tables without zebra rows: {len(flat)} sheets",
                      ", ".join(flat[:6]), "style.row_bands: every other row #f6f1ef"))
    if grey:
        out.append(_f("table", "T3", WARN, "", grey[0].split(":")[0],
                      f"deltas not colored by sign: {len(grey)} sheets",
                      "; ".join(grey[:4]), "edit_sign_color: growth green, decline red"))
    return out


def judge_bands(page: str, deep: dict) -> list:
    """An empty page band: no content across the canvas at that height."""
    cw, ch = (deep.get("canvas") or [0, 0])[:2]
    if not ch:
        return []
    spans = sorted((c[1], c[1] + c[3]) for z in deep.get("zones") or []
                   for c in [z.get("content")] if c)
    if not spans:
        return []
    gaps, cur = [], spans[0][1]
    for a, b in spans[1:]:
        if a > cur:
            gaps.append((cur, a))
        cur = max(cur, b)
    need = max(EMPTY_BAND_PX, EMPTY_BAND_SHARE * ch)
    big = [(a, b) for a, b in gaps if b - a >= need]
    if not big:
        return []
    a, b = max(big, key=lambda g: g[1] - g[0])
    return [_f("emptiness", "E3", WARN, page, "",
               f"empty page band {b - a:.0f} px ({(b - a) / ch:.0%} of the height)",
               f"y {a:.0f}-{b:.0f} px of {ch}; such bands {len(big)}",
               "move blocks up or shrink zones to their content")]


def judge_page(page: str, deep: dict, fr_page: dict, sheets: dict) -> list:
    """All findings of one page."""
    out = []
    by_id = {z.get("id"): z for z in (fr_page or {}).get("zones") or []}
    zones = deep.get("zones") or []
    for z in zones:
        ws = sheets.get(z.get("name")) if z.get("sheet") else None
        st = sheet_style(ws)
        out += judge_zone(page, z, st, by_id.get(z.get("id")))
        if z.get("sheet"):
            out += judge_colors(page, z, ws)
            out += judge_book_ink(page, z.get("name", ""), ws)
    for sq in (fr_page or {}).get("squashed") or []:
        out.append(_f("overlap", "P1", ERROR, page, sq.get("name", ""),
                      f"table rows overlap: {sq.get('rows')} rows",
                      f"row {sq.get('row_px')} px at font {sq.get('font_px')} px "
                      f"(fit '{sq.get('fit')}')",
                      "remove fit height, use top-N or enlarge the zone"))
    out += judge_drift(page, zones)
    out += judge_strips(page, zones, sheets)
    out += judge_floating(page, zones)
    out += judge_bands(page, deep)
    return out


def _fallback(page: str, fr_page: dict) -> list:
    """Without the detailed measurement: only what the frame reported (warn level)."""
    out = []
    for c in fr_page.get("clipped") or []:
        out.append(_f("clipped", "K0", WARN, page, c.get("name", ""),
                      f"the frame clips labels: {c.get('cut')} of {c.get('total')}",
                      ", ".join(f"'{s[:30]}'" for s in c.get("samples") or []),
                      "see the detailed critic measurement"))
    for sq in fr_page.get("squashed") or []:
        out.append(_f("overlap", "P1", ERROR, page, sq.get("name", ""),
                      f"table rows overlap: {sq.get('rows')} rows",
                      f"row {sq.get('row_px')} px at font {sq.get('font_px')} px",
                      "remove fit height, use top-N or enlarge the zone"))
    return out


_ORDER = {ERROR: 0, WARN: 1, INFO: 2}


def wrap_lines(text: str, width: float, pt: float) -> int:
    """Lines a header takes when wrapped word by word into `width` px at `pt`; a word wider
    than the column cannot wrap and is clipped, reported as 99."""
    from . import layoutmodel as LM
    if not text.strip():
        return 0
    lines, cur, sp = 1, 0.0, LM.text_width(" ", pt)
    for word in text.split():
        ww = LM.text_width(word, pt)
        if ww > width:
            return 99
        if cur and cur + sp + ww > width:
            lines, cur = lines + 1, ww
        else:
            cur += (sp if cur else 0.0) + ww
    return lines


def content_needs(path: str, out_dir: str = "", frame_result: dict | None = None) -> dict:
    """Space each text sheet needs as the frame draws it: {sheet: {h, w, title_lines, rows, cols, head_lines}}.

    `cols` are natural column widths, ignoring widths set in the XML, so a builder that widens a
    column from them reaches the same answer on every pass."""
    from . import frame, safexml
    fr = frame_result or frame.check(
        path, out_dir=out_dir or os.path.join(tempfile.gettempdir(), "twkit_needs"), shots=False)
    sheets = _sheets(safexml.from_twbx(path))
    opts = {"title_px": {n: sheet_style(ws)["title_pt"] * PX_PER_PT for n, ws in sheets.items()}}
    out: dict = {}
    for pg in fr.get("pages") or []:
        pf = _page_file(pg)
        if not pf or not os.path.exists(pf):
            continue
        d, err = probe(pf, opts)
        if d is None:
            raise RuntimeError(f"{os.path.basename(pf)}: no measurement ({err})")
        for z in d.get("zones") or []:
            name = z.get("name") or ""
            tbs = [t for t in (z.get("tables") or []) if t.get("first") is not None]
            if not (z.get("sheet") and name and tbs):
                continue
            x, y, w, h = z["box"]
            # a stretched table fills its zone: its drawn bottom is the zone, not the need
            bottom = max(t["first"] + t.get("nbody", 0) * t["natrh"] if t.get("natrh") else
                         t.get("last") or t["first"] + t.get("nbody", 0) * (t.get("rowh") or 24)
                         for t in tbs)
            e = out.setdefault(name, {"h": 0, "w": 0})
            e["h"] = max(e["h"], round(bottom - y + 8))
            cols = [c for c in (tbs[0].get("cols") or []) if c]
            if cols and name in sheets:
                st, fit = sheet_style(sheets[name]), z.get("fit", "standard")
                need = column_widths(cols, st, w - 12, fit)[3]
                e["w"] = max(e["w"], round(need + 12))
                nat = column_widths([dict(c, src="auto") for c in cols], st, w - 12, fit)[0]
                e["cols"] = [round(x) for x in nat]
                have = column_widths(cols, st, w - 12, fit)[0]
                e["head_lines"] = max([wrap_lines((c.get("head") or {}).get("text") or "", hv - 10,
                                                  st["label_pt"]) for c, hv in zip(cols, have)
                                       if c.get("head")] or [0])
            e["title_lines"] = (z.get("title") or {}).get("lines", 0)
            e["rows"] = sum(t.get("nbody", 0) for t in tbs)
    return out


def critique(path: str, out_dir: str = "", frame_result: dict | None = None,
             deep: bool = True) -> dict:
    """Publish a workbook into the frame (`frame.check`), measure the pages and report findings."""
    from . import frame, safexml
    if not os.path.exists(path):
        return {"book": os.path.basename(path), "verdict": f"file not found: {path}", "findings": [],
                "by_class": {}, "not_checked": [f"file not found: {path}"]}
    out_dir = out_dir or os.path.join(tempfile.gettempdir(), "twkit_critic")
    if frame_result is None:
        saved = {k: dict(v) for k in ("_SEP", "_MARK")
                 if isinstance(v := getattr(frame, k, None), dict)}
        try:
            fr = frame.check(path, out_dir=out_dir, shots=True)
        finally:
            for k, v in saved.items():
                getattr(frame, k).clear()
                getattr(frame, k).update(v)
    else:
        fr = frame_result
    root = safexml.from_twbx(path)
    sheets = _sheets(root)
    gaps: list = []
    if fr.get("data") and fr["data"] != "present":
        gaps.append(f"frame without data: {fr['data']}")
    findings: list = []
    placed: set = set()
    shots = []
    for pg in fr.get("pages") or []:
        page = pg.get("page", "")
        if pg.get("image"):
            shots.append(pg["image"])
        if pg.get("error"):
            gaps.append(f"page '{page}': no frame measurement ({pg['error']})")
            continue
        placed |= {z.get("name") for z in pg.get("zones") or [] if z.get("name")}
        d, err = None, ""
        pf = _page_file(pg)
        if deep and pf and os.path.exists(pf):
            opts = {"title_px": {n: sheet_style(ws)["title_pt"] * PX_PER_PT
                                 for n, ws in sheets.items()}}
            d, err = probe(pf, opts)
        elif deep:
            err = "no page HTML"
        if d and not d.get("error"):
            findings += judge_page(page, d, pg, sheets)
            for z in d.get("zones") or []:
                e = z.get("empty") or ""
                if z.get("sheet") and e and e != "no data" and not e.startswith("empty"):
                    gaps.append(f"'{z.get('name')}': the frame did not draw the sheet ({e[:60]})")
        else:
            if deep:
                gaps.append(f"page '{page}': detailed measurement not run "
                            f"({err or (d or {}).get('error', '?')}); frame counters only")
            findings += _fallback(page, pg)
    findings += judge_book_colors(root, sheets, placed)
    findings += judge_fonts(root, sheets, placed)
    findings += judge_tables(root, sheets, placed)
    findings.sort(key=lambda f: (_ORDER.get(f["level"], 3), CLASSES.index(f["class"])
                                 if f["class"] in CLASSES else 9))
    by_cls = {c: {"error": 0, "warn": 0} for c in CLASSES}
    for f in findings:
        if f["level"] in (ERROR, WARN):
            by_cls.setdefault(f["class"], {"error": 0, "warn": 0})[f["level"]] += 1
    hard = sum(v["error"] for v in by_cls.values())
    soft = sum(v["warn"] for v in by_cls.values())
    if not fr.get("pages"):
        gaps.append("the workbook has no pages; the view is not checked")
    verdict = ("no pages; the view is not checked" if not fr.get("pages") else
               "view clean" if not hard and not soft else
               f"reading breaks {hard}, notes {soft}" if hard else f"notes {soft}")
    return {"book": fr.get("book") or os.path.basename(path), "verdict": verdict,
            "findings": findings, "by_class": by_cls, "not_checked": gaps,
            "images": shots, "frame_limits": list(FRAME_GAPS)}


def format_report(r: dict, limit: int = 40) -> str:
    lines = [f"View critic - {r.get('book', '?')}: {r.get('verdict', '?')}"]
    cls = r.get("by_class") or {}
    if cls:
        lines.append("  " + " · ".join(f"{k} {v['error']}/{v['warn']}" for k, v in cls.items())
                     + "   (breaks/notes)")
    for f in (r.get("findings") or [])[:limit]:
        where = f" [{f['page']}]" if f.get("page") else ""
        lines.append(f"  {f['level'].upper():5s} {f['code']} {f['class']}{where} "
                     f"{f['sheet'][:40]}: {f['what']}")
        lines.append(f"        ↳ {f['evidence'][:160]}")
    rest = len(r.get("findings") or []) - limit
    if rest > 0:
        lines.append(f"  ...and {rest} more")
    for g in r.get("not_checked") or []:
        lines.append(f"  ? not checked: {g}")
    return "\n".join(lines)

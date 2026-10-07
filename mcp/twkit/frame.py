"""Frame: a Tableau workbook rendered as a local HTML page for viewing in Chrome."""
from __future__ import annotations

import html
import json
import os
import pathlib
import re

from . import layoutmodel as LM
from . import render as R

TABLEAU_RCC = ("/Applications/Tableau Desktop (Apple silicon) 2026.1.app/Contents/Resources/"
               "tablangres.rcc")


def _sfnt_names(blob: bytes) -> tuple:
    import struct
    n, = struct.unpack(">H", blob[4:6])
    for i in range(n):
        tag, _, off, ln = struct.unpack(">4sIII", blob[12 + 16 * i:28 + 16 * i])
        if tag != b"name":
            continue
        cnt, so = struct.unpack(">HH", blob[off + 2:off + 6])
        got = {}
        for j in range(cnt):
            pid, eid, _lid, nid, l2, o2 = struct.unpack(">6H", blob[off + 6 + 12 * j:off + 18 + 12 * j])
            if nid in (1, 2) and nid not in got:
                raw = blob[off + so + o2:off + so + o2 + l2]
                got[nid] = raw.decode("utf-16-be" if pid in (0, 3) else "latin-1", "replace")
        return got.get(1, ""), got.get(2, "")
    return "", ""


def tableau_fonts(rcc: str = TABLEAU_RCC) -> list:
    import struct
    import tempfile
    cache = os.path.join(tempfile.gettempdir(), "twkit_fonts")
    idx = os.path.join(cache, "index.json")
    if os.path.exists(idx):
        return [tuple(x) for x in json.load(open(idx))]
    if not os.path.exists(rcc):
        return []
    d = open(rcc, "rb").read()
    os.makedirs(cache, exist_ok=True)
    out, seen = [], set()
    for m in re.finditer(rb"\x00\x01\x00\x00|OTTO", d):
        o = m.start()
        n, = struct.unpack(">H", d[o + 4:o + 6])
        if not 5 <= n <= 40:
            continue
        recs = [d[o + 12 + 16 * i:o + 28 + 16 * i] for i in range(n)]
        if not all(re.fullmatch(rb"[A-Za-z0-9/ ]{4}", r[:4]) for r in recs):
            continue
        end = max(struct.unpack(">II", r[8:16])[0] + struct.unpack(">II", r[8:16])[1] for r in recs)
        if b"name" not in [r[:4] for r in recs] or end > 5_000_000:
            continue
        blob = d[o:o + end]
        try:
            fam, sub = _sfnt_names(blob)
        except struct.error:
            continue
        if not fam.startswith("Tableau") or (fam, sub) in seen:
            continue
        seen.add((fam, sub))
        path = os.path.join(cache, f"{fam}-{sub}.ttf".replace(" ", ""))
        open(path, "wb").write(blob)
        out.append((fam, "bold" in sub.lower(), path))
    json.dump(out, open(idx, "w"))
    return out


def font_css() -> str:
    return "".join(f"@font-face{{font-family:'{f}';font-weight:{700 if b else 400};"
                   f"src:url('{pathlib.Path(p).as_uri()}')}}" for f, b, p in tableau_fonts())


CANVAS_MARGIN = 12
FONT = "'Tableau Book', 'Benton Sans', Arial, sans-serif"
INK, MUTED, GRID, BAR, SURFACE = "#333333", "#7a7a7a", "#e6e6e6", "#4e79a7", "#ffffff"


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


_SEP = {"group": ","}
_MARK = {"color": BAR}


def mark_color(ws) -> str:
    for sr in (ws.iter("style-rule") if ws is not None else ()):
        if sr.get("element") == "mark":
            for f in sr.findall("format"):
                if f.get("attr") == "mark-color" and (f.get("value") or "").startswith("#"):
                    return f.get("value")[:7]
    return BAR


_ALIAS: dict = {}


def _alias_key(k: str) -> tuple:
    s = str(k)
    if s == "%null%":
        return ("null", None)
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return ("s", s[1:-1])
    if s.lower() in ("true", "false"):
        return ("b", s.lower() == "true")
    f = _num(s)
    return ("n", f) if f is not None else ("s", s)


def column_alias_map(root) -> dict:
    out: dict = {}
    for ds in (root.findall("datasources/datasource") if root is not None else ()):
        if ds.get("name") == "Parameters":
            continue
        for c in ds.findall("column"):
            al = c.find("aliases")
            if al is None:
                continue
            name = (c.get("name") or "").strip("[]")
            m = out.setdefault(name, {})
            for a in al.findall("alias"):
                k, v = a.get("key"), a.get("value")
                if k is None or v is None:
                    continue
                if name == ":Measure Names":
                    m.setdefault(("mn", (re.findall(r"\[[^\]]+\]", k) or [""])[-1]), v)
                else:
                    m.setdefault(_alias_key(k), v)
    return out


def _ref_column(ref: str) -> str:
    m = re.match(r"^\[(?:[a-z]+:)?(.+?):[a-z]{2}(?::\d+)?\]$", ref or "")
    return m.group(1) if m else (ref or "").strip("[]")


def value_alias(v, ref: str) -> str | None:
    m = _ALIAS.get(_ref_column(ref)) if ref else None
    if not m:
        return None
    if v is None or str(v) in ("None", "nan", "NaN", "NULL"):
        return m.get(("null", None))
    if isinstance(v, bool):
        return m.get(("b", v))
    sv = str(v)
    if ("s", sv) in m:
        return m[("s", sv)]
    if sv.lower() in ("true", "false") and ("b", sv.lower() == "true") in m:
        return m[("b", sv.lower() == "true")]
    f = _num(sv)
    return m.get(("n", f)) if f is not None else None


def measure_alias(mref: str) -> str | None:
    return _ALIAS.get(":Measure Names", {}).get(("mn", mref or ""))
_MON = ["January", "February", "March", "April", "May", "June", "July", "August",
        "September", "October", "November", "December"]


def fmt_icu_date(v, mask: str) -> str | None:
    if not mask or not mask.startswith("i"):
        return None
    sv = str(v or "")
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", sv)
    if m:
        y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif re.fullmatch(r"\d{1,2}", sv) and 1 <= int(sv) <= 12:
        y, mo, dd = 0, int(sv), 1
    else:
        return None
    name = _MON[mo - 1]

    def tok(mt):
        t = mt.group(0)
        c, n = t[0], len(t)
        if c in "ML":
            return name[0] if n >= 5 else name if n == 4 else name[:3] if n == 3 else f"{mo:0{n}d}"
        if c in "yY":
            return f"{y % 100:02d}" if n == 2 else f"{y}"
        if c == "d":
            return f"{dd:0{n}d}"
        return t
    return re.sub(r"M+|L+|y+|Y+|d+", tok, mask[1:])


def fmt_date(v, mask: str) -> str | None:
    import datetime as _dt
    icu = fmt_icu_date(v, mask)
    if icu is not None:
        return icu
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if not m or not mask or not mask.startswith("*") or not re.search(r"[dmy]", mask):
        return None
    d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    out = mask[1:]
    for tok, val in (("mmmmm", _MON[d.month - 1][0]), ("mmmm", _MON[d.month - 1]),
                     ("mmm", _MON[d.month - 1][:3]),
                     ("yyyy", f"{d.year}"), ("YYYY", f"{d.year}"), ("yy", f"{d.year % 100:02d}"),
                     ("dd", f"{d.day:02d}"), ("mm", f"{d.month:02d}"), ("d", f"{d.day}")):
        out = re.sub(rf"(?<![\x01A-Za-z]){tok}(?![A-Za-z\x02])", f"\x01{val}\x02", out)
    return re.sub("[\x01\x02]", "", out)


_LCID_CUR = {1033: ("$", "", ",", "."), 2057: ("£", "", ",", "."), 4105: ("$", "", ",", "."),
             3081: ("$", "", ",", "."), 1031: ("", " €", ".", ","), 1036: ("", " €", " ", ","),
             1040: ("", " €", ".", ","), 3082: ("", " €", ".", ","), 1043: ("€ ", "", ".", ","),
             1049: ("", " ₽", " ", ","), 1041: ("¥", "", ",", "."), 6153: ("€", "", ",", ".")}


def _fmt_currency_lcid(f: float, lcid: int) -> str:
    pre, suf, grp, dot = _LCID_CUR.get(lcid, ("", "", ",", "."))
    num = f"{abs(f):,.2f}".replace(",", "\0").replace(".", dot).replace("\0", grp)
    return f"{'-' if f < 0 else ''}{pre}{num}{suf}"


def fmt_mask(v, mask: str) -> str | None:
    f = _num(v)
    if f is None or not mask:
        return None
    m = re.sub(r"![A-Za-z]{2,3}(?:_[A-Za-z]{2,4})?!", "", mask)
    lc = re.fullmatch(r"C(\d{4,5})%", m)
    if lc:
        return _fmt_currency_lcid(f, int(lc.group(1)))
    if m.startswith("*"):
        m = m[1:]
    segs = m.split(";")
    pos = segs[0]
    neg = segs[1] if len(segs) > 1 else None
    zero = segs[2] if len(segs) > 2 else None
    if f == 0 and zero is not None:
        return zero.strip()
    seg = neg if (f < 0 and neg) else pos
    val = abs(f) if (f < 0 and neg) else f
    kind = seg[:1] if seg[:1] in "pnc" else ""
    body = seg[1:] if kind else seg
    head = re.split(r"[#0]", body, maxsplit=1)[0]
    pre = re.sub(r'"([^"]*)"', r"\1", head)
    sm = re.search(r"[#0](,+)(?![#0,])", body)
    scale = 1000.0 ** len(sm.group(1)) if sm else 1.0
    sl = re.search(r",+(?:\.[0#]+)?([KMB])", body) if sm else None
    suf = sl.group(1) if sl else ""
    dec = len(re.search(r"\.(0+)", body).group(1)) if re.search(r"\.(0+)", body) else 0
    pct = "%" in re.sub(r'"[^"]*"', "", body) or kind == "p"
    if pct:
        val *= 100
    from decimal import Decimal, ROUND_HALF_UP
    q = Decimal(1).scaleb(-dec)
    grp = "," if re.search(r"[#0],[#0]", body) else ""
    num = f"{float(Decimal(str(val / scale)).quantize(q, rounding=ROUND_HALF_UP)):{grp}.{dec}f}"
    if _SEP["group"] != ",":
        num = num.replace(",", _SEP["group"])
    core = re.search(r"[#0][#0,.]*(?:[KMB])?%?", body)
    tail = re.sub(r'"([^"]*)"', r"\1", body[core.end():]) if core else ""
    if suf and tail.startswith(suf):
        tail = tail[len(suf):]
    if pct and tail.startswith("%"):
        tail = tail[1:]
    return f"{pre}{num}{suf}{'%' if pct else ''}{tail}".strip()


def _fmt(v, caption: str = "", mask: str = "") -> str:
    if v is None or str(v) in ("None", "nan", "NaN", "NULL"):
        return ""
    m = fmt_mask(v, mask)
    if m is not None:
        return m
    """A number as a person would read it, guessed from the measure caption (no mask)."""
    f = _num(v)
    if f is None:
        dv = (fmt_date(v, mask) if mask else None) or fmt_default_date(v)
        if dv is not None:
            return dv
        return "" if v is None else str(v)
    low = caption.lower()
    if "%" in caption and abs(f) <= 1.5:
        return f"{f * 100:,.1f}%"
    if "€" in caption:
        return f"€ {f:,.0f}"
    return f"{f:,.0f}" if float(f).is_integer() or abs(f) >= 100 else f"{f:,.2f}"


def fmt_default_date(v) -> str | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}):(\d{2}))?(?:\.\d+)?", str(v or ""))
    if not m:
        return None
    y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
    us = _SEP.get("locale", "").startswith("en_US")
    out = f"{mo}/{d}/{y}" if us else f"{d:02d}/{mo:02d}/{y}"
    if m.group(4) is not None and (m.group(4), m.group(5), m.group(6)) != ("00", "00", "00"):
        hh, mm, ss = int(m.group(4)), m.group(5), m.group(6)
        out += (f" {hh % 12 or 12}:{mm}:{ss} {'AM' if hh < 12 else 'PM'}" if us
                else f" {hh:02d}:{mm}:{ss}")
    return out


_WD = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def fmt_dim(v, ref: str = "", mask: str = "") -> str:
    al = value_alias(v, ref) if ref else None
    if al is not None:
        return al
    if v is None or str(v) in ("None", "nan", "NaN", "NULL"):
        return "Null"
    sv = str(v)
    if mask:
        d = fmt_date(sv, mask)
        if d is not None:
            return d
        if _num(sv) is not None and re.search(r"[#0]", mask) and not mask.startswith("*"):
            got = fmt_mask(sv, mask)
            if got is not None:
                return got
    der = (re.match(r"\[([a-z]+):", ref or "") or [None, ""])[1]
    n = _num(sv)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", sv)
    if der in ("yr", "qr", "mn", "dy", "wd", "wk", "hr") and n is not None and float(n).is_integer():
        k = int(n)
        if der == "qr" and 1 <= k <= 4:
            return f"Q{k}"
        if der == "mn" and 1 <= k <= 12:
            return _MON[k - 1]
        if der == "wd" and 1 <= k <= 7:
            return _WD[k - 1]
        if der == "wk":
            return f"Week {k}"
        return str(k)
    if m:
        y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if der in ("yr", "tyr"):
            return str(y)
        if der in ("qr", "tqr"):
            return f"Q{(mo - 1) // 3 + 1}" + (f" {y}" if der == "tqr" else "")
        if der in ("my", "tmn"):
            return f"{_MON[mo - 1]} {y}"
        if der == "mdy":
            return f"{_MON[mo - 1]} {dd}, {y}"
        return fmt_default_date(sv) or sv
    if n is not None and float(n).is_integer() and re.fullmatch(r"-?\d+(\.0+)?", sv):
        return str(int(n))
    return sv


def _style(z) -> str:
    st = z.style or {}
    css = []
    if st.get("background-color") and st["background-color"] not in ("#00000000",):
        css.append(f"background:{st['background-color']}")
    if st.get("border-style") and st["border-style"] != "none":
        css.append(f"border:{st.get('border-width', '1')}px {st['border-style']} "
                   f"{st.get('border-color', '#000')}")
    return ";".join(css)


def _opaque(c: str | None) -> str | None:
    c = (c or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", c) or c[7:9] == "00":
        return None
    return c


def _sides(st: dict, key: str) -> tuple:
    base = _num(st.get(key))
    sides = [_num(st.get(f"{key}-{s}")) for s in ("top", "right", "bottom", "left")]
    return [v if v is not None else (base or 0.0) for v in sides], \
        base is not None or any(v is not None for v in sides)


def zone_box(z) -> tuple:
    st = z.style or {}
    m, hm = _sides(st, "margin")
    p, hp = _sides(st, "padding")
    for a, b, size in ((0, 2, z.h), (3, 1, z.w)):
        if m[a] + m[b] + p[a] + p[b] > 0.5 * size:
            m[a] = m[b] = p[a] = p[b] = 0.0
    bg = _opaque(st.get("background-color"))
    bw = (_num(st.get("border-width")) or 0.0) if st.get("border-style") not in (None, "", "none") else 0.0
    css = []
    if any(m):
        css.append("border-style:solid;border-color:transparent;border-width:"
                   + " ".join(f"{v:.0f}px" for v in m))
    if bg:
        css.append(f"background:{bg};background-clip:padding-box")
    if bw:
        css.append(f"box-shadow:inset 0 0 0 {bw:.0f}px {_opaque(st.get('border-color')) or '#000000'}")
    if hm or hp or bw:
        css.append("padding:" + " ".join(f"{v + bw:.0f}px" for v in p))
    ins = tuple(a + b + bw for a, b in zip(m, p)) if (hm or hp or bw) else (0.0, 0.0, 0.0, 0.0)
    return ";".join(css), hm or hp, ins


def sheet_background(ws) -> str | None:
    for sr in (ws.findall("table/style/style-rule") if ws is not None else ()):
        if sr.get("element") != "table":
            continue
        for f in sr.findall("format"):
            if f.get("attr") == "background-color" and not f.get("field") and not f.get("scope"):
                return _opaque(f.get("value"))
    return "#ffffff"


def _sheet_kind(ws, rows: list, ndims: int, mrefs: list | None = None) -> str:
    from . import sketch as SK
    from . import dryrun as DR
    if ws is None:
        return "table"
    mark = LM.mark_class(ws)
    if any("(generated)" in r for r in _shelf_refs(ws, "rows") + _shelf_refs(ws, "cols")):
        return "map"
    axis_measure = any(r.endswith(("qk]",)) or re.search(r":qk:\d+\]$", r)
                       for r in _shelf_refs(ws, "rows") + _shelf_refs(ws, "cols"))
    if any(p.find("mark") is not None and p.find("mark").get("class") == "Pie" and
           p.find("encodings/wedge-size") is not None and
           "[Multiple Values]" not in (p.find("encodings/wedge-size").get("column") or "")
           for p in ws.iter("pane")):
        return "pie"
    fields = [t for ln in SK.card_lines(ws) for t, _, _, f in ln if f]
    mv_only = bool(fields) and all("[Multiple Values]" in t for t in fields)
    if mv_only and "[Multiple Values]" not in _shelf_refs(ws, "rows") + _shelf_refs(ws, "cols"):
        return "table"
    if SK.card_lines(ws) and not mv_only and \
            (not axis_measure or _axis_is_constant(ws, rows, ndims, mrefs)):
        return "card"
    if mark in ("Line", "Area", "Automatic") and "[Multiple Values]" in _shelf_refs(ws, "rows") and \
            any(re.match(r"\[(mn|my|tmn|tdy|twk|tqr|tyr|qr|yr|wk|dy):", r) for r in _shelf_refs(ws, "cols")):
        return "mvline"
    if any(m_ == "Bar" for _r, m_, _s in folded(ws, "rows")[0]) and _shelf_refs(ws, "cols"):
        return "bar"
    if mark in ("Line", "Area"):
        return "line"
    blank_dims = ndims and rows and all(str(x or "").strip() == "" for r in rows for x in r[:ndims])
    if mark in ("Circle", "Shape") and (blank_dims or not any(
            re.search(r":(nk|ok)(:\d+)?\]$", r_) for r_ in _shelf_refs(ws, "rows") + _shelf_refs(ws, "cols"))) \
            and len(rows) <= 3 and not scatter_refs(ws):
        return "glyph"
    if mark in ("Circle", "Shape") and scatter_refs(ws) and \
            not _axis_is_constant(ws, rows, ndims, mrefs):
        return "scatter"
    if mark == "Automatic" and any(re.match(r"\[t(yr|qr|mn|wk|dy):", r) for r in _shelf_refs(ws, "cols")) \
            and any(r.endswith("qk]") or re.search(r":qk:\d+\]$", r) for r in _shelf_refs(ws, "rows")):
        return "line"
    if mark == "Pie":
        return "pie"
    marks = {(p.find("mark").get("class") if p.find("mark") is not None else "Automatic")
             for p in ws.iter("pane")} or {"Automatic"}
    if marks == {"Automatic"} and axis_measure and not _axis_is_constant(ws, rows, ndims, mrefs):
        return "bar"
    if mark in ("Square", "Heatmap", "Text", "Automatic") and \
            "[:Measure Names]" in _shelf_refs(ws, "cols") and _enc_ref(ws, "text") == "[Multiple Values]":
        return "table"
    if mark in ("Square", "Heatmap") and ndims >= 2:
        return "matrix"
    if mark == "Square" and ndims == 1 and ws.find(".//encodings/size") is not None:
        return "treemap"
    if (DR._is_text_table(ws) or mark in ("Text", "Automatic")) and ws.find(
            ".//encodings/text") is not None and _all_headers_hidden(ws):
        return "bigtext"
    if DR._is_text_table(ws) or (mark in ("Text", "Automatic") and ndims >= 2):
        return "table"
    if mark == "Text":
        return "table"
    return "bar"


_AGG_REF = re.compile(r"^\[(sum|avg|cnt|ctd|cntd|usr|min|max|attr|median|agg):")


def pane_style(ws, ref: str = "") -> dict:
    from .dryrun import inst_refs
    out = {"color": None, "labels": None}
    for p in (ws.iter("pane") if ws is not None else ()):
        ax = p.get("y-axis-name") or p.get("x-axis-name") or ""
        if ref and (inst_refs(ax) or [""])[0] != ref:
            continue
        for f in p.iter("format"):
            if f.get("attr") == "mark-color" and (f.get("value") or "").startswith("#"):
                out["color"] = out["color"] or f.get("value")[:7]
            if f.get("attr") == "mark-labels-show" and out["labels"] is None:
                out["labels"] = f.get("value") == "true"
        if ref:
            break
    return out


def line_labels(ws) -> dict | None:
    for p in (ws.iter("pane") if ws is not None else ()):
        m = p.find("mark")
        if m is None or m.get("class") not in ("Line", "Area"):
            continue
        f = {x.get("attr"): x.get("value") for x in p.iter("format")
             if (x.get("attr") or "").startswith("mark-labels")}
        if f.get("mark-labels-show") != "true":
            continue
        mode = f.get("mark-labels-mode") or "all"
        if mode in ("selection", "highlight"):
            return None
        return {"mode": mode, "first": f.get("mark-labels-line-first") != "false",
                "last": f.get("mark-labels-line-last") != "false",
                "min": f.get("mark-labels-range-min") != "false",
                "max": f.get("mark-labels-range-max") != "false"}
    return None


def pick_labels(pts: list, spec: dict) -> list:
    n = len(pts)
    if not n or not spec:
        return []
    mode = spec["mode"]
    if mode == "line-ends":
        return sorted({k for k, on in ((0, spec["first"]), (n - 1, spec["last"])) if on})
    if mode == "range":
        ys = [v for _, v in pts]
        out = set()
        if spec["max"]:
            out.add(ys.index(max(ys)))
        if spec["min"]:
            out.add(ys.index(min(ys)))
        return sorted(out)
    return list(range(n))


def marks_shown(ws, ref: str = "") -> bool:
    if ws is None:
        return True
    st = pane_style(ws, ref)
    if st["labels"] is None and ref:
        st = pane_style(ws)
    return bool(st["labels"]) or ws.find(".//customized-label") is not None


def folded(ws, scope: str) -> tuple:
    from .dryrun import inst_refs
    shelf = list(dict.fromkeys(r for r in _shelf_refs(ws, scope) if re.search(r":qk(:\d+)?\]$", r))) \
        if ws is not None else []
    fold, sync = False, False
    for e in (ws.iter("encoding") if ws is not None else ()):
        if e.get("attr") == "space" and e.get("scope") == scope and e.get("fold") == "true":
            if (inst_refs(e.get("field") or "") or [""])[0] in shelf:
                fold = True
                sync |= e.get("synchronized") == "true"
    refs = shelf
    if not fold or len(refs) < 2:
        return [], False
    marks, shows = {}, {}
    for p in ws.iter("pane"):
        ax = p.get("y-axis-name" if scope == "rows" else "x-axis-name")
        if ax:
            r = (inst_refs(ax) or [""])[0]
            marks[r] = p.find("mark").get("class") if p.find("mark") is not None else "Automatic"
            shows[r] = any(f.get("attr") == "mark-labels-show" and f.get("value") == "true"
                           for f in p.iter("format"))
    order = [r for r in _shelf_refs(ws, scope) if r in refs]
    return [(r, marks.get(r, "Automatic"), shows.get(r, False)) for r in dict.fromkeys(order)], sync


def scatter_refs(ws) -> tuple | None:
    def first(tag):
        return next((r for r in _shelf_refs(ws, tag) if _AGG_REF.match(r)
                     and re.search(r":qk(:\d+)?\]$", r)), None)
    x, y = first("cols"), first("rows")
    return (x, y) if x and y else None


def _axis_ticks_of(ws, ref: str, lo: float, hi: float, px: float, amask: str,
                   horizontal: bool) -> tuple:
    import math
    for e in (ws.iter("encoding") if ws is not None else ()):
        if e.get("attr") == "space" and (e.get("field") or "").endswith(ref) and \
                _num(e.get("major-spacing")):
            st = _num(e.get("major-spacing"))
            a2, b2 = axis_domain(lo, hi)
            org = _num(e.get("major-origin")) or 0.0
            ks = range(math.ceil((a2 - org) / st - 1e-9), math.floor((b2 - org) / st + 1e-9) + 1)
            if len(ks) <= 60:
                return a2, b2, [round(org + k * st, 10) for k in ks]
    if horizontal:
        return nice_axis(lo, hi, px, min_px=20.0, label=lambda t, ts: axis_label(t, ts, amask or ""))
    return nice_axis(lo, hi, px)


def const_measure(root, ref: str):
    m = re.match(r"^\[(?:[a-z]+:)?(.+?):[a-z]{2}(?::\d+)?\]$", ref or "")
    if root is None or not m:
        return None
    for c in root.iter("column"):
        if (c.get("name") or "").strip("[]") != m.group(1) or c.find("calculation") is None:
            continue
        f = c.find("calculation").get("formula") or ""
        f = re.sub(r"\{\s*FIXED\s*:\s*(.*?)\s*\}", r"\1", f.strip(), flags=re.I | re.S)
        for _ in range(3):
            f = re.sub(r"\b(?:SUM|AVG|MIN|MAX|ATTR|MEDIAN)\s*\(\s*(-?\d+(?:\.\d+)?)\s*\)", r"\1",
                       f.strip(), flags=re.I)
        return _num(f) if re.fullmatch(r"-?\d+(?:\.\d+)?", f.strip()) else None
    return None


def ref_line_columns(root, ws, mrefs: list) -> dict:
    from .dryrun import inst_refs
    out = {}
    for rl in (ws.iter("reference-line") if ws is not None else ()):
        vref = (inst_refs(rl.get("value-column") or "") or [""])[0]
        if vref and vref not in mrefs:
            v = const_measure(root, vref)
            if v is not None:
                out[vref] = [v]
    return out


def ref_lines(ws, ref: str, values: list, mask: str, columns: dict | None = None) -> list:
    from .dryrun import inst_refs
    out = []
    for rl in (ws.iter("reference-line") if ws is not None else ()):
        if not (rl.get("axis-column") or "").endswith(ref):
            continue
        vref = (inst_refs(rl.get("value-column") or "") or [ref])[0]
        src = values if vref == ref else (columns or {}).get(vref)
        if not src:
            continue
        vals = sorted(v for v in src if v is not None)
        if not vals:
            continue
        f = rl.get("formula") or ""
        v = {"average": sum(vals) / len(vals), "median": vals[len(vals) // 2] if len(vals) % 2
             else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2,
             "min": vals[0], "max": vals[-1]}.get(f)
        if f == "constant":
            v = _num(rl.get("value"))
        if v is None:
            continue
        mk = mask
        for sr in ws.iter("style-rule"):
            if sr.get("element") == "refline":
                for fm in sr.findall("format"):
                    if fm.get("attr") == "text-format" and fm.get("id") == rl.get("id"):
                        mk = fm.get("value") or mk
        txt = _fmt(v, "", mk)
        lt = rl.get("label-type") or "automatic"
        lab = "" if lt == "none" else (rl.get("label") or "<Value>").replace("<Value>", txt) \
            if lt == "custom" else txt
        out.append((v, lab))
    return out


def _axis_title(ws, ref: str, caption: str) -> str:
    for sr in (ws.iter("style-rule") if ws is not None else ()):
        if sr.get("element") != "axis":
            continue
        for f in sr.findall("format"):
            if f.get("attr") == "title" and (f.get("field") or "").endswith(ref):
                return f.get("value") or ""
    return caption


def _render_scatter(ws, rows: list, ndims: int, refs: list, mrefs: list, caps: list,
                    masks: list, amasks: list, w: float, h: float, root) -> str:
    xr, yr = scatter_refs(ws)
    if xr not in mrefs or yr not in mrefs or not rows:
        return "<div class='empty'>no data</div>"
    xi, yi = ndims + mrefs.index(xr), ndims + mrefs.index(yr)
    pts = [(r, _num(r[xi]), _num(r[yi])) for r in rows if len(r) > max(xi, yi)]
    pts = [(r, x, y) for r, x, y in pts if x is not None and y is not None]
    if not pts:
        return "<div class='empty'>no data</div>"
    am = dict(zip(mrefs, amasks or []))
    xm = None if axis_hidden(ws, xr) else am.get(xr, "")
    ym = None if axis_hidden(ws, yr) else am.get(yr, "")
    xt = _axis_title(ws, xr, caps[xi] if xi < len(caps) else "") if xm is not None else ""
    yt = _axis_title(ws, yr, caps[yi] if yi < len(caps) else "") if ym is not None else ""
    H = max(30.0, h - 8 - (14 if xm is not None else 0) - (14 if xt else 0))
    ya, yb, yticks = _axis_ticks_of(ws, yr, min(p[2] for p in pts), max(p[2] for p in pts), H,
                                    ym or "", False)
    ylab = [axis_label(t, yticks, ym or "") for t in yticks] if ym is not None else []
    aw = (max((len(t) for t in ylab), default=0) * 6 + 8 if ylab else 0) + (14 if yt else 0)
    W = max(40.0, w - 12 - aw)
    xa, xb, xticks = _axis_ticks_of(ws, xr, min(p[1] for p in pts), max(p[1] for p in pts), W,
                                    xm or "", True)
    X = lambda v: (v - xa) / ((xb - xa) or 1.0) * W
    Y = lambda v: H - (v - ya) / ((yb - ya) or 1.0) * H
    cref, tref = _enc_ref(ws, "color"), _enc_ref(ws, "text") or _enc_ref(ws, "label")
    cmap = (color_map(root, ws) if root is not None else None) or {}
    ci = refs.index(cref) if cref in refs else (ndims + mrefs.index(cref) if cref in mrefs else None)
    cats = sorted({str(r[ci]) for r, _, _ in pts}) if ci is not None and ci < ndims else []
    auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(cats)}
    ti = refs.index(tref) if tref in refs else (ndims + mrefs.index(tref) if tref in mrefs else None)
    dots, labs = [], []
    for r, x, y in pts[:2000]:
        col = _MARK["color"]
        if ci is not None and ci < ndims:
            col = cmap.get(str(r[ci])) or auto.get(str(r[ci]), col)
        dots.append(f"<circle cx='{X(x):.1f}' cy='{Y(y):.1f}' r='4' fill='{col}' fill-opacity='0.75'/>")
        if ti is not None:
            txt = fmt_dim(r[ti], tref, masks[ti] if ti < len(masks) else "") if ti < ndims else \
                _fmt(r[ti], "", masks[ti] if ti < len(masks) else "")
            labs.append(f"<span class='lbl' style='position:absolute;left:{X(x) + 6:.0f}px;"
                        f"top:{Y(y) - 7:.0f}px;font-size:9px'>{_esc(txt)}</span>")
    grid = "".join(f"<line x1='0' x2='{W:.0f}' y1='{Y(t):.1f}' y2='{Y(t):.1f}' stroke='{GRID}'/>"
                   for t in yticks)
    for v, lab in ref_lines(ws, yr, [p[2] for p in pts], am.get(yr) or masks[yi] if yi < len(masks) else ""):
        grid += (f"<line x1='0' x2='{W:.0f}' y1='{Y(v):.1f}' y2='{Y(v):.1f}' stroke='#898989' "
                 f"stroke-dasharray='4 3'/>")
        if lab:
            labs.append(f"<span class='lbl' style='position:absolute;right:2px;top:{Y(v) - 13:.0f}px;"
                        f"font-size:9px;color:#898989'>{_esc(lab)}</span>")
    for v, lab in ref_lines(ws, xr, [p[1] for p in pts], am.get(xr) or masks[xi] if xi < len(masks) else ""):
        grid += (f"<line y1='0' y2='{H:.0f}' x1='{X(v):.1f}' x2='{X(v):.1f}' stroke='#898989' "
                 f"stroke-dasharray='4 3'/>")
        if lab:
            labs.append(f"<span class='lbl' style='position:absolute;left:{X(v) + 3:.0f}px;top:0;"
                        f"font-size:9px;color:#898989'>{_esc(lab)}</span>")
    yax = ""
    if ym is not None:
        yax = (f"<div class='vaxis' style='width:{aw - (14 if yt else 0)}px;height:{H:.0f}px'>" + "".join(
            f"<span class='lbl' style='top:{Y(t) - 6:.1f}px'>{_esc(s_)}</span>"
            for t, s_ in zip(yticks, ylab)) + "</div>")
        if yt:
            yax = (f"<div class='lbl' style='width:14px;height:{H:.0f}px;writing-mode:vertical-rl;"
                   f"transform:rotate(180deg);text-align:center;font-size:10px;color:{MUTED}'>"
                   f"{_esc(yt)}</div>") + yax
    xax = ""
    if xm is not None:
        xax = (f"<div class='axis hax' style='margin-left:{aw}px;width:{W:.0f}px'>" + "".join(
            f"<span class='lbl' style='left:{X(t) / W * 100:.1f}%'>{_esc(axis_label(t, xticks, xm))}</span>"
            for t in xticks) + "</div>")
        if xt:
            xax += (f"<div class='lbl' style='margin-left:{aw}px;text-align:center;font-size:10px;"
                    f"color:{MUTED}'>{_esc(xt)}</div>")
    return (f"<div style='display:flex;height:{H:.0f}px'>{yax}<div style='position:relative;"
            f"width:{W:.0f}px'><svg width='{W:.0f}' height='{H:.0f}'>{grid}{''.join(dots)}</svg>"
            f"{''.join(labs)}</div></div>{xax}")


def _render_glyph(ws, rows: list, ndims: int, refs: list, masks: list, w: float, h: float) -> str:
    st = pane_style(ws)
    col = st["color"] or _MARK["color"]
    ring = "box-shadow:0 0 0 1px #d0d0d0;" if _lum(col) > 0.9 else ""
    ink = "#ffffff" if _lum(col) < 0.55 else INK
    tref = _enc_ref(ws, "text") or _enc_ref(ws, "label")
    ti = refs.index(tref) if tref in refs[:ndims] else None
    d = max(6.0, min(24.0, h - 8, (w - 12) * 0.8))
    cells = []
    for r in rows[:3]:
        txt = fmt_dim(r[ti], tref, masks[ti] if ti < len(masks or []) else "") if ti is not None else ""
        cells.append(f"<i class='lbl' style='display:flex;align-items:center;justify-content:center;"
                     f"width:{d:.0f}px;height:{d:.0f}px;border-radius:50%;background:{col};{ring}"
                     f"color:{ink};font-style:normal;font-size:{max(8.0, d * 0.6):.0f}px'>{_esc(txt)}</i>")
    return ("<div style='display:flex;justify-content:center;align-items:center;gap:4px;"
            f"height:{max(8.0, h - 8):.0f}px'>{''.join(cells)}</div>")


def _axis_is_constant(ws, rows: list, ndims: int, mrefs: list | None) -> bool:
    if not rows or not mrefs:
        return False
    shelf = set(_shelf_refs(ws, "rows")) | set(_shelf_refs(ws, "cols"))
    idx = [ndims + k for k, m in enumerate(mrefs) if m in shelf and ndims + k < len(rows[0])]
    return bool(idx) and all(len({str(r[i]) for r in rows}) <= 1 for i in idx)


def _render_mvline(rows, ndims: int, refs: list, ws, w: float, h: float) -> str:
    if not rows:
        return "<div class='empty'>no data</div>"
    cols = _shelf_refs(ws, "cols")
    xi = next((refs.index(r) for r in cols if r in refs), 0)
    order = sorted(range(len(rows)), key=lambda k: (_num(rows[k][xi]) is None,
                                                    _num(rows[k][xi]) or 0, str(rows[k][xi])))
    series = [j for j in range(ndims, len(rows[0]))
              if len({str(r[j]) for r in rows}) > 1 and any(_num(r[j]) is not None for r in rows)]
    vals = [_num(rows[k][j]) for j in series for k in order if _num(rows[k][j]) is not None]
    if not series or not vals:
        return "<div class='empty'>no data</div>"
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    W, H = max(20.0, w - 8), max(16.0, h - 8)
    n = max(1, len(order) - 1)
    pal = [_MARK["color"], "#bfbfbf", "#8c8c8c", "#d4d4d4"]
    lines = []
    for si, j in enumerate(series):
        pts = [(4 + i / n * W, 4 + H - ((_num(rows[k][j]) - lo) / span) * H)
               for i, k in enumerate(order) if _num(rows[k][j]) is not None]
        if len(pts) >= 2:
            lines.append(f"<polyline points='{' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)}' "
                         f"fill='none' stroke='{pal[si % len(pal)]}' stroke-width='1.6'/>")
    return f"<svg width='{W + 8:.0f}' height='{H + 8:.0f}'>{''.join(lines)}</svg>"


def _render_map(ws, rows, ndims: int, refs: list, mrefs: list, w: float, h: float, root) -> str:
    from . import geodata as G
    if not rows:
        return "<div class='empty'>no data</div>"
    gi = next((i for i in range(ndims) if sum(1 for r in rows if G.us_state(r[i])) >= len(rows) / 2),
              None)
    if gi is None:
        return "<div class='empty'>map: geography not recognized</div>"
    sref, cref = _enc_ref(ws, "size"), _enc_ref(ws, "color")
    si = ndims + mrefs.index(sref) if sref in mrefs else None
    ci = refs.index(cref) if cref in refs else (ndims + mrefs.index(cref) if cref in mrefs else None)
    cmap = (color_map(root, ws) if root is not None else None) or {}
    svals = [_num(r[si]) or 0 for r in rows] if si is not None else []
    smax = max([abs(v) for v in svals] or [1]) or 1
    cnum = ci is not None and ci >= ndims
    cvals = [_num(r[ci]) for r in rows] if cnum else []
    lo, hi = (min(v for v in cvals if v is not None), max(v for v in cvals if v is not None)) \
        if cvals and any(v is not None for v in cvals) else (0, 1)
    cats = sorted({str(r[ci]) for r in rows}) if ci is not None and not cnum else []
    auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(cats)}
    dots = []
    filled = any(p.find("encodings/geometry") is not None and p.find("encodings/color") is not None
                 for p in ws.iter("pane")) if ws is not None else False
    spec_ = measure_palette(root, ws, cref) if cnum else {}
    for k, r in enumerate(rows):
        g = G.us_state(r[gi])
        if not g:
            continue
        x, y = G.project(g[1], g[2], w, h)
        rad = 3 + (9 * (abs(svals[k]) / smax) ** 0.5 if svals else 2)
        if filled and cnum and cvals[k] is not None:
            dots.append(f"<circle cx='{x:.0f}' cy='{y:.0f}' r='{max(6.0, min(w, h) / 26):.1f}' "
                        f"fill='{measure_color(spec_, cvals[k], lo, hi)}' stroke='#fff' stroke-width='0.5'/>")
            if not svals:
                continue
            col = _MARK["color"]
        elif cnum and cvals[k] is not None:
            col = measure_color(spec_, cvals[k], lo, hi) or _MARK["color"]
        elif ci is not None:
            col = cmap.get(str(r[ci])) or auto.get(str(r[ci]), _MARK["color"])
        else:
            col = _MARK["color"]
        dots.append(f"<circle cx='{x:.0f}' cy='{y:.0f}' r='{rad:.1f}' fill='{col}' "
                    f"fill-opacity='0.8' stroke='#fff' stroke-width='0.5'/>")
    return (f"<svg width='{w:.0f}' height='{h:.0f}' style='background:#f4f4f2'>"
            f"{''.join(dots)}</svg>")


def _hidden_headers(ws) -> set:
    out = set()
    for sr in ws.iter("style-rule"):
        if sr.get("element") != "label":
            continue
        for f in sr.findall("format"):
            if f.get("attr") == "display" and f.get("value") == "false" and f.get("field"):
                out.add(f.get("field").split("].")[-1] if "]." in f.get("field") else f.get("field"))
    return {x if x.startswith("[") else "[" + x for x in out}


def _all_headers_hidden(ws) -> bool:
    on = _shelf_refs(ws, "rows") + _shelf_refs(ws, "cols")
    dims = [r for r in on if ":nk]" in r or ":ok]" in r]
    return bool(dims) and set(dims) <= _hidden_headers(ws)


def _cell_format(ws, ref: str) -> dict:
    out = {}
    for sr in ws.iter("style-rule"):
        if sr.get("element") != "cell":
            continue
        for f in sr.findall("format"):
            fld = f.get("field") or ""
            if not fld or fld.endswith(ref):
                out.setdefault(f.get("attr"), f.get("value"))
    return out


def _palette_color(root, ws, inst: str, value) -> str | None:
    v = _num(value)
    if v is None:
        return None
    scopes = [ws] + ([d for d in root.iter("datasource")] if root is not None else [])
    for sc in scopes:
        for e in sc.iter("encoding"):
            if e.get("attr") != "color" or not (e.get("field") or "").endswith(inst):
                continue
            cols = [c.text for c in e.iter("color") if c.text]
            if not cols:
                continue
            center = _num(e.get("center")) if e.get("center") is not None else 0.0
            return cols[0] if v < center else cols[-1]
    return None


def _plate(ws, root, rows: list, ndims: int, refs: list, mrefs: list) -> str | None:
    from .dryrun import inst_refs
    if ws is None or not rows:
        return None
    axis = any(re.search(r":qk(:\d+)?\]$", r) for r in _shelf_refs(ws, "cols") + _shelf_refs(ws, "rows"))
    for pane in ws.iter("pane"):
        mk = pane.find("mark")
        cls = mk.get("class") if mk is not None else "Automatic"
        enc = pane.find("encodings/color")
        if enc is None or not (cls == "Bar" or (cls == "Automatic" and axis)):
            continue
        cref = (inst_refs(enc.get("column") or "") or [""])[0]
        if cref in refs:
            i = refs.index(cref)
        elif cref in mrefs:
            i = ndims + mrefs.index(cref)
        else:
            continue
        val = rows[0][i] if i < len(rows[0]) else None
        if re.search(r":qk(:\d+)?\]$", cref):
            col = _palette_color(root, ws, cref, val)
        else:
            col = color_map(root, ws).get(str(val)) if root is not None else None
        if not col or not re.fullmatch(r"#[0-9a-fA-F]{6}", col):
            continue
        alpha = 1.0
        for f in pane.iter("format"):
            if f.get("attr") == "mark-transparency" and _num(f.get("value")) is not None:
                alpha = max(0.0, min(1.0, _num(f.get("value")) / 255))
        r_, g_, b_ = (int(col[k:k + 2], 16) for k in (1, 3, 5))
        return f"rgba({r_},{g_},{b_},{alpha:.2f})"
    return None


def _render_bigtext(ws, rows, ndims: int, masks: list, mrefs: list) -> str:
    first = rows[0] if rows else []
    texts = [ (e.get("column") or "").split("].")[-1] for e in ws.findall(".//encodings/text")]
    out = []
    for tref in texts:
        k = next((i for i, m in enumerate(mrefs) if m == tref), None)
        if k is None or ndims + k >= len(first):
            continue
        cf = _cell_format(ws, tref)
        pt = float(cf.get("font-size") or 9)
        fam = cf.get("font-family") or ""
        mk = masks[ndims + k] if ndims + k < len(masks) else ""
        style = f"font-size:{pt * 4 / 3:.0f}px;line-height:1.1"
        if fam:
            style += f";font-family:'{_esc(fam)}'"
        out.append(f"<div class='ln lbl' style='{style}'>"
                   f"{_esc(_fmt(first[ndims + k], '', mk))}</div>")
    return (f"<div style='display:flex;flex-direction:column;justify-content:center;"
            f"align-items:center;height:100%'>{''.join(out)}</div>")


def _card_value(tok: str, first: list, ndims: int, masks: list, refs: list, mrefs: list,
                params: dict):
    inner = re.findall(r"\[([^\]]+)\]", tok)
    if not inner:
        return None, ""
    if len(inner) >= 2 and inner[-2] == "Parameters":
        return params.get(inner[-1], ""), ""
    ref = "[" + inner[-1] + "]"
    base = re.sub(r":\d+\]$", "]", ref)
    for k, m in enumerate(mrefs):
        if m in (ref, base) or re.sub(r":\d+\]$", "]", m) == base:
            i = ndims + k
            return (first[i] if i < len(first) else None), (masks[i] if i < len(masks) else "")
    for k, d in enumerate(refs):
        if d in (ref, base) or re.sub(r":\d+\]$", "]", d) == base:
            return (first[k] if k < len(first) else None), (masks[k] if k < len(masks) else "")
    return None, ""


def card_text(tok: str, first: list, ndims: int, masks: list, refs: list, mrefs: list,
              params: dict, caption: str = "") -> str:
    inner = re.findall(r"\[([^\]]+)\]", tok)
    if len(inner) >= 2 and inner[-2] == "Parameters":
        return str(params.get(inner[-1], ""))
    v, mk = _card_value(tok, first, ndims, masks, refs, mrefs, params)
    if v is None:
        return ""
    base = re.sub(r":\d+\]$", "]", "[" + inner[-1] + "]")
    if not any(re.sub(r":\d+\]$", "]", m) == base for m in mrefs) and \
            any(re.sub(r":\d+\]$", "]", d) == base for d in refs):
        return fmt_dim(v, base, mk)
    return _fmt(v, caption, mk)


def param_text(raw, mk: str = "") -> str:
    import datetime as _dt
    cur = str(raw if raw is not None else "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", cur)
    if m and mk == "L":
        d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return f"{_WD[(d.weekday() + 1) % 7]}, {_MON[d.month - 1]} {d.day}, {d.year}"
    if mk == "*" or re.fullmatch(r"[A-Z]", mk or ""):
        mk = ""
    if m and not mk:
        return fmt_default_date(cur) or cur
    if m:
        return fmt_date(cur, ("i" + mk[1:]) if mk.startswith("*") and re.search(r"[MY]", mk)
                        else mk) or cur
    if mk:
        return fmt_mask(cur, mk) or cur
    return cur


def _render_card(ws, rows, ndims: int, masks: list | None = None, refs: list | None = None,
                 mrefs: list | None = None, params: dict | None = None) -> str:
    from . import sketch as SK
    lines = SK.card_lines(ws)
    first = rows[0] if rows else []
    vals = list(first[ndims:])
    by_ref = bool(mrefs or refs)
    out, vi = [], 0
    for ln in lines:
        size = max(t[1] for t in ln)
        bold = any(t[2] for t in ln)
        txt = []
        for tok, _sz, _b, is_field in ln:
            if is_field and by_ref:
                txt.append(card_text(tok, first, ndims, masks or [], refs or [], mrefs or [],
                                     params or {}, tok))
            elif is_field:
                v = vals[vi] if vi < len(vals) else ""
                mk = (masks or [])[ndims + vi] if masks and ndims + vi < len(masks) else ""
                vi += 1
                txt.append(_fmt(v, tok, mk))
            else:
                txt.append(tok)
        out.append(f'<div class="ln lbl" style="font-size:{size * 4 / 3:.0f}px;'
                   f'font-weight:{700 if bold else 400}">{_esc("".join(txt))}</div>')
    hdr = ""
    if ndims and first and _shelf_refs(ws, "cols"):
        hdr = f"<div class='hdr lbl'>{_esc(fmt_dim(first[0], (refs or [''])[0]))}</div>"
    return hdr + "".join(out)


def _render_cards(ws, rows, ndims: int, masks: list, refs: list, mrefs: list,
                  params: dict, cap: int = 40) -> str:
    hidden = _hidden_headers(ws)
    on_rows = [r for r in _shelf_refs(ws, "rows") if r in refs and r not in hidden]
    on_cols = [r for r in _shelf_refs(ws, "cols") if r in refs and r not in hidden]
    if len(rows) < 2 or not (on_rows or on_cols):
        return _render_card(ws, rows, ndims, masks, refs, mrefs, params)
    head_i = [refs.index(x) for x in on_rows if x in refs]
    one = []
    for r in rows[:cap]:
        hdr = "".join(f"<span class='lbl' style='min-width:0;margin-right:8px'>{_esc(fmt_dim(r[i], refs[i]))}</span>"
                      for i in head_i if i < len(r))
        one.append(f"<div style='flex:1 1 0;min-width:0;min-height:0;overflow:hidden;"
                   f"display:flex;align-items:center'>{hdr}<div style='flex:1;min-width:0'>"
                   f"{_render_card(ws, [r], ndims, masks, refs, mrefs, params)}</div></div>")
    flow = "column" if on_rows else "row"
    return (f"<div style='display:flex;flex-direction:{flow};gap:4px;height:100%'>"
            f"{''.join(one)}</div>")


def _chip_refs(ws, refs: list):
    t, c = _enc_ref(ws, "text"), _enc_ref(ws, "color")
    if t in refs and c in refs:
        return refs.index(t), refs.index(c)
    return None


def _render_chips(ws, rows: list, refs: list, root) -> str:
    ti, ci = _chip_refs(ws, refs)
    cmap = (color_map(root, ws) if root is not None else None) or {}
    vals = sorted({str(r[ci]) for r in rows})
    auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(vals)}
    if set(v.lower() for v in vals) <= {"true", "false"}:
        auto = {v: (_MARK["color"] if v.lower() == "true" else "#ededed") for v in vals}
    vertical = bool(_shelf_refs(ws, "rows")) and not _shelf_refs(ws, "cols")
    cells = []
    for r in rows:
        bg = cmap.get(str(r[ci])) or auto.get(str(r[ci]), "#ededed")
        ink = "#ffffff" if _lum(bg) < 0.55 else INK
        cells.append(f"<span class='lbl' style='flex:1;min-width:0;display:flex;align-items:center;"
                     f"justify-content:center;background:{bg};color:{ink};font-size:11px'>"
                     f"{_esc(fmt_dim(r[ti], refs[ti]))}</span>")
    return (f"<div style='display:flex;flex-direction:{'column' if vertical else 'row'};gap:6px;"
            f"height:100%'>{''.join(cells)}</div>")


def _lum(hex_: str) -> float:
    h = hex_.lstrip("#")[:6]
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 1.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


_TOKEN = re.compile(r"<(\[[^>]*\]|Sheet Name|Page Name|Workbook Name)>")


def _runs_html(ze, subst=None) -> str:
    out, align = [], "left"
    for r in ze.iter("run"):
        txt = (r.text or "").replace("\u00c6", "")
        if subst is not None:
            txt = _TOKEN.sub(lambda m: subst(m.group(1)), txt)
        al = r.get("fontalignment")
        if al in ("0", "1", "2"):
            align = {"0": "left", "1": "center", "2": "right"}[al]
        st = [f"font-size:{float(r.get('fontsize') or 9) * 4 / 3:.0f}px"]
        if r.get("bold") == "true":
            st.append("font-weight:700")
        if (r.get("fontcolor") or "").startswith("#"):
            st.append(f"color:{r.get('fontcolor')[:7]}")
        parts = txt.split("\n")
        out.append("<br>".join(f"<span class='lbl' style='{';'.join(st)}'>{_esc(p)}</span>" for p in parts))
    return f"<div style='text-align:{align}'>{''.join(out)}</div>"


def _legend_html(z, ws, d: dict, root) -> str:
    field = _field_of(z.param)
    cap = _caption_of(root, field) if root is not None else field
    inst = (re.findall(r"\[[^\]]+\]", z.param) or [""])[-1]
    refs, mrefs, rows = d.get("refs") or [], d.get("mrefs") or [], d.get("rows") or []
    head = f"<b class='lbl' style='display:block;font-size:11px'>{_esc(cap)}</b>"
    if inst in refs and rows:
        i = refs.index(inst)
        vals = sorted({str(r[i]) for r in rows if str(r[i]) not in ("None", "")})
        cmap = (color_map(root, ws) if root is not None and ws is not None else None) or {}
        items = "".join(f"<span class='lbl' style='display:block;font-size:10px'>"
                        f"<i style='display:inline-block;width:8px;height:8px;margin-right:4px;"
                        f"background:{cmap.get(v) or PALETTE[k % len(PALETTE)]}'></i>{_esc(fmt_dim(v, inst))}</span>"
                        for k, v in enumerate(vals[:20]))
        return head + items
    if inst in mrefs and rows:
        k = len(rows[0]) - len(mrefs) + mrefs.index(inst)
        nums = [x for x in (_num(r[k]) for r in rows) if x is not None]
        if nums:
            lo, hi = min(nums), max(nums)
            sp = measure_palette(root, ws, inst)
            grad = ",".join(measure_color(sp, lo + (hi - lo) * t / 8, lo, hi) or BAR for t in range(9))
            return (head + f"<div style='height:8px;background:linear-gradient(90deg,{grad})'></div>"
                    f"<div class='axis'><span class='lbl'>{_esc(_fmt(lo))}</span>"
                    f"<span class='lbl'>{_esc(_fmt(hi))}</span></div>")
    return head


def _button_html(btn, assets: dict) -> str:
    st = btn.find("button-visual-state")
    if st is None:
        return ""
    img = (st.findtext("image-path") or "").strip()
    if img and assets.get(img):
        return (f"<img src='{_esc(assets[img])}' style='width:100%;height:100%;"
                f"object-fit:contain;display:block'>")
    cap = st.findtext("caption") or ""
    fs = st.find("button-caption-font-style")
    css = ["display:flex;align-items:center;justify-content:center;height:100%;font-size:11px"]
    if fs is not None:
        if (fs.get("fontcolor") or "").startswith("#"):
            css.append(f"color:{fs.get('fontcolor')[:7]}")
        if fs.get("fontname"):
            css.append(f"font-family:'{_esc(fs.get('fontname'))}'")
        if fs.get("fontsize"):
            css.append(f"font-size:{float(fs.get('fontsize')) * 4 / 3:.0f}px")
    for f in btn.iter("format"):
        if f.get("attr") == "background-color" and (f.get("value") or "").startswith("#"):
            css.append(f"background:{f.get('value')[:7]}")
    return f"<div class='lbl' style='{';'.join(css)}'>{_esc(cap)}</div>"


def _control_text(z, ze, root, sheets: dict, pcap: dict, pval: dict, pfmt: dict):
    title = None
    if ze is not None and ze.get("custom-title") == "true" and ze.find("formatted-text") is not None:
        title = _runs_html(ze.find("formatted-text"), _subst(
            {k: param_text(v, pfmt.get(k, "")) for k, v in pval.items()}, z.name, None, None))
    if z.kind == "paramctrl":
        pid = z.param.split("].[")[-1].strip("[]") if z.param else ""
        cur = param_text(pval.get(pid, ""), pfmt.get(pid, ""))
        if title is None:
            title = f"<b class='lbl'>{_esc(pcap.get(pid) or pid)}</b>"
        return title, cur
    field = _field_of(z.param)
    cap = _caption_of(root, field) if root is not None else field
    if title is None:
        title = f"<b class='lbl'>{_esc(cap or z.name)}</b>"
    return title, _filter_state(sheets.get(z.name), z.param)


def _field_of(param: str) -> str:
    inner = re.findall(r"\[([^\]]+)\]", param or "")
    if not inner:
        return ""
    parts = inner[-1].split(":")
    return ":".join(parts[1:-1]) if len(parts) >= 3 else inner[-1]


def _caption_of(root, field: str) -> str:
    for c in root.iter("column"):
        if (c.get("name") or "").strip("[]") == field and c.get("caption"):
            return c.get("caption")
    return field


def _filter_state(ws, param: str) -> str:
    if ws is None or not param:
        return "(All)"
    inst = re.findall(r"\[[^\]]+\]", param)[-1]
    for fl in ws.iter("filter"):
        if not (fl.get("column") or "").endswith(inst):
            continue
        funcs = {g.get("function") for g in fl.iter("groupfilter")}
        if "except" in funcs or "level-members" in funcs and "member" not in funcs:
            return "(All)"
        mem = [g.get("member") for g in fl.iter("groupfilter") if g.get("function") == "member"]
        if len(mem) == 1:
            return (mem[0] or "").strip('"')
        if len(mem) > 1:
            return "(Multiple values)"
    return "(All)"


def _subst(pval: dict, sheet: str, d: dict | None, ws):
    def f(tok: str) -> str:
        if tok == "Sheet Name":
            return sheet
        if tok in ("Page Name", "Workbook Name"):
            return ""
        inner = re.findall(r"\[([^\]]+)\]", tok)
        if len(inner) >= 2 and inner[-2] == "Parameters":
            return str(pval.get(inner[-1], ""))
        if d and d.get("rows"):
            return card_text("<" + tok + ">", d["rows"][0], d.get("ndims", 0), d.get("masks") or [],
                             d.get("refs") or [], d.get("mrefs") or [], pval)
        return ""
    return f


def tooltip_text(ws, name: str, pval: dict, d: dict) -> str:
    """The sheet's custom tooltip as plain text for its first mark: what hovering shows."""
    node = ws.find(".//pane/customized-tooltip/formatted-text") if ws is not None else None
    if node is None:
        return ""
    sub = _subst(pval, name, d, ws)
    txt = "".join(_TOKEN.sub(lambda m: sub(m.group(1)), r.text or "") for r in node.iter("run"))
    return txt.replace("\u00c6", "").strip()


def _title_html(ws, name: str, pval: dict, d: dict) -> str:
    node = ws.find(".//layout-options/title/formatted-text") if ws is not None else None
    if node is None:
        return f"<div class='ttl lbl'>{_esc(name)}</div>"
    return f"<div class='ttl'>{_runs_html(node, _subst(pval, name, d, ws))}</div>"


def _mark_text_color(ws) -> str:
    if ws is None:
        return INK
    for run in ws.iter("run"):
        if (run.get("fontcolor") or "").startswith("#"):
            return run.get("fontcolor")[:7]
    for f in ws.iter("format"):
        if f.get("attr") == "color" and (f.get("value") or "").startswith("#"):
            return f.get("value")[:7]
    return INK


def _render_crosstab(ws, rows, ndims: int, refs: list, caps: list, masks: list,
                     fit: str = "", sized: bool = False, mref: str = "") -> str | None:
    cols = _shelf_refs(ws, "cols")
    ci = [i for i in range(min(ndims, len(refs))) if refs[i] in cols
          and re.search(r":(nk|ok)(:\d+)?\]$", refs[i])]
    if len(ci) != 1 or not rows or len(rows[0]) <= ndims:
        return None
    c = ci[0]
    ri = [i for i in range(ndims) if i != c]
    fmt = ""
    for sr in ws.iter("style-rule"):
        for f in sr.findall("format"):
            if f.get("attr") == "text-format" and (f.get("field") or "").endswith(refs[c]):
                fmt = fmt or f.get("value") or ""
    fmt = fmt or ((masks or [])[c] if c < len(masks or []) else "")
    keys = sorted({str(r[c]) for r in rows})
    lab = {k: fmt_dim(k, refs[c], fmt) for k in keys}

    def rlab(i, v):
        mk_ = (masks or [])[i] if i < len(masks or []) else ""
        return fmt_dim(v, refs[i] if i < len(refs) else "", mk_)
    shown = _field_labels_shown(ws, "rows")
    grid, order = {}, []
    for r in rows:
        rk = tuple(str(r[i]) for i in ri)
        if rk not in grid:
            grid[rk] = {}
            order.append(rk)
        grid[rk][str(r[c])] = r[ndims]
    mk = (masks or [""] * (ndims + 1))[ndims] if len(masks or []) > ndims else ""
    cap = caps[ndims] if len(caps) > ndims else ""
    rt, ct, top = grand_totals(ws)
    add = additive(mref)
    rules = style_rules(ws)
    hcss = header_css(ws, refs[c], rules)
    rcss = {i: header_css(ws, refs[i] if i < len(refs) else "", rules) for i in ri}
    flcss = field_label_css(ws, rules)
    vcss = text_css(ws, "cell", mref, rules)
    head = [(caps[i] if i < len(caps) and shown else "", "lbl", flcss) for i in ri] + \
        [(lab[k], "lbl num", hcss) for k in keys] + ([("Grand Total", "lbl num")] if ct and add else [])

    def tot(vals):
        xs = [_num(v) for v in vals if _num(v) is not None]
        return _fmt(sum(xs), cap, mk) if xs else ""
    body = [[(rlab(i, v), "lbl", rcss[i]) for i, v in zip(ri, rk)] +
            [(_fmt(grid[rk].get(k), cap, mk), "num", vcss) for k in keys] +
            ([(tot(grid[rk].values()), "num", "font-weight:600")] if ct and add else [])
            for rk in order[:300]]
    if rt and add and ri:
        gt = [("Grand Total", "lbl", "font-weight:600")] + [("", "lbl", "")] * (len(ri) - 1) + \
            [(tot(grid[rk].get(k) for rk in order), "num", "font-weight:600") for k in keys] + \
            ([(tot(v for rk in order for v in grid[rk].values()), "num", "font-weight:600")] if ct else [])
        body = [gt] + body if top else body + [gt]
    kinds = [("h", refs[i] if i < len(refs) else "") for i in ri] + \
        [("v", "") for _ in range(len(head) - len(ri))]
    return _table_html(head, body, kinds if sized else None, ws, fit)


def grand_totals(ws) -> tuple:
    r = ws.find(".//table/rows") if ws is not None else None
    c = ws.find(".//table/cols") if ws is not None else None
    return ((r is not None and r.get("total") == "true"), (c is not None and c.get("total") == "true"),
            (r is not None and r.get("onTop") == "true"))


def additive(mref: str) -> bool:
    return bool(re.match(r"^\[(sum|cnt):", mref or ""))


HEAD_CAP, VALUE_CAP = 90, 170
FRAME_TABLE_PT = 11 * 72 / 96


def xml_width(ws, element: str, ref: str = "") -> float | None:
    for sr in (ws.iter("style-rule") if ws is not None else ()):
        if sr.get("element") != element:
            continue
        for f in sr.findall("format"):
            if f.get("attr") != "width" or _num(f.get("value")) is None:
                continue
            fld = f.get("field") or ""
            if element == "header" and not (ref and fld.endswith(ref)):
                continue
            return _num(f.get("value"))
    return None


def col_widths(ws, kinds: list, heads: list, texts: list, fit: str, src: list | None = None,
               pts: list | None = None) -> list:
    from . import layoutmodel as LM_
    cell = xml_width(ws, "cell")
    out = []
    for k, (kind, ref) in enumerate(kinds):
        px = xml_width(ws, "header", ref) if kind == "h" else cell
        if src is not None:
            src.append("auto" if px is None else "xml")
        if px is None:
            col = [t for t in (texts[k] if k < len(texts) else [])[:120] if t]
            pt = (pts[k] if pts and k < len(pts) else None) or FRAME_TABLE_PT
            nat = max((LM_.text_width(t, pt) for t in col), default=0.0) * 1.1 + 10
            hd = LM_.text_width(heads[k], FRAME_TABLE_PT) * 1.1 + 10 if k < len(heads or []) and heads[k] else 0.0
            px = max(24.0, min(VALUE_CAP * pt / FRAME_TABLE_PT, max(nat, min(hd, HEAD_CAP))))
        out.append(float(px))
    return out


def _inst_key(ref: str) -> str:
    return re.sub(r":\d+\]$", "]", ref or "")


def style_rules(ws) -> dict:
    out: dict = {}
    st = ws.find("table/style") if ws is not None else None
    for sr in (st.findall("style-rule") if st is not None else ()):
        el = sr.get("element") or ""
        for f in sr.findall("format"):
            if f.get("scope") or f.get("data-class"):
                continue
            fld = _inst_key((re.findall(r"\[[^\]]+\]", f.get("field") or "") or [""])[-1])
            out.setdefault((el, fld), {}).setdefault(f.get("attr"), f.get("value"))
    return out


_TEXT_ATTRS = ("font-size", "font-weight", "font-style", "font-family", "color", "text-align")


def text_css(ws, element: str, ref: str = "", rules: dict | None = None) -> str:
    rules = style_rules(ws) if rules is None else rules
    got: dict = {}
    keys = ([(element, _inst_key(ref))] if ref else []) + [(element, ""), ("worksheet", "")]
    for key in keys:
        for a, v in rules.get(key, {}).items():
            if a in _TEXT_ATTRS and v and not (key[0] == "worksheet" and a == "text-align"):
                got.setdefault(a, v)
    css = []
    if _num(got.get("font-size")):
        css.append(f"font-size:{_num(got['font-size']) * 4 / 3:.1f}px")
    if got.get("font-weight") in ("bold", "normal"):
        css.append(f"font-weight:{700 if got['font-weight'] == 'bold' else 400}")
    if got.get("font-style") == "italic":
        css.append("font-style:italic")
    fam = re.sub(r"[\"'<>;]", "", got.get("font-family") or "")
    if fam:
        css.append(f'font-family:"{fam}","Tableau Book",Arial,sans-serif')
    if (got.get("color") or "").startswith("#") and len(got["color"]) >= 7 and \
            not got["color"][7:9] == "00":
        css.append(f"color:{got['color'][:7]}")
    if got.get("text-align") in ("left", "center", "right"):
        css.append(f"text-align:{got['text-align']}")
    return ";".join(css)


def header_css(ws, ref: str, rules: dict | None = None) -> str:
    rules = style_rules(ws) if rules is None else rules
    css = text_css(ws, "label", ref, rules)
    bg = None
    for key in (("header", _inst_key(ref)), ("header", "")):
        bg = bg or _opaque(rules.get(key, {}).get("background-color"))
    return ";".join(x for x in (css, f"background:{bg}" if bg else "") if x)


def field_label_css(ws, rules: dict | None = None) -> str:
    rules = style_rules(ws) if rules is None else rules
    deco = rules.get(("field-labels-decoration", ""), {})
    css = []
    if _num(deco.get("font-size")):
        css.append(f"font-size:{_num(deco['font-size']) * 4 / 3:.1f}px")
    if deco.get("font-weight") == "bold":
        css.append("font-weight:700")
    if _opaque(deco.get("color")):
        css.append(f"color:{_opaque(deco['color'])}")
    bg = _opaque(rules.get(("field-labels", ""), {}).get("background-color"))
    if bg:
        css.append(f"background:{bg}")
    return ";".join(css)


def bands(ws) -> tuple:
    out = {"pane": None, "header": None}
    for sr in (ws.findall("table/style/style-rule") if ws is not None else ()):
        if sr.get("element") in out:
            for f in sr.findall("format"):
                if f.get("attr") == "band-color" and f.get("scope") == "rows":
                    out[sr.get("element")] = _opaque(f.get("value"))
    return out["pane"], out["header"]


def head_height(ws, refs: list) -> float | None:
    want = {_inst_key(r) for r in refs}
    for sr in (ws.findall("table/style/style-rule") if ws is not None else ()):
        if sr.get("element") != "header":
            continue
        for f in sr.findall("format"):
            if f.get("attr") == "height" and _inst_key(
                    (re.findall(r"\[[^\]]+\]", f.get("field") or "") or [""])[-1]) in want:
                return _num(f.get("value"))
    return None


def lines_off(ws, element: str, scope: str) -> bool:
    for sr in (ws.iter("style-rule") if ws is not None else ()):
        if sr.get("element") != element:
            continue
        for f in sr.findall("format"):
            if f.get("attr") == "line-visibility" and f.get("scope") in (scope, None) and \
                    f.get("value") == "off":
                return True
    return False


def row_height(ws) -> float | None:
    hs = [_num(f.get("value")) for sr in (ws.iter("style-rule") if ws is not None else ())
          if sr.get("element") == "cell" for f in sr.findall("format")
          if f.get("attr") == "height" and _num(f.get("value"))]
    return max(hs) if hs else None


def _css_pt(css: str) -> float:
    m = re.search(r"font-size:([\d.]+)px", css or "")
    return float(m.group(1)) * 0.75 if m else FRAME_TABLE_PT


def _table_html(head: list | None, body: list, kinds: list | None = None, ws=None,
                fit: str = "", zone_w: float = 0.0) -> str:
    hh = head_height(ws, _shelf_refs(ws, "cols")) if ws is not None else None
    clamp = f" style='-webkit-line-clamp:{max(2, int((hh - 4) / 15.3))}'" if hh else ""
    th = "".join(f"<th class='{h[1]}'{(' style=' + chr(39) + h[2] + chr(39)) if len(h) > 2 and h[2] else ''}>"
                 f"<div class='lbl h2'{clamp}>{_esc(h[0])}</div></th>" for h in (head or []))
    thead = (f"<thead><tr{(' style=' + chr(39) + f'height:{hh:.0f}px' + chr(39)) if hh else ''}>{th}</tr></thead>"
             if head and any(str(h[0]).strip() for h in head) else "")
    rh = row_height(ws)
    hcss = f"height:{rh:.0f}px;" if rh else ""

    pband, hband = bands(ws)

    def band(k, c, st):
        col = (hband if "num" not in c else pband) if k % 2 else None
        return f"background:{col};" if col and "background" not in (st or "") else ""
    rows_ = "".join("<tr>" + "".join(
        f"<td class='{c}'{(' style=' + chr(39) + hcss + band(k, c, st) + st + chr(39)) if st or hcss or band(k, c, st) else ''}>"
        f"{_esc(t)}</td>" for t, c, st in r) + "</tr>" for k, r in enumerate(body))
    cls = " class='nodiv'" if lines_off(ws, "table-div", "rows") else ""
    if not kinds:
        return f"<table{cls}>{thead}<tbody>{rows_}</tbody></table>"
    texts = [[r[k][0] for r in body if k < len(r)] for k in range(len(kinds))]
    pts = [max([_css_pt(r[k][2]) for r in body[:5] if k < len(r)] or [FRAME_TABLE_PT])
           for k in range(len(kinds))]
    src = []
    ws_ = col_widths(ws, kinds, [h[0] for h in head] if head else [], texts, fit, src, pts)
    tot = sum(ws_) or 1.0
    if fit in ("fit-width", "entire-view"):
        cg = "".join(f"<col data-src='{s_}' data-px='{w_:.0f}' style='width:{w_ / tot * 100:.2f}%'>"
                     for w_, s_ in zip(ws_, src))
        return (f"<table{cls} data-cols='fit'><colgroup>{cg}</colgroup>{thead}<tbody>{rows_}</tbody></table>")
    cg = "".join(f"<col data-src='{s_}' data-px='{w_:.0f}' style='width:{w_:.0f}px'>"
                 for w_, s_ in zip(ws_, src))
    return (f"<table{cls} data-cols='px' style='width:{tot:.0f}px'><colgroup>{cg}</colgroup>{thead}"
            f"<tbody>{rows_}</tbody></table>")


def cell_colors(ws, root, rows: list, ndims: int, mrefs: list) -> dict:
    if ws is None or not rows:
        return {}
    cref = _enc_ref(ws, "color")
    if not cref or not (cref == "[Multiple Values]" or re.search(r":qk(:\d+)?\]$", cref)):
        return {}
    fill = LM.mark_class(ws) in ("Square", "Heatmap")
    sep = any((e.get("separate-domains") == "true") for e in ws.iter("color"))
    cols = {}
    for k, m in enumerate(mrefs):
        i = ndims + k
        if i >= len(rows[0]) or (cref != "[Multiple Values]" and m != cref):
            continue
        spec = measure_palette(root, ws, m)
        if not spec.get("colors") and cref == "[Multiple Values]":
            spec = measure_palette(root, ws, "[Multiple Values]")
        cols[i] = spec
    if not cols:
        return {}
    rng = {i: [x for x in (_num(r[i]) for r in rows) if x is not None] for i in cols}
    allv = [x for v in rng.values() for x in v] or [0.0]
    out = {}
    for i, spec in cols.items():
        v = rng[i] if (sep or cref != "[Multiple Values]") and rng[i] else allv
        out[i] = (spec, min(v), max(v), fill)
    return out


def _render_table(rows, ndims: int, captions: list, masks: list | None = None,
                  heads: list | None = None, tint: list | None = None,
                  refs: list | None = None, ccolor: dict | None = None,
                  ws=None, fit: str = "", sized: bool = False, mrefs: list | None = None) -> str:
    heads = captions if heads is None else heads
    n = len(rows[0]) if rows else len(heads)
    rules = style_rules(ws)
    ccss = [header_css(ws, (refs or [""] * n)[i] if i < len(refs or []) else "", rules) if i < ndims
            else text_css(ws, "cell", (mrefs or [])[i - ndims] if i - ndims < len(mrefs or []) else "", rules)
            for i in range(n)]
    body = []
    for k, r in enumerate(rows):
        tds = []
        col = tint[k] if tint and k < len(tint) and tint[k] else ""
        for i, v in enumerate(r):
            cls = "lbl" if i < ndims else "lbl num"
            cap = captions[i] if i < len(captions) else ""
            mk = (masks or [""] * len(r))[i] if masks and i < len(masks) else ""
            shown = _fmt(v, cap, mk) if i >= ndims else \
                fmt_dim(v, (refs or [])[i] if i < len(refs or []) else "", mk)
            sty = f"color:{col}" if col and i >= ndims else ""
            if ccolor and i in ccolor:
                spec, lo, hi, fill = ccolor[i]
                c_ = measure_color(spec, v, lo, hi)
                if c_:
                    sty = (f"background:{c_};color:{'#ffffff' if _lum(c_) < 0.55 else INK}"
                           if fill else f"color:{c_}")
            base = ccss[i] if i < len(ccss) else ""
            tds.append((shown, cls, ";".join(x for x in (base, sty) if x)))
        body.append(tds)
    rt, _ct, top = grand_totals(ws)
    if rt and rows and ndims and mrefs and any(additive(m) for m in mrefs):
        gt = [("Grand Total", "lbl", "font-weight:600")] + [("", "lbl", "")] * (ndims - 1)
        for i in range(ndims, n):
            m = mrefs[i - ndims] if i - ndims < len(mrefs) else ""
            xs = [_num(r[i]) for r in rows if _num(r[i]) is not None]
            mk = (masks or [""] * n)[i] if masks and i < len(masks) else ""
            gt.append((_fmt(sum(xs), captions[i] if i < len(captions) else "", mk)
                       if additive(m) and xs else "", "lbl num", "font-weight:600"))
        body = [gt] + body if top else body + [gt]
    kinds = [("h", (refs or [""] * n)[i] if i < len(refs or []) else "") if i < ndims else ("v", "")
             for i in range(n)] if sized else None
    mn_css, fl_css = header_css(ws, "[:Measure Names]", rules), field_label_css(ws, rules)
    return _table_html([(str(h), "lbl" if i < ndims else "lbl num", fl_css if i < ndims else mn_css)
                        for i, h in enumerate(heads)], body, kinds, ws, fit)


def _field_labels_shown(ws, scope: str) -> bool:
    for f in ws.iter("format") if ws is not None else ():
        if f.get("attr") == "display-field-labels" and f.get("scope") == scope:
            return f.get("value") != "false"
    return True


def _table_view(ws, root, rows: list, ndims: int, refs: list, caps: list, masks: list):
    if ws is None or not rows:
        return rows, ndims, caps, masks, None, None, list(refs[:ndims])
    from .dryrun import inst_refs
    shelf = set(_shelf_refs(ws, "rows") + _shelf_refs(ws, "cols"))
    card, text = set(), set()
    for enc in ws.iter("encodings"):
        for el in enc:
            (text if el.tag in ("text", "label") else card).update(inst_refs(el.get("column") or ""))
    keep = [i for i in range(ndims) if not (i < len(refs) and refs[i] in card
                                            and refs[i] not in shelf and refs[i] not in text)]
    hidden = _hidden_headers(ws)
    shown = [i for i in keep if not (i < len(refs) and refs[i] in hidden)]
    if any(i < len(refs) and refs[i] in shelf for i in shown):
        keep = shown
    tint = None
    if len(keep) < ndims:
        cref = _enc_ref(ws, "color")
        if cref and cref in refs[:ndims]:
            cmap = color_map(root, ws) if root is not None else {}
            ci = refs.index(cref)
            tint = [cmap.get(str(r[ci])) for r in rows]
        sel = keep + list(range(ndims, len(rows[0])))

        def pick(lst):
            return [lst[i] if i < len(lst) else "" for i in sel]
        rows = [pick(r) for r in rows]
        caps, masks = pick(caps or []), pick(masks or [])
        refs = [refs[i] if i < len(refs) else "" for i in keep]
        ndims = len(keep)
    heads = None
    if not _field_labels_shown(ws, "rows"):
        heads = [""] * ndims + list(caps[ndims:])
    if not _shelf_refs(ws, "cols") and len(rows[0]) - ndims == 1:
        heads = (heads or list(caps))[:ndims] + [""]
    return rows, ndims, caps, masks, heads, tint, list(refs[:ndims])


SEQ = ("#c6dbef", "#2a5783")

TABLEAU_PALETTES = {
    "blue_10_0": ('#b9ddf1', '#8cbbdc', '#6698c0', '#4675a3', '#2a5783'),
    "blue_teal_10_0": ('#bce4d8', '#82c4cb', '#46a2b8', '#337b9f', '#2c5985'),
    "brown_10_0": ('#eedbbd', '#e6b171', '#d08853', '#bb5c39', '#9f3632'),
    "gold_purple_diverging_10_0": ('#ad9024', '#caad47', '#e1d0c3', '#ca95ba', '#ac7299'),
    "gray_10_0": ('#d5d5d5', '#afb3b4', '#889296', '#64707a', '#49525e'),
    "gray_warm_10_0": ('#dcd4d0', '#bab2ae', '#98908c', '#766d6b', '#59504e'),
    "Just black": ('#000000', '#000000'),
    "green_10_0": ('#b3e0a6', '#80c673', '#5ea654', '#368647', '#24693d'),
    "green_blue_diverging_10_0": ('#24693d', '#5ca455', '#b8d6c7', '#6192bc', '#2a5783'),
    "green_blue_white_diverging_10_0": ('#24693d', '#6db461', '#eef7f4', '#70a2c9', '#2a5783'),
    "green_gold_10_0": ('#f4d166', '#a9bf5a', '#60a656', '#37874c', '#146c36'),
    "orange_10_0": ('#ffc685', '#f5a03f', '#ec6f20', '#c65222', '#9e3d22'),
    "orange_blue_diverging_10_0": ('#9e3d22', '#e96c21', '#d4cfbd', '#5f94c1', '#2b5c8a'),
    "orange_blue_white_diverging_10_0": ('#9e3d22', '#f2842d', '#f6f4f2', '#71a7cf', '#2b5c8a'),
    "orange_gold_10_0": ('#f4d166', '#f6a244', '#ee701c', '#cc4d22', '#9e3a26'),
    "purple_10_0": ('#eec9e5', '#d7a7c7', '#bb86a9', '#976894', '#7c4d79'),
    "red_10_0": ('#ffbeb2', '#fb937d', '#f16250', '#d72e3e', '#ae123a'),
    "red_black_10_0": ('#ae123a', '#f05c4f', '#dcccca', '#858e93', '#49525e'),
    "red_black_white_diverging_10_0": ('#ae123a', '#f87f6a', '#faf6f6', '#99a0a2', '#49525e'),
    "red_blue_diverging_10_0": ('#a90c38', '#ef594e', '#dacaca', '#6496bf', '#2e5a87'),
    "red_blue_white_diverging_10_0": ('#a90c38', '#f77d67', '#f5f6f9', '#75a6cc', '#2e5a87'),
    "red_gold_10_0": ('#f4d166', '#faa14f', '#ee724a', '#d34845', '#b71d3e'),
    "red_green_diverging_10_0": ('#ae123a', '#f05c4f', '#ccceb0', '#5ba454', '#24693d'),
    "red_green_gold_diverging_10_0": ('#be2a3e', '#ee754a', '#eeca61', '#64aa65', '#22763f'),
    "red_green_white_diverging_10_0": ('#ae123a', '#f78069', '#f6f6f2', '#6eb562', '#24693d'),
    "sunrise_sunset_diverging_10_0": ('#33608c', '#bf6a9d', '#f6ad59', '#e25e47', '#b81840'),
    "tableau-blue-light": ('#e5e5e5', '#dde2e8', '#d4deec', '#ccdaf0', '#c4d8f3'),
    "tableau-map-blue-green": ('#feffd9', '#edf8b4', '#c2e9b1', '#7accbb', '#41b7c4'),
    "tableau-map-temperatur": ('#529985', '#77a064', '#d8cc48', '#f2b94e', '#c26b51'),
    "tableau-orange-blue-light": ('#ffcc9e', '#f5d8c0', '#e4e4e4', '#d4deec', '#c4d8f3'),
    "tableau-orange-light": ('#e5e5e5', '#eddfd3', '#f4d8c2', '#fbd1af', '#ffcc9e'),
}


def measure_palette(root, ws, inst: str) -> dict:
    enc = None
    scopes = ([ws] if ws is not None else []) + (list(root.iter("datasource")) if root is not None else [])
    for sc in scopes:
        enc = next((e for e in sc.iter("encoding") if e.get("attr") == "color"
                    and e.get("type") in ("interpolated", "custom-interpolated")
                    and (e.get("field") or "").endswith(inst)), None)
        if enc is not None:
            break
    spec = {"colors": None, "diverging": None, "reverse": False, "steps": None, "center": None,
            "full": False, "min": None, "max": None}
    if enc is None:
        return spec
    name = enc.get("palette") or ""
    cols = [c.text.strip() for c in enc.iter("color") if (c.text or "").strip()]
    ptype = (enc.find("color-palette").get("type") if enc.find("color-palette") is not None else "") or ""
    if not cols and name and root is not None:
        for cp in root.findall("preferences/color-palette"):
            if cp.get("name") == name:
                cols = [c.text.strip() for c in cp.findall("color") if (c.text or "").strip()]
                ptype = cp.get("type") or ptype
    if not cols and name in TABLEAU_PALETTES:
        cols = list(TABLEAU_PALETTES[name])
    spec.update(colors=cols or None,
                diverging=("diverging" in ptype or "diverging" in name) if (cols or name) else None,
                reverse=enc.get("reverse") == "true",
                steps=int(_num(enc.get("num-steps"))) if _num(enc.get("num-steps")) else None,
                center=_num(enc.get("center")), full=enc.get("symmetric") == "false",
                min=_num(enc.get("min")), max=_num(enc.get("max")))
    return spec


def _interp(cols: list, t: float) -> str:
    t = max(0.0, min(1.0, t))
    if len(cols) == 1:
        return cols[0]
    x = t * (len(cols) - 1)
    k = min(len(cols) - 2, int(x))
    return _mix(cols[k][:7], cols[k + 1][:7], x - k)


def measure_color(spec: dict, v, lo: float, hi: float) -> str | None:
    v = _num(v)
    if v is None:
        return None
    lo = spec.get("min") if spec.get("min") is not None else lo
    hi = spec.get("max") if spec.get("max") is not None else hi
    cols = spec.get("colors")
    div = spec.get("diverging")
    if not cols:
        div = lo < 0 < hi or spec.get("center") is not None
        cols = list(TABLEAU_PALETTES["orange_blue_diverging_10_0" if div else "blue_10_0"])
    if spec.get("reverse"):
        cols = cols[::-1]
    if div:
        c = spec.get("center") if spec.get("center") is not None else 0.0
        if spec.get("full"):
            t = 0.5 + 0.5 * (v - c) / ((hi - c) or 1.0) if v >= c else 0.5 - 0.5 * (c - v) / ((c - lo) or 1.0)
        else:
            m = max(abs(hi - c), abs(c - lo)) or 1.0
            t = 0.5 + 0.5 * (v - c) / m
    else:
        t = (v - lo) / (hi - lo) if hi > lo else 1.0
    n = spec.get("steps")
    if n and n > 1:
        t = min(n - 1, int(max(0.0, min(1.0, t)) * n)) / (n - 1)
    return _interp(cols, t)


def _mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def _pie_spec(ws, refs: list, mrefs: list, ndims: int) -> dict:
    from .dryrun import inst_refs
    out = {"wi": None, "ci": None, "donut": False}
    panes = list(ws.iter("pane")) if ws is not None else []
    pies = [p for p in panes if p.find("mark") is not None and p.find("mark").get("class") == "Pie"]
    pie = next((p for p in pies if p.find("encodings/wedge-size") is not None),
               pies[0] if pies else None)
    if pie is None:
        return out

    def idx(tag):
        el = pie.find(f"encodings/{tag}")
        r = (inst_refs(el.get("column") or "") or [""])[0] if el is not None else ""
        if r in mrefs:
            return ndims + mrefs.index(r)
        return refs.index(r) if r in refs else None
    out.update(wi=idx("wedge-size"), ci=idx("color"),
               donut=any(p is not pie and p.find("mark") is not None and
                         p.find("mark").get("class") == "Circle" for p in panes))
    return out


def _render_pie(rows, ndims: int, captions: list, masks: list, w: float, h: float,
                cmap: dict | None = None, ws=None, refs: list | None = None,
                mrefs: list | None = None, params: dict | None = None) -> str:
    import math
    from . import sketch as SK
    sp = _pie_spec(ws, refs or [], mrefs or [], ndims) if ws is not None else {}
    wi = sp.get("wi") if sp.get("wi") is not None else ndims
    ci = sp.get("ci") if sp.get("ci") is not None else 0
    data = [r for r in rows if r and len(r) > wi and (_num(r[wi]) or 0) > 0]
    if not data:
        return "<div class='empty'>no data</div>"
    tot = sum(_num(r[wi]) for r in data)
    vals = sorted({str(r[ci]) for r in data})
    auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(vals)}
    lab_lines = SK.card_lines(ws) if ws is not None else []

    def label(r):
        if not lab_lines:
            return _fmt(r[-1], captions[-1] if captions else "", (masks or [""])[-1] if masks else "")
        parts = []
        for ln in lab_lines:
            for tok, _sz, _b, is_field in ln:
                if is_field:
                    parts.append(card_text(tok, r, ndims, masks or [], refs or [], mrefs or [],
                                           params or {}))
                else:
                    parts.append(tok)
        return "".join(parts).strip()
    R = max(20.0, min(w, h - 24) / 2 - 18)
    cx, cy = w / 2, R + 14
    a0, parts = -math.pi / 2, []
    for r in data:
        frac = _num(r[wi]) / tot
        a1 = a0 + frac * 2 * math.pi
        big = 1 if frac > 0.5 else 0
        x0, y0 = cx + R * math.cos(a0), cy + R * math.sin(a0)
        x1, y1 = cx + R * math.cos(a1), cy + R * math.sin(a1)
        col = (cmap or {}).get(str(r[ci])) or auto[str(r[ci])]
        d = (f"M{cx:.1f},{cy:.1f} L{x0:.1f},{y0:.1f} A{R:.1f},{R:.1f} 0 {big} 1 {x1:.1f},{y1:.1f} Z"
             if frac < 0.9999 else f"M{cx - R:.1f},{cy:.1f} a{R:.1f},{R:.1f} 0 1 0 {2 * R:.1f},0 "
                                   f"a{R:.1f},{R:.1f} 0 1 0 {-2 * R:.1f},0")
        parts.append(f"<path d='{d}' fill='{col}' stroke='#fff' stroke-width='1'/>")
        am = (a0 + a1) / 2
        lx, ly = cx + (R + 10) * math.cos(am), cy + (R + 10) * math.sin(am)
        lab = label(r)
        anchor = "start" if math.cos(am) >= 0 else "end"
        parts.append(f"<text class='lbl' x='{lx:.1f}' y='{ly:.1f}' font-size='9' "
                     f"text-anchor='{anchor}'>{_esc(lab)}</text>")
        a0 = a1
    if sp.get("donut"):
        parts.append(f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='{R * 0.72:.1f}' fill='#fff'/>")
    return f"<svg width='{w:.0f}' height='{2 * R + 28:.0f}'>{''.join(parts)}</svg>"


def squarify(vals: list, x: float, y: float, w: float, h: float) -> list:
    tot = sum(vals) or 1.0
    areas = [v / tot * w * h for v in vals]
    out = []

    def worst(row, side):
        s_ = sum(row)
        return max(max(side * side * a / (s_ * s_), s_ * s_ / (side * side * a)) for a in row)
    i = 0
    while i < len(areas):
        side = min(w, h)
        row = [areas[i]]
        j = i + 1
        while j < len(areas) and worst(row + [areas[j]], side) <= worst(row, side):
            row.append(areas[j])
            j += 1
        s_ = sum(row)
        if w >= h:
            cw = s_ / h if h else 0
            yy = y
            for a in row:
                out.append((x, yy, cw, a / cw if cw else 0))
                yy += a / cw if cw else 0
            x, w = x + cw, w - cw
        else:
            rh = s_ / w if w else 0
            xx = x
            for a in row:
                out.append((xx, y, a / rh if rh else 0, rh))
                xx += a / rh if rh else 0
            y, h = y + rh, h - rh
        i = j
    return out


def _render_treemap(rows, ndims: int, captions: list, masks: list, w: float, h: float,
                    ws=None, root=None, refs: list | None = None, mrefs: list | None = None) -> str:
    refs, mrefs = refs or [], mrefs or []
    sref = _enc_ref(ws, "size") if ws is not None else ""
    si = ndims + mrefs.index(sref) if sref in mrefs and ndims + mrefs.index(sref) < len(rows[0] if rows else []) else -1
    data = sorted((r for r in rows if r and (_num(r[si]) or 0) > 0), key=lambda r: -_num(r[si]))
    if not data:
        return "<div class='empty'>no data</div>"
    cref = _enc_ref(ws, "color") if ws is not None else ""
    ci = refs.index(cref) if cref in refs else (ndims + mrefs.index(cref) if cref in mrefs else None)
    cnum = ci is not None and ci >= ndims
    spec = measure_palette(root, ws, cref) if cnum else {}
    cv = [_num(r[ci]) for r in data] if cnum else [_num(r[si]) for r in data]
    cv_ = [v for v in cv if v is not None] or [0.0]
    cmap = (color_map(root, ws) if root is not None and ws is not None else None) or {}
    cats = sorted({str(r[ci]) for r in data}) if ci is not None and not cnum else []
    auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(cats)}
    H = max(20.0, h - 22)
    boxes = squarify([_num(r[si]) for r in data], 0.0, 0.0, w - 12, H)
    out = []
    for r, v, (x, y, bw, bh) in zip(data, cv, boxes):
        if ci is not None and not cnum:
            col = cmap.get(str(r[ci])) or auto.get(str(r[ci]), _MARK["color"])
        else:
            col = measure_color(spec, v, min(cv_), max(cv_)) or _MARK["color"]
        ink = "#ffffff" if _lum(col) < 0.55 else INK
        name = fmt_dim(r[0], refs[0] if refs else "", masks[0] if masks else "") if ndims else ""
        lab = f"{_esc(name)}<br>{_esc(_fmt(r[si], captions[si] if captions else '', (masks or [''] * len(r))[si] if masks else ''))}"
        out.append(f"<div class='lbl' style='position:absolute;left:{x:.1f}px;top:{y:.1f}px;width:{bw:.1f}px;"
                   f"height:{bh:.1f}px;background:{col};color:{ink};font-size:9px;overflow:hidden;"
                   f"white-space:normal;padding:2px;box-shadow:inset -1px -1px 0 #fff'>{lab}</div>")
    return f"<div style='position:relative;height:{H:.0f}px'>{''.join(out)}</div>"


def _render_heat(rows, ndims: int, captions: list, masks: list, ws=None, root=None,
                 refs: list | None = None, mrefs: list | None = None) -> str:
    if ndims < 2:
        return _render_table(rows, ndims, captions, masks)
    refs, mrefs = refs or [], mrefs or []
    cref = _enc_ref(ws, "color") if ws is not None else ""
    vi = ndims + mrefs.index(cref) if cref in mrefs and ndims + mrefs.index(cref) < len(rows[0]) else ndims
    spec = measure_palette(root, ws, cref) if cref else {}
    text = ws is None or bool(_enc_ref(ws, "text") or _enc_ref(ws, "label")) or any(
        f.get("attr") == "mark-labels-show" and f.get("value") == "true" for f in ws.iter("format"))
    tref = (_enc_ref(ws, "text") or _enc_ref(ws, "label")) if ws is not None else ""
    ti = ndims + mrefs.index(tref) if tref in mrefs and ndims + mrefs.index(tref) < len(rows[0]) else len(rows[0]) - 1
    lab0 = lambda r, i: fmt_dim(r[i], refs[i] if i < len(refs) else "", masks[i] if i < len(masks or []) else "")
    cols = list(dict.fromkeys(lab0(r, 1) for r in rows))
    rws = list(dict.fromkeys(lab0(r, 0) for r in rows))
    cell = {(lab0(r, 0), lab0(r, 1)): r for r in rows}
    nums = [_num(r[vi]) for r in rows if _num(r[vi]) is not None]
    lo, hi = (min(nums), max(nums)) if nums else (0, 1)
    rules = style_rules(ws)
    ccss = text_css(ws, "label", refs[1] if len(refs) > 1 else "", rules)
    rcss = text_css(ws, "label", refs[0] if refs else "", rules)
    vcss = text_css(ws, "cell", tref or cref, rules)
    head = "<th></th>" + "".join(f"<th class='lbl' style='{ccss}'>{_esc(c)}</th>" for c in cols)
    body = []
    for a in rws:
        tds = [f"<td class='lbl' style='{rcss}'>{_esc(a)}</td>"]
        for b in cols:
            r = cell.get((a, b))
            if not r:
                tds.append("<td></td>")
                continue
            col = measure_color(spec, r[vi], lo, hi) or SEQ[1]
            ink = "#ffffff" if _lum(col) < 0.55 else INK
            lab = _fmt(r[ti], captions[ti] if ti < len(captions) else "", (masks or [""] * (ti + 1))[ti]
                       if ti < len(masks or []) else "") if text else ""
            own = vcss if "color:" in vcss else f"{vcss};color:{ink}"
            tds.append(f"<td class='lbl num' style='text-align:center;{own};background:{col}'>"
                       f"{_esc(lab)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
           "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]


def color_map(root, ws) -> dict:
    if ws is None:
        return {}
    enc = ws.find(".//encodings/color")
    if enc is None or "].[" not in (enc.get("column") or ""):
        return {}
    ds_name, inst = enc.get("column")[1:].split("].[", 1)
    inst = "[" + inst
    for ds in root.findall("datasources/datasource"):
        if ds.get("name") != ds_name or ds.find("style") is None:
            continue
        if ds.find(f"column-instance[@name='{inst}']") is None:
            return {}
        for e in ds.find("style").iter("encoding"):
            if e.get("attr") == "color" and e.get("field") == inst:
                return _CMap({(m.findtext("bucket") or "").strip('"'): m.get("to")
                              for m in e.findall("map") if m.get("to")})
    return {}


class _CMap(dict):

    def get(self, k, d=None):
        v = super().get(k)
        if v is None:
            v = super().get(str(k).lower())
        return d if v is None else v


def _render_bars(rows, ndims: int, cap: str, mask: str = "", h: float = 0.0,
                 entire: bool = True, cmap: dict | None = None, vi: int | None = None,
                 ci: int | None = None, labels: list | None = None,
                 panels: list | None = None, pmasks: list | None = None,
                 marks_on: bool = True) -> str:
    vi = -1 if vi is None else vi
    panels = [i for i in (panels or []) if rows and i < len(rows[0])]
    if len(panels) < 2:
        panels = [vi]
        pmasks = [mask]
    pmasks = list(pmasks or [mask] * len(panels))
    lab_of = {id(r): labels[k] for k, r in enumerate(rows)} if labels and len(labels) == len(rows) else {}
    data = [r for r in rows if r and len(r) > vi and _num(r[vi]) is not None]
    if not data:
        return "<div class='empty'>no data</div>"
    colors, cidx = {}, ci if ci is not None else (1 if ndims >= 2 else None)
    if cidx is not None:
        vals2 = list(dict.fromkeys(str(r[cidx]) for r in data))
        if len(vals2) <= 6:
            auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(sorted(vals2))}
            colors = {v: (cmap or {}).get(v) or auto[v] for v in vals2}
    dom = [axis_domain(min([0.0] + [_num(r[i]) for r in data if _num(r[i]) is not None]),
                       max([0.0] + [_num(r[i]) for r in data if _num(r[i]) is not None]))
           for i in panels]
    row_h = 16.0
    if entire and h:
        row_h = max(12.0, min(140.0, (h - 22) / len(data)))
    out = []
    for r in data:
        lab = lab_of.get(id(r)) if lab_of else (
            str(r[0]) if (colors or ndims <= 1 or ci is not None) else " · ".join(str(x) for x in r[:ndims]))
        col = colors.get(str(r[cidx]), _MARK["color"]) if colors else _MARK["color"]
        tracks = []
        for i, (lo, hi), mk in zip(panels, dom, pmasks):
            val = _num(r[i])
            if val is None:
                tracks.append("<span class='track'></span>")
                continue
            if lo < 0:
                tracks.append(_neg_track(val, lo, hi, row_h, col, _fmt(val, cap, mk) if marks_on else ""))
                continue
            pct = max(0.5, abs(val) / hi * 100)
            bv_ = f"<span class='lbl bval'>{_esc(_fmt(val, cap, mk))}</span>" if marks_on else ""
            tracks.append(f"<span class='track'><span class='fill' style='width:{pct:.1f}%;"
                          f"height:{row_h * 0.62:.1f}px;background:{col}'></span>{bv_}</span>")
        out.append(f"<div class='bar' style='height:{row_h:.1f}px'><span class='lbl blab'>{_esc(lab)}</span>"
                   f"{''.join(tracks)}</div>")
    return "".join(out)


def _axis_panels(ws, rows: list, ndims: int, mrefs: list) -> list:
    if ws is None or not rows:
        return []
    out = []
    for r_ in _shelf_refs(ws, "cols"):
        if r_ in mrefs and re.search(r":qk(:\d+)?\]$", r_):
            i = ndims + mrefs.index(r_)
            if i < len(rows[0]) and i not in out and len({str(x[i]) for x in rows}) > 1:
                out.append(i)
    return out


def _bar_indices(ws, refs: list, mrefs: list, ndims: int) -> tuple:
    shelf = _shelf_refs(ws, "cols") + _shelf_refs(ws, "rows")
    vi = next((ndims + k for k, m in enumerate(mrefs) if m in shelf), None)
    cref = _enc_ref(ws, "color")
    ci = None
    if cref:
        if cref in refs:
            ci = refs.index(cref)
        elif cref in mrefs and re.search(r":(nk|ok)(:\d+)?\]$", cref):
            ci = ndims + mrefs.index(cref)
    return vi, ci


def _shelf_refs(ws, tag: str) -> list:
    from .dryrun import inst_refs
    el = ws.find(f".//table/{tag}") if ws is not None else None
    return inst_refs(el.text) if el is not None and el.text else []


def _enc_ref(ws, tag: str) -> str:
    el = ws.find(f".//encodings/{tag}") if ws is not None else None
    from .dryrun import inst_refs
    found = inst_refs(el.get("column") or "") if el is not None else []
    return found[0] if found else ""


def _ticks(hi: float, n: int = 4) -> list:
    import math
    if hi <= 0:
        return [0.0]
    raw = hi / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return [k * step for k in range(int(hi // step) + 2) if k * step <= hi * 1.05 + 1e-9]


def axis_ticks(hi: float, n: int = 4) -> list:
    import math
    t = _ticks(hi, n)
    if t and t[-1] < hi and len(t) > 1:
        step = t[1] - t[0]
        t.append(math.ceil(hi / step) * step)
    return t


def axis_tick(v: float, hi: float, mask: str) -> str:
    if "%" in (mask or "") or (mask or "").lstrip("*")[:1] == "p":
        return fmt_mask(v, mask) or _fmt(v, "", mask)
    unit, div = ("B", 1e9) if hi >= 1e9 else ("M", 1e6) if hi >= 1e6 else \
        ("K", 1e3) if hi >= 1e3 else ("", 1.0)
    x = v / div
    num = f"{x:,.0f}" if float(x).is_integer() else f"{x:,.1f}".rstrip("0").rstrip(".")
    seg = (mask or "").lstrip("*").split(";")[0]
    body = seg[1:] if seg[:1] in "pnc" else seg
    pre = re.sub(r'"([^"]*)"', r"\1", re.split(r"[#0]", body, maxsplit=1)[0]) if body else ""
    core = re.search(r"[#0][#0,.]*(?:[KMB])?", body) if body else None
    post = re.sub(r'"([^"]*)"', r"\1", body[core.end():]) if core else ""
    post = re.sub(r"^[KMB]", "", post)
    return f"{pre}{num}{unit}{post}"


def stack_sums(rows: list, ndims: int, ci: int) -> list:
    acc: dict = {}
    for r in rows:
        v = _num(r[-1])
        if v is None:
            continue
        k = tuple(str(r[i]) for i in range(ndims) if i != ci)
        p, n = acc.get(k, (0.0, 0.0))
        acc[k] = (p + max(v, 0.0), n + min(v, 0.0))
    return list(acc.values()) or [(0.0, 0.0)]


def _render_hdots(rows: list, ndims: int, ci: int | None, cap: str, mask: str, h: float,
                  cmap: dict | None, labels: list, marks_on: bool, mark: str) -> str:
    data = [r for r in rows if r and _num(r[-1]) is not None]
    if not data:
        return "<div class='empty'>no data</div>"
    lab_of = {id(r): labels[k] for k, r in enumerate(rows)} if labels and len(labels) == len(rows) else {}
    groups: dict = {}
    for r in data:
        groups.setdefault(tuple(str(r[i]) for i in range(ndims) if i != ci), []).append(r)
    vals = [_num(r[-1]) for r in data]
    a2, b2 = axis_domain(min(vals), max(vals))
    span = (b2 - a2) or 1.0
    cats = sorted({str(r[ci]) for r in data}) if ci is not None else []
    auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(cats)}
    row_h = max(12.0, min(140.0, (h - 22) / len(groups))) if h else 16.0
    d = max(6.0, min(14.0, row_h * 0.6))
    radius = "50%" if mark == "Circle" else "2px"
    out = []
    for k, g in groups.items():
        dots = []
        for r in g:
            v = _num(r[-1])
            col = ((cmap or {}).get(str(r[ci])) or auto[str(r[ci])]) if ci is not None else _MARK["color"]
            x = (v - a2) / span * 100
            lab = (f"<span class='lbl' style='position:absolute;left:{x:.2f}%;top:calc(50% - {d / 2 + 13:.0f}px);"
                   f"transform:translateX(-50%);font-size:9px'>{_esc(_fmt(v, cap, mask))}</span>"
                   if marks_on else "")
            dots.append(f"<i style='position:absolute;left:calc({x:.2f}% - {d / 2:.0f}px);top:calc(50% - "
                        f"{d / 2:.0f}px);width:{d:.0f}px;height:{d:.0f}px;border-radius:{radius};"
                        f"background:{col};opacity:0.85'></i>{lab}")
        out.append(f"<div class='bar' style='height:{row_h:.1f}px'><span class='lbl blab'>"
                   f"{_esc(lab_of.get(id(g[0]), ' · '.join(k)))}</span><span class='track' "
                   f"style='position:relative;height:{row_h:.1f}px;border-bottom:1px solid {GRID}'>"
                   f"{''.join(dots)}</span></div>")
    return "".join(out)


def _render_hstack(rows: list, ndims: int, ci: int, cap: str, mask: str, h: float,
                   cmap: dict | None, labels: list, marks_on: bool) -> str:
    data = [r for r in rows if r and _num(r[-1]) is not None]
    if not data:
        return "<div class='empty'>no data</div>"
    lab_of = {id(r): labels[k] for k, r in enumerate(rows)} if labels and len(labels) == len(rows) else {}
    groups: dict = {}
    for r in data:
        groups.setdefault(tuple(str(r[i]) for i in range(ndims) if i != ci), []).append(r)
    sums = stack_sums(data, ndims, ci)
    a2, b2 = axis_domain(min(n for _, n in sums), max(p for p, _ in sums))
    span = (b2 - a2) or 1.0
    cats = sorted({str(r[ci]) for r in data})
    auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(cats)}
    row_h = max(12.0, min(140.0, (h - 22) / len(groups))) if h else 16.0
    out = []
    for k, g in groups.items():
        pos, neg, segs = 0.0, 0.0, []
        for r in sorted(g, key=lambda r: cats.index(str(r[ci]))):
            v = _num(r[-1])
            x0 = pos if v >= 0 else neg + v
            if v >= 0:
                pos += v
            else:
                neg += v
            col = (cmap or {}).get(str(r[ci])) or auto[str(r[ci])]
            left, wd = (x0 - a2) / span * 100, abs(v) / span * 100
            txt = _fmt(v, cap, mask) if marks_on and wd * 2.4 > len(_fmt(v, cap, mask)) * 6 else ""
            ink = "#ffffff" if _lum(col) < 0.55 else INK
            segs.append(f"<span class='seg lbl' style='left:{left:.2f}%;width:{wd:.2f}%;background:{col};"
                        f"color:{ink}'>{_esc(txt)}</span>")
        lab = lab_of.get(id(g[0]), " · ".join(k))
        out.append(f"<div class='bar' style='height:{row_h:.1f}px'><span class='lbl blab'>{_esc(lab)}</span>"
                   f"<span class='track' style='position:relative;height:{row_h * 0.62:.1f}px'>"
                   f"{''.join(segs)}</span></div>")
    return "".join(out)


def _neg_track(val: float, lo: float, hi: float, row_h: float, col: str, text: str) -> str:
    span = (hi - lo) or 1.0
    z = -lo / span * 100
    w = max(0.5, abs(val) / span * 100)
    fill = f"<span class='fill' style='width:{w:.1f}%;height:{row_h * 0.62:.1f}px;background:{col}'></span>"
    if val >= 0:
        return (f"<span class='track'><span style='flex:0 0 {z:.1f}%'></span>{fill}"
                f"<span class='lbl bval'>{_esc(text)}</span></span>")
    return (f"<span class='track'><span class='lbl bval' style='flex:0 0 {max(0.0, z - w):.1f}%;"
            f"text-align:right'>{_esc(text)}</span>{fill}</span>")


def _axis_html(lo: float, hi: float, amask: str | None, px: float = 4 * 43) -> str:
    if amask is None:
        return ""
    a2, b2, ticks = nice_axis(lo, hi, px, min_px=20.0, label=lambda t, ts: axis_label(t, ts, amask))
    span = (b2 - a2) or 1.0
    return ("<div class='axis hax'>" + "".join(
        f"<span class='lbl' style='left:{(t - a2) / span * 100:.1f}%'>{_esc(axis_label(t, ticks, amask))}"
        f"</span>" for t in ticks) + "</div>")


def row_headers(ws, refs: list, mrefs: list, rows: list, ndims: int, masks: list) -> list:
    if not rows or ws is None:
        return []
    hidden = _hidden_headers(ws)
    cols, had = [], False
    for r_ in _shelf_refs(ws, "rows"):
        known = r_ in refs[:ndims] or (r_ in mrefs and bool(re.search(r":ok(:\d+)?\]$", r_)))
        had |= known
        if r_ in hidden:
            continue
        if r_ in refs[:ndims]:
            cols.append(refs.index(r_))
        elif r_ in mrefs and re.search(r":ok(:\d+)?\]$", r_):
            cols.append(ndims + mrefs.index(r_))
    if not cols and had:
        from .dryrun import inst_refs
        for enc in ws.iter("encodings"):
            for e in enc:
                if e.tag not in ("text", "label"):
                    continue
                for r_ in inst_refs(e.get("column") or ""):
                    if r_ in refs[:ndims] and refs.index(r_) not in cols:
                        cols.append(refs.index(r_))
        if not cols:
            return ["" for _ in rows]
    if not cols:
        return []
    out = []
    for r in rows:
        parts = []
        for i in cols:
            v = r[i] if i < len(r) else ""
            mk = masks[i] if i < len(masks) else ""
            parts.append(_fmt(v, "", mk) if i >= ndims else fmt_dim(v, refs[i] if i < len(refs) else "", mk))
        out.append("  ".join(p for p in parts if p))
    return out


def dim_labels(ws, refs: list, rows: list, ndims: int, masks: list | None = None) -> list:
    if not rows or not ndims:
        return ["" for _ in rows]
    hidden = _hidden_headers(ws) if ws is not None else set()
    vis = [i for i in range(min(ndims, len(refs))) if refs[i] not in hidden]
    if not vis:
        return ["" for _ in rows]
    cols = _shelf_refs(ws, "cols") if ws is not None else []
    on = [i for i in vis if refs[i] in cols]
    i = (on or vis)[-1]
    got = {}
    for sr in (ws.iter("style-rule") if ws is not None else ()):
        for f in sr.findall("format"):
            if f.get("attr") == "text-format" and (f.get("field") or "").endswith(refs[i]):
                got.setdefault(sr.get("element"), f.get("value") or "")
    fmt = got.get("label") or got.get("header") or got.get("cell") or \
        ((masks or [])[i] if i < len(masks or []) else "")
    out = []
    for r in rows:
        out.append(fmt_dim(r[i], refs[i], fmt))
    return out


def _render_cols(rows, ndims: int, cap: str, mask: str, h: float, cmap: dict | None = None,
                 color_i: int | None = None, labels: list | None = None,
                 stack: bool = False, amask: str | None = None, vi: int = -1,
                 overlay: list | None = None, sync: bool = True, marks_on: bool = True,
                 ws=None, aref: str = "", mrefs: list | None = None,
                 consts: dict | None = None) -> str:
    data = [r for r in rows if r and _num(r[-1]) is not None]
    if not data:
        return "<div class='empty'>no data</div>"
    hi = max(abs(_num(r[-1])) for r in data) or 1.0
    vals = sorted({str(r[color_i]) for r in data}) if color_i is not None else []
    auto = {v: PALETTE[k % len(PALETTE)] for k, v in enumerate(vals)}
    H = max(30.0, h - 40)
    out = []
    lab = dict(zip(map(id, rows), labels)) if labels else {}
    if stack and color_i is not None:
        groups: dict = {}
        for r in data:
            groups.setdefault(tuple(str(r[i]) for i in range(ndims) if i != color_i), []).append(r)
        hi = max(sum(abs(_num(r[-1])) for r in g) for g in groups.values()) or 1.0
        for k, g in groups.items():
            segs = []
            for r in sorted(g, key=lambda r: str(r[color_i])):
                v = _num(r[-1])
                hh = max(0.5, abs(v) / hi * H)
                key = str(r[color_i])
                col = (cmap or {}).get(key) or auto.get(key, _MARK["color"])
                txt = _esc(_fmt(v, cap, mask)) if hh >= 12 and marks_on else ""
                segs.append(f"<i style='height:{hh:.1f}px;background:{col};font-style:normal;"
                            f"font-size:9px;color:#fff;text-align:center;overflow:hidden'>{txt}</i>")
            x = lab.get(id(g[0]), k[0] if k else "")
            out.append(f"<div class='col'>{''.join(segs)}<span class='lbl'>{_esc(x)}</span></div>")
        return f"<div class='cols' style='height:{H + 30:.0f}px'>{''.join(out)}</div>"
    if vi != -1:
        data = [r for r in rows if r and len(r) > vi and _num(r[vi]) is not None]
        if not data:
            return "<div class='empty'>no data</div>"
    vals = [_num(r[vi]) for r in data]
    ov = [(o[0], o[1], [(_num(r[o[0]]) if o[0] < len(r) else None) for r in data], o[2], o[3],
           (o[4] if len(o) > 4 else None) or _MARK["color"], o[5] if len(o) > 5 else "")
          for o in (overlay or [])]
    allv = vals + ([x for o in ov for x in o[2] if x is not None] if sync else [])
    P = max(20.0, H - 4)
    a, b, ticks = nice_axis(min(allv), max(allv), P,
                            integer=all(float(v).is_integer() for v in vals) and "." not in (amask or mask))
    t0, b0 = (14.0 if max(vals) > 0 else 0.0), (14.0 if min(vals) < 0 else 0.0)
    y = lambda v: t0 + (b - v) / ((b - a) or 1.0) * max(1.0, P - t0 - b0)
    cols = []
    for r, v in zip(data, vals):
        col = _MARK["color"]
        if color_i is not None:
            key = str(r[color_i])
            col = (cmap or {}).get(key) or auto.get(key, _MARK["color"])
        top, bot = y(max(v, 0.0)), y(min(v, 0.0))
        lab_pos = f"bottom:{P - top + 1:.1f}px" if v >= 0 else f"top:{bot + 1:.1f}px"
        txt_ = (f"<span class='lbl vval' style='{lab_pos}'>{_esc(_fmt(v, cap, mask))}</span>"
                if marks_on else "")
        cols.append(f"<div class='vcol'><i style='top:{top:.1f}px;height:{max(1.0, bot - top):.1f}px;"
                    f"background:{col}'></i>{txt_}</div>")
    zero = (f"<b class='vzero' style='top:{y(0.0):.1f}px'></b>" if a < 0 else "")
    base_ = zero
    cols_v = dict(consts or {})
    cols_v.update({m: [_num(r[ndims + k]) for r in data if ndims + k < len(r)]
                   for k, m in enumerate(mrefs or [])})
    for rv, rlab in (ref_lines(ws, aref, vals, mask, cols_v) if ws is not None and aref else []):
        base_ += (f"<b class='vref' style='top:{y(rv):.1f}px'></b>" + (
            f"<span class='lbl vrefl' style='top:{y(rv) - 13:.1f}px'>{_esc(rlab)}</span>" if rlab else ""))
    zero = base_
    n = len(data)
    raxis, rw = "", 0
    for oi, mk, ovals, show, om, ocol, oam in ov:
        pts_ = [(k + 0.5, v) for k, v in enumerate(ovals) if v is not None]
        if not pts_:
            continue
        if sync:
            yo = y
        else:
            oa, ob, oticks = nice_axis(min(v for _, v in pts_), max(v for _, v in pts_), P)
            yo = (lambda oa_, ob_: lambda v: t0 + (ob_ - v) / ((ob_ - oa_) or 1.0)
                  * max(1.0, P - t0 - b0))(oa, ob)
            if oam is not None and not raxis:
                rl = [axis_label(t, oticks, oam) for t in oticks]
                rw = max(len(t_) for t_ in rl) * 6 + 8
                raxis = (f"<div class='vaxis vaxr' style='width:{rw}px;"
                         f"height:{P:.0f}px'>" + "".join(
                             f"<span class='lbl' style='top:{yo(t) - 6:.1f}px'>{_esc(t_)}</span>"
                             for t, t_ in zip(oticks, rl)) + "</div>")
        if mk in ("Line", "Area"):
            zero += (f"<svg class='vov' viewBox='0 0 {n} {P:.0f}' preserveAspectRatio='none'>"
                     f"<polyline points='{' '.join(f'{x:.2f},{yo(v):.1f}' for x, v in pts_)}' "
                     f"fill='none' stroke='{ocol}' stroke-width='2' "
                     f"vector-effect='non-scaling-stroke'/></svg>")
        else:
            zero += "".join(f"<b class='vdot' style='left:{x / n * 100:.2f}%;top:{yo(v) - 4:.1f}px;"
                            f"background:{ocol}'></b>" for x, v in pts_)
        if show:
            zero += "".join(f"<span class='lbl vovl' style='left:{x / n * 100:.2f}%;top:{yo(v) - 16:.1f}px'>"
                            f"{_esc(_fmt(v, '', om))}</span>" for x, v in pts_)
    axis, aw = "", 0
    if amask is not None:
        texts = [axis_label(t, ticks, amask) for t in ticks]
        aw = max(len(t_) for t_ in texts) * 6 + 8
        axis = (f"<div class='vaxis' style='width:{aw}px;height:{P:.0f}px'>" + "".join(
            f"<span class='lbl' style='top:{y(t) - 6:.1f}px'>{_esc(s)}</span>"
            for t, s in zip(ticks, texts)) + "</div>")
    xl = "".join(f"<span class='lbl'>{_esc(lab.get(id(r), r[0]))}</span>" for r in data)
    return (f"<div class='vplot' style='height:{P:.0f}px'>{axis}<div class='vbars'>{base_}"
            f"{''.join(cols)}{zero[len(base_):]}</div>{raxis}</div>"
            f"<div class='vxl' style='margin-left:{aw}px;margin-right:{rw}px'>{xl}</div>")


def axis_domain(lo: float, hi: float) -> tuple:
    a, b = min(0.0, lo), max(0.0, hi)
    span = (b - a) or 1.0
    a2 = a - 0.15 * span if a < 0 else a
    b2 = b + 0.15 * span if b > 0 else b
    return (a2, b2) if b2 > a2 else (a2, a2 + 1.0)


def nice_axis(lo: float, hi: float, px: float, integer: bool = False,
              min_px: float = 43.0, label=None) -> tuple:
    import math
    a2, b2 = axis_domain(lo, hi)

    def ticks_of(step):
        return [0.0 if abs(k * step) < 1e-12 else round(k * step, 10)
                for k in range(math.ceil(a2 / step - 1e-9), math.floor(b2 / step + 1e-9) + 1)]
    raw = (b2 - a2) * min_px / max(min_px * 2, px)
    mag = 10 ** math.floor(math.log10(raw))
    steps = [m * mag * 10 ** e for e in range(0, 4) for m in (1, 2, 5)]
    step = next(st for st in steps if st >= raw - 1e-12)
    if integer:
        step = max(step, 1.0)
    while label is not None and len(ticks_of(step)) > 1:
        t = ticks_of(step)
        need = max(len(label(x, t)) for x in t) * 6 + 10
        if step / (b2 - a2) * px >= need:
            break
        step = next((st for st in steps if st > step + 1e-12), step * 2)
    return a2, b2, ticks_of(step)


def axis_label(v: float, ticks: list, mask: str) -> str:
    if mask:
        got = fmt_mask(v, mask)
        if got is not None:
            return got
    big = max((abs(t) for t in ticks), default=abs(v))
    unit, div = ("B", 1e9) if big >= 1e9 else ("M", 1e6) if big >= 1e6 else \
        ("K", 1e3) if big >= 1e3 else ("", 1.0)
    x = v / div
    return f"{x:,.0f}{unit}" if float(x).is_integer() else f"{x:,.2f}".rstrip("0").rstrip(".") + unit


def axis_mask(ws, mref: str, by_name: dict) -> str:
    for sr in (ws.iter("style-rule") if ws is not None else ()):
        if sr.get("element") != "label":
            continue
        for f in sr.findall("format"):
            if f.get("attr") == "text-format" and (f.get("field") or "").endswith(mref) and f.get("value"):
                return f.get("value")
    m = re.match(r"^\[(?:[a-z]+:)?(.+?):[a-z]{2}(?::\d+)?\]$", mref or "")
    return (by_name.get(f"[{m.group(1)}]") or "") if m else ""


def axis_hidden(ws, mref: str) -> bool:
    n_false, seen_true = 0, False
    for sr in (ws.iter("style-rule") if ws is not None else ()):
        if sr.get("element") != "axis":
            continue
        for f in sr.findall("format"):
            if f.get("attr") == "display" and (f.get("field") or "").endswith(mref):
                n_false += f.get("value") == "false"
                seen_true |= f.get("value") == "true"
    axes = (_shelf_refs(ws, "rows") + _shelf_refs(ws, "cols")).count(mref) if ws is not None else 0
    return n_false >= max(1, axes) and not seen_true


def _x_label(v) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(v))
    return _MON[int(m.group(2)) - 1][:3] if m else str(v)


def _y_axis(ws, lo: float, hi: float, H: float) -> tuple:
    y0, y1 = min(0.0, lo), hi
    fixed = False
    for e in (ws.iter("encoding") if ws is not None else ()):
        if e.get("attr") != "space" or e.get("scope") != "rows":
            continue
        rt = e.get("range-type") or ""
        if rt in ("fixed", "fixedmin") and _num(e.get("min")) is not None:
            y0, fixed = _num(e.get("min")), True
        if rt in ("fixed", "fixedmax") and _num(e.get("max")) is not None:
            y1, fixed = _num(e.get("max")), True
        if fixed:
            break
    n = max(2, int(H // 52))
    if not fixed and y0 >= 0:
        t = axis_ticks(y1, n)
        y1 = max(y1, t[-1] if t else y1)
    if y0 >= 0 and y1 > 0:
        ticks = [v for v in _ticks(y1, n) if y0 - 1e-9 <= v <= y1 + 1e-9]
    else:
        ticks = []
    return y0, (y1 if y1 > y0 else y0 + 1.0), ticks


def _grey(h: str) -> bool:
    try:
        c = [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    except ValueError:
        return False
    return max(c) - min(c) < 16


def _render_line(rows, ndims: int, cap: str, w: float, h: float, ws=None,
                 refs: list | None = None, mask: str = "", _panel: bool = False,
                 amask: str | None = "", extra: list | None = None, sync: bool = True,
                 cmap: dict | None = None) -> str:
    refs = refs or []
    xi = next((k for k, r in enumerate(refs) if r in _shelf_refs(ws, "cols")), 0)
    cref = _enc_ref(ws, "color")
    si = next((k for k, r in enumerate(refs) if r == cref and k != xi), None)
    dref = _enc_ref(ws, "lod")
    di = next((k for k, r in enumerate(refs) if dref and r == dref and k not in (xi, si)), None)
    data = [r for r in rows if r and _num(r[-1]) is not None]
    if len(data) < 2:
        return _render_bars(rows, ndims, cap)
    pi = next((k for k, r in enumerate(refs) if r in _shelf_refs(ws, "rows")
               and k not in (xi, si) and re.search(r":(nk|ok)(:\d+)?\]$", r)), None)
    if pi is not None and not _panel:
        vals_ = list(dict.fromkeys(str(r[pi]) for r in data))
        if 1 < len(vals_) <= 12:
            ph = max(30.0, h / len(vals_))
            return "".join(
                f"<div style='height:{ph:.0f}px;overflow:hidden;border-bottom:1px solid {GRID}'>"
                + _render_line([r for r in data if str(r[pi]) == v], ndims, cap, w, ph, ws=ws,
                               refs=refs, mask=mask, _panel=True, amask=amask, cmap=cmap) + "</div>"
                for v in (sorted(vals_) if ws is None or ws.find("table/view/manual-sort") is None
                          else vals_))
    xs = list(dict.fromkeys(str(r[xi]) for r in data))
    has_manual = ws is not None and ws.find("table/view/manual-sort") is not None
    if not has_manual:
        xs = sorted(xs)
    cvals = sorted({str(r[si]) for r in data}) if si is not None else [""]
    pal = {v: (cmap or {}).get(v) or PALETTE[k % len(PALETTE)] for k, v in enumerate(cvals)}

    def skey(r):
        return (str(r[si]) if si is not None else "", str(r[di]) if di is not None else "")
    series = sorted({skey(r) for r in data}, key=lambda s: (not _grey(pal.get(s[0], "#000")), s))
    vals = [_num(r[-1]) for r in data]
    extra = [i for i in (extra or []) if i < len(data[0])]
    if sync:
        vals += [_num(r[i]) for r in data for i in extra if _num(r[i]) is not None]
    lo, hi = min(vals), max(vals)
    W, H = max(40.0, w - 16), max(30.0, h - 34)
    y0, y1, ticks = _y_axis(ws, lo, hi, H)
    span = (y1 - y0) or 1.0
    area = ws is not None and any(p.find("mark") is not None and p.find("mark").get("class") == "Area"
                                  for p in ws.iter("pane"))
    pos = {x: (k / max(1, len(xs) - 1)) * W for k, x in enumerate(xs)}
    lines, labs = [], []
    lspec = line_labels(ws) if ws is not None else None
    for sv in series:
        vals_s = sorted(((pos[str(r[xi])], _num(r[-1])) for r in data if skey(r) == sv),
                        key=lambda p: p[0])
        pts = [(x, H - (v - y0) / span * H) for x, v in vals_s]
        if lspec:
            last_x = -1e9
            for k in pick_labels(vals_s, lspec):
                x, v = vals_s[k]
                t = _fmt(v, cap, mask)
                if lspec["mode"] == "all" and x - last_x < len(t) * 5.5 + 4:
                    continue
                last_x = x
                tw = len(t) * 5.5 + 4
                room = W >= tw
                right = (k == len(vals_s) - 1 and len(vals_s) > 1) or (room and x + tw / 2 > W)
                anchor = "translateX(-100%)" if right else \
                    ("none" if k == 0 or (room and x < tw / 2) else "translateX(-50%)")
                labs.append(f"<span class='lbl lnl' style='left:{x:.1f}px;top:{pts[k][1] - 14:.1f}px;"
                            f"transform:{anchor}'>{_esc(t)}</span>")
        if len(pts) >= 2:
            poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            col = pal[sv[0]] if si is not None else _MARK["color"]
            if area:
                lines.append(f"<polygon points='{pts[0][0]:.1f},{H:.1f} {poly} {pts[-1][0]:.1f},{H:.1f}' "
                             f"fill='{col}' fill-opacity='0.55' stroke='none'/>")
            lines.append(f"<polyline points='{poly}' fill='none' stroke='{col}' "
                         f"stroke-width='{1.5 if area else 2}'/>")
    for i in extra:
        ev = [(pos[str(r[xi])], _num(r[i])) for r in data if _num(r[i]) is not None]
        if len(ev) < 2:
            continue
        ea, eb = (y0, y0 + span) if sync else axis_domain(min(v for _, v in ev), max(v for _, v in ev))
        pts = sorted((x, H - (v - ea) / ((eb - ea) or 1.0) * H) for x, v in ev)
        lines.append(f"<polyline points='{' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)}' fill='none' "
                     f"stroke='{_MARK['color']}' stroke-width='2'/>")
    leg = ""
    if si is not None and ws is None:
        leg = "<div class='legend'>" + "".join(
            f"<span class='lbl'><i style='background:{pal[v]}'></i>{_esc(fmt_dim(v, refs[si]))}</span>"
            for v in cvals) + "</div>"
    labs_ = [value_alias(v, refs[xi] if xi < len(refs) else "") or _x_label(v) for v in xs]
    yref = next((r for r in _shelf_refs(ws, "rows") if re.search(r":qk(:\d+)?\]$", r)), None) \
        if ws is not None else None
    for rv, rlab in (ref_lines(ws, yref, vals, mask) if yref else []):
        yy = H - (rv - y0) / span * H
        lines.append(f"<line class='vref' x1='0' x2='{W:.0f}' y1='{yy:.1f}' y2='{yy:.1f}' "
                     f"stroke='#8c8c8c' stroke-dasharray='4 3'/>")
        if rlab:
            labs.append(f"<span class='lbl vrefl' style='position:absolute;right:0;"
                        f"top:{yy - 13:.1f}px'>{_esc(rlab)}</span>")
    need = max((len(t) for t in labs_), default=3) * 6 + 12
    step = next((k for k in range(1, len(xs) + 1) if W / max(1, -(-len(xs) // k)) >= need), len(xs))
    xl = "".join(f"<span class='lbl'>{_esc(t)}</span>" for t in labs_[::step])
    yt = "".join(f"<span class='lbl' style='position:absolute;left:0;"
                 f"top:{H - (v - y0) / span * H - 6:.0f}px'>{_esc(axis_label(v, ticks, amask))}</span>"
                 for v in ticks) if amask is not None else ""
    yax = (f"<div class='axis' style='position:absolute;left:0;top:0;"
           f"height:{H:.0f}px'>{yt}</div>") if yt else ""
    return (f"{leg}<div style='position:relative'>{yax}<svg width='{W:.0f}' height='{H:.0f}' "
            f"class='line'>{''.join(lines)}</svg>{''.join(labs)}</div><div class='axis'>{xl}</div>")


CSS = f"""
*{{box-sizing:border-box}} body{{margin:0;background:#f2f2f2;font-family:{FONT};color:{INK}}}
.canvas{{position:relative;background:{SURFACE};margin:{CANVAS_MARGIN}px;box-shadow:0 0 0 1px #ccc}}
.zone{{position:absolute;overflow:hidden}}
.sheet{{padding:4px 6px;font-size:10px}}
.sheet .ttl{{font-weight:400;font-size:20px;line-height:1.15;color:#333;white-space:normal;overflow:hidden;margin-bottom:3px}}
.sheet .ttl > div{{font-size:0}} .sheet .ttl,.sheet .ttl .lbl{{white-space:normal;overflow-wrap:anywhere}}
.lbl{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
table{{border-collapse:collapse;width:100%;table-layout:fixed}}
th,td{{font-size:11px;padding:2px 4px;border-bottom:1px solid {GRID};text-align:left}}
td.num{{text-align:right}} th{{color:{MUTED};font-weight:600}} th.num{{text-align:center}}
th .h2{{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;line-height:1.15;overflow-wrap:anywhere}}
.bar{{display:flex;align-items:center;height:16px;gap:4px;font-size:11px}}
.nolab .blab{{display:none}} .nolab .hax{{margin-left:0}}
.blab{{flex:0 0 40%;text-align:right;white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;line-height:1.15}} .track{{flex:1;display:flex;align-items:center;gap:3px;min-width:0}}
.fill{{display:block;height:11px}} .bval{{flex:0 0 auto;font-size:11px}}
.cols{{display:flex;align-items:flex-end;gap:4px}} .col{{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;font-size:10px}}
.col .lbl{{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.col i{{display:block;width:70%}} .hdr{{font-size:12px;color:#333;border-bottom:1px solid {GRID};padding:2px 0;margin-bottom:4px}}
.ln{{line-height:1.15}} .row{{display:flex;justify-content:space-around;text-align:center;font-size:18px}} .cell small{{font-size:12px;color:#333}} .empty{{color:{MUTED};font-style:italic}} .plate{{border-radius:3px;height:100%;display:flex;flex-direction:column;justify-content:center}}
.legend{{display:flex;gap:8px;font-size:9px;color:{MUTED};height:14px}} .legend i{{display:inline-block;width:8px;height:8px;margin-right:3px}}
.axis{{display:flex;justify-content:space-between;color:{MUTED};font-size:9px}}
.hax{{display:block;position:relative;height:12px;margin-left:calc(40% + 4px)}} .hax span{{position:absolute;transform:translateX(-50%);white-space:nowrap}}
.text{{font-size:11px;padding:2px 4px}} .ctl{{font-size:11px;padding:2px 4px}}
.ctl b{{display:block;color:#333;font-weight:400;font-size:12px}} .ctl .box{{display:block;border:1px solid #bdbdbd;padding:1px 4px;background:#fff}}
.stamp{{position:fixed;right:10px;bottom:6px;font:11px Arial;color:#c0392b;background:#fff8;padding:2px 6px}}
.vplot{{display:flex}} .vbars{{flex:1;display:flex;gap:4px;position:relative}} .vzero{{position:absolute;left:0;right:0;height:1px;background:#bdbdbd}}
.vref{{position:absolute;left:0;right:0;border-top:1px dashed #898989;z-index:2}} .vrefl{{position:absolute;left:2px;font-size:9px;color:#898989;z-index:2}}
.seg{{position:absolute;top:0;bottom:0;font-size:9px;text-align:center;line-height:1.6;box-shadow:inset -1px 0 0 #fff}}
.lnl{{position:absolute;font-size:10px;color:{INK};white-space:nowrap}}
.vov{{position:absolute;left:0;top:0;width:100%;height:100%;overflow:visible;pointer-events:none}}
.vdot{{position:absolute;width:8px;height:8px;margin-left:-4px;border-radius:50%}} .vovl{{position:absolute;transform:translateX(-50%);font-size:10px}}
.vcol{{flex:1;min-width:0;position:relative}} .vcol i{{position:absolute;left:15%;width:70%}} .vval{{position:absolute;left:50%;transform:translateX(-50%);white-space:nowrap;text-align:center;font-size:10px;line-height:12px}}
.vaxis{{position:relative;flex:0 0 auto;color:{MUTED};font-size:9px}} .vaxis span{{position:absolute;right:4px;line-height:12px}} .vaxr span{{left:4px;right:auto}}
.vxl{{display:flex;gap:4px;font-size:10px;padding-top:2px}} .vxl span{{flex:1;min-width:0;text-align:center}}
.nodiv td,.nodiv th{{border-bottom:0}}
.fitv td{{height:var(--rh);line-height:var(--rh);padding-top:0;padding-bottom:0;border-bottom-width:0;overflow:visible;vertical-align:middle}}
"""

FIT_JS = r"""() => {
  for (const t of document.querySelectorAll('.fitv')) {
    const z = t.closest('.zone');
    const rows = [...t.querySelectorAll('tr')].filter(r => r.querySelector('td'));
    if (!z || !rows.length) continue;
    const zr = z.getBoundingClientRect();
    const pad = parseFloat(getComputedStyle(z).paddingBottom) || 0;
    const top = rows[0].getBoundingClientRect().top;
    if (!t.dataset.natrh)
      t.dataset.natrh = ((rows[rows.length - 1].getBoundingClientRect().bottom - top) / rows.length).toFixed(2);
    const rh = Math.max(0, (zr.bottom - pad - top) / rows.length);
    t.style.setProperty('--rh', rh.toFixed(2) + 'px');
    t.dataset.rows = rows.length;
  }
}"""

PROBE_JS = r"""() => {
  const out = {zones: [], cut: [], overflow: [], squashed: []};
  const textW = el => { const rg = document.createRange(); rg.selectNodeContents(el);
                        return rg.getBoundingClientRect().width; };
  const bgOf = el => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const b = getComputedStyle(e).backgroundColor;
      if (b && b !== 'transparent' && !/rgba\([^)]*,\s*0\)/.test(b)) return b;
    }
    return 'rgb(255, 255, 255)';
  };
  for (const t of document.querySelectorAll('.fitv')) {
    const z = t.closest('.zone[data-kind]');
    const td = t.querySelector('td');
    if (!z || !td) continue;
    const rh = td.parentElement.getBoundingClientRect().height;
    const font = parseFloat(getComputedStyle(td).fontSize);
    if (rh < font) out.squashed.push({id: z.dataset.id, name: z.dataset.name || '', fit: t.dataset.fit,
                                      rows: +t.dataset.rows || 0, row_px: Math.round(rh * 10) / 10, font_px: font});
  }
  for (const z of document.querySelectorAll('.zone[data-kind]')) {
    const r = z.getBoundingClientRect(), c = z.closest('.canvas').getBoundingClientRect();
    const item = {id: z.dataset.id, kind: z.dataset.kind, name: z.dataset.name || '',
                  form: z.dataset.form || '', x: Math.round(r.left - c.left), y: Math.round(r.top - c.top),
                  w: Math.round(r.width), h: Math.round(r.height), text: z.innerText};
    if (z.scrollHeight > z.clientHeight + 2 || z.scrollWidth > z.clientWidth + 2) {
      item.overflow = {sh: z.scrollHeight, ch: z.clientHeight, sw: z.scrollWidth, cw: z.clientWidth};
      out.overflow.push(item);
    }
    let cut = 0, total = 0, samples = [];
    for (const l of z.querySelectorAll('.lbl')) {
      total++;
      const clamped = getComputedStyle(l).webkitLineClamp !== 'none';
      const over = clamped ? l.scrollHeight > l.clientHeight + 1 : l.scrollWidth > l.clientWidth + 1;
      if (over) { cut++; if (samples.length < 3) samples.push(l.textContent.slice(0, 40)); }
    }
    item.labels = total; item.cut = cut;
    if (cut) out.cut.push({id: item.id, name: item.name, cut, total, samples});
    const t = z.querySelector(':scope > .ttl');
    if (t) {
      const cs = getComputedStyle(t), fs = parseFloat(cs.fontSize);
      const lh = parseFloat(cs.lineHeight) || fs * 1.15;
      item.title = {need: Math.ceil(textW(t)), width: t.clientWidth, font_px: fs,
                    lines: Math.max(1, Math.round(t.scrollHeight / lh))};
    }
    const tabs = [];
    for (const tb of z.querySelectorAll('table')) {
      const body = [...tb.rows].filter(rw => rw.querySelector('td'));
      const top = k => body[k].getBoundingClientRect().top - c.top;
      const srcs = [...tb.querySelectorAll('colgroup > col')].map(cg => cg.dataset.src || '');
      const cols = [];
      for (const tr of tb.rows) [...tr.cells].forEach((cell, ci) => {
        const col = cols[ci] || (cols[ci] = {head: '', head_need: 0, have: cell.clientWidth, nat: 0,
                                              n: 0, num: 0, src: srcs[ci] || '', cut: []});
        const txt = cell.textContent.trim();
        if (!txt) return;
        const need = Math.ceil(textW(cell) + 8);
        if (cell.tagName === 'TH') { col.head = txt.slice(0, 60); col.head_need = need; return; }
        col.n++; col.have = cell.clientWidth;
        if (cell.classList.contains('num')) col.num++;
        col.nat = Math.max(col.nat, need);
        if (need > cell.clientWidth + 1 && col.cut.length < 5) col.cut.push(txt.slice(0, 40));
      });
      tabs.push({first: body.length ? Math.round(top(0)) : null, nbody: body.length,
                 pitch: body.length > 1 ? Math.round((top(body.length - 1) - top(0)) / (body.length - 1) * 10) / 10
                        : (body.length ? Math.round(body[0].getBoundingClientRect().height * 10) / 10 : 0),
                 cols});
    }
    if (tabs.length) item.tables = tabs;
    const boxes = [], inks = {};
    for (const l of z.querySelectorAll('.lbl')) {
      if (l.closest('table') || l.querySelector('.lbl')) continue;
      const rr = l.getBoundingClientRect();
      if (!rr.width || !rr.height || !l.textContent.trim()) continue;
      if (boxes.length < 200) boxes.push(rr);
      const key = getComputedStyle(l).color + ' | ' + bgOf(l);
      inks[key] = (inks[key] || 0) + 1;
    }
    let ovl = 0;
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2 &&
          Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2) ovl++;
    }
    item.overlaps = ovl;
    item.inks = inks;
    out.zones.push(item);
  }
  return out;
}"""


def _swap_state(root) -> dict:
    params = {}
    for d in root.iter("datasource"):
        if d.get("name") == "Parameters":
            for c in d.findall("column"):
                params[c.get("caption") or c.get("name", "").strip("[]")] = (c.get("value") or "").strip('"')
                params[c.get("name", "").strip("[]")] = (c.get("value") or "").strip('"')
    state = {}
    for c in root.iter("column"):
        cap = c.get("caption") or ""
        calc = c.find("calculation")
        if not cap.startswith("Swap ") or calc is None:
            continue
        m = re.search(r"\[Parameters\]\.\[([^\]]+)\]\s*=\s*'([^']*)'", calc.get("formula") or "")
        if m:
            state[cap[5:]] = params.get(m.group(1), "") == m.group(2)
    return state


def zone_fits(root, dashboard: str) -> dict:
    out = {}
    for win in (root.iter("window") if root is not None else ()):
        if win.get("class") != "dashboard" or win.get("name") != dashboard:
            continue
        for vp in win.iter("viewpoint"):
            zm = vp.find("zoom")
            out[vp.get("name")] = (zm.get("type") if zm is not None else "") or "standard"
    return out


TEXT_FORMS = ("table", "mlist", "matrix")
FIT_ROWS = ("entire-view", "fit-height")


def fit_rows(body: str, kind: str, fit: str) -> str:
    if kind not in TEXT_FORMS or fit not in FIT_ROWS or "<td" not in body:
        return body
    return f"<div class='fitv' data-fit='{_esc(fit)}'>{body}</div>"


def _walk_parent(node, parent=None):
    if getattr(node, "hidden", False) and not os.environ.get("TWKIT_FRAME_SHOW_HIDDEN"):
        return
    yield node, parent
    for c in node.children:
        yield from _walk_parent(c, node)


def axis_measure_last(rows: list, ndims: int, caps: list, masks: list, mrefs: list, ws):
    pick = _axis_pick(rows, ndims, mrefs, ws)
    if pick is None:
        return rows, caps, masks
    i = ndims + pick
    move = lambda xs: xs[:i] + xs[i + 1:] + xs[i:i + 1] if len(xs) > i else xs
    return [move(list(r)) for r in rows], move(list(caps)), move(list(masks))


def _axis_pick(rows: list, ndims: int, mrefs: list, ws) -> int | None:
    if not rows or len(rows[0]) - ndims < 2:
        return None
    shelf = set(_shelf_refs(ws, "rows")) | set(_shelf_refs(ws, "cols"))
    nm = len(rows[0]) - ndims
    on = [k for k in range(min(nm, len(mrefs))) if mrefs[k] in shelf]
    qk = [k for k in on if re.search(r":qk(:\d+)?\]$", mrefs[k])]
    varies = [k for k in qk if len({str(r[ndims + k]) for r in rows}) > 1]
    pick = (varies or qk or on or [None])[0]
    if pick is None:
        pick = next((k for k in range(nm)
                     if any(_num(r[ndims + k]) is not None for r in rows)), None)
    return None if pick is None or pick == nm - 1 else pick


def _mrefs_axis_last(rows: list, ndims: int, mrefs: list, ws) -> list:
    pick = _axis_pick(rows, ndims, mrefs, ws)
    if pick is None or pick >= len(mrefs):
        return list(mrefs)
    return mrefs[:pick] + mrefs[pick + 1:] + mrefs[pick:pick + 1]


def hide_filtered(ws, rows: list, refs: list) -> list:
    if ws is None or not rows:
        return rows
    for f in ws.iter("filter"):
        if f.get("kind") != "hide" or f.get("class") != "categorical":
            continue
        col = f.get("column") or ""
        key = "[" + col.split("].[", 1)[1] if "].[" in col else col
        idx = next((i for i, r in enumerate(refs or []) if r == key or r.endswith(key)), None)
        if idx is None:
            continue
        top = f.find("groupfilter")
        if top is None:
            continue
        mem = {(g.get("member") or "").strip('"').lower() for g in top.iter("groupfilter")
               if g.get("function") == "member" and g.get("member") is not None}
        mem = {"none" if m == "%null%" else m for m in mem}
        if top.get("function") == "except":
            keep = lambda v: str(v).strip('"').lower() not in mem
        elif top.get("function") == "member" or mem:
            keep = lambda v: str(v).strip('"').lower() in mem
        else:
            continue
        rows = [r for r in rows if idx < len(r) and keep(r[idx])]
    return rows


def default_order(ws, rows: list, ndims: int) -> list:
    if ws is None or not rows or not ndims:
        return rows

    def key(v):
        f = _num(v)
        return (0, f, "") if f is not None else (1, 0, str(v).lower())
    return sorted(rows, key=lambda r: tuple(key(r[i]) for i in range(min(ndims, len(r)))))


def _render_mlist(rows, ndims: int, captions: list, masks: list, ws=None,
                  refs: list | None = None, fit: str = "", sized: bool = False,
                  mrefs: list | None = None) -> str:
    if not rows:
        return "<div class='empty'>no data</div>"
    refs = refs or []
    hidden = _hidden_headers(ws) if ws is not None else set()
    in_label = ws is not None and any((e.get("column") or "").endswith("[:Measure Names]")
                                      for e in ws.iter() if e.tag in ("text", "label"))
    show_names = "[:Measure Names]" not in hidden or in_label
    cols = _shelf_refs(ws, "cols") if ws is not None else []
    ci = next((i for i in range(min(ndims, len(refs))) if refs[i] in cols), None)
    groups = rows if ci is not None else rows[:1]
    head = None
    rules = style_rules(ws)
    if ci is not None and refs[ci] not in hidden:
        hcss = header_css(ws, refs[ci], rules)
        head = ([("", "lbl")] if show_names else []) + [
            (fmt_dim(r[ci], refs[ci], masks[ci] if ci < len(masks or []) else ""), "lbl num", hcss)
            for r in groups]
    out = []
    ncss = header_css(ws, "[:Measure Names]", rules)
    for i in range(ndims, len(rows[0])):
        cap = captions[i] if i < len(captions) else ""
        mk = masks[i] if masks and i < len(masks) else ""
        vcss = text_css(ws, "cell", (mrefs or [])[i - ndims] if i - ndims < len(mrefs or []) else "", rules)
        out.append(([(cap, "lbl", ncss)] if show_names else []) +
                   [(_fmt(r[i], cap, mk), "lbl num", vcss) for r in groups])
    kinds = ([("h", "[:Measure Names]")] if show_names else []) + [("v", "") for _ in groups]
    return _table_html(head, out, kinds if sized else None, ws, fit)


def manual_order(ws, rows: list, ndims: int) -> list:
    if ws is None or not rows:
        return rows
    for ms in ws.findall("table/view/manual-sort"):
        order = [(b.text or "").strip('"') for b in ms.iter("bucket")]
        rank = {v: i for i, v in enumerate(order)}
        for col in range(ndims):
            if all(str(r[col]) in rank for r in rows):
                return sorted(rows, key=lambda r: rank[str(r[col])])
    return rows


def _extract_images(path: str, root, dst: str) -> dict:
    import zipfile
    want = {z.get("param") for z in root.iter("zone")
            if (z.get("type-v2") or z.get("type")) == "bitmap" and z.get("param")}
    want |= {(ip.text or "").strip() for ip in root.iter("image-path") if (ip.text or "").strip()}
    if not want or not str(path).lower().endswith(".twbx"):
        return {}
    out = {}
    try:
        with zipfile.ZipFile(path) as zf:
            names = {n.replace("\\", "/"): n for n in zf.namelist()}
            for p in want:
                arc = names.get(p.replace("\\", "/"))
                if not arc:
                    continue
                rel = os.path.join("assets", re.sub(r"[^\w\-.]+", "_", p))
                os.makedirs(os.path.join(dst, "assets"), exist_ok=True)
                with open(os.path.join(dst, rel), "wb") as f:
                    f.write(zf.read(arc))
                out[p] = rel
    except (OSError, zipfile.BadZipFile):
        return {}
    return out


def title_width(body: str, kind: str, fit: str) -> float | None:
    if kind not in TEXT_FORMS or fit in FIT_ROWS[:1] + ("fit-width",):
        return None
    m = re.search(r"<table[^>]*data-cols='px' style='width:(\d+)px'", body or "")
    return max(44.0, float(m.group(1))) if m else None


def measure_order(root, ws, d: dict) -> dict:
    if ws is None or not d.get("rows") or "[:Measure Names]" not in \
            _shelf_refs(ws, "rows") + _shelf_refs(ws, "cols"):
        return d
    ds = next((d for d in ws.iterfind("table/view/datasources/datasource")
               if d.get("name") != "Parameters"), None)
    order = []
    srcs = list(ws.iter("manual-sort")) + [ms for x in (root.findall("datasources/datasource")
                                                      if root is not None else ())
                                           if ds is None or x.get("name") == ds.get("name")
                                           for ms in x.findall("default-sorts/manual-sort")]
    for ms in srcs:
        if (ms.get("column") or "").endswith("[:Measure Names]"):
            order = [_inst_key((re.findall(r"\[[^\]]+\]", b.text or "") or [""])[-1])
                     for b in ms.iter("bucket")]
            break
    nd, mr = d.get("ndims", 0), list(d.get("mrefs") or [])
    if not order or len(mr) < 2 or any(len(r) != nd + len(mr) for r in d["rows"]):
        return d
    rank = {k: i for i, k in enumerate(order)}
    perm = sorted(range(len(mr)), key=lambda k: (rank.get(_inst_key(mr[k]), len(order)), k))
    if perm == list(range(len(mr))):
        return d
    cols = list(range(nd)) + [nd + k for k in perm]

    def pick(xs):
        return [xs[i] for i in cols] if len(xs) == nd + len(mr) else xs
    out = dict(d)
    out["rows"] = [pick(list(r)) for r in d["rows"]]
    out["captions"], out["masks"] = pick(list(d.get("captions") or [])), pick(list(d.get("masks") or []))
    out["mrefs"] = [mr[k] for k in perm]
    if len(d.get("amasks") or []) == len(mr):
        out["amasks"] = [d["amasks"][k] for k in perm]
    return out


def _page_html(name: str, dash, sheets: dict, data: dict, title: str, root=None,
               assets: dict | None = None, dyn: dict | None = None) -> str:
    cw, ch, mode = LM.dashboard_size(dash)
    tree = R._build_tree(dash, cw, ch)
    swap = _swap_state(root) if root is not None else {}
    pcap, pval = {}, {}
    for d in (root.iter("datasource") if root is not None else ()):
        if d.get("name") == "Parameters":
            for c in d.findall("column"):
                key = (c.get("name") or "").strip("[]")
                pcap[key] = c.get("caption") or ""
                raw = (c.get("value") or "")
                al = {(a.get("key") or ""): a.get("value") for a in c.iter("alias")}
                pval[key] = c.get("alias") or al.get(raw) or raw.strip('"').strip("#")
    pval.update(dyn or {})
    pfmt = {}
    for d in (root.iter("datasource") if root is not None else ()):
        if d.get("name") == "Parameters":
            for c in d.findall("column"):
                if c.get("default-format"):
                    pfmt[(c.get("name") or "").strip("[]")] = c.get("default-format")
    pdisp = {k: param_text(v, pfmt.get(k, "")) for k, v in pval.items()}
    fits = zone_fits(root, name)
    zone_el = {}
    texts = {}
    zroot = dash.find("zones")
    for ze in (zroot if zroot is not None else dash).iter("zone"):
        zone_el.setdefault(ze.get("id"), ze)
    for ze in (zroot if zroot is not None else dash).iter("zone"):
        if (ze.get("type-v2") or ze.get("type")) == "text":
            texts[ze.get("id")] = _runs_html(ze, _subst(pdisp, name, None, None))
    parts = []
    for top in tree:
        for z, parent in _walk_parent(top):
            if z.is_container:
                st = zone_box(z)[0]
                if st:
                    parts.append(f"<div class='zone' style='left:{z.x:.0f}px;top:{z.y:.0f}px;"
                                 f"width:{z.w:.0f}px;height:{z.h:.0f}px;{st}'></div>")
                continue
            x, y, w, h = z.x, z.y, z.w, z.h
            if R.is_sheet(z) and z.name in swap:
                if not swap[z.name]:
                    continue
                if parent is not None:
                    x, y, w, h = parent.x, parent.y, parent.w, parent.h
            zcss_, explicit_, ins_ = zone_box(z)
            box = (f"left:{x:.0f}px;top:{y:.0f}px;width:{w:.0f}px;height:{h:.0f}px;"
                   f"{zcss_}" + (";z-index:5" if z.floating else ""))
            w, h = max(8.0, w - ins_[1] - ins_[3]), max(8.0, h - ins_[0] - ins_[2])
            if R.is_sheet(z):
                sbg_ = sheet_background(sheets.get(z.name))
                zbg_ = _opaque((z.style or {}).get("background-color"))
                if sbg_ and explicit_:
                    box += (f";background:linear-gradient({sbg_},{sbg_}) content-box"
                            + (f",{zbg_} padding-box" if zbg_ else ""))
                elif sbg_:
                    box += f";background:{sbg_}"
            attrs = f"data-id='{_esc(z.id)}' data-kind='{_esc(z.kind)}' data-name='{_esc(z.name)}'"
            if R.is_sheet(z):
                ws = sheets.get(z.name)
                d = measure_order(root, ws, data.get(z.name) or {})
                rows, ndims = d.get("rows") or [], d.get("ndims", 0)
                caps, masks = d.get("captions") or [], d.get("masks") or []
                mr0_ = d.get("mrefs") or []
                caps = [(measure_alias(mr0_[i - ndims]) or c) if ndims <= i < ndims + len(mr0_) else c
                        for i, c in enumerate(caps)]
                kind = _sheet_kind(ws, rows, ndims, d.get("mrefs"))
                rows = hide_filtered(ws, rows, d.get("refs") or [])
                rows = default_order(ws, rows, ndims)
                if ws is not None and any(":Measure Names" in r for r in _shelf_refs(ws, "rows")) \
                        and kind in ("table", "card"):
                    kind = "mlist"
                if ws is not None and rows and ndims < len(rows[0]):
                    ss = ws.find(".//shelf-sort-v2")
                    if ss is not None and ss.get("measure-to-sort-by", "").endswith(("qk]", "ok]")):
                        rev = (ss.get("direction") or "DESC") == "DESC"
                        sref = (re.findall(r"\[[^\]]+\]", ss.get("measure-to-sort-by")) or [""])[-1]
                        mr_ = d.get("mrefs") or []
                        si_ = ndims + mr_.index(sref) if sref in mr_ else len(rows[0]) - 1
                        si_ = si_ if si_ < len(rows[0]) else len(rows[0]) - 1
                        rows = sorted(rows, key=lambda r: (_num(r[si_]) is None, _num(r[si_]) or 0),
                                      reverse=rev)
                        if rev:
                            rows = [r for r in rows if _num(r[si_]) is not None] + \
                                   [r for r in rows if _num(r[si_]) is None]
                rows = manual_order(ws, rows, ndims)
                _MARK["color"] = mark_color(ws) if ws is not None and \
                    ws.find(".//encodings/color") is None else BAR
                mrefs_ = list(d.get("mrefs") or [])
                if kind in ("bar", "line") and ws is not None:
                    mrefs_ = _mrefs_axis_last(rows, ndims, mrefs_, ws)
                    rows, caps, masks = axis_measure_last(rows, ndims, caps, masks,
                                                          d.get("mrefs") or [], ws)
                if d.get("synthetic") and kind in ("card", "table", "bar") and ndims and not (
                        kind == "card" and len(rows) == 1 and ws is not None
                        and ws.find(".//customized-label") is not None):
                    kind = "row"
                cap = caps[-1] if caps else ""
                mask = masks[-1] if masks else ""
                ttl_h = 26 if z.title else 0
                if not rows:
                    body = f"<div class='empty'>{_esc(d.get('note') or 'no data')}</div>"
                elif kind == "row" and _chip_refs(ws, d.get("refs") or []):
                    body = _render_chips(ws, rows, d.get("refs") or [], root)
                elif kind == "row":
                    mc = _mark_text_color(ws)
                    rf_ = d.get("refs") or [""]
                    cells = "".join(f"<span class='lbl cell'><small>{_esc(fmt_dim(r[0], rf_[0]))}</small><br>"
                                    f"<span style='color:{mc}'>{_esc(' '.join(str(x) for x in r[1:ndims]))}</span>"
                                    f"</span>" for r in rows)
                    body = f"<div class='row'>{cells}</div>"
                elif kind == "mvline":
                    body = _render_mvline(rows, ndims, d.get("refs") or [], ws, w, h - ttl_h)
                elif kind == "map":
                    body = _render_map(ws, rows, ndims, d.get("refs") or [], d.get("mrefs") or [],
                                       w, h - ttl_h, root)
                elif kind == "card":
                    body = _render_cards(ws, rows, ndims, masks, d.get("refs") or [],
                                         d.get("mrefs") or [], pdisp)
                elif kind == "bigtext":
                    body = _render_bigtext(ws, rows, ndims, masks, d.get("mrefs") or [])
                    pl_ = _plate(ws, root, rows, ndims, d.get("refs") or [], d.get("mrefs") or [])
                    if pl_:
                        body = f"<div class='plate' style='background:{pl_}'>{body}</div>"
                elif kind == "mlist":
                    body = _render_mlist(rows, ndims, caps, masks, ws, d.get("refs") or [],
                                         fits.get(z.name, "standard"), sized=True,
                                         mrefs=d.get("mrefs") or [])
                elif kind == "matrix":
                    body = _render_heat(rows, ndims, caps, masks, ws, root, d.get("refs") or [],
                                        d.get("mrefs") or [])
                elif kind == "pie":
                    body = _render_pie(rows, ndims, caps, masks, w, h - ttl_h,
                                       cmap=color_map(root, ws) if root is not None else None,
                                       ws=ws, refs=d.get("refs") or [],
                                       mrefs=d.get("mrefs") or [], params=pdisp)
                elif kind == "glyph":
                    body = _render_glyph(ws, rows, ndims, d.get("refs") or [], masks, w, h - ttl_h)
                elif kind == "scatter":
                    body = _render_scatter(ws, rows, ndims, d.get("refs") or [], d.get("mrefs") or [],
                                           caps, masks, d.get("amasks") or [], w, h - ttl_h, root)
                elif kind == "treemap":
                    body = _render_treemap(rows, ndims, caps, masks, w, h - ttl_h, ws, root,
                                           d.get("refs") or [], d.get("mrefs") or [])
                elif kind == "table":
                    body = _render_crosstab(ws, rows, ndims, d.get("refs") or [], caps, masks,
                                            fits.get(z.name, "standard"), sized=True,
                                            mref=(d.get("mrefs") or [""])[0]) \
                        if ws is not None else None
                    if not body:
                        t_ = _table_view(ws, root, rows, ndims, d.get("refs") or [], caps, masks)
                        body = _render_table(t_[0], t_[1], t_[2], t_[3], heads=t_[4], tint=t_[5],
                                             refs=t_[6], ccolor=cell_colors(ws, root, t_[0], t_[1],
                                                                            d.get("mrefs") or []),
                                             ws=ws, fit=fits.get(z.name, "standard"), sized=True,
                                             mrefs=d.get("mrefs") or [])
                elif kind == "line":
                    ax_ = mrefs_[-1] if mrefs_ else ""
                    am_ = dict(zip(d.get("mrefs") or [], d.get("amasks") or [])).get(ax_, "")
                    fold_, sync_ = folded(ws, "rows")
                    ex_ = [ndims + mrefs_.index(r_) for r_, _m, _s in fold_ if r_ in mrefs_ and r_ != ax_]
                    pan_ = list(dict.fromkeys(
                        r_ for r_ in _shelf_refs(ws, "rows") if r_ in mrefs_
                        and re.search(r":qk(:\d+)?\]$", r_))) if not fold_ else []
                    if len(pan_) >= 2 and rows:
                        amap_ = dict(zip(d.get("mrefs") or [], d.get("amasks") or []))
                        ph_ = max(40.0, (h - ttl_h) / len(pan_))
                        body = ""
                        for r_ in pan_:
                            i_ = ndims + mrefs_.index(r_)
                            if i_ >= len(rows[0]):
                                continue
                            rr_ = [list(x[:i_]) + list(x[i_ + 1:]) + [x[i_]] for x in rows]
                            body += (f"<div style='height:{ph_:.0f}px;overflow:hidden'>" + _render_line(
                                rr_, ndims, caps[i_] if i_ < len(caps) else cap, w, ph_, ws=ws,
                                refs=d.get("refs"), mask=masks[i_] if i_ < len(masks) else "",
                                _panel=True, amask=None if axis_hidden(ws, r_) else amap_.get(r_, ""),
                                cmap=color_map(root, ws) if root is not None else None)
                                + "</div>")
                    else:
                        body = _render_line(rows, ndims, cap, w, h - ttl_h, ws=ws,
                                            refs=d.get("refs"), mask=mask,
                                            amask=None if axis_hidden(ws, ax_) else am_,
                                            extra=ex_, sync=sync_,
                                            cmap=color_map(root, ws) if root is not None else None)
                else:
                    refs_ = d.get("refs") or []
                    cols_ = _shelf_refs(ws, "cols")
                    cm_ = color_map(root, ws) if root is not None else None
                    if refs_ and refs_[0] in cols_ and not _shelf_refs(ws, "rows")[:1] == refs_[:1]:
                        cref_ = _enc_ref(ws, "color")
                        ci_ = next((k for k, rr in enumerate(refs_) if rr == cref_), None)
                        ax_ = mrefs_[-1] if mrefs_ else ""
                        fold_, sync_ = folded(ws, "rows")
                        vi_, ov_ = -1, []
                        if fold_ and all(r_ in mrefs_ for r_, _m, _s in fold_):
                            ax_ = next((r_ for r_, m_, _s in fold_ if m_ == "Bar"), fold_[0][0])
                            vi_ = ndims + mrefs_.index(ax_)
                            amap_ = dict(zip(d.get("mrefs") or [], d.get("amasks") or []))
                            ov_ = [(ndims + mrefs_.index(r_), m_, s_, masks[ndims + mrefs_.index(r_)]
                                    if ndims + mrefs_.index(r_) < len(masks) else "",
                                    pane_style(ws, r_)["color"],
                                    None if axis_hidden(ws, r_) else amap_.get(r_, ""))
                                   for r_, m_, s_ in fold_ if r_ != ax_]
                            cap = caps[vi_] if vi_ < len(caps) else cap
                            mask = masks[vi_] if vi_ < len(masks) else mask
                        am_ = dict(zip(d.get("mrefs") or [], d.get("amasks") or [])).get(ax_, "")
                        body = _render_cols(rows, ndims, cap, mask, h - ttl_h, cmap=cm_, color_i=ci_,
                                            labels=dim_labels(ws, refs_, rows, ndims, masks),
                                            stack=ci_ is not None and cref_ not in cols_,
                                            amask=None if axis_hidden(ws, ax_) or ax_ not in
                                            _shelf_refs(ws, "rows") + cols_ else am_,
                                            vi=vi_, overlay=ov_, sync=sync_,
                                            marks_on=marks_shown(ws, ax_ if fold_ else ""),
                                            ws=ws, aref=ax_, mrefs=mrefs_,
                                            consts=ref_line_columns(root, ws, mrefs_))
                    else:
                        _vi, ci_ = _bar_indices(ws, refs_, mrefs_, ndims)
                        pan_ = _axis_panels(ws, rows, ndims, mrefs_)
                        ax_ = mrefs_[-1] if mrefs_ else ""
                        am_ = dict(zip(d.get("mrefs") or [], d.get("amasks") or [])).get(ax_, "")
                        if axis_hidden(ws, ax_) or ax_ not in _shelf_refs(ws, "rows") + cols_:
                            am_ = None
                        nums_ = [_num(r[-1]) for r in rows if r and _num(r[-1]) is not None]
                        dots_ = len(pan_) < 2 and {(p_.find("mark").get("class") if p_.find("mark")
                                                    is not None else "Automatic")
                                                   for p_ in ws.iter("pane")} <= {"Circle", "Shape"} and \
                            not any(re.search(r":(nk|ok)(:\d+)?\]$", r_) for r_ in cols_)
                        stack_ = ci_ is not None and ci_ < ndims and len(pan_) < 2 and not dots_ and \
                            refs_[ci_] not in _shelf_refs(ws, "rows") + cols_
                        if stack_ and nums_:
                            sums_ = stack_sums(rows, ndims, ci_)
                            nums_ = [min(0.0, min(n_ for _p, n_ in sums_)), max(0.0, max(p_ for p_, _n in sums_))]
                        rh_ = row_headers(ws, refs_, mrefs_, rows, ndims, masks)
                        nolab_ = bool(rh_) and not any(rh_)
                        axis_ = _axis_html(min(nums_), max(nums_), am_,
                                           (w - 12) * (1.0 if nolab_ else 0.6) - 4) \
                            if nums_ else ""
                        hh_ = h - ttl_h - (14 if axis_ else -14)
                        if dots_:
                            body = _render_hdots(rows, ndims, ci_ if ci_ is not None and ci_ < ndims and
                                                 refs_[ci_] not in _shelf_refs(ws, "rows") else None,
                                                 cap, mask, hh_, cm_, rh_,
                                                 marks_shown(ws), LM.mark_class(ws)) + axis_
                        elif stack_:
                            body = _render_hstack(rows, ndims, ci_, cap, mask, hh_, cm_, rh_,
                                                  marks_shown(ws)) + axis_
                        else:
                            body = _render_bars(rows, ndims, cap, mask, hh_,
                                                cmap=cm_, ci=ci_,
                                                labels=rh_,
                                                panels=pan_, pmasks=[masks[i] if i < len(masks) else ""
                                                                     for i in pan_],
                                                marks_on=marks_shown(ws)) + axis_
                        if nolab_:
                            body = f"<div class='nolab'>{body}</div>"
                fit = fits.get(z.name, "standard")
                body = fit_rows(body, kind, fit)
                ttl = _title_html(ws, z.name, pdisp, d) if z.title else ""
                tw_ = title_width(body, kind, fit)
                if ttl and tw_:
                    ttl = ttl.replace("<div class='ttl", f"<div style='max-width:{tw_:.0f}px' class='ttl", 1)
                tip_ = tooltip_text(ws, z.name, pdisp, d)
                tip_ = f" data-tooltip='1' title='{_esc(tip_)}'" if tip_ else ""
                parts.append(f"<div class='zone sheet' {attrs} data-form='{kind}' "
                             f"data-fit='{_esc(fit)}'{tip_} style='{box}'>{ttl}{body}</div>")
            elif z.kind == "text":
                pad_ = ";padding:0" if not explicit_ and (z.w < 16 or z.h < 12) else ""
                parts.append(f"<div class='zone text' {attrs} style='{box}{pad_}'>"
                             f"{texts.get(z.id, '')}</div>")
            elif z.kind in ("paramctrl", "filter"):
                ze = zone_el.get(z.id)
                label, cur = _control_text(z, ze, root, sheets, pcap, pval, pfmt)
                parts.append(f"<div class='zone ctl' {attrs} style='{box}'>"
                             f"{label}<span class='box lbl'>{_esc(cur)} ▾</span></div>")
            elif z.kind == "color" and z.param:
                parts.append(f"<div class='zone' {attrs} style='{box}'>"
                             f"{_legend_html(z, sheets.get(z.name), data.get(z.name) or {}, root)}</div>")
            elif z.kind == "dashboard-object" and zone_el.get(z.id) is not None and \
                    zone_el[z.id].find("button") is not None:
                parts.append(f"<div class='zone' {attrs} style='{box}'>"
                             f"{_button_html(zone_el[z.id].find('button'), assets or {})}</div>")
            elif z.kind == "bitmap" and (assets or {}).get(z.param):
                fit = "contain" if z.scaled else "none"
                parts.append(f"<div class='zone' {attrs} style='{box}'>"
                             f"<img src='{_esc(assets[z.param])}' style='width:100%;height:100%;"
                             f"object-fit:{fit};object-position:left top;display:block'></div>")
            elif z.kind not in ("empty", "blank"):
                parts.append(f"<div class='zone' {attrs} style='{box};border:1px dashed #ddd'>"
                             f"<span class='lbl' style='font-size:9px;color:{MUTED}'>{_esc(z.kind)}</span></div>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_esc(title)} · {_esc(name)}</title>"
            f"<style>{font_css()}{CSS}</style></head><body>"
            f"<div class='canvas' data-page='{_esc(name)}' style='width:{cw}px;height:{ch}px'>"
            f"{''.join(parts)}</div><div class='stamp'>FRAME - a model, not Tableau - {cw}x{ch} {mode}</div>"
            f"<script>window.addEventListener('load',()=>{{({FIT_JS})();const r=({PROBE_JS})();"
            f"const e=document.createElement('script');e.type='application/json';e.id='probe-out';"
            f"e.textContent=JSON.stringify(r);document.body.appendChild(e);}});</script>"
            f"</body></html>")


def sheet_data(path: str, limit: int = 300) -> dict:
    from .dryrun import dry_run
    from .lint import load
    results = dry_run(path, limit=limit, sample_rows=limit, dynamic=True)
    stuck = [r.sheet for r in results if r.status == "skipped"]
    if stuck:
        relaxed = {r.sheet: r for r in dry_run(path, limit=limit, sample_rows=limit, relax=True,
                                                dynamic=True)
                   if r.status == "ok"}
        results = [relaxed.get(r.sheet, r) if r.status == "skipped" else r for r in results]
    root = load(path).root
    fmt_of = {}
    for c in root.iter("column"):
        if c.get("default-format"):
            fmt_of.setdefault(c.get("caption") or c.get("name", "").strip("[]"), c.get("default-format"))
    sheet_fmt = {}
    for w in root.iter("worksheet"):
        m_ = {}
        for f in w.iter("format"):
            if f.get("attr") == "text-format" and f.get("field") and f.get("value"):
                inst = re.findall(r"\[[^\]]+\]", f.get("field"))
                if inst:
                    m_[inst[-1]] = f.get("value")
        sheet_fmt[w.get("name")] = m_
    by_name = {c.get("name"): c.get("default-format") for c in root.iter("column")
               if c.get("default-format")}
    wss = {w.get("name"): w for w in root.iter("worksheet")}
    out = {}
    for r in results:
        caps = list(getattr(r, "dim_labels", []) or []) + list(getattr(r, "measure_labels", []) or [])
        if len(caps) != len(r.dim_exprs) + len(r.measure_exprs):
            caps = [_caption(e) for e in list(r.dim_exprs) + list(r.measure_exprs)]
        out[r.sheet] = {"rows": [list(x) for x in (r.sample or [])], "ndims": len(r.dim_exprs),
                        "captions": caps, "masks": _masks(r, caps, fmt_of, sheet_fmt.get(r.sheet, {})),
                        "synthetic": bool(r.synthetic_measure),
                        "refs": list(getattr(r, "dim_refs", []) or []),
                        "mrefs": list(getattr(r, "measure_refs", []) or []),
                        "amasks": [axis_mask(wss.get(r.sheet), m, by_name)
                                   for m in (getattr(r, "measure_refs", []) or [])],
                        "status": r.status,
                        "note": "" if r.status == "ok" else f"{r.status}: {r.note[:60]}"}
    return out


def _masks(r, caps: list, fmt_of: dict, sfmt: dict) -> list:
    nd = len(r.dim_exprs)
    mrefs = list(getattr(r, "measure_refs", []) or [])
    drefs = list(getattr(r, "dim_refs", []) or [])
    out = []
    for i, c in enumerate(caps):
        k = i - nd
        own = sfmt.get(mrefs[k]) if 0 <= k < len(mrefs) else \
            (sfmt.get(drefs[i]) if 0 <= i < len(drefs) else None)
        out.append(own or fmt_of.get(c, ""))
    return out


def _caption(expr: str) -> str:
    m = re.findall(r'"([^"]+)"', expr or "")
    return m[-1] if m else (expr or "")[:30]


def _default_out(path: str) -> str:
    import tempfile
    ap = os.path.abspath(path)
    if ap.startswith(os.path.expanduser("~/Documents")):
        return os.path.join(tempfile.gettempdir(), "twkit_frame")
    return os.path.join(os.path.dirname(ap), "_frame")


def publish(path: str, out_dir: str = "", limit: int = 300, default_locale: str = "") -> dict:
    from .lint import load
    book = load(path)
    root = book.root
    loc = root.get("locale") or default_locale
    _SEP["locale"] = loc
    _ALIAS.clear()
    _ALIAS.update(column_alias_map(root))
    if not loc:
        _SEP["group"] = "\u202f"
    elif loc.split("_")[0] in ("ru", "fr", "de", "pl", "uk"):
        _SEP["group"] = "\u00a0"
    else:
        _SEP["group"] = ","
    title = os.path.splitext(os.path.basename(path))[0]
    out_dir = out_dir or _default_out(path)
    dst = os.path.join(out_dir, re.sub(r"[^\w\-. ]+", "_", title))
    os.makedirs(dst, exist_ok=True)
    wsn = root.find("worksheets")
    sheets = {w.get("name"): w for w in (list(wsn) if wsn is not None else [])}
    try:
        data = sheet_data(path, limit=limit)
    except Exception as exc:                                  # noqa: BLE001
        data, note = {}, f"no data: {type(exc).__name__}: {str(exc)[:80]}"
    else:
        note = ""
    assets = _extract_images(path, root, dst)
    try:
        from .dryrun import dynamic_param_values
        dyn = dynamic_param_values(path)
    except Exception:                                         # noqa: BLE001
        dyn = {}
    pages = []
    for i, dash in enumerate(root.iter("dashboard"), 1):
        name = dash.get("name") or f"page {i}"
        fn = f"page_{i:02d}.html"
        with open(os.path.join(dst, fn), "w", encoding="utf-8") as f:
            f.write(_page_html(name, dash, sheets, data, title, root, assets, dyn))
        pages.append({"page": name, "file": os.path.join(dst, fn)})
    links = "".join(f"<li><a href='{os.path.basename(p['file'])}'>{_esc(p['page'])}</a></li>"
                    for p in pages)
    with open(os.path.join(dst, "index.html"), "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset='utf-8'><title>{_esc(title)}</title>"
                f"<h3 style='font-family:Arial'>{_esc(title)}</h3><ol>{links}</ol>")
    return {"book": title, "folder": dst, "pages": pages, "data": note or "present",
            "how_to_view": "chrome-devtools new_page('file://' + page file); "
                           "measure with evaluate_script(frame.PROBE_JS)"}


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _chrome(args: list, timeout: int = 20, until=None, tries: int = 3) -> str:
    import signal
    import subprocess
    import tempfile
    import time
    for attempt in range(tries):
        prof = tempfile.mkdtemp(prefix="twkit_frame_chrome_")
        out_path = os.path.join(prof, "out.txt")
        with open(out_path, "w") as fo:
            pr = subprocess.Popen([CHROME, "--headless", "--disable-gpu", "--no-first-run",
                                   "--hide-scrollbars", f"--user-data-dir={prof}", *args],
                                  stdout=fo, stderr=subprocess.DEVNULL, start_new_session=True)
            t0, done = time.time(), False
            try:
                while time.time() - t0 < timeout and pr.poll() is None:
                    txt = open(out_path, encoding="utf-8", errors="replace").read()
                    if (until and until()) or (until is None and "</html>" in txt):
                        done = True
                        break
                    time.sleep(0.3)
            finally:
                time.sleep(0.3)
                try:
                    os.killpg(pr.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pr.kill()
                pr.wait()
        txt = open(out_path, encoding="utf-8", errors="replace").read()
        if done or (until and until()) or (until is None and "</html>" in txt):
            return txt
        with open(os.path.join(tempfile.gettempdir(), "twkit_chrome_hangs.log"), "a") as lg:
            lg.write(f"{time.strftime('%H:%M:%S')} attempt {attempt + 1} {timeout}s "
                     f"{' '.join(a for a in args if a.startswith('--'))[:100]} {args[-1][-70:]}\n")
    return txt


def canvas_size(page: str):
    return re.search(r"class='canvas'[^>]*style='width:(\d+)px;height:(\d+)px", page)


def probe(page_file: str, shot: str = "") -> dict:
    try:
        return _probe_cdp(page_file, shot)
    except Exception:  # noqa: BLE001
        import tempfile
        import traceback
        with open(os.path.join(tempfile.gettempdir(), "twkit_chrome_hangs.log"), "a") as lg:
            lg.write("cdp: " + traceback.format_exc(limit=2).replace("\n", " | ")[:300] + "\n")
        return _probe_oneshot(page_file, shot)


def _probe_cdp(page_file: str, shot: str = "") -> dict:
    from . import cdp
    url = pathlib.Path(os.path.abspath(page_file)).as_uri()
    m = canvas_size(open(page_file, encoding="utf-8").read())
    w, h = (int(m.group(1)) + 40, int(m.group(2)) + 40) if m else (1600, 1200)
    with cdp.Tab() as t:
        t.open(url, w, h, "document.fonts.status === 'loaded' && "
                          "!!document.getElementById('probe-out')")
        out = json.loads(t.eval("document.getElementById('probe-out').textContent"))
        if shot:
            t.screenshot(shot)
            out["image"] = shot
    return out


def _probe_oneshot(page_file: str, shot: str = "") -> dict:
    url = pathlib.Path(os.path.abspath(page_file)).as_uri()
    m = canvas_size(open(page_file, encoding="utf-8").read())
    w, h = (int(m.group(1)) + 40, int(m.group(2)) + 40) if m else (1600, 1200)
    dom = _chrome(["--virtual-time-budget=2000", "--dump-dom", url])
    mm = re.search(r'<script type="application/json" id="probe-out">(.*?)</script>', dom, re.S)
    out = json.loads(html.unescape(mm.group(1))) if mm else {"error": "no measurement returned"}
    if shot:
        if os.path.exists(shot):
            os.unlink(shot)
        _chrome([f"--window-size={w},{h}", f"--screenshot={os.path.abspath(shot)}", url],
                until=lambda: os.path.exists(shot) and os.path.getsize(shot) > 0)
        out["image"] = shot
    return out


def check(path: str, out_dir: str = "", limit: int = 300, shots: bool = True,
          default_locale: str = "") -> dict:
    pub = publish(path, out_dir=out_dir, limit=limit, default_locale=default_locale)
    pages = []
    for p in pub["pages"]:
        shot = p["file"].replace(".html", ".png") if shots else ""
        r = probe(p["file"], shot)
        pages.append({"page": p["page"], "file": p["file"], "zone_count": len(r.get("zones", [])),
                      "clipped": [c for c in r.get("cut", []) if c.get("cut")],
                      "overflow": r.get("overflow", []), "image": r.get("image", ""),
                      "squashed": r.get("squashed", []),
                      "zones": r.get("zones", []),
                      **({"error": r["error"]} if "error" in r else {})})
    cut = sum(sum(c["cut"] for c in pg["clipped"]) for pg in pages)
    return {"book": pub["book"], "page_count": len(pages), "clipped_labels": cut,
            "overflowing_zones": sum(len(pg["overflow"]) for pg in pages),
            "squashed_tables": sum(len(pg["squashed"]) for pg in pages),
            "pages": pages, "data": pub["data"],
            "note": "this is a view MODEL; open the images with Read and compare with Tableau"}

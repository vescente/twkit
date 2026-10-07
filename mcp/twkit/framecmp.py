"""Compare frame images with reference renders (Tableau Public / Desktop)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile

_M = 20

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "ocr.swift")


def _ocr_bin() -> str:
    """The compiled OCR helper lives in a temp dir; rebuilt when the source changes."""
    tag = hashlib.md5(open(_SRC, "rb").read()).hexdigest()[:8]
    out = os.path.join(tempfile.gettempdir(), f"twkit_ocr_{tag}")
    if not os.path.exists(out):
        subprocess.run(["swiftc", "-O", _SRC, "-o", out], check=True, capture_output=True)
    return out


def ocr(png: str) -> list:
    """Text lines of a reference image: [{t, c, x, y, w, h}] in pixels, y from the top."""
    r = subprocess.run([_ocr_bin(), png], capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout or "[]")


_NUM = re.compile(r"[-+−]?[$€£]?\d[\d,.   ]*\d?%?[KMB]?", re.I)


def tokens(text: str) -> set:
    """Normalized tokens: lowercase words, numbers without group separators."""
    out = set()
    for m in _NUM.finditer(text):
        v = m.group(0).strip().replace("−", "-").replace(" ", "").replace(" ", "")
        if any(ch.isdigit() for ch in v):
            out.add(v.rstrip(".,"))
    for w in re.findall(r"[^\W\d_]{2,}", text):
        out.add(w.lower())
    return out


def shape(tok: str) -> str:
    """Number shape: digits -> 9 ('$733.2K' -> '$999.9K')."""
    return re.sub(r"\d", "9", tok)


_ERR = re.compile(r"error", re.I)


def classes(ref_t: set, fr_t: set, text: str, empty: bool) -> list:
    """Zone mismatch classes (order = weight: error > empty > value > format > text)."""
    out = []
    if _ERR.search(text):
        out.append("error")
    if empty:
        out.append("empty")
    miss = ref_t - fr_t
    nums = {t for t in miss if any(ch.isdigit() for ch in t)}
    fshapes = {shape(t) for t in fr_t if any(ch.isdigit() for ch in t)}
    if any(shape(t) in fshapes for t in nums):
        out.append("value")
    if any(shape(t) not in fshapes for t in nums):
        out.append("format")
    if miss - nums:
        out.append("text")
    return out


def _ink(img, box) -> float:
    """Ink share of a rectangle: pixels clearly darker or more colorful than the zone background."""
    x, y, w, h = box
    c = img.crop((x, y, x + w, y + h)).convert("RGB").resize((max(1, w // 2), max(1, h // 2)))
    px = list(c.getdata())
    if not px:
        return 0.0
    from collections import Counter
    bg = Counter(px).most_common(1)[0][0]
    far = sum(1 for p in px if sum(abs(a - b) for a, b in zip(p, bg)) > 60)
    return far / len(px)


def _zone_cmp(z: dict, fimg, rimg, lines: list, k: float, flines: list | None = None) -> dict:
    rb = (int(z["x"] * k), int(z["y"] * k), int(z["w"] * k), int(z["h"] * k))
    inside = [l["t"] for l in lines
              if rb[0] <= l["x"] + l["w"] / 2 <= rb[0] + rb[2]
              and rb[1] <= l["y"] + l["h"] / 2 <= rb[1] + rb[3]]
    text = z.get("text", "")
    if z["kind"] == "bitmap" and flines:
        fb = (z["x"] + _M, z["y"] + _M, z["w"], z["h"])
        text += " " + " ".join(l["t"] for l in flines
                               if fb[0] <= l["x"] + l["w"] / 2 <= fb[0] + fb[2]
                               and fb[1] <= l["y"] + l["h"] / 2 <= fb[1] + fb[3])
    ref_t, fr_t = tokens(" ".join(inside)), tokens(text)
    ink_r = _ink(rimg, rb)
    ink_f = _ink(fimg, (z["x"] + _M, z["y"] + _M, z["w"], z["h"]))
    empty = ink_r > 0.02 and ink_f < 0.2 * ink_r
    return {"zone": z["name"] or z["kind"], "view": z["kind"], "form": z.get("form", ""),
            "id": z.get("id", ""), "xy": [z["x"], z["y"], z["w"], z["h"]],
            "found": round(len(ref_t & fr_t) / len(ref_t), 2) if ref_t else None,
            "missing": sorted(ref_t - fr_t)[:12], "extra": sorted(fr_t - ref_t)[:12],
            "empty": empty, "classes": classes(ref_t, fr_t, z.get("text", ""), empty),
            "ink": [round(ink_r, 3), round(ink_f, 3)]}


CLASSES = ("error", "empty", "value", "format", "text")


def _summary(zones: list) -> dict:
    scored = [z["found"] for z in zones if z["found"] is not None]
    return {"zone_count": len(zones),
            "text_median": sorted(scored)[len(scored) // 2] if scored else None,
            "below_0.5": sum(1 for v in scored if v < 0.5),
            "classes": {c: sum(1 for z in zones if c in z["classes"]) for c in CLASSES}}


def ref_date(refs: dict) -> str:
    """Reference capture date (earliest PNG): the workbook TODAY() is evaluated at this date."""
    import datetime as _dt
    ts = [os.path.getmtime(p) for p in refs.values() if p and os.path.exists(p)]
    return _dt.date.fromtimestamp(min(ts)).isoformat() if ts else ""


def _freeze_today(day: str) -> None:
    """TODAY()/NOW() of the run: fixed to the reference capture date (comparison only)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or ""):
        return
    from . import dryrun
    dryrun.DIALECTS["hyper"].update(today=f"DATE '{day}'", now=f"TIMESTAMP '{day} 12:00:00'")


def compare(book: str, refs: dict, out_dir: str = "", today: str = "") -> dict:
    """Frame against reference PNGs per zone: {dashboard name: png}."""
    from PIL import Image
    from . import frame
    _freeze_today(today)
    r = frame.check(book, out_dir=out_dir, default_locale="en_US")
    pages = {}
    for pg in r["pages"]:
        ref = refs.get(pg["page"])
        if not ref or not os.path.exists(ref) or not pg.get("image"):
            continue
        fimg, rimg = Image.open(pg["image"]), Image.open(ref)
        zones = [z for z in pg.get("zones", []) if z["w"] > 4 and z["h"] > 4]
        cw = max((z["x"] + z["w"] for z in zones), default=1)
        k = rimg.width / cw
        lines = [l for l in ocr(ref) if l["c"] >= 0.5]
        flines = ([l for l in ocr(pg["image"]) if l["c"] >= 0.5]
                  if any(z["kind"] == "bitmap" for z in zones) else [])
        others = [(z["x"] + _M, z["y"] + _M, z["w"], z["h"]) for z in zones if z["kind"] != "bitmap"]
        flines = [l for l in flines if not any(
            b[0] <= l["x"] + l["w"] / 2 <= b[0] + b[2] and b[1] <= l["y"] + l["h"] / 2 <= b[1] + b[3]
            for b in others)]
        zs = [_zone_cmp(z, fimg, rimg, lines, k, flines) for z in zones]
        pages[pg["page"]] = {**_summary(zs), "zones": zs, "image": pg["image"], "reference": ref}
    return {"book": os.path.basename(book), "data": r["data"], "pages": pages}


def corpus(manifest: str, books_dir: str, out_json: str, out_dir: str = "",
           timeout: int = 180, only: list | None = None) -> dict:
    """Run the corpus by the reference manifest: a score snapshot for regression plus a class summary."""
    import sys
    import time
    man = json.load(open(manifest))
    unknown = sorted(set(only or ()) - {b["book"] for b in man})
    if unknown:
        import difflib
        near = {u: difflib.get_close_matches(u, [b["book"] for b in man], 1, 0.3) for u in unknown}
        raise ValueError(f"not in the manifest (names match whole): {near}")
    snap = json.load(open(out_json)).get("books", {}) if only and os.path.exists(out_json) else {}
    for b in man:
        if only and b["book"] not in only:
            continue
        refs = {d["name"]: os.path.abspath(os.path.join(os.path.dirname(manifest), d["file"]))
                for d in b.get("dashboards", []) if d.get("status") == 200}
        path = os.path.join(books_dir, b["book"] + ".twbx")
        if not refs or not os.path.exists(path):
            continue
        job = json.dumps({"book": os.path.abspath(path),
                          "refs": refs,
                          "today": ref_date(refs),
                          "out": os.path.abspath(os.path.join(out_dir, b["book"])) if out_dir else ""})
        t0 = time.time()
        pr = subprocess.Popen([sys.executable, "-m", "twkit.framecmp", job], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              cwd=os.path.dirname(_HERE), start_new_session=True)
        try:
            so, se = pr.communicate(timeout=timeout)
            res = json.loads(so.strip().splitlines()[-1]) if pr.returncode == 0 else {"failure": se[-300:]}
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(pr.pid, signal.SIGKILL)
            pr.communicate()
            res = {"failure": f"timeout {timeout}s"}
        except json.JSONDecodeError:
            res = {"failure": "output is not JSON"}
        res["sec"] = round(time.time() - t0, 1)
        snap[b["book"]] = res
        _write(out_json, snap)
    return _write(out_json, snap)


def _write(out_json: str, snap: dict) -> dict:
    by_class = {c: sorted({b for b, v in snap.items() for pg in v.get("pages", {}).values()
                           if pg["classes"].get(c)}) for c in CLASSES}
    out = {"book_count": len(snap), "failures": sum(1 for v in snap.values() if "failure" in v),
           "classes_by_book": {c: len(v) for c, v in by_class.items()}, "books": snap}
    json.dump(out, open(out_json, "w"), ensure_ascii=False, indent=1)
    return out


_W = {"error": 16, "empty": 8, "value": 4, "format": 2, "text": 1}


def _zone_cost(z: dict) -> int:
    return sum(_W[c] for c in z.get("classes", []))


def _align(old: list, new: list) -> list:
    """Pairs of zones of the old and new snapshot by (name, kind)."""
    if all(z.get("id") for z in old + new):
        by = {z["id"]: z for z in old}
        return [(by[z["id"]], z) for z in new if z["id"] in by]
    import difflib
    ka = [(z["zone"], z["view"]) for z in old]
    kb = [(z["zone"], z["view"]) for z in new]
    out = []
    for blk in difflib.SequenceMatcher(a=ka, b=kb, autojunk=False).get_matching_blocks():
        out += [(old[blk.a + k], new[blk.b + k]) for k in range(blk.size)]
    return out


def diff(old_json: str, new_json: str) -> dict:
    """Regression gate: a zone is worse when its class weight grew (error > empty > value > format > text)."""
    a, b = json.load(open(old_json))["books"], json.load(open(new_json))["books"]
    better = worse = same = 0
    worse_list = []
    for book, nv in b.items():
        for page, pg in nv.get("pages", {}).items():
            opg = a.get(book, {}).get("pages", {}).get(page)
            if not opg:
                continue
            for oz, nz in _align(opg["zones"], pg["zones"]):
                co, cn = _zone_cost(oz), _zone_cost(nz)
                if cn < co:
                    better += 1
                elif cn > co:
                    worse += 1
                    worse_list.append({"book": book, "page": page, "zone": nz["zone"],
                                       "before": oz["classes"], "after": nz["classes"],
                                       "missing": nz["missing"][:6]})
                else:
                    same += 1
    clean = lambda d: sum(1 for v in d.values() for pg in v.get("pages", {}).values()
                          for z in pg["zones"] if not z["classes"])
    return {"better": better, "worse": worse, "same": same,
            "clean_zones": [clean(a), clean(b)], "worse_zones": worse_list}


def gate(old_json: str, new_json: str, rerun) -> dict:
    """`diff` with one second chance: a book whose zone became empty is drawn again first.

    Under load a headless page can be measured before it draws: a zone read as empty in a full
    run and clean alone. `rerun(books)` redraws those books into `new_json`; zones that come
    back are listed in `recovered`, not counted as worse."""
    d = diff(old_json, new_json)
    key = lambda z: f"{z['book']} | {z['page']} | {z['zone']}"
    went = [z for z in d["worse_zones"] if "empty" in z["after"] and "empty" not in z["before"]]
    books = sorted({z["book"] for z in went})
    if not books:
        return dict(d, redrawn=[], recovered=[])
    rerun(books)
    d2 = diff(old_json, new_json)
    still = {key(z) for z in d2["worse_zones"]}
    return dict(d2, redrawn=books, recovered=[key(z) for z in went if key(z) not in still])


if __name__ == "__main__":
    import sys
    a = json.loads(sys.argv[1])
    print(json.dumps(compare(a["book"], a["refs"], out_dir=a["out"], today=a.get("today", "")),
                     ensure_ascii=False))

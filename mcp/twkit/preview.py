"""Sheet previews: the real Tableau render embedded as base64 PNG in <thumbnails> on save."""
from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass


@dataclass
class Thumb:
    name: str
    width: int
    height: int
    path: str
    bytes_: int

    def as_dict(self) -> dict:
        return {"sheet": self.name, "size": f"{self.width}×{self.height}",
                "file": self.path, "bytes": self.bytes_}


def list_thumbnails(book_path: str) -> list[dict]:
    """List the previews stored in the workbook without writing them to disk."""
    from .lint import load
    root = load(book_path).root
    out = []
    for t in root.findall(".//thumbnails/thumbnail"):
        payload = (t.text or "").strip()
        out.append({"name": t.get("name") or "", "width": int(t.get("width") or 0),
                    "height": int(t.get("height") or 0), "b64_len": len(payload)})
    return out


def extract_thumbnails(book_path: str, out_dir: str = "") -> list[Thumb]:
    """Extract previews to PNG files."""
    from .lint import load
    book = load(book_path)
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(book_path)),
                                      "_preview")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(book_path))[0]

    result: list[Thumb] = []
    for i, t in enumerate(book.root.findall(".//thumbnails/thumbnail")):
        payload = (t.text or "").strip()
        if not payload:
            continue
        try:
            data = base64.b64decode(payload)
        except Exception:
            continue
        safe = (t.get("name") or f"sheet{i}").replace("/", "_").replace(os.sep, "_")[:40]
        path = os.path.join(out_dir, f"{stem} — {safe}.png")
        with open(path, "wb") as f:
            f.write(data)
        result.append(Thumb(t.get("name") or "", int(t.get("width") or 0),
                            int(t.get("height") or 0), path, len(data)))
    return result


def strip_thumbnails(root) -> int:
    """Remove previews from the workbook tree; returns how many were removed."""
    removed = 0
    for th in list(root.findall(".//thumbnails")):
        removed += len(th.findall("thumbnail"))
        parent = th.getparent()
        if parent is not None:
            parent.remove(th)
    return removed


def compare_with_source(ported_book: str, source_book: str) -> dict:
    """Check whether a ported workbook inherited the source's previews (compared by payload length)."""
    a = {t["name"]: t["b64_len"] for t in list_thumbnails(ported_book)}
    b = {t["name"]: t["b64_len"] for t in list_thumbnails(source_book)}
    same = [n for n, ln in a.items() if b.get(n) == ln]
    return {"in_ported": len(a), "in_source": len(b), "identical": same,
            "verdict": ("previews INHERITED from the source - the workbook shows foreign data"
                        if same else "no foreign previews")}


def format_report(book_path: str, thumbs: list[Thumb]) -> str:
    if not thumbs:
        return (f"{os.path.basename(book_path)}: no previews - the workbook was never saved "
                f"from Tableau.\n  To get a real image: open it, press Cmd+S, extract again.")
    lines = [f"{os.path.basename(book_path)}: {len(thumbs)} previews "
             f"(rendered by Tableau itself)"]
    for t in thumbs:
        lines.append(f"  · {t.name or '(unnamed)':28s} {t.width}×{t.height}  {t.path}")
    lines.append("  Open these PNGs and look: the only way to see what the linter and dry run miss.")
    return "\n".join(lines)


def _stamp_path() -> str:
    return os.path.join(tempfile.gettempdir(), "twkit_written.json")


def _sig(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [int(st.st_mtime), st.st_size]


def mark_written(path: str) -> None:
    """Record that our layer wrote the workbook (called from `safexml.to_twbx`)."""
    sig = _sig(path)
    if sig is None:
        return
    try:
        seen = json.load(open(_stamp_path(), encoding="utf-8"))
    except Exception:
        seen = {}
    seen[os.path.abspath(path)] = sig
    try:
        json.dump(seen, open(_stamp_path(), "w", encoding="utf-8"))
    except OSError:
        pass


def written_by_us(path: str) -> bool | None:
    """True if our layer wrote the file last, None if the file is unknown to us."""
    sig = _sig(path)
    if sig is None:
        return None
    try:
        seen = json.load(open(_stamp_path(), encoding="utf-8"))
    except Exception:
        return None
    known = seen.get(os.path.abspath(path))
    return None if known is None else known == sig


def thumbs_state(book_path: str) -> dict:
    """Whether the workbook holds a real Tableau render and whether it can be trusted."""
    thumbs = list_thumbnails(book_path)
    if not thumbs:
        return {"verdict": "no previews - the workbook was never saved from Tableau",
                "fresh": False, "previews": []}
    ours = written_by_us(book_path)
    if ours is True:
        return {"verdict": f"{len(thumbs)} previews are STALE: our layer wrote the "
                           f"workbook last, the image predates the edit",
                "fresh": False, "previews": thumbs}
    if ours is None:
        return {"verdict": f"{len(thumbs)} previews, freshness UNKNOWN: we do not "
                           f"know who wrote the file last",
                "fresh": None, "previews": thumbs}
    return {"verdict": f"{len(thumbs)} previews are FRESH - a render by Tableau itself, "
                       f"no window screenshot needed",
            "fresh": True, "previews": thumbs}

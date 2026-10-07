"""Custom named colour palettes — the `Preferences.tps` file."""
from __future__ import annotations

import os
import re
import shutil
import time

from . import safexml

TYPES = ("regular", "ordered-sequential", "ordered-diverging")
DIALOG_LIMIT = 20
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def default_path() -> str:
    """`Preferences.tps` sits next to `Workbooks/` in the Tableau repository."""
    return os.path.expanduser("~/Documents/My Tableau Repository/Preferences.tps")


def snippet(name: str, colors: list, kind: str = "ordered-diverging") -> str:
    """The XML to paste."""
    if kind not in TYPES:
        raise ValueError(f"palette type must be one of {TYPES}, got {kind!r}")
    if not name.strip():
        raise ValueError("a palette needs a name — that name is how a workbook refers to it")
    bad = [c for c in colors if not HEX.match(c)]
    if bad:
        raise ValueError(f"colours must be #rrggbb, got: {bad}")
    if kind != "regular" and len(colors) < 2:
        raise ValueError(f"{kind} needs at least the two end colours; Tableau fills the middle")
    body = "\n".join(f"      <color>{c}</color>" for c in colors)
    return (f'    <color-palette name="{name}" type="{kind}">\n{body}\n'
            f'    </color-palette>')


def existing(path: str = "") -> list:
    """Palette names already declared, so we never silently shadow one."""
    path = path or default_path()
    if not os.path.exists(path):
        return []
    try:
        root = safexml.from_file(path)
    except Exception:
        return []
    return [p.get("name") for p in root.iter("color-palette") if p.get("name")]


def install(name: str, colors: list, kind: str = "ordered-diverging",
            path: str = "", apply: bool = False) -> dict:
    """Return the snippet; write it only when `apply=True`."""
    path = path or default_path()
    text = snippet(name, colors, kind)
    already = existing(path)
    result = {"palette": name, "type": kind, "colors": len(colors),
              "file": path, "snippet": text, "written": False,
              "existing_palettes": already}
    if len(colors) > DIALOG_LIMIT:
        result["note"] = (f"{len(colors)} colours — Edit Colors shows only {DIALOG_LIMIT}; "
                          "the palette still works, the dialog just truncates the preview")
    if name in already:
        result["refused"] = f"a palette named {name!r} is already declared — rename or edit it by hand"
        return result
    if not apply:
        result["next_step"] = "paste the snippet inside <preferences>, or call again with apply=True"
        return result

    if os.path.exists(path):
        backup = f"{path}.{time.strftime('%Y-%m-%dT%H-%M-%S')}.bak"
        shutil.copy2(path, backup)
        result["backup"] = backup
        raw = open(path, encoding="utf-8").read()
        if "</preferences>" not in raw:
            result["refused"] = "no </preferences> in the file — not guessing where to put it"
            return result
        raw = raw.replace("</preferences>", text + "\n  </preferences>", 1)
    else:
        raw = ("<?xml version='1.0'?>\n<workbook>\n  <preferences>\n"
               + text + "\n  </preferences>\n</workbook>\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(raw)
    result["written"] = True
    result["restart_needed"] = "Tableau reads Preferences.tps at startup — restart it to see the palette"
    return result

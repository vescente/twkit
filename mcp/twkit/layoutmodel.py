"""A model of the view without pixels: compute dashboard geometry straight from XML."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

CANVAS = 100_000

DEFAULT_SIZE = (1366, 768)

DEFAULT_FONT_PT = 9
DEFAULT_FAMILY = "Arial"

_FONT_DIRS = ("/System/Library/Fonts/Supplemental", "/System/Library/Fonts",
              "/Library/Fonts", os.path.expanduser("~/Library/Fonts"))


@lru_cache(maxsize=64)
def _font_file(family: str, bold: bool = False) -> str:
    """Font file for a family name."""
    want = [f"{family} Bold.ttf", f"{family}.ttf"] if bold else [f"{family}.ttf"]
    want += ["Arial Bold.ttf" if bold else "Arial.ttf", "Arial.ttf", "Helvetica.ttc"]
    for name in want:
        for d in _FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return ""


@lru_cache(maxsize=4096)
def text_width(text: str, pt: float = DEFAULT_FONT_PT, family: str = DEFAULT_FAMILY,
               bold: bool = False) -> float:
    """Text width in pixels at a given size."""
    px = pt * 96.0 / 72.0
    try:
        from PIL import ImageFont
    except ImportError:
        return len(text) * px * 0.55
    path = _font_file(family, bold)
    if not path:
        return len(text) * px * 0.55
    try:
        f = ImageFont.truetype(path, max(1, int(round(px))))
        return float(f.getlength(text))
    except Exception:
        return len(text) * px * 0.55


@dataclass
class Zone:
    """A dashboard rectangle in pixels and what it holds."""
    kind: str
    name: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass
class DashboardModel:
    name: str
    width: int
    height: int
    sizing: str
    zones: list[Zone] = field(default_factory=list)

    LAYOUT = ("layout-basic", "layout-flow")

    def sheets(self) -> list[Zone]:
        """Zones holding sheets: the only ones that draw data."""
        return [z for z in self.zones
                if z.name and z.kind not in self.LAYOUT and z.kind != "filter"]

    def controls(self) -> list[Zone]:
        return [z for z in self.zones if z.kind in ("filter", "paramctrl")]


def dashboard_size(dash) -> tuple[int, int, str]:
    """Canvas size in pixels."""
    size = dash.find(".//size")
    if size is None:
        return DEFAULT_SIZE[0], DEFAULT_SIZE[1], "none"
    mode = size.get("sizing-mode") or ""

    def _int(*keys):
        for k in keys:
            v = size.get(k)
            if v and str(v).isdigit():
                return int(v)
        return 0

    w = _int("minwidth", "width", "maxwidth")
    h = _int("minheight", "height", "maxheight")
    return (w or DEFAULT_SIZE[0]), (h or DEFAULT_SIZE[1]), (mode or "fixed")


def build(dash, width: int = 0, height: int = 0) -> DashboardModel:
    """Build the dashboard model from its XML node."""
    w_px, h_px, mode = dashboard_size(dash)
    w_px, h_px = width or w_px, height or h_px

    root = dash.find("zones")
    src = root.iter("zone") if root is not None else dash.iter("zone")

    zones = []
    for z in src:
        try:
            x, y, zw, zh = (int(z.get(k, 0)) for k in ("x", "y", "w", "h"))
        except (TypeError, ValueError):
            continue
        kind = z.get("type-v2") or ("worksheet" if z.get("name") else "")
        zones.append(Zone(kind=kind, name=z.get("name") or "",
                          x=x / CANVAS * w_px, y=y / CANVAS * h_px,
                          w=zw / CANVAS * w_px, h=zh / CANVAS * h_px))
    return DashboardModel(dash.get("name") or "?", w_px, h_px, mode, zones)


_SHELF_FIELD = re.compile(r"\[([^\]]+)\]\s*$")


def sheet_font(ws) -> tuple[float, str, bool]:
    """Size, family and weight of a sheet's labels."""
    pt, family, bold = DEFAULT_FONT_PT, DEFAULT_FAMILY, False
    for f in ws.iter("format"):
        attr, val = f.get("attr"), f.get("value") or ""
        if attr == "font-size" and val.replace(".", "").isdigit():
            pt = float(val)
        elif attr == "font-family" and val:
            family = val
        elif attr == "font-weight" and val == "bold" and not f.get("data-class"):
            bold = True
    return pt, family, bold


def mark_class(ws) -> str:
    m = next(ws.iter("mark"), None)
    return (m.get("class") if m is not None else "") or "Automatic"


def shelf_fields(ws, shelf: str) -> list[str]:
    """Fields on the rows/cols shelf."""
    node = next((e for e in ws.iter(shelf)), None)
    if node is None or not (node.text or "").strip():
        return []
    return [p.strip() for p in re.split(r"\s*/\s*", node.text.strip()) if p.strip()]


@lru_cache(maxsize=256)
def avg_char_width(pt: float = DEFAULT_FONT_PT, family: str = DEFAULT_FAMILY) -> float:
    """Average character width."""
    sample = "abcdefghijklmnopqrstuvwxyz0123456789 "
    return text_width(sample, pt, family) / len(sample)


def _width_in(rule, want: str) -> float:
    """Width for a field inside one <style-rule>."""
    for f in rule.iter("format"):
        if f.get("attr") == "width" and (f.get("field") or "").strip() == want:
            try:
                return float(f.get("value") or 0)
            except ValueError:
                return 0.0
    return 0.0


def declared_width(ws, field_ref: str, element: str = "") -> float:
    """Column width set explicitly in the workbook: <format attr='width' field='…' value='…'/>."""
    if not field_ref:
        return 0.0
    want = field_ref.strip().lstrip("(").rstrip(")").strip()
    scope = ws
    if element:
        rules = [r for r in ws.iter("style-rule") if r.get("element") == element]
        if not rules:
            return 0.0
        return max((_width_in(r, want) for r in rules), default=0.0)
    for f in scope.iter("format"):
        if f.get("attr") != "width":
            continue
        fld = (f.get("field") or "").strip()
        if fld and fld == want:
            try:
                return float(f.get("value") or 0)
            except ValueError:
                return 0.0
    return 0.0

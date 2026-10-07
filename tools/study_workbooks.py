"""Measure a folder of Tableau workbooks: forms, layout, analytics, formatting. Prints markdown.

    .venv/bin/python tools/study_workbooks.py <folder> --label "Corpus" [--json out.json]
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import zipfile
from collections import Counter, defaultdict

from lxml import etree

# ── reading ────────────────────────────────────────────────────────────────────
def read_book(path: str):
    if path.lower().endswith(".twbx"):
        with zipfile.ZipFile(path) as z:
            inner = [n for n in z.namelist() if n.lower().endswith(".twb")][0]
            raw = z.read(inner)
    else:
        with open(path, "rb") as f:
            raw = f.read()
    return etree.parse(io.BytesIO(raw)).getroot(), raw.decode("utf-8", "replace")


def collect(paths: list[str]) -> list[str]:
    files: list[str] = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "**", "*.twbx"), recursive=True))
            files += sorted(glob.glob(os.path.join(p, "**", "*.twb"), recursive=True))
        elif os.path.exists(p):
            files.append(p)
    return files


# ── measurements ─────────────────────────────────────────────────────────────────
LOD = re.compile(r"\{\s*(FIXED|INCLUDE|EXCLUDE)", re.I)
TABLECALC = re.compile(r"\b(WINDOW_\w+|RUNNING_\w+|LOOKUP|INDEX|RANK\w*|TOTAL|FIRST|LAST|PREVIOUS_VALUE)\s*\(", re.I)
SWITCH = re.compile(r"\[Parameters\]\.\[", re.I)


def study_one(path: str) -> dict:
    root, txt = read_book(path)
    d: dict = {"file": os.path.basename(path)}

    sheets = list(root.iter("worksheet"))
    dashes = list(root.iter("dashboard"))
    d["sheets"] = len(sheets)
    d["dashboards"] = len(dashes)
    d["stories"] = len(list(root.iter("story")))
    d["hidden_sheets"] = sum(1 for w in root.iter("window")
                             if w.get("class") == "worksheet" and w.get("hidden") == "true")

    marks = Counter()
    for p in root.iter("pane"):
        m = p.find("mark")
        if m is not None and m.get("class"):
            marks[m.get("class")] += 1
    d["marks"] = dict(marks.most_common())

    zones, depths, per_dash, sizing = Counter(), [], [], Counter()
    dash_bg = Counter()
    for dash in dashes:
        sizing[(dash.find("size").get("sizing-mode") if dash.find("size") is not None else "?")] += 1
        n = 0
        for z in dash.iter("zone"):
            t = z.get("type-v2") or z.get("type") or ("worksheet" if z.get("name") else "layout")
            if z.get("param") or t == "paramctrl":
                t = "paramctrl"
            zones[t] += 1
            n += 1
            depth, cur = 0, z
            while cur is not None and cur.tag == "zone":
                depth += 1
                cur = cur.getparent()
            depths.append(depth)
        per_dash.append(n)
        for st in dash.iter("format"):
            if st.get("attr") == "background-color" and st.get("value"):
                dash_bg[st.get("value")] += 1
    d["zones"] = dict(zones.most_common())
    d["zones_per_dashboard"] = round(sum(per_dash) / len(per_dash), 1) if per_dash else 0
    d["max_nesting"] = max(depths) if depths else 0
    d["sizing"] = dict(sizing)
    d["dashboard_bg"] = dict(dash_bg.most_common(5))

    d["actions"] = dict(Counter(a.get("class") or a.tag for a in root.iter("action")).most_common())
    d["param_count"] = sum(1 for c in root.iter("column") if c.get("param-domain-type"))

    formulas = [c.get("formula") or "" for c in root.iter("calculation") if c.get("formula")]
    d["calcs"] = len(formulas)
    d["lod"] = sum(1 for f in formulas if LOD.search(f))
    d["table_calcs"] = sum(1 for f in formulas if TABLECALC.search(f))
    d["param_driven"] = sum(1 for f in formulas if SWITCH.search(f))
    d["ref_lines"] = len(list(root.iter("reference-line"))) + len(list(root.iter("refline")))
    d["bands"] = len(list(root.iter("reference-band")))
    d["annotations"] = len(list(root.iter("annotation")))
    d["sets"] = len(list(root.iter("group")))
    d["top_n_filters"] = len(re.findall(r"function=['\"]top['\"]|<top\b", txt))
    d["filters"] = txt.count("<filter ")

    d["formats"] = dict(Counter(
        c.get("default-format") for c in root.iter("column") if c.get("default-format")
    ).most_common(12))
    fonts = Counter()
    for f in root.iter("format"):
        if f.get("attr") in ("font-size", "font-family", "font-weight") and f.get("value"):
            fonts[f"{f.get('attr')}={f.get('value')}"] += 1
    d["fonts"] = dict(fonts.most_common(10))
    colors = Counter()
    for e in root.iter():
        for attr in ("color", "value"):
            v = e.get(attr)
            if v and re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                colors[v.lower()] += 1
    d["colors"] = dict(colors.most_common(12))
    d["custom_palettes"] = len([m for m in root.iter("map") if m.get("to-element")])
    d["tooltips"] = sum(1 for t in root.iter("tooltip") if (t.text or "").strip()
                        or len(t))
    d["title_customized"] = sum(1 for t in root.iter("layout-options")
                                if t.find("title") is not None)
    d["device_layouts"] = len(list(root.iter("device-layout")))
    return d


# ── summary ──────────────────────────────────────────────────────────────────────
def summarize(rows: list[dict], label: str) -> str:
    n = len(rows)
    if not n:
        return f"## {label}\n\nno workbooks found\n"

    def total(key):
        return sum(r.get(key, 0) for r in rows)

    def merge(key):
        c = Counter()
        for r in rows:
            c.update(r.get(key, {}))
        return c

    out = [f"## {label}", "",
           f"Workbooks: **{n}**, sheets: **{total('sheets')}**, dashboards: **{total('dashboards')}**, "
           f"calculations: **{total('calcs')}**, parameters: **{total('param_count')}**.", ""]

    out += ["### Forms (mark type)", ""]
    marks = merge("marks")
    tot = sum(marks.values()) or 1
    for k, v in marks.most_common(12):
        out.append(f"- `{k}` — {v} ({v * 100 // tot}%)")
    out.append("")

    out += ["### Dashboard composition", "",
            f"- average zones per dashboard: **{round(sum(r['zones_per_dashboard'] for r in rows) / n, 1)}**",
            f"- max container nesting: **{max(r['max_nesting'] for r in rows)}**", ""]
    for k, v in merge("zones").most_common(12):
        out.append(f"- zone `{k}`: {v}")
    out.append("")
    out.append("Sizing mode: " + ", ".join(f"`{k}` {v}" for k, v in merge("sizing").most_common()))
    out.append("")

    out += ["### Analytics", "",
            f"- LOD expressions: **{total('lod')}** ({total('lod') * 100 // max(total('calcs'), 1)}% of calculations)",
            f"- table calculations: **{total('table_calcs')}**",
            f"- parameter-driven formulas: **{total('param_driven')}**",
            f"- reference lines: **{total('ref_lines')}**, bands: **{total('bands')}**, "
            f"annotations: **{total('annotations')}**",
            f"- filters: **{total('filters')}**, of them top-N: **{total('top_n_filters')}**",
            f"- actions: " + (", ".join(f"`{k}` {v}" for k, v in merge("actions").most_common(6))
                                         or "none"), ""]

    out += ["### Formatting", ""]
    out.append("Number formats (top):")
    for k, v in merge("formats").most_common(12):
        out.append(f"- `{k}`: {v}")
    out.append("")
    out.append("Fonts: " + (", ".join(f"`{k}` {v}" for k, v in merge("fonts").most_common(8)) or "default"))
    out.append("")
    out.append("Colors (top hex):")
    for k, v in merge("colors").most_common(15):
        out.append(f"- `{k}`: {v}")
    out.append("")
    out.append(f"Custom palettes: **{total('custom_palettes')}**, "
               f"custom tooltips: **{total('tooltips')}**, "
               f"custom titles: **{total('title_customized')}**, "
               f"device-layout: **{total('device_layouts')}**")
    out.append("")

    out += ["### Per workbook", "",
            "| workbook | sheets | dashboards | zones/dash | LOD | tablecalc | ref lines | parameters |",
            "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: -x["sheets"]):
        out.append(f"| {r['file']} | {r['sheets']} | {r['dashboards']} | {r['zones_per_dashboard']} | "
                   f"{r['lod']} | {r['table_calcs']} | {r['ref_lines']} | {r['param_count']} |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", help="folders or .twbx/.twb files")
    ap.add_argument("--label", default="Corpus")
    ap.add_argument("--json", default="", help="where to write raw measurements")
    args = ap.parse_args()

    files = collect(args.paths)
    rows, broken = [], []
    for f in files:
        try:
            rows.append(study_one(f))
        except Exception as exc:
            broken.append(f"{os.path.basename(f)}: {type(exc).__name__}: {exc}")
    print(summarize(rows, args.label))
    if broken:
        print("### Failed to parse\n")
        for b in broken:
            print(f"- {b}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

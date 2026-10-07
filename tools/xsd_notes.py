"""What the Tableau XSD allows versus what Tableau actually writes, versus what we write.

    .venv/bin/python tools/xsd_notes.py > docs/FORMAT_NOTES.md
"""
from __future__ import annotations

import glob
import io
import os
import sys
import zipfile
from collections import Counter, defaultdict

from lxml import etree

XS = "{http://www.w3.org/2001/XMLSchema}"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCHEMA_DIR = os.path.join(ROOT, "vendor", "tableau-document-schemas", "schemas")
sys.path.insert(0, os.path.join(ROOT, "mcp"))
from twkit import config  # noqa: E402

CORPUS = config.path("corpus")

VERIFIED = {
    ("filter", "kind"): "only on hide filters (`kind='hide'`, 17 of 574): appears when the "
                        "user hides individual values by hand. Not needed by the generator.",
}

WATCH = ["workbook", "datasource", "connection", "relation", "column", "calculation",
         "members", "member", "range", "aliases", "worksheet", "view", "pane", "mark",
         "encodings", "rows", "cols", "filter", "groupfilter", "slices", "style-rule",
         "format", "dashboard", "size", "zone", "zones", "reference-line", "action",
         "layout-options", "window", "parameters"]


# ── XSD ───────────────────────────────────────────────────────────────────────
def load_schema() -> tuple[etree._Element, str]:
    files = sorted(glob.glob(os.path.join(SCHEMA_DIR, "*", "twb_*.xsd")))
    if not files:
        raise SystemExit(f"no XSD found in {SCHEMA_DIR}")
    latest = files[-1]
    return etree.parse(latest).getroot(), os.path.basename(latest)


def simple_types(root) -> dict[str, list[str]]:
    """Enumerations: type name -> allowed values."""
    out: dict[str, list[str]] = {}
    for st in root.iter(XS + "simpleType"):
        name = st.get("name")
        if not name:
            continue
        vals = [e.get("value") for e in st.iter(XS + "enumeration") if e.get("value")]
        if vals:
            out[name] = vals
    return out


def element_specs(root) -> dict[str, dict]:
    """Required and optional XSD attributes per element name."""
    specs: dict[str, dict] = defaultdict(lambda: {"required": set(), "optional": set()})
    named_types: dict[str, etree._Element] = {
        ct.get("name"): ct for ct in root.iter(XS + "complexType") if ct.get("name")
    }
    for el in root.iter(XS + "element"):
        name = el.get("name")
        if not name:
            continue
        ct = el.find(XS + "complexType")
        if ct is None and el.get("type") in named_types:
            ct = named_types[el.get("type")]
        if ct is None:
            continue
        for a in ct.iter(XS + "attribute"):
            an = a.get("name")
            if not an:
                continue
            key = "required" if a.get("use") == "required" else "optional"
            specs[name][key].add(an)
            if a.get("type"):
                specs[name].setdefault("types", {})[an] = a.get("type")
    return specs


# ── corpus ────────────────────────────────────────────────────────────────────
def corpus_usage(paths: list[str]) -> tuple[dict[str, Counter], dict[tuple[str, str], Counter]]:
    """Attribute frequency per element, overall and per parent element."""
    usage: dict[str, Counter] = defaultdict(Counter)
    by_parent: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for p in paths:
        try:
            with zipfile.ZipFile(p) as z:
                inner = [n for n in z.namelist() if n.lower().endswith(".twb")][0]
                root = etree.parse(io.BytesIO(z.read(inner))).getroot()
        except Exception:
            continue
        for el in root.iter():
            tag = etree.QName(el).localname if isinstance(el.tag, str) else None
            if tag not in WATCH:
                continue
            parent = el.getparent()
            ptag = etree.QName(parent).localname if parent is not None else "—"
            usage[tag]["<element>"] += 1
            by_parent[(ptag, tag)]["<element>"] += 1
            for a in el.attrib:
                an = etree.QName(a).localname if a.startswith("{") else a
                usage[tag][an] += 1
                by_parent[(ptag, tag)][an] += 1
    return usage, by_parent


def ours_usage() -> dict[str, Counter]:
    """What our code writes, measured on a workbook built from blocks."""
    import sys
    os.environ.setdefault("TWKIT_SCHEMA_OFFLINE", "1")
    for p in (os.path.join(ROOT, "mcp"), os.path.abspath(os.path.join(ROOT, "..", ".."))):
        if p not in sys.path:
            sys.path.insert(0, p)
    import tempfile

    from twkit import blocks as B
    from twkit.book import Book
    from twkit import style as S
    from twkit.schema import apply_to_workbook, fetch_schema
    from twkit import config

    wb = Book()
    wb.set_mysql_connection(server=config.get("host"), dbname="reports",
                            username=config.get("user"),
                            table_name="partner_daily",
                            port=config.get("port") or "3306")
    apply_to_workbook(wb, fetch_schema("reports", "partner_daily"))
    S.date_range_params(wb, "2026-07-01", "2026-07-31")
    S.period_param(wb)
    B.period_filter(wb, "_filter_period", "event_date")
    metric = B.metric_switcher(wb, "Metric", {"NGR": "SUM([ngr])", "Deposits": "SUM([dep_sum])"})
    _, delta = B.delta_vs_prior(wb, "NGR Δ", "ngr", "event_date")
    kpis = B.kpi_tile(wb, "NGR", "SUM([ngr])", delta_field=delta)
    B.trend(wb, "Trend", "event_date", metric)
    B.top_n_bar(wb, "Top", "traffic_source", "ngr", top=10)
    B.heatmap(wb, "Heatmap", "traffic_source", "event_date", "ngr")
    S.apply_sizing(wb)
    wb.add_dashboard("Overview", width=1600, height=1000,
                     worksheet_names=kpis + ["Trend", "Top", "Heatmap"])
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "probe.twbx")
        wb.save(out)
        return corpus_usage([out])


# ── report ─────────────────────────────────────────────────────────────────────
def main() -> None:
    root, schema_name = load_schema()
    specs = element_specs(root)
    enums = simple_types(root)
    corpus_files = sorted(glob.glob(os.path.join(CORPUS, "*.twbx")))
    corpus, corpus_by_parent = corpus_usage(corpus_files)
    try:
        ours, ours_by_parent = ours_usage()
        ours_note = ""
    except Exception as exc:
        ours, ours_by_parent = {}, {}
        ours_note = f"our workbook failed to build: {type(exc).__name__}: {exc}"

    print("# Tableau format: specification versus practice\n")
    print("Generated by `tools/xsd_notes.py`. Regenerate after changing the builders "
          "or the schemas.\n")
    print(f"- XSD: `{schema_name}` (`vendor/tableau-document-schemas/`)")
    print(f"- corpus: {len(corpus_files)} workbooks")
    print("- \"we\": a workbook built from `twkit/blocks.py` blocks\n")
    if ours_note:
        print(ours_note + "\n")

    print("## Required attributes: do we write them\n")
    print("A missing required attribute is not forgiven: Tableau refuses the file or "
          "silently drops the setting.\n")
    print("| element | required by XSD | Tableau writes | we write |")
    print("|---|---|---|---|")
    gaps, false_alarms = [], []
    for tag in WATCH:
        spec = specs.get(tag)
        if not spec or not spec["required"]:
            continue
        req = sorted(spec["required"])
        c_has = [a for a in req if corpus.get(tag, Counter()).get(a)]
        o_has = [a for a in req if ours.get(tag, Counter()).get(a)]
        seen_by_us = ours.get(tag, Counter()).get("<element>", 0)
        ours_cell = ", ".join(o_has) if o_has else ("—" if seen_by_us else "_element not written_")
        print(f"| `{tag}` | {', '.join(req)} | {', '.join(c_has) or '—'} | {ours_cell} |")
        if not seen_by_us:
            continue
        our_parents = {pt for (pt, t) in ours_by_parent if t == tag}
        for a in req:
            if a in o_has:
                continue
            same_ctx = [(pt, cnt[a], cnt["<element>"])
                        for (pt, t), cnt in corpus_by_parent.items()
                        if t == tag and pt in our_parents and cnt[a]]
            if same_ctx:
                gaps.append((tag, a, same_ctx))
            else:
                other_ctx = sorted({pt for (pt, t), cnt in corpus_by_parent.items()
                                    if t == tag and cnt[a]})
                false_alarms.append((tag, a, other_ctx))

    print("\n## Gaps: Tableau writes the attribute in our context and we do not\n")
    if gaps:
        print("Required by the XSD, present in real workbooks in the SAME context, "
              "missing in ours: check these first.\n")
        for tag, a, ctx in gaps:
            where = "; ".join(f"in `<{pt}>` {n} of {tot}" for pt, n, tot in ctx)
            verdict = VERIFIED.get((tag, a))
            print(f"- `<{tag} {a}>` — {where}"
                  + (f"\n  · **resolved:** {verdict}" if verdict else ""))
    else:
        print("None: everything required is present in our contexts.")

    print("\n## XSD false alarms\n")
    if false_alarms:
        print("Marked required, but Tableau itself does not write it in OUR context: "
              "either the schema is wider than reality or the attribute belongs to a "
              "same-named element under another parent.\n")
        for tag, a, other in false_alarms:
            where = (f" (only inside {', '.join('`' + o + '`' for o in other)})"
                     if other else "")
            print(f"- `<{tag} {a}>`{where}")
    else:
        print("None.")

    print("\n## Allowed values (XSD enumerations)\n")
    print("Useful where a builder accepts any string: Tableau ignores a value outside "
          "the list without an error.\n")
    interesting = {"class", "sizing-mode", "param-domain-type", "role", "type", "datatype",
                   "direction", "scope", "function", "end"}
    shown = 0
    for tag in WATCH:
        spec = specs.get(tag) or {}
        for attr, type_name in sorted((spec.get("types") or {}).items()):
            if attr not in interesting or type_name not in enums:
                continue
            vals = enums[type_name]
            used = Counter()
            print(f"**`<{tag} {attr}>`** ({len(vals)} values): "
                  f"{', '.join('`' + v + '`' for v in vals[:14])}"
                  f"{' …' if len(vals) > 14 else ''}")
            shown += 1
            if shown > 24:
                break
        if shown > 24:
            break

    print("\n## What Tableau writes and we do not\n")
    print("Not everything needs copying, but part of this list explains visual "
          "differences.\n")
    print("| element | attributes we lack | corpus frequency |")
    print("|---|---|---|")
    for tag in WATCH:
        c, o = corpus.get(tag), ours.get(tag)
        if not c or not o:
            continue
        missing = [(a, n) for a, n in c.most_common() if a != "<element>" and not o.get(a)]
        if not missing:
            continue
        top = missing[:6]
        print(f"| `{tag}` | {', '.join('`' + a + '`' for a, _ in top)}"
              f"{f' (+{len(missing) - len(top)})' if len(missing) > len(top) else ''} "
              f"| {', '.join(str(n) for _, n in top)} |")


if __name__ == "__main__":
    main()

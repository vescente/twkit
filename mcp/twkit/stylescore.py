"""Style as a number: how closely a built workbook resembles the reference ones."""
from __future__ import annotations

import re
from dataclasses import dataclass

PROFILES = {
    "house": {
        "params_per_book": 7, "params_driven_share": 0.18,
        "zones_per_dashboard": 43, "automatic_share": 0.29,
        "reflines_per_dashboard": 0.0, "empty_zones_per_dashboard": 0.0,
        "text_zones_per_dashboard": 0.0,
    },
    "vendor": {
        "params_per_book": 1, "params_driven_share": 0.14,
        "zones_per_dashboard": 24, "automatic_share": 0.41,
        "reflines_per_dashboard": 0.67, "empty_zones_per_dashboard": 0.0,
        "text_zones_per_dashboard": 0.33,
    },
    "public": {
        "params_per_book": 4, "params_driven_share": 0.20,
        "zones_per_dashboard": 53, "automatic_share": 0.17,
        "reflines_per_dashboard": 0.0, "empty_zones_per_dashboard": 5.0,
        "text_zones_per_dashboard": 8.0,
    },
}

OUTLIER = {
    "params_per_book":     (2, None),
    "automatic_share":     (None, 0.71),
    "zones_per_dashboard": (None, 87),
}


TARGET = {
    "params_per_book":           (4, None,   "parameters are the core of self-service; house median 7, p10 = 3"),
    "automatic_share":           (None, 0.0, "choose the form for the task; STRICTER than all corpora: house 29%, vendor 41%"),
    "reflines_per_dashboard":    (0.5, None, "a number needs a baseline; a TARGET, not a norm (median 0 in every corpus)"),
    "empty_zones_per_dashboard": (1, None,   "white space is part of layout; house median 0, Public 5"),
    "zones_per_dashboard":       (None, 40,  "house density (43) is excessive; vendor keeps 24"),
    "text_zones_per_dashboard":  (1, None,   "a block without a title is not understood; house median 0, Public 8"),
}


@dataclass
class Metric:
    name: str
    value: float
    lo: float | None
    hi: float | None
    why: str

    @property
    def ok(self) -> bool:
        if self.lo is not None and self.value < self.lo:
            return False
        if self.hi is not None and self.value > self.hi:
            return False
        return True

    @property
    def verdict(self) -> str:
        """Three states instead of two."""
        if self.ok:
            return "ok"
        lo, hi = OUTLIER.get(self.name, (None, None))
        if lo is not None and self.value < lo:
            return "worse than almost all workbooks"
        if hi is not None and self.value > hi:
            return "worse than almost all workbooks"
        return "stricter than target"

    def as_dict(self) -> dict:
        return {"metric": self.name, "value": round(self.value, 3),
                "min": self.lo, "max": self.hi, "ok": self.ok,
                "verdict": self.verdict, "references": {
                    n: prof[self.name] for n, prof in PROFILES.items()
                    if self.name in prof},
                "why": self.why}


def measure(path: str) -> dict[str, float]:
    """Measure the workbook on the same metrics the corpus profiles use."""
    from .lint import load
    book = load(path)
    root, txt = book.root, book.text

    sheets = [w for holder in root.iter("worksheets") for w in holder.findall("worksheet")]
    dashboards = list(root.iter("dashboard"))
    nd = max(len(dashboards), 1)

    marks = [m.get("class") for w in sheets for m in w.iter("mark")]
    auto = sum(1 for m in marks if m == "Automatic")

    params = [c for c in root.iter("column") if c.get("param-domain-type")]
    param_names = {(c.get("name") or "") for c in params}
    formulas = [(c.find("calculation").get("formula") or "")
                for c in root.iter("column")
                if c.find("calculation") is not None and c.find("calculation").get("formula")]
    driven = sum(1 for f in formulas if "[Parameters]." in f)

    zones = [z for d in dashboards for z in d.iter("zone")]
    def _ztype(z):
        return z.get("type-v2") or z.get("type") or ("worksheet" if z.get("name") else "")

    return {
        "params_per_book": float(len(param_names)),
        "params_driven_share": (driven / len(formulas)) if formulas else 0.0,
        "zones_per_dashboard": len(zones) / nd,
        "automatic_share": (auto / len(marks)) if marks else 0.0,
        "reflines_per_dashboard": len(list(root.iter("reference-line"))) / nd,
        "empty_zones_per_dashboard": sum(1 for z in zones if _ztype(z) == "empty") / nd,
        "text_zones_per_dashboard": sum(1 for z in zones if _ztype(z) == "text") / nd,
        "delta_arrows": float(txt.count("↑") + txt.count("▲")),
        "sheets": float(len(sheets)),
        "dashboards": float(len(dashboards)),
    }


def score(path: str) -> tuple[int, list[Metric], dict[str, float]]:
    """Return (score 0-100, metrics with verdicts, all measurements)."""
    vals = measure(path)
    metrics = [Metric(k, vals.get(k, 0.0), lo, hi, why)
               for k, (lo, hi, why) in TARGET.items()]
    good = sum(1 for m in metrics if m.ok)
    return round(100 * good / len(metrics)), metrics, vals


def score_vs_corpus(path: str) -> dict:
    """Score against REAL workbooks, not an ideal."""
    total, metrics, vals = score(path)
    bad = [m for m in metrics if m.verdict == "worse than almost all workbooks"]
    strict = [m for m in metrics if m.verdict == "stricter than target"]
    return {
        "against_target": f"{total}/100",
        "corpus_reference": "house 33, Public 50, vendor 41 (medians)",
        "worse than almost all workbooks": [{"metric": m.name, "value": round(m.value, 3),
                                "references": {n: p[m.name] for n, p in PROFILES.items()
                                            if m.name in p},
                                "why_it_matters": m.why} for m in bad],
        "stricter than target (not a defect)": [m.name for m in strict],
        "verdict": ("style is fine: no metric is worse than real workbooks"
                    if not bad else
                    f"worse on {len(bad)}: "
                    + ", ".join(m.name for m in bad)),
    }


def closest_profile(vals: dict[str, float]) -> tuple[str, dict[str, float]]:
    """Which reference corpus the workbook resembles most, and by how much."""
    keys = [k for k in PROFILES["house"] if k in vals]
    spans = {}
    for k in keys:
        seen = [prof[k] for prof in PROFILES.values() if k in prof]
        spans[k] = max(max(seen) - min(seen), 1e-9)

    dist = {}
    for name, prof in PROFILES.items():
        d = sum(abs(vals[k] - prof[k]) / spans[k] for k in keys if k in prof)
        dist[name] = round(d / max(1, len(keys)), 2)
    return min(dist, key=dist.get), dist


def format_report(path: str) -> str:
    pts, metrics, vals = score(path)
    profile, dist = closest_profile(vals)
    lines = [f"Style: {pts}/100 - closest profile '{profile}' "
             f"(distances: {', '.join(f'{k} {v}' for k, v in sorted(dist.items(), key=lambda x: x[1]))})"]
    lines.append(f"{'metric':28s}{'book':>8s}{'normal':>9s}   {'house':>6s}{'vendor':>8s}{'public':>8s}")
    for m in sorted(metrics, key=lambda x: x.ok):
        mark = "✓" if m.ok else "⚠"
        bound = (f"≥{m.lo}" if m.lo is not None and m.hi is None else
                 f"≤{m.hi}" if m.hi is not None and m.lo is None else
                 f"{m.lo}…{m.hi}")
        ref = [PROFILES[p].get(m.name) for p in ("house", "vendor", "public")]
        cells = "".join(f"{('—' if r is None else format(r, '.2f')):>8s}" for r in ref)
        lines.append(f"{mark} {m.name:26s}{m.value:8.2f}{bound:>9s} {cells}")
        if not m.ok:
            lines.append(f"      {m.why}")
    lines.append(f"  - sheets {int(vals['sheets'])}, dashboards {int(vals['dashboards'])}, "
                 f"arrow deltas {int(vals['delta_arrows'])}")
    lines.append("  The score is about TASTE, not errors: the linter, canon and dry run catch errors.")
    lines.append("  Reference on the same scale: house 33, Public 50, vendor 41 (medians).")
    worse = [m.name for m in metrics if m.verdict == "worse than almost all workbooks"]
    lines.append("  Worse than almost all real workbooks: " + ", ".join(worse) if worse
                 else "  No metric is worse than real workbooks.")
    return "\n".join(lines)

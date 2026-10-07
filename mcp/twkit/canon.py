"""Metric definitions as executable checks on workbook formulas and SQL.

Domain rules come from the canon file (`config.path("canon")`):
  {"checks": {"<caption>": {"canon", "required", "required_all", "advised", "forbidden", "why"}},
   "final_schemas": ["<schema>", ...]}
Built in: shares must be computed from sums, never as an average of ratios.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass


@dataclass
class MetricRule:
    canon: str
    required: tuple[str, ...] = ()
    required_all: tuple[str, ...] = ()
    advised: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    why: str = ""


def _canon_file() -> dict:
    from . import config
    path = config.path("canon")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rules() -> dict[str, MetricRule]:
    """Metric rules keyed by normalized caption."""
    out = {}
    for key, r in (_canon_file().get("checks") or {}).items():
        out[_norm(key)] = MetricRule(
            canon=r.get("canon", ""), required=tuple(r.get("required", ())),
            required_all=tuple(r.get("required_all", ())), advised=tuple(r.get("advised", ())),
            forbidden=tuple(r.get("forbidden", ())), why=r.get("why", ""))
    return out


def final_schemas() -> list[str]:
    """Schemas whose tables must be read with FINAL (ClickHouse ReplacingMergeTree)."""
    return list(_canon_file().get("final_schemas") or [])


_RATIO_OF_RATIOS = re.compile(r"\b(SUM|AVG)\s*\(\s*(\[[^\]]+\]|\w+)\s*/", re.I)


@dataclass
class Finding:
    metric: str
    severity: str
    message: str = ""
    formula: str = ""
    canon: str = ""

    def as_dict(self) -> dict:
        return {"metric": self.metric, "severity": self.severity,
                "message": self.message, "canon": self.canon,
                "formula": self.formula[:200]}


def _norm(caption: str) -> str:
    return re.sub(r"[^a-z0-9\u0400-\u04ff ]+", "", (caption or "").lower()).strip()


def check_formulas(pairs: list[tuple[str, str]]) -> list[Finding]:
    """Check (caption, formula) pairs against the canon."""
    out: list[Finding] = []
    canon = rules()
    for caption, formula in pairs:
        if not formula:
            continue
        rule = canon.get(_norm(caption))

        m = _RATIO_OF_RATIOS.search(formula)
        if m:
            out.append(Finding(
                metric=caption, severity="error",
                message=f"share computed as {m.group(1).upper()}(a/b): an average of ratios",
                canon="compute shares from sums: SUM([a]) / NULLIF(SUM([b]), 0)",
                formula=formula))

        if rule is None:
            continue

        low = formula.lower()
        if rule.required and not any(t.lower() in low for t in rule.required):
            out.append(Finding(
                metric=caption, severity="warn",
                message=f"the formula references none of the expected fields "
                        f"({', '.join(rule.required)})",
                canon=rule.canon, formula=formula))
        for term in rule.required_all:
            if term.lower() not in low:
                out.append(Finding(
                    metric=caption, severity="error",
                    message=f"required '{term}' is missing: {rule.why}",
                    canon=rule.canon, formula=formula))
        for term in rule.advised:
            if term.lower() not in low:
                out.append(Finding(
                    metric=caption, severity="warn",
                    message=f"no '{term}': {rule.why}",
                    canon=rule.canon, formula=formula))
        for bad in rule.forbidden:
            if bad.lower() in low:
                out.append(Finding(
                    metric=caption, severity="error",
                    message=f"'{bad}' is wrong for this metric: {rule.why}",
                    canon=rule.canon, formula=formula))
    return out


def check_sql(sql: str) -> list[Finding]:
    """Tables of `final_schemas` must be read with FINAL, or ReplacingMergeTree returns duplicates."""
    out = []
    sql = sql or ""
    for schema in final_schemas():
        s = re.escape(schema)
        ok = re.compile(rf"\b{s}\.(\w+)(?:\s+(?:AS\s+)?(?!FINAL\b)\w+)?\s+FINAL\b", re.I)
        ok_spans = {m.start() for m in ok.finditer(sql)}
        for m in re.finditer(rf"\b{s}\.(\w+)", sql, re.I):
            if m.start() in ok_spans:
                continue
            out.append(Finding(
                metric=f"{schema}.{m.group(1)}", severity="error",
                message=f"{schema}.* read without FINAL: ReplacingMergeTree returns duplicates",
                canon=f"FROM {schema}.<table> FINAL", formula=m.group(0)))
    return out


def expand_refs(formula: str, by_name: dict, depth: int = 0) -> str:
    """Inline the formulas of referenced calculations."""
    if depth > 8:
        return formula
    out = formula
    for ref in set(re.findall(r"\[([^\]]+)\]", formula)):
        inner = by_name.get(ref)
        if inner and inner != formula:
            out = out.replace(f"[{ref}]",
                              "(" + expand_refs(inner, by_name, depth + 1) + ")")
    return out


def check_workbook(path: str) -> list[Finding]:
    """Check every calculation of a .twb/.twbx against the canon."""
    from .lint import load
    book = load(path)
    by_name, raw = {}, []
    for c in book.root.iter("column"):
        calc = c.find("calculation")
        if calc is None:
            continue
        name = (c.get("name") or "").strip("[]")
        formula = calc.get("formula") or ""
        if name:
            by_name[name] = formula
        raw.append((c.get("caption") or name, formula))
    return check_formulas([(cap, expand_refs(f, by_name)) for cap, f in raw])


def format_report(findings: list[Finding]) -> str:
    if not findings:
        return "canon respected: no discrepancies"
    errors = sum(1 for f in findings if f.severity == "error")
    lines = [f"discrepancies with the canon: {len(findings)} (errors {errors})"]
    for f in findings:
        lines.append(f"[{f.severity.upper():5s}] {f.metric}: {f.message}")
        if f.canon:
            lines.append(f"         canon: {f.canon}")
        if f.formula:
            lines.append("         formula: " + re.sub(r"\s+", " ", f.formula)[:140])
    return "\n".join(lines)

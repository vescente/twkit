"""A declarative dashboard spec: YAML or dict in, workbook out."""
from __future__ import annotations

import os
from typing import Any

from . import blocks as B
from . import style as S


class SpecError(ValueError):
    """Spec error."""


BLOCK_TYPES = {
    "trend":    (("sheet",), "line over time, granularity by parameter"),
    "top":      (("sheet", "dimension"), "horizontal top-N bar"),
    "heatmap":  (("sheet", "dimension"), "dimension x period density as squares"),
    "table":    (("sheet", "measures"), "text table dimension x measures"),
    "map":      (("sheet", "geo"), "map by a geo field (needs a semantic role); "
                                    "states/cities also need `country` or a country column"),
    "margin":   (("sheet", "actual", "target"), "GOOD/OKAY/BAD thresholds, measure split by status"),
}

FORMATS = {"eur": "eur", "eur_k": "eur_k", "eur_m": "eur_m", "int": "int",
           "dec1": "dec1", "pct1": "pct1", "pct0": "pct0",
           "eur_fin": "eur_fin", "eur_fin_k": "eur_fin_k", "eur_fin_b": "eur_fin_b"}


def load_spec(path_or_dict: str | dict) -> dict:
    """Read a spec from a YAML file, or take a dict as is."""
    if isinstance(path_or_dict, dict):
        return path_or_dict
    if not os.path.exists(path_or_dict):
        raise SpecError(f"spec file not found: {path_or_dict}")
    try:
        import yaml
    except ImportError as exc:                       # pragma: no cover
        raise SpecError("PyYAML is required: .venv/bin/pip install pyyaml") from exc
    with open(path_or_dict, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate(spec: dict) -> list[str]:
    """Validate a spec before building."""
    problems: list[str] = []
    src = spec.get("source") or {}
    sql = src.get("sql")
    if sql and src.get("table"):
        problems.append("source: both 'table' and 'sql' are set; choose one")
    elif sql:
        if not str(sql).strip():
            problems.append("source.sql is empty")
        elif str(sql).strip().endswith(".sql") and not os.path.exists(os.path.expanduser(str(sql))):
            problems.append(f"source.sql: file not found: {sql}")
    elif not src.get("table"):
        problems.append("source: needs 'table' ('schema.table') or 'sql' (a query or a path to .sql)")
    elif "." not in str(src["table"]):
        problems.append(f"source.table = {src['table']!r}; expected 'schema.table'")

    period = src.get("period")
    if period and (not isinstance(period, (list, tuple)) or len(period) != 2):
        problems.append("source.period must be a list of two dates [from, to]")

    params = spec.get("parameters") or {}
    metrics = params.get("metrics") or {}
    if metrics and not isinstance(metrics, dict):
        problems.append("parameters.metrics must be a dict {label: Tableau expression}")

    for i, k in enumerate(spec.get("kpi") or []):
        if not isinstance(k, dict) or "title" not in k or "expr" not in k:
            problems.append(f"kpi[{i}]: title and expr are required")
            continue
        fmt = k.get("format")
        if fmt and fmt not in FORMATS:
            problems.append(f"kpi[{i}].format = {fmt!r}; available: {', '.join(FORMATS)}")

    seen_sheets: set[str] = set()
    for i, b in enumerate(spec.get("blocks") or []):
        if not isinstance(b, dict) or "type" not in b:
            problems.append(f"blocks[{i}]: no 'type' key")
            continue
        t = b["type"]
        if t not in BLOCK_TYPES:
            problems.append(f"blocks[{i}].type = {t!r}; available: {', '.join(BLOCK_TYPES)}")
            continue
        need, _ = BLOCK_TYPES[t]
        for key in need:
            if not b.get(key):
                problems.append(f"blocks[{i}] ({t}): required '{key}' is missing")
        name = b.get("sheet")
        if name in seen_sheets:
            problems.append(f"blocks[{i}]: sheet '{name}' is already used; names must be unique")
        seen_sheets.add(name)

    story = spec.get("story")
    if story is not None:
        if not isinstance(story, dict):
            problems.append("story must be a dict with name/title/steps")
        else:
            steps = story.get("steps") or []
            if not steps:
                problems.append("story.steps is empty; a story needs at least one step")
            known_sheets = {b.get("sheet") for b in (spec.get("blocks") or [])}
            for j, st in enumerate(steps):
                if not isinstance(st, dict) or not st.get("sheet") or not st.get("caption"):
                    problems.append(f"story.steps[{j}]: 'sheet' and 'caption' are required")
                elif st["sheet"] not in known_sheets:
                    problems.append(f"story.steps[{j}]: sheet '{st['sheet']}' is not among the blocks")

    if not spec.get("kpi") and not spec.get("blocks"):
        problems.append("the spec has neither kpi nor blocks; nothing to build")
    return problems


def build(spec: str | dict, out_path: str = "", *, db_override: str = "") -> str:
    """Build a workbook from a spec and return its path."""
    from .book import Book
    from .schema import apply_to_workbook, fetch_schema

    spec = load_spec(spec)
    problems = validate(spec)
    if problems:
        raise SpecError("invalid spec:\n  - " + "\n  - ".join(problems))

    src = spec["source"]
    sql_src = src.get("sql")
    if sql_src:
        sql_src = str(sql_src)
        if sql_src.strip().endswith(".sql"):
            with open(os.path.expanduser(sql_src.strip()), encoding="utf-8") as f:
                sql_src = f.read()
        db, table = "", "Extract"
    else:
        db, table = str(src["table"]).split(".", 1)
        if db_override:
            db = db_override
    period = src.get("period") or ["2026-01-01", "2026-12-31"]

    wb = Book()

    extract = src.get("extract")
    if extract:
        extract = os.path.abspath(os.path.expanduser(str(extract)))
    if sql_src:
        if not extract:
            raise SpecError("source.sql requires 'extract': give a .hyper path; it is built from the query")
        if not os.path.exists(extract):
            from .extract import build_hyper_from_sql
            build_hyper_from_sql(sql_src, extract, table=table)
        wb.set_hyper_connection(extract)
    elif extract:
        if not os.path.exists(extract):
            raise SpecError(f"extract not found: {extract}")
        wb.set_hyper_connection(extract)
    else:
        from . import config
        wb.set_mysql_connection(server=config.get("host"), dbname=db,
                                username=config.get("user"), table_name=table,
                                port=config.get("port", "3306"))
    if extract:
        from .extract import schema_from_hyper
        fields = schema_from_hyper(extract)
    else:
        fields = fetch_schema(db, table)
    apply_to_workbook(wb, fields)
    known = {f["name"] for f in fields}
    B.auto_folders(wb, fields)

    S.date_range_params(wb, str(period[0]), str(period[1]))
    S.period_param(wb)
    B.period_filter(wb, "_filter_period", src.get("date", "event_date"))

    params = spec.get("parameters") or {}
    metric_field = ""
    if params.get("metrics"):
        metric_field = B.metric_switcher(wb, "Metric", dict(params["metrics"]))
    dim_field = ""
    if params.get("dimensions"):
        dims = [d for d in params["dimensions"] if d in known]
        skipped = [d for d in params["dimensions"] if d not in known]
        if skipped:
            print(f"  ! dimensions not in the table were skipped: {', '.join(skipped)}")
        if dims:
            dim_field = B.dim_switcher(wb, "Dimension", dims)

    kpi_sheets: list[str] = []
    date_field = src.get("date", "event_date")
    for k in spec.get("kpi") or []:
        delta = ""
        if k.get("delta_by"):
            _, delta = B.delta_vs_prior(wb, f"{k['title']} Δ", k["delta_by"], date_field)
        kpi_sheets += B.kpi_tile(wb, k["title"], k["expr"], delta_field=delta,
                                 fmt=S.FMT.get(FORMATS.get(k.get("format", "eur_k"), "eur_k")))

    sheets: list[str] = []
    for b in spec.get("blocks") or []:
        t, name = b["type"], b["sheet"]
        measure = b.get("measure") or metric_field or "count"
        if t == "trend":
            B.trend(wb, name, date_field, measure, color=b.get("color") or dim_field)
        elif t == "top":
            B.top_n_bar(wb, name, b["dimension"], measure, top=int(b.get("top", 10)))
        elif t == "heatmap":
            period_field = f"{name} - period"
            wb.add_calculated_field(period_field, S.period_trunc(date_field),
                                    datatype="date", role="dimension", field_type="ordinal")
            B.heatmap(wb, name, b["dimension"], period_field, measure)
        elif t == "table":
            wb.add_worksheet(name)
            wb.configure_chart(name, mark_type="Text", rows=[b.get("dimension") or dim_field],
                               measure_values=list(b["measures"]))
            S.style_sheet(wb, name, bands=True)
        elif t == "map":
            B.geo_map(wb, name, b["geo"], measure, country=b.get("country", ""))
        elif t == "margin":
            ratio = B.ratio_to_target(wb, f"{name} - share", b["actual"], b["target"])
            status = B.threshold_status(wb, f"{name} - status", ratio,
                                        good=float(b.get("good", 0.30)),
                                        okay=float(b.get("okay", 0.20)))
            parts = B.split_by_status(wb, name, f"SUM([{b['actual']}])", status)
            wb.add_worksheet(name)
            wb.configure_chart(name, mark_type="Bar", rows=[b.get("dimension") or dim_field],
                               measure_values=parts)
            S.style_sheet(wb, name)
        sheets.append(name)

    controls = [S.PARAM_DATE_FROM, S.PARAM_DATE_TO, S.PARAM_PERIOD]
    if metric_field:
        controls.append(S.PARAM_METRIC)
    if dim_field:
        controls.append("p_dim1")

    content: list[dict] = [B.title_zone()]
    if kpi_sheets:
        content.append({"type": "container", "direction": "horizontal", "fixed_size": 150,
                        "children": [{"type": "worksheet", "name": n} for n in kpi_sheets]})
        content.append({"type": "empty", "fixed_size": 12})
    for name in sheets:
        content.append({"type": "text", "text": name, "fixed_size": 24,
                        "font_size": S.FONT_SIZES["label"], "bold": True})
        content.append({"type": "worksheet", "name": name, "weight": 2, "show_title": False})
        content.append({"type": "empty", "fixed_size": 10})

    layout = {"type": "container", "direction": "horizontal",
              "children": [S.control_panel(controls, width=250),
                           {"type": "container", "direction": "vertical", "weight": 5,
                            "children": content}]}
    S.apply_sizing(wb)
    wb.add_dashboard(spec.get("name", "Dashboard"), width=1600, height=1000,
                     layout=layout, worksheet_names=kpi_sheets + sheets)

    if spec.get("story"):
        from . import story as ST
        st = spec["story"]
        ST.add_story(wb, st.get("name", "Story"), st.get("steps", []),
                     title=st.get("title", ""))

    import re as _re
    bad_refs = []
    for col in wb.root.iter("column"):
        calc = col.find("calculation")
        if calc is None or not calc.get("formula"):
            continue
        for ref in _re.findall(r"\[([^\]]+)\]", calc.get("formula")):
            if ref in known or ref.startswith(("Parameters", "Calculation")):
                continue
            if ref in {c.get("caption") for c in wb.root.iter("column")}:
                continue
            if any(c.get("name") == f"[{ref}]" for c in wb.root.iter("column")):
                continue
            bad_refs.append((col.get("caption") or col.get("name"), ref))
    if bad_refs:
        details = "; ".join(f"'{c}' -> [{r}]" for c, r in bad_refs[:6])
        raise SpecError(
            f"formulas reference fields missing from the source: {details}. "
            f"Check the names: the workbook builds but Tableau will not open it")

    B.calc_folders(wb)

    from . import order as ORD
    fixed = ORD.normalize_workbook(wb.root if hasattr(wb, "root") else wb._root)
    if fixed:
        print(f"  - element order normalized to the schema: datasource {fixed}")

    out = out_path or S.out_path(spec.get("name", "Dashboard"))
    wb.save(out)
    return out


def describe() -> dict:
    """What a spec may contain."""
    return {
        "source": {"table": "schema.table (or sql)",
                   "sql": "a custom query or a path to .sql; excludes 'table' and requires 'extract', "
                          "which is built from the query",
                   "period": ["from", "to"],
                   "date": "date column, event_date by default",
                   "extract": "path to a .hyper: data goes INSIDE the workbook. Without it the workbook "
                              "needs a live connection and neither the dry run nor a screenshot can check it"},
        "parameters": {"metrics": "{label: Tableau expression}",
                       "dimensions": "[column, ...]; columns missing from the table are skipped"},
        "kpi": [{"title": "label", "expr": "expression", "format": list(FORMATS),
                 "delta_by": "column for the delta against the prior period"}],
        "blocks": {t: {"required": list(need), "what": why}
                   for t, (need, why) in BLOCK_TYPES.items()},
        "name": "dashboard title and file name",
        "story": {"name": "tab name", "title": "story title",
                  "steps": [{"sheet": "a sheet name from blocks", "caption": "the step's CONCLUSION, "
                             "not the chart name: a story is read through its captions"}]},
        "note": "a spec does not replace the checks: run lint_workbook and dry_run_workbook "
                "after building",
    }

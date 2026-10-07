"""A library of dashboard constructions that are known to work."""
from __future__ import annotations

from . import style as S


STATUS_GOOD, STATUS_OKAY, STATUS_BAD = "GOOD", "OKAY", "BAD"
STATUS_COLORS = {STATUS_GOOD: "#59a14f", STATUS_OKAY: "#edc948", STATUS_BAD: "#e15759"}


def ratio_to_target(editor, name: str, fact: str, target: str) -> str:
    """Share of target: SUM(actual) / SUM(target)."""
    editor.add_calculated_field(name, f"SUM([{fact}]) / SUM([{target}])",
                                datatype="real", default_format=S.FMT["pct1"])
    return name


def threshold_status(editor, name: str, ratio_field: str,
                     good: float = 1.0, okay: float = 0.95) -> str:
    """GOOD/OKAY/BAD status by explicit thresholds."""
    editor.add_calculated_field(
        name,
        f"IF [{ratio_field}] >= {good} THEN '{STATUS_GOOD}'\n"
        f"ELSEIF [{ratio_field}] >= {okay} THEN '{STATUS_OKAY}'\n"
        f"ELSE '{STATUS_BAD}'\nEND",
        datatype="string", role="dimension", field_type="nominal")
    return name


def split_by_status(editor, base_name: str, expression: str, status_field: str,
                    fmt: str = "") -> list[str]:
    """Split a measure into three by status instead of coloring by value."""
    out = []
    for status in (STATUS_GOOD, STATUS_OKAY, STATUS_BAD):
        field = f"{base_name} — {status.lower()}"
        editor.add_calculated_field(
            field,
            f"IF [{status_field}] = '{status}' THEN {expression} ELSE NULL END",
            datatype="real", default_format=fmt or S.FMT["dec1"])
        out.append(field)
    return out


def shared_axis_max(editor, name: str, measure: str, dims: list[str],
                    padding: float = 1.1) -> str:
    """One maximum across panes: {FIXED : MAX({FIXED dims: SUM(measure)})} * padding."""
    inner = ", ".join(f"[{d}]" for d in dims)
    editor.add_calculated_field(
        name,
        "{ FIXED : MAX( { FIXED " + inner + f": SUM([{measure}]) " + "} ) } * " + str(padding),
        datatype="real")
    return name


def add_shared_axis_line(editor, worksheet: str, axis_field: str, max_field: str) -> None:
    """Reference line that aligns pane scales to the shared maximum."""
    editor.add_reference_line(worksheet, axis_field=axis_field, value_field=max_field,
                              scope="per-pane", formula="max", label_type="none", tooltip="")


def delta_vs_prior(editor, name: str, measure: str, date_field: str,
                   param_from: str = S.PARAM_DATE_FROM,
                   param_to: str = S.PARAM_DATE_TO) -> tuple[str, str]:
    """Prior period plus a percent delta with ↑↓ arrows."""
    span = f"DATEDIFF('day', [Parameters].[{param_from}], [Parameters].[{param_to}]) + 1"
    prior = f"{name} - prior period"
    editor.add_calculated_field(
        prior,
        f"SUM(IF [{date_field}] >= DATEADD('day', -({span}), [Parameters].[{param_from}])\n"
        f"   AND [{date_field}] <  [Parameters].[{param_from}]\n"
        f"THEN [{measure}] ELSE NULL END)",
        datatype="real")
    current = (f"SUM(IF [{date_field}] >= [Parameters].[{param_from}]\n"
               f"   AND [{date_field}] <= [Parameters].[{param_to}]\n"
               f"THEN [{measure}] ELSE NULL END)")
    editor.add_calculated_field(
        name,
        f"({current} - [{prior}]) / ABS([{prior}])",
        datatype="real", default_format=S.FMT["delta_arrow"])
    return prior, name


def kpi_tile(editor, title: str, measure_expr: str, *, delta_field: str = "",
             fmt: str = "", compact: bool = True) -> list[str]:
    """KPI as TWO micro sheets: the number and the delta below it."""
    value_fmt = fmt or (S.FMT["eur_k"] if compact else S.FMT["eur"])
    field = f"KPI {title}"
    editor.add_calculated_field(field, measure_expr, datatype="real", default_format=value_fmt)

    sheets = [f"{title} — BAN"]
    editor.add_worksheet(sheets[0])
    editor.configure_chart(sheets[0], mark_type="Text", label=field)
    S.style_sheet(editor, sheets[0])

    if delta_field:
        name = f"{title} — Δ"
        editor.add_worksheet(name)
        editor.configure_chart(name, mark_type="Text", label=delta_field)
        S.style_sheet(editor, name)
        sheets.append(name)
    return sheets


def trend(editor, sheet: str, date_field: str, measure: str, *,
          color: str = "", mark: str = "Line", baseline: bool = True) -> str:
    """Line over time; granularity controlled by the p_period_granuality parameter."""
    trunc = f"{sheet} - period"
    editor.add_calculated_field(trunc, S.period_trunc(date_field),
                                datatype="date", role="dimension", field_type="ordinal")
    editor.add_worksheet(sheet)
    editor.configure_chart(sheet, mark_type=mark, columns=[trunc], rows=[measure],
                           color=color or None)
    if baseline:
        try:
            editor.add_reference_line(sheet, axis_field=measure, value_field=measure,
                                      scope="per-table", formula="average",
                                      label_type="value", tooltip="Average = <Value>")
        except Exception as exc:
            print(f"  ! reference line on '{sheet}' not added: {type(exc).__name__}")
    S.style_sheet(editor, sheet)
    return trunc


def top_n_bar(editor, sheet: str, dim: str, measure: str, *, top: int = 10,
              label: bool = True) -> None:
    """Horizontal top-N bar, one tone, direct labels."""
    editor.add_worksheet(sheet)
    editor.configure_chart(
        sheet, mark_type="Bar", columns=[measure], rows=[dim],
        label=measure if label else None,
        sort_descending=dim,
        filters=[{"column": dim, "top": top, "by": measure, "direction": "DESC"}],
    )
    S.style_sheet(editor, sheet)


def heatmap(editor, sheet: str, row_dim: str, col_field: str, measure: str) -> None:
    """Density: period x segment."""
    editor.add_worksheet(sheet)
    editor.configure_chart(sheet, mark_type="Square", columns=[col_field],
                           rows=[row_dim], color=measure, label=measure)
    S.style_sheet(editor, sheet)


def metric_switcher(editor, name: str, mapping: dict[str, str],
                    param: str = S.PARAM_METRIC, fmt: str = "") -> str:
    """One view for N metrics: IF [Parameters].[p_metric] = 'X' THEN ... END."""
    editor.add_parameter(param, datatype="string", domain_type="list",
                         default_value=list(mapping)[0], allowed_values=list(mapping))
    editor.add_calculated_field(name, S.switcher(param, mapping), datatype="real",
                                default_format=fmt or S.FMT["dec1"])
    return name


def dim_switcher(editor, name: str, dims: list[str], idx: int = 1) -> str:
    """Dimension switcher: p_dimN -> the matching dimension; empty = no breakdown."""
    param = S.dim_param(editor, idx, dims)
    editor.add_calculated_field(
        name, S.switcher(param, {d: f"[{d}]" for d in dims}, default="''"),
        datatype="string", role="dimension", field_type="nominal")
    return name


def period_filter(editor, name: str, date_field: str) -> str:
    """Boolean period filter."""
    editor.add_calculated_field(name, S.date_filter(date_field), datatype="boolean",
                                role="dimension", field_type="nominal")
    return name


CATALOG = {
    "ratio_to_target": "share of target, computed from sums",
    "threshold_status": "GOOD/OKAY/BAD status by explicit thresholds",
    "split_by_status": "split a measure into three by status instead of coloring by value",
    "shared_axis_max": "shared maximum for small multiples ({FIXED : MAX(...)} * 1.1)",
    "add_shared_axis_line": "reference line aligning pane scales",
    "delta_vs_prior": "prior period plus percent delta with ↑↓",
    "kpi_tile": "KPI as two micro sheets: number and delta",
    "trend": "line over time with switchable granularity",
    "top_n_bar": "horizontal top-N bar, one tone, direct labels",
    "heatmap": "period x segment density as squares",
    "metric_switcher": "one view for N metrics via a parameter",
    "dim_switcher": "dimension switcher p_dimN",
    "period_filter": "boolean period filter (role=dimension required)",
    "geo_map": "map by a geo field (needs a semantic role, set by schema.apply_geo_roles)",
    "title_zone": "the page title zone (Tableau draws its text)",
    "caption_zone": "a block caption inside a page: a text zone with its own text",
    "bins": "measure bins for a histogram",
    "field_folders": "sort fields into data pane folders",
    "auto_folders": "source fields into Fields/Date/Measures/System folders (10+ fields)",
    "calc_folders": "calculations -> Calcs, helpers starting with _ -> System; run LAST",
    "top_n_with_other": "top-N plus an Other bucket so totals still match (table calculation)",
    "cohort_table": "cohort table: cohort x AGE, metric as color",
}


def geo_map(editor, sheet: str, geo_field: str, measure: str, *,
            mark: str = "Automatic", country: str = "") -> None:
    """Map by a geographic field."""
    if mark not in ("Automatic", "Map"):
        raise ValueError(f"geo_map: mark {mark!r} is not a map; use Automatic or Map")
    editor.add_worksheet(sheet)
    try:
        editor.configure_chart(sheet, mark_type=mark, geographic_field=geo_field,
                               color=measure, label=measure, map_country=country or None)
    except ValueError:
        from . import edit as ED
        ED.remove_worksheet(editor.root, sheet)
        raise
    S.style_sheet(editor, sheet)


def title_zone(*, size: str = "") -> dict:
    """The page title zone."""
    return {"type": "title", "fixed_size": 44,
            "font_size": size or S.FONT_SIZES["title"], "bold": True}


def caption_zone(text: str, *, size: str = "", height: int = 26) -> dict:
    """A block caption inside a page: a text zone with its own content."""
    return {"type": "text", "text": text, "fixed_size": height,
            "font_size": size or S.FONT_SIZES["label"], "bold": True}


def bins(editor, name: str, measure: str, size: float) -> str:
    """Measure bins for histograms."""
    editor.add_calculated_field(name, f"FLOOR([{measure}] / {size}) * {size}",
                                datatype="real", role="dimension", field_type="ordinal")
    return name


_AFTER_FOLDERS = ("folders-parameters", "actions", "calculated-members", "extract",
                  "layout", "style", "semantic-values", "date-options",
                  "default-date-format", "default-sorts", "field-sort-info",
                  "datasource-dependencies", "explainability", "filter", "object-graph")

FOLDER_NAMES = {"dims": "Fields", "measures": "Measures",
                "calcs": "Calcs", "dates": "Date", "system": "System"}


def field_folders(editor, groups: dict[str, list[str]]) -> int:
    """Sort fields into data pane folders."""
    from lxml import etree

    ds = getattr(editor, "datasource", None)
    if ds is None:
        return 0
    have = {(c.get("name") or "").strip("[]") for c in ds.findall("column")}

    holder = ds.find("folders-common")
    if holder is None:
        holder = etree.Element("folders-common")
        anchor = next((el for tag in _AFTER_FOLDERS
                       if (el := ds.find(tag)) is not None), None)
        if anchor is not None:
            anchor.addprevious(holder)
        else:
            ds.append(holder)

    made = 0
    for folder_name, fields in groups.items():
        present = [f for f in fields if f in have]
        if not present:
            continue
        folder = next((el for el in holder.findall("folder")
                       if el.get("name") == folder_name), None)
        if folder is None:
            folder = etree.SubElement(holder, "folder")
            folder.set("name", folder_name)
            made += 1
        already = {(el.get("name") or "") for el in folder.findall("folder-item")}
        for f in present:
            if f"[{f}]" in already:
                continue
            item = etree.SubElement(folder, "folder-item")
            item.set("name", f"[{f}]")
            item.set("type", "field")
    return made


def auto_folders(editor, fields: list[dict], threshold: int = 10) -> int:
    """Sort source fields into Fields / Date / Measures / System."""
    if len(fields) < threshold:
        return 0
    system = {"updated_at", "_loaded", "_row_hash"}
    def is_date(f):
        return str(f.get("datatype", "")).startswith("date")
    groups = {
        FOLDER_NAMES["dims"]: [f["name"] for f in fields
                               if f["role"] == "dimension" and f["name"] not in system
                               and not is_date(f)],
        FOLDER_NAMES["dates"]: [f["name"] for f in fields
                                if is_date(f) and f["name"] not in system],
        FOLDER_NAMES["measures"]: [f["name"] for f in fields
                                   if f["role"] == "measure" and f["name"] not in system],
        FOLDER_NAMES["system"]: [f["name"] for f in fields if f["name"] in system],
    }
    return field_folders(editor, {k: v for k, v in groups.items() if v})


def calc_folders(editor) -> dict:
    """Calculated fields -> `Calcs`; helpers starting with `_` -> `System`."""
    ds = getattr(editor, "datasource", None)
    if ds is None:
        return {"calcs": 0, "system": 0}
    calcs, helpers = [], []
    for c in ds.findall("column"):
        if c.find("calculation") is None:
            continue
        name = (c.get("name") or "").strip("[]")
        if not name:
            continue
        (helpers if name.startswith("_") else calcs).append(name)
    groups = {}
    if calcs:
        groups[FOLDER_NAMES["calcs"]] = calcs
    if helpers:
        groups[FOLDER_NAMES["system"]] = helpers
    if not groups:
        return {"calcs": 0, "system": 0}
    field_folders(editor, groups)
    return {"calcs": len(calcs), "system": len(helpers)}


def top_n_with_other(editor, name: str, dim: str, measure: str, top: int = 10,
                     other_label: str = "Other") -> str:
    """A dimension where everything outside the top N folds into one Other row."""
    editor.add_calculated_field(
        name,
        f"IF RANK(SUM([{measure}])) <= {int(top)} THEN [{dim}] ELSE '{other_label}' END",
        datatype="string", role="dimension", field_type="nominal",
        table_calc="Table")
    return name


def cohort_table(editor, sheet: str, *, cohort_date: str, event_date: str,
                 measure: str, unit: str = "month", max_age: int = 12) -> dict:
    """Triangular cohort table: cohort x age, retention as color."""
    if unit not in ("day", "week", "month", "quarter", "year"):
        raise ValueError(f"unit={unit!r}: day/week/month/quarter/year")

    cohort_field = f"{sheet} - cohort"
    age_field = f"{sheet} - age"
    editor.add_calculated_field(cohort_field,
                                f"DATETRUNC('{unit}', [{cohort_date}])",
                                datatype="date", role="dimension", field_type="ordinal")
    editor.add_calculated_field(
        age_field,
        f"DATEDIFF('{unit}', DATETRUNC('{unit}', [{cohort_date}]), "
        f"DATETRUNC('{unit}', [{event_date}]))",
        datatype="integer", role="dimension", field_type="ordinal")

    editor.add_worksheet(sheet)
    editor.configure_chart(sheet, mark_type="Square", columns=[age_field],
                           rows=[cohort_field], color=measure, label=measure,
                           filters=[{"column": age_field, "type": "quantitative",
                                     "min": "0", "max": str(int(max_age))}])
    S.style_sheet(editor, sheet)
    return {"cohort": cohort_field, "age": age_field}

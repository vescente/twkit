import os

import pytest

from twkit import blocks as B
from twkit import style as S
from twkit.lint import ERROR, counts, lint

DB, TABLE = "reports", "partner_daily"


@pytest.fixture
def wb():
    from twkit.book import Book

    from twkit.schema import apply_to_workbook, fetch_schema
    from twkit import config
    e = Book()
    e.set_mysql_connection(server=config.get("host"), dbname=DB, username=config.get("user"),
                           table_name=TABLE, port=config.get("port"))
    apply_to_workbook(e, fetch_schema(DB, TABLE))
    S.date_range_params(e, "2026-07-01", "2026-07-31")
    S.period_param(e)
    return e


def _save_and_lint(wb, tmp_path, name="block.twbx"):
    out = str(tmp_path / name)
    wb.save(out)
    v = lint(out)
    assert counts(v)[ERROR] == 0, "\n".join(str(x) for x in v)
    return out


def _fields(wb) -> set[str]:
    return {(c.get("caption") or "") for c in wb.root.iter("column")}


def _sheets(wb) -> set[str]:
    return {w.get("name") for w in wb.root.iter("worksheet")}


def test_threshold_status(wb, tmp_path):
    B.ratio_to_target(wb, "% of plan", "ngr", "dep_sum")
    st = B.threshold_status(wb, "Status", "% of plan")
    assert st in _fields(wb)
    _save_and_lint(wb, tmp_path)


def test_split_by_status_makes_three_measures(wb, tmp_path):
    B.ratio_to_target(wb, "% of plan", "ngr", "dep_sum")
    B.threshold_status(wb, "Status", "% of plan")
    got = B.split_by_status(wb, "NGR", "SUM([ngr])", "Status")
    assert len(got) == 3
    assert set(got) <= _fields(wb)
    _save_and_lint(wb, tmp_path)


def test_shared_axis_max_is_lod(wb, tmp_path):
    name = B.shared_axis_max(wb, "Shared maximum", "ngr", ["traffic_source", "event_date"])
    formula = next(c.find("calculation").get("formula")
                   for c in wb.root.iter("column")
                   if c.get("caption") == name and c.find("calculation") is not None)
    assert "{ FIXED" in formula and "MAX" in formula, formula
    _save_and_lint(wb, tmp_path)


def test_delta_vs_prior_uses_arrow_format(wb, tmp_path):
    prior, delta = B.delta_vs_prior(wb, "NGR Δ", "ngr", "event_date")
    fmts = {c.get("caption"): c.get("default-format") for c in wb.root.iter("column")}
    assert fmts.get(delta) == S.FMT["delta_arrow"], fmts.get(delta)
    assert prior in _fields(wb)
    _save_and_lint(wb, tmp_path)


def test_period_filter_is_dimension(wb, tmp_path):
    name = B.period_filter(wb, "_filter_period", "event_date")
    col = next(c for c in wb.root.iter("column") if c.get("caption") == name)
    assert col.get("role") == "dimension" and col.get("type") == "nominal"
    _save_and_lint(wb, tmp_path)


def test_kpi_tile_makes_two_sheets(wb, tmp_path):
    _, delta = B.delta_vs_prior(wb, "NGR Δ", "ngr", "event_date")
    sheets = B.kpi_tile(wb, "NGR", "SUM([ngr])", delta_field=delta)
    assert len(sheets) == 2
    assert set(sheets) <= _sheets(wb)
    _save_and_lint(wb, tmp_path)


def test_kpi_tile_uses_compact_money_format(wb):
    B.kpi_tile(wb, "NGR", "SUM([ngr])")
    fmts = {c.get("caption"): c.get("default-format") for c in wb.root.iter("column")}
    assert fmts.get("KPI NGR") == S.FMT["eur_k"]


def test_trend(wb, tmp_path):
    B.trend(wb, "Trend", "event_date", "ngr")
    assert "Trend" in _sheets(wb)
    _save_and_lint(wb, tmp_path)


def test_top_n_bar_writes_top_filter(wb, tmp_path):
    B.top_n_bar(wb, "Top sources", "traffic_source", "ngr", top=10)
    out = _save_and_lint(wb, tmp_path)
    import zipfile
    with zipfile.ZipFile(out) as z:
        inner = [n for n in z.namelist() if n.endswith(".twb")][0]
        txt = z.read(inner).decode("utf-8")
    assert 'count="10"' in txt or "count='10'" in txt


def test_heatmap(wb, tmp_path):
    B.heatmap(wb, "Heatmap", "traffic_source", "event_date", "ngr")
    assert "Heatmap" in _sheets(wb)
    _save_and_lint(wb, tmp_path)


def test_metric_switcher(wb, tmp_path):
    name = B.metric_switcher(wb, "Metric", {"NGR": "SUM([ngr])", "Deposits": "SUM([dep_sum])"})
    param = next(c for c in wb.root.iter("column") if c.get("caption") == S.PARAM_METRIC)
    internal = (param.get("name") or "").strip("[]")
    formula = next(c.find("calculation").get("formula")
                   for c in wb.root.iter("column")
                   if c.get("caption") == name and c.find("calculation") is not None)
    assert f"[Parameters].[{internal}]" in formula, formula
    _save_and_lint(wb, tmp_path)


def test_dim_switcher_has_empty_option(wb, tmp_path):
    B.dim_switcher(wb, "Dimension", ["traffic_source", "traffic_geo"])
    param = next(c for c in wb.root.iter("column")
                 if c.get("caption") == "p_dim1")
    members = [m.get("value") for m in param.iter("member")]
    assert any(S.NO_DIM in (m or "") for m in members)
    _save_and_lint(wb, tmp_path)


def test_full_dashboard_from_blocks(wb, tmp_path):
    B.period_filter(wb, "_filter_period", "event_date")
    metric = B.metric_switcher(wb, "Metric", {"NGR": "SUM([ngr])", "Deposits": "SUM([dep_sum])"})
    _, delta = B.delta_vs_prior(wb, "NGR Δ", "ngr", "event_date")
    kpis = B.kpi_tile(wb, "NGR", "SUM([ngr])", delta_field=delta)
    B.trend(wb, "Trend", "event_date", metric)
    B.top_n_bar(wb, "Top sources", "traffic_source", "ngr", top=10)
    B.heatmap(wb, "Heatmap", "traffic_source", "event_date", "ngr")

    S.apply_sizing(wb)
    wb.add_dashboard("Overview", width=1600, height=1000,
                     worksheet_names=kpis + ["Trend", "Top sources", "Heatmap"])
    out = _save_and_lint(wb, tmp_path, "full.twbx")
    assert os.path.getsize(out) > 0


def test_catalog_covers_every_public_block():
    public = {n for n in dir(B)
              if not n.startswith("_") and callable(getattr(B, n))
              and getattr(B, n).__module__ == B.__name__}
    assert public == set(B.CATALOG)


def test_top_n_with_other_keeps_tail(wb, tmp_path):
    name = B.top_n_with_other(wb, "Dimension+other", "traffic_source", "ngr", top=5)
    formula = next(c.find("calculation").get("formula")
                   for c in wb.root.iter("column")
                   if c.get("caption") == name and c.find("calculation") is not None)
    assert "Other" in formula and "RANK" in formula, formula
    wb.add_worksheet("s")
    wb.configure_chart("s", mark_type="Bar", rows=[name], columns=["ngr"])
    _save_and_lint(wb, tmp_path, "other.twbx")


def test_top_n_with_other_is_skipped_by_dry_run():
    from twkit import dryrun
    tr = dryrun.Translator({}, {}, {}, {"traffic_source", "ngr"}, dialect="hyper")
    sql, why = tr.to_sql("IF RANK(SUM([ngr])) <= 5 THEN [traffic_source] ELSE 'Other' END")
    assert not sql and "table calculation" in why, (sql, why)


def test_cohort_table_uses_age_not_calendar(wb, tmp_path):
    fields = B.cohort_table(wb, "Cohorts", cohort_date="event_date",
                            event_date="event_date", measure="ngr", unit="month")
    formula = next(c.find("calculation").get("formula")
                   for c in wb.root.iter("column")
                   if c.get("caption") == fields["age"] and c.find("calculation") is not None)
    assert "DATEDIFF" in formula, formula
    assert "Cohorts" in {w.get("name") for h in wb.root.iter("worksheets")
                         for w in h.findall("worksheet")}
    _save_and_lint(wb, tmp_path, "cohort.twbx")


def test_cohort_table_rejects_bad_unit(wb):
    import pytest as _pt
    with _pt.raises(ValueError, match="day/week"):
        B.cohort_table(wb, "X", cohort_date="event_date", event_date="event_date",
                       measure="ngr", unit="decade")

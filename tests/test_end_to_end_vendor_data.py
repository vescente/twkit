"""End-to-end test on data that ships with Tableau Desktop (`World Indicators.hyper`).

extract → fields → blocks → dashboard → linter → canon → dry run against the `.hyper`.
"""
import glob
import os
import shutil
import tempfile

import pytest
from twkit.extract import HYPER_QUIET

TABLEAU_APP = "/Applications/Tableau Desktop (Apple silicon) 2026.1.app/Contents"
HYPERS = sorted(glob.glob(os.path.join(TABLEAU_APP, "install", "defaults",
                                       "Datasources", "*", "World Indicators.hyper")))
pytestmark = pytest.mark.skipif(not HYPERS, reason="Tableau Desktop is not installed")


@pytest.fixture(scope="module")
def vendor_hyper(tmp_path_factory) -> str:
    dst = str(tmp_path_factory.mktemp("vendor") / "world_indicators.hyper")
    shutil.copy(HYPERS[0], dst)
    return dst


def _fields_of(hyper_path: str) -> list[dict]:
    from tableauhyperapi import Connection, HyperProcess, TableName, Telemetry
    kind = {"text": "string", "big_int": "integer", "double": "real",
            "date": "date", "timestamp": "datetime", "bool": "boolean"}
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters=HYPER_QUIET) as hp:
        with Connection(endpoint=hp.endpoint, database=hyper_path) as conn:
            tdef = conn.catalog.get_table_definition(TableName("Extract", "Extract"))
            out = []
            for col in tdef.columns:
                t = kind.get(str(col.type).lower().split("(")[0], "string")
                out.append({"name": col.name.unescaped, "datatype": t,
                            "role": "measure" if t in ("integer", "real") else "dimension"})
            return out


@pytest.fixture(scope="module")
def built_book(vendor_hyper, tmp_path_factory) -> str:
    from twkit.book import Book

    from twkit import blocks as B
    from twkit import style as S
    from twkit.conn import register
    from twkit.schema import apply_geo_roles

    fields = _fields_of(vendor_hyper)
    wb = Book()
    wb.set_hyper_connection(vendor_hyper)
    register(wb, fields)
    apply_geo_roles(wb, fields)

    S.date_range_params(wb, "2000-01-01", "2012-12-31")
    S.period_param(wb)
    metric = B.metric_switcher(wb, "Indicator", {
        "GDP": "SUM([GDP])",
        "Population": "SUM([Population Total])",
    })
    B.top_n_bar(wb, "Top countries", "Country/Region", metric, top=10)
    B.heatmap(wb, "Region x year", "Region", "Year", metric)
    S.apply_sizing(wb)
    wb.add_dashboard("World", width=1600, height=1000,
                     worksheet_names=["Top countries", "Region x year"])
    out = str(tmp_path_factory.mktemp("built") / "World.twbx")
    wb.save(out)
    return out


def test_geo_role_assigned_from_vendor_schema(vendor_hyper):
    from twkit.schema import infer_geo_role
    names = {f["name"] for f in _fields_of(vendor_hyper)}
    assert "Country/Region" in names
    assert infer_geo_role("country", "string") == "[Country].[ISO3166_2]"
    assert infer_geo_role("latitude", "real") == "[Geographical].[Latitude]"
    assert infer_geo_role("country_group", "string") == ""


def test_book_passes_linter(built_book):
    from twkit.lint import ERROR, counts, lint
    v = lint(built_book)
    assert counts(v)[ERROR] == 0, "\n".join(str(x) for x in v if x.severity == ERROR)


def test_book_passes_canon(built_book):
    from twkit import canon
    errs = [f for f in canon.check_workbook(built_book) if f.severity == "error"]
    assert not errs, [f.message for f in errs]


def test_extract_is_packed(built_book):
    import zipfile
    with zipfile.ZipFile(built_book) as z:
        assert any(n.lower().endswith(".hyper") for n in z.namelist()), z.namelist()


def test_dry_run_returns_data(built_book):
    from twkit import dryrun
    res = dryrun.dry_run(built_book)
    ok = [r for r in res if r.status == "ok"]
    empty = [r.sheet for r in res if r.status == "empty"]
    errors = [(r.sheet, r.note) for r in res if r.status == "error"]
    assert not errors, errors
    assert not empty
    assert ok, dryrun.format_report(res)


def test_style_score_runs(built_book):
    from twkit import stylescore
    pts, metrics, vals = stylescore.score(built_book)
    assert 0 <= pts <= 100
    assert vals["sheets"] >= 2

import glob
import os
import re
import tempfile
import zipfile

import pytest

from twkit import dryrun
from _userdata import FIXTURES  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOOKS = [b for b in sorted(glob.glob(os.path.join(FIXTURES, "*.twbx")))
         if not b.endswith(".REF.twbx")]
WITH_EXTRACT = [p for p in BOOKS
                if any(n.lower().endswith(".hyper")
                       for n in zipfile.ZipFile(p).namelist())]


def _book_with(marker: str) -> str | None:
    for path in WITH_EXTRACT:
        with zipfile.ZipFile(path) as z:
            twb = [n for n in z.namelist() if n.endswith(".twb")][0]
            if marker in z.read(twb).decode("utf-8", "replace"):
                return path
    return None


def test_strip_comments():
    assert "SUM" in dryrun.Translator.strip_comments("SUM([x]) // a comment")
    assert "comment" not in dryrun.Translator.strip_comments("SUM([x]) // comment")
    assert "block" not in dryrun.Translator.strip_comments("SUM(/* block */[x])")


def test_fold_case_picks_selected_branch():
    sql = "CASE 'NGR' WHEN 'FTD' THEN SUM(a) WHEN 'NGR' THEN SUM(b) ELSE NULL END"
    assert dryrun.Translator.fold_case(sql).strip() == "(SUM(b))"


def test_fold_case_falls_back_to_else():
    sql = "CASE 'no such' WHEN 'FTD' THEN SUM(a) ELSE 0 END"
    assert dryrun.Translator.fold_case(sql).strip() == "(0)"


def test_fold_case_survives_nested_case():
    sql = ("CASE 'B' WHEN 'A' THEN CASE WHEN x > 0 THEN 1 ELSE 2 END "
           "WHEN 'B' THEN SUM(b) ELSE 0 END")
    out = dryrun.Translator.fold_case(sql)
    assert out.strip() == "(SUM(b))", out


def test_aggregate_detection_routes_switcher_to_measures():
    assert dryrun._is_aggregated("CASE 'x' WHEN 'x' THEN SUM(a) END")
    assert not dryrun._is_aggregated("CAST(partner_id AS TEXT)")


@pytest.mark.parametrize("dialect,needle", [("hyper", "DATE_TRUNC"),
                                            ("clickhouse", "toStartOfMonth")])
def test_dialect_date_trunc(dialect, needle):
    tr = dryrun.Translator({}, {}, {}, {"d"}, dialect=dialect)
    sql, why = tr.to_sql("DATETRUNC('month', [d])")
    assert not why and needle in sql, sql


def test_unsupported_is_skipped_not_guessed():
    tr = dryrun.Translator({}, {}, {}, set(), dialect="hyper")
    for formula in ("{ FIXED [a] : SUM([b]) }", "WINDOW_SUM(SUM([x]))"):
        sql, why = tr.to_sql(formula)
        assert not sql and why, formula


@pytest.mark.skipif(not WITH_EXTRACT, reason="no books with an extract")
@pytest.mark.parametrize("path", WITH_EXTRACT)
def test_delivered_books_have_data(path):
    res = dryrun.dry_run(path)
    empty = [r.sheet for r in res if r.status == "empty"]
    errors = [(r.sheet, r.note) for r in res if r.status == "error"]
    assert not empty
    assert not errors


@pytest.mark.skipif(not WITH_EXTRACT, reason="no books with an extract")
def test_dry_run_detects_empty_sheets():
    src = _book_with("<shared-views>")
    if not src:
        pytest.skip("no book where the period filters sheets")
    with zipfile.ZipFile(src) as z:
        twb = [n for n in z.namelist() if n.endswith(".twb")][0]
        hyp = [n for n in z.namelist() if n.endswith(".hyper")][0]
        txt, data = z.read(twb).decode("utf-8"), z.read(hyp)
    shifted = re.sub(r"#\d{4}-\d{2}-\d{2}#", "#2030-01-01#", txt)
    assert shifted != txt
    dst = os.path.join(tempfile.mkdtemp(), "empty.twbx")
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr(twb, shifted)
        z.writestr(hyp, data)
    res = dryrun.dry_run(dst)
    assert any(r.status == "empty" for r in res), dryrun.format_report(res)


@pytest.mark.skipif(not WITH_EXTRACT, reason="no books with an extract")
def test_shared_view_filters_are_applied():
    src = _book_with("<shared-views>")
    if not src:
        pytest.skip("no book with shared filters")
    res = dryrun.dry_run(src)
    with_where = [r for r in res if r.sql and "WHERE" in r.sql]
    assert with_where


def _book_on_custom_sql(tmp_path, server: str, sql: str = "SELECT 1 AS a") -> str:
    from lxml import etree

    xml = (
        "<?xml version='1.0' encoding='utf-8' ?>\n"
        "<workbook version='18.1'><datasources>"
        "<datasource caption='ds' inline='true' name='federated.x' version='18.1'>"
        "<connection class='federated'><named-connections>"
        f"<named-connection caption='ch' name='mysql.x'><connection class='mysql' "
        f"dbname='marts' port='3306' server='{server}' username='tableau' /></named-connection>"
        "</named-connections>"
        "<relation connection='mysql.x' name='Custom SQL Query' type='text'>SQLHERE</relation>"
        "</connection></datasource></datasources>"
        "<worksheets /><windows /></workbook>").replace("SQLHERE", sql)
    dst = str(tmp_path / "live.twbx")
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("book.twb", xml)
    etree.fromstring(xml.encode())
    return dst


def test_custom_sql_picked_up_from_our_host(tmp_path):
    from twkit import config

    from twkit.lint import load

    path = _book_on_custom_sql(tmp_path, config.get("host"))
    assert dryrun.custom_sql_of(load(path)) == "SELECT 1 AS a"


def test_foreign_server_not_sent_to_our_clickhouse(tmp_path):
    from twkit.lint import load

    path = _book_on_custom_sql(tmp_path, "10.0.0.1")
    assert dryrun.custom_sql_of(load(path)) == ""
    with pytest.raises(RuntimeError, match="db/table"):
        dryrun._pick_target(load(path), "", "")


def _multi_source_book(tmpdir) -> str:
    def ds(name, sql):
        return f"""
      <datasource name='{name}' caption='{name}'>
        <connection class='federated'>
          <named-connections>
            <named-connection name='mysql.{name}'>
              <connection class='mysql' server='{_HOST}' port='3306'/>
            </named-connection>
          </named-connections>
          <relation connection='mysql.{name}' name='Custom SQL Query' type='text'>{sql}</relation>
        </connection>
      </datasource>"""

    def ws(name, dsname, field):
        return f"""
      <worksheet name='{name}'><table><view>
        <datasources><datasource name='{dsname}'/></datasources>
      </view>
      <rows>[{dsname}].[none:{field}:nk]</rows></table></worksheet>"""

    xml = ("<workbook><datasources>"
           + ds("A", "SELECT 1 AS a") + ds("B", "SELECT 2 AS b") + ds("C", "SELECT 3 AS c")
           + "</datasources>" + ws("wA", "A", "a") + ws("wB", "B", "b")
           + ws("wC", "C", "c") + "</workbook>")
    path = os.path.join(tmpdir, "multi.twb")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path


try:
    from twkit import config as _c
    _HOST = _c.get("host")
except Exception:
    _HOST = "0.0.0.0"


def test_query_map_per_source_not_collapsed():
    if _HOST == "0.0.0.0":
        pytest.skip("ClickHouse host not configured (twkit.config)")
    from twkit import lint
    with tempfile.TemporaryDirectory() as td:
        book = lint.load(_multi_source_book(td))
        m = dryrun.custom_sql_map(book)
        assert m == {"A": "SELECT 1 AS a", "B": "SELECT 2 AS b", "C": "SELECT 3 AS c"}, m
        assert dryrun.custom_sql_of(book) == "SELECT 1 AS a"


def test_sheet_knows_its_source():
    if _HOST == "0.0.0.0":
        pytest.skip("ClickHouse connection not configured (twkit.config)")
    from twkit import lint
    with tempfile.TemporaryDirectory() as td:
        root = lint.load(_multi_source_book(td)).root
        got = {ws.get("name"): dryrun.sheet_datasource(ws) for ws in root.iter("worksheet")}
        assert got == {"wA": "A", "wB": "B", "wC": "C"}, got


def test_string_concat_translated_to_double_pipe():
    tr = dryrun.Translator({}, {}, {}, {"x"}, dialect="clickhouse")
    sql, why = tr.to_sql("'W ' + STR([x])")
    assert why == "", why
    assert "||" in sql and " + " not in sql, sql


def test_numeric_addition_not_concat():
    tr = dryrun.Translator({}, {}, {}, {"a", "b"}, dialect="clickhouse")
    sql, why = tr.to_sql("[a] + [b]")
    assert why == "" and "||" not in sql, sql


def test_measure_values_shelf_gives_skipped():
    from lxml import etree
    ws = etree.fromstring(
        "<worksheet name='w'><table><rows>[ds].[none:Multiple Values:nk]</rows>"
        "</table></worksheet>")
    tr = dryrun.Translator({}, {}, {}, {"x"}, dialect="clickhouse")
    r = dryrun._run_sheet(ws, tr, None, 5)
    assert r.status == "skipped", r
    assert "[Measure Values]" in (r.note or ""), r.note


def test_comparison_operators_unescaped():
    src = ("SELECT 1 WHERE a >>= 1 AND b <<= 2 AND c >> 3 AND d << 4")
    got = dryrun.unescape_sql(src)
    assert got == "SELECT 1 WHERE a >= 1 AND b <= 2 AND c > 3 AND d < 4", got
    for bad in (">>=", "<<=", ">>", "<<"):
        assert bad not in got


def test_normal_sql_untouched():
    src = "SELECT 1 WHERE a >= 1 AND b <= 2 AND c > 3 AND d < 4"
    assert dryrun.unescape_sql(src) == src


def test_custom_sql_read_normalizes_operators():
    if _HOST == "0.0.0.0":
        pytest.skip("ClickHouse connection not configured (twkit.config)")
    from twkit import lint
    xml = f"""<workbook><datasources>
      <datasource name='D' caption='D'><connection class='federated'>
        <named-connections><named-connection name='mysql.D'>
          <connection class='mysql' server='{_HOST}' port='3306'/>
        </named-connection></named-connections>
        <relation connection='mysql.D' name='Custom SQL Query' type='text'>SELECT 1 WHERE x &gt;&gt;= 5 AND y &lt;&lt;= 9</relation>
      </connection></datasource></datasources></workbook>"""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "esc.twb")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        book = lint.load(path)
        assert dryrun.custom_sql_of(book) == "SELECT 1 WHERE x >= 5 AND y <= 9"
        assert list(dryrun.custom_sql_map(book).values()) == ["SELECT 1 WHERE x >= 5 AND y <= 9"]


def test_top_filter_cuts_category_count():
    from twkit import safexml
    from twkit.dryrun import top_n_cap
    xml = b"""<workbook><datasources><datasource name='Parameters'>
      <column caption='Top N' name='[Parameter 1]' value='15' datatype='integer'/>
    </datasource></datasources><worksheets>
    <worksheet name='A'><table><view><filter class='categorical' column='[x].[none:a:nk]'>
      <groupfilter count='10' end='top' function='end'><groupfilter function='order'/></groupfilter>
    </filter></view></table></worksheet>
    <worksheet name='B'><table><view><filter class='categorical' column='[x].[none:a:nk]'>
      <groupfilter count='[Parameters].[Parameter 1]' end='top' function='end'/>
    </filter></view></table></worksheet>
    <worksheet name='C'><table><view/></table></worksheet>
    </worksheets></workbook>"""
    root = safexml.from_bytes(xml)
    assert top_n_cap(root, 'A') == 10
    assert top_n_cap(root, 'B') == 15
    assert top_n_cap(root, 'C') is None

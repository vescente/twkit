import os
import shutil
import subprocess
import sys
import zipfile
from html.parser import HTMLParser

import pytest
from lxml import etree

from twkit import chsafe, safexml, shot
from twkit import frame as F

sys.path.insert(0, os.path.dirname(__file__))
import _matrix_book  # noqa: E402

SHORT = "#'><u>x"
LONG = "Tableau'\"><u>pwn</u>"


@pytest.mark.parametrize("sql", [
    "SELECT * FROM numbers(1) /* /* */ ' */ , url('http://x', CSV, 'a String') --'",
    "SELECT * FROM numbers(1) -- x\r'\n, url('http://x', CSV, 'a String') --'",
])
def test_comments_that_dialects_end_differently_are_refused(sql):
    with pytest.raises(PermissionError):
        chsafe.read_only(sql)


def test_plain_comments_still_pass():
    assert chsafe.read_only("SELECT 1 /* note */ -- tail\r\n")
    assert chsafe.read_only("SELECT 1 -- tail")


@pytest.mark.skipif(not shutil.which("osascript"), reason="no AppleScript")
def test_applescript_literal_round_trips_a_hostile_title():
    title = 'Book" & (do shell script "echo pwn") & "\\'
    r = subprocess.run(["osascript", "-e", "return " + shot._lit(title)],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and r.stdout.rstrip("\n") == title


def test_dialog_title_reaches_applescript_as_a_literal(monkeypatch):
    title = 'Error in "x" & (do shell script "echo pwn") & ""'
    seen = []
    monkeypatch.setattr(shot, "list_dialogs", lambda: [title])
    monkeypatch.setattr(shot, "_osa", lambda script, timeout=25.0: seen.append(script))
    monkeypatch.setattr(shot.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr=""))
    shot.read_dialog()
    shot._press_default(title)
    assert len(seen) == 2 and all(shot._lit(title) in s for s in seen)


def test_cached_helper_writable_by_others_is_not_run(tmp_path):
    exe = tmp_path / "helper"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert shot._trusted(str(exe))
    exe.chmod(0o775)
    assert not shot._trusted(str(exe))


def test_workbook_colours_and_fonts_are_checked_before_css():
    assert F._hex("#4E79A7ff") == "#4E79A7" and F._hex(SHORT) is None
    assert F._font(LONG) == "Tableauupwnu"
    btn = etree.fromstring("<button><button-visual-state><caption>Go</caption>"
                           "<button-caption-font-style/></button-visual-state>"
                           "<format attr='background-color'/></button>")
    btn.find(".//button-caption-font-style").attrib.update({"fontcolor": SHORT, "fontname": LONG})
    btn.find("format").set("value", SHORT)
    assert "<u>" not in F._button_html(btn, {})


def _poison(root) -> int:
    n = 0
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        style = table.find("style")
        if style is None:
            style = etree.SubElement(table, "style")
        for element, attr, value in (("mark", "mark-color", SHORT), ("cell", "color", SHORT),
                                     ("cell", "font-family", LONG), ("table", "background-color", SHORT)):
            rule = etree.SubElement(style, "style-rule", element=element)
            etree.SubElement(rule, "format", attr=attr, value=value)
    for e in root.iter():
        for a, v in (("fontcolor", SHORT), ("fontname", LONG), ("to", SHORT)):
            if e.get(a) is not None:
                e.set(a, v)
                n += 1
        if e.tag == "format" and e.get("attr") in ("color", "mark-color", "background-color",
                                                    "border-color", "font-family"):
            e.set("value", LONG if e.get("attr") == "font-family" else SHORT)
            n += 1
        if e.tag == "color" and (e.text or "").startswith("#"):
            e.text = SHORT
            n += 1
    return n


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_hostile_workbook_strings_never_become_page_markup(tmp_path):
    src = _matrix_book.build(str(tmp_path))
    root = safexml.from_twbx(src)
    assert _poison(root) > 10
    bad = str(tmp_path / "hostile.twbx")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = safexml.serialize(root) if info.filename.endswith(".twb") else zin.read(info)
            zout.writestr(info.filename, data)
    out = F.publish(bad, out_dir=str(tmp_path / "frame"))
    assert out["pages"]
    for pg in out["pages"]:
        p = _Tags()
        p.feed(open(pg["file"], encoding="utf-8").read())
        names = [t for t, _ in p.tags]
        assert "u" not in names, f"workbook text became markup on {pg['page']}"
        assert names.count("script") == 1
        assert any(a.get("http-equiv") == "Content-Security-Policy" for t, a in p.tags if t == "meta")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM view(SELECT * FROM someNewFn('h'))",
    "SELECT * FROM (someNewFn('h'))",
    "SELECT * FROM numbers(1) WHERE ‘'’ = '' , url('http://x', CSV, 'a String') --'",
    "SELECT “x” FROM t",
    "SELECT * FROM viewIfPermitted(SELECT 1 ELSE null('a Int8'))",
    "SELECT * FROM t WHERE x IN someNewFn('h')",
])
def test_table_functions_hidden_from_the_guard_are_refused(sql):
    with pytest.raises(PermissionError):
        chsafe.read_only(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t WHERE d IN (toDate('2026-01-01'), toDate('2026-02-01'))",
    "SELECT * FROM view(SELECT number FROM numbers(3))",
    "SELECT * FROM t JOIN u ON (t.a = lower(u.b))",
    "SELECT 'Zürich' AS r, count() FROM t -- naïve note\n",
    "SELECT * FROM (SELECT 1) AS a, (SELECT 2) AS b",
])
def test_ordinary_reads_still_pass(sql):
    assert chsafe.read_only(sql) == sql


def test_a_keyword_before_a_bracket_is_never_a_table_function():
    assert chsafe._table_functions("SELECT * FROM a, b, FROM (SELECT 1)") == []


def _read(table_fn: str) -> list:
    """The server's tree of `SELECT * FROM <table_fn>(3)`, complete."""
    return ["SelectWithUnionQuery (children 2)", " ExpressionList (children 1)",
            "  SelectQuery (children 2)", "   ExpressionList (children 1)", "    Asterisk",
            "   TablesInSelectQuery (children 1)", "    TablesInSelectQueryElement (children 1)",
            "     TableExpression (children 1)", f"      Function {table_fn} (alias n) (children 1)",
            "       ExpressionList (children 1)", "        Literal UInt64_3",
            " Identifier TabSeparated"]


_VIEW = ["SelectWithUnionQuery (children 1)", " ExpressionList (children 1)",
         "  SelectQuery (children 2)", "   ExpressionList (children 1)", "    Asterisk",
         "   TablesInSelectQuery (children 1)", "    TablesInSelectQueryElement (children 1)",
         "     TableExpression (children 1)", "      Function view (children 1)",
         "       ExpressionList (children 1)", "        SelectWithUnionQuery (children 1)",
         "         ExpressionList (children 1)", "          SelectQuery (children 2)",
         "           ExpressionList (children 1)", "            Asterisk",
         "           TablesInSelectQuery (children 1)",
         "            TablesInSelectQueryElement (children 1)",
         "             TableExpression (children 1)",
         "              Function someNewFn (alias s) (children 1)",
         "               ExpressionList (children 1)", "                Literal UInt64_1"]

_DESCRIBE = ["DescribeQuery (children 2)", " TableExpression (children 1)", "  Subquery (children 1)",
             "   SelectWithUnionQuery (children 1)", "    ExpressionList (children 1)",
             "     SelectQuery (children 1)", "      ExpressionList (children 1)",
             "       Literal UInt64_1 (alias a)", " Identifier TabSeparated"]


def test_server_tree_with_a_table_function_off_the_list_is_refused():
    with pytest.raises(PermissionError, match="someNewFn"):
        chsafe.ast_read_only(_VIEW)


def test_server_tree_of_a_plain_read_passes():
    chsafe.ast_read_only(_read("numbers"))
    chsafe.ast_read_only(_DESCRIBE)


@pytest.mark.parametrize("lines", [
    ["InsertQuery"],
    ["SelectWithUnionQuery", "SelectWithUnionQuery"],
    ["SelectWithUnionQuery (children 1)", " Function file"],
    [],
    _read("numbers")[:-1],
    _read("numbers")[:5] + ["      Asterisk"],
    ['{"data": [["SelectWithUnionQuery"]]}'],
])
def test_server_tree_that_is_not_one_plain_read_is_refused(lines):
    with pytest.raises(PermissionError):
        chsafe.ast_read_only(lines)


class _Server:
    def __init__(self, tree=None, fail=False):
        self.tree, self.fail, self.ran = tree or [], fail, []

    def explain_ast(self, sql):
        if self.fail:
            raise RuntimeError("Syntax error")
        return self.tree

    def execute(self, sql):
        self.ran.append(sql)
        return [[1]]


def test_guarded_client_runs_nothing_the_server_tree_refuses():
    srv = _Server(_read("someNewFn"))
    with pytest.raises(PermissionError):
        chsafe.ReadOnlyClient(srv).execute("SELECT * FROM numbers(1)")
    assert srv.ran == []


def test_guarded_client_refuses_what_the_server_cannot_parse():
    srv = _Server(fail=True)
    with pytest.raises(PermissionError, match="could not parse"):
        chsafe.ReadOnlyClient(srv).execute("SELECT 1")
    assert srv.ran == []


def test_guarded_client_runs_a_plain_read():
    srv = _Server(_read("numbers"))
    assert chsafe.ReadOnlyClient(srv).execute("SELECT * FROM numbers(1)") == [[1]]
    assert srv.ran == ["SELECT * FROM (\nSELECT * FROM numbers(1)\n)"]


def test_guarded_client_checks_exactly_the_statement_it_runs():
    class Seen(_Server):
        def explain_ast(self, sql):
            self.explained = sql
            return _read("numbers")
    srv = Seen()
    chsafe.ReadOnlyClient(srv).execute("SELECT 1 -- tail")
    assert srv.ran == [srv.explained]
    chsafe.ReadOnlyClient(srv).execute("DESCRIBE (SELECT 1)")
    assert srv.ran[-1] == srv.explained == "DESCRIBE (SELECT 1)"


def test_a_query_never_chooses_the_output_format():
    with pytest.raises(PermissionError, match="FORMAT"):
        chsafe.read_only("SELECT 1 FORMAT JSONEachRow")
    assert chsafe.read_only("SELECT format('{}', 1)")


@pytest.mark.parametrize("sql", ["SELECT 1) UNION ALL (SELECT 2", "SELECT (1", "SELECT ')' AS a)"])
def test_unbalanced_brackets_are_refused(sql):
    with pytest.raises(PermissionError, match="unbalanced"):
        chsafe.read_only(sql)


def test_arithmetic_before_a_bracket_is_not_a_table_function():
    # Hyper SQL from a dry run: a quoted column plus a bracket is arithmetic, not a call
    sql = ('SELECT EXTRACT(DOW FROM (("Call Date" + (CAST(CURRENT_DATE AS DATE) - 1)))) '
           'FROM "Extract"."Extract"')
    assert chsafe.read_only(sql) == sql


def test_a_call_off_the_list_is_still_refused_after_an_operator():
    with pytest.raises(PermissionError, match="not on the allowed list"):
        chsafe.read_only("SELECT 1 + 2 FROM t, generateSeries2(1, 5)")


def test_a_bracket_after_from_inside_extract_is_a_scalar():
    sql = ('SELECT EXTRACT(YEAR FROM "OrderDate") - EXTRACT(YEAR FROM (CAST("Ship" AS DATE))) '
           '+ EXTRACT(YEAR FROM (DATE_TRUNC(\'year\', "Ship"))) FROM "Extract"."Extract"')
    assert chsafe.read_only(sql) == sql


def test_a_table_function_in_brackets_after_from_is_still_checked():
    with pytest.raises(PermissionError, match="not on the allowed list"):
        chsafe.read_only("SELECT * FROM (generateSeries2(1, 5))")


def test_read_only_queries_carry_server_limits_before_readonly():
    from twkit.chclient import HttpClickhouse
    c = HttpClickhouse("h", "8443", "u", "p", read_only=True)
    seen = []

    class _S:
        def post(self, url, **k):
            seen.append(url)
            return type("R", (), {"status_code": 200, "text": "1\n"})()

    c._session = _S()
    c._account_read_only = lambda: False
    c._request(b"SELECT 1")
    qs = seen[0].split("?", 1)[1]
    assert "max_memory_usage=3000000000" in qs and "max_execution_time=" in qs
    assert qs.index("max_memory_usage") < qs.index("readonly=1"), "a setting after readonly=1 is refused"

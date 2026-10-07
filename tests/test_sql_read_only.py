import os
import zipfile

import pytest

from twkit import chsafe, config, dryrun, extract
from test_chclient import _Resp, _client

ATTACKS = [
    "DROP TABLE marts.t",
    "SELECT 1; DROP TABLE marts.t",
    "INSERT INTO marts.t SELECT 1",
    "/* SELECT */ ALTER TABLE marts.t DELETE WHERE 1",
    "SELECT * FROM url('http://example/?d=' || (SELECT 1), CSV, 'a String')",
    "SELECT * FROM t INTO OUTFILE 'x.csv'",
    "SELECT 'a\\'; DROP TABLE x; SELECT '--'",
    "SELECT $$'$$; DROP TABLE x; SELECT $$'$$",
    "SELECT 1 --x\r; DROP TABLE t",
    "SELECT * FROM external('/etc/passwd')",
]


@pytest.mark.parametrize("sql", ATTACKS)
def test_untrusted_sql_is_refused(sql):
    with pytest.raises(PermissionError):
        chsafe.read_only(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1", "select a from t;", "WITH x AS (SELECT 1) SELECT * FROM x",
    "(SELECT 1) UNION ALL (SELECT 2)", "SELECT 'a;b' -- c;d\nFROM t",
    "SELECT match(x, '\\\\d+'), 'it''s' FROM t",
])
def test_ordinary_reads_pass(sql):
    assert chsafe.read_only(sql) == sql


def _book_with_sql(tmp_path, sql):
    twb = ("<?xml version='1.0' encoding='utf-8' ?><workbook><datasources><datasource name='d'>"
           f"<connection class='federated'><relation name='Custom SQL Query' type='text'>{sql}"
           "</relation></connection></datasource></datasources></workbook>")
    path = tmp_path / "b.twbx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("b.twb", twb)
    return str(path)


def test_workbook_sql_never_reaches_the_server_for_extract(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "clickhouse", lambda *a, **k: _Refusing())
    book = _book_with_sql(tmp_path, "DROP TABLE marts.t")
    with pytest.raises(Exception, match="refused"):
        extract.to_extract(book, str(tmp_path / "out.twbx"))
    assert not os.path.exists(tmp_path / "out.twbx")


class _Refusing:
    def query_stream(self, *a, **k):
        raise AssertionError("the database was reached")

    execute = query_stream


def test_custom_sql_dry_run_refuses_before_describe(monkeypatch):
    monkeypatch.setattr(config, "clickhouse", lambda *a, **k: _Refusing())
    with pytest.raises(Exception, match="refused"):
        dryrun._CustomSqlTarget("SELECT 1; DROP TABLE marts.t")


def test_dry_run_target_checks_every_query(monkeypatch):
    monkeypatch.setattr(config, "clickhouse", lambda *a, **k: _Refusing())
    monkeypatch.setattr("twkit.schema.fetch_schema", lambda db, t: [{"name": "a"}])
    target = dryrun._ClickhouseTarget("marts", "t")
    with pytest.raises(Exception, match="refused"):
        target.execute("TRUNCATE TABLE marts.t")


class _Server:
    """Answers the readonly probe with `level`, every query with `answer`."""

    def __init__(self, level, answer):
        self.level, self.answer, self.calls = level, answer, []

    def post(self, url, data=None, **k):
        self.calls.append((url, data.decode()))
        if "getSetting('readonly')" in data.decode():
            return _Resp(payload={"data": [[self.level]]})
        return self.answer


def _ro_client(level, answer):
    c = _client(_Resp(payload={}))
    c._session = _Server(level, answer)
    c._read_only = True
    return c


def test_client_asks_the_server_for_read_only():
    c = _ro_client("0", _Resp(payload={"data": [[1]]}))
    c.execute("SELECT 1")
    c.execute("SELECT 2")
    queries = [u for u, d in c._session.calls if "getSetting" not in d]
    assert all("readonly=1" in u for u in queries) and len(c._session.calls) == 3


def test_client_leaves_the_flag_to_an_account_at_readonly_1():
    c = _ro_client("1", _Resp(payload={"data": [[1]]}))
    assert c.execute("SELECT 1") == [[1]]
    assert "readonly" not in c._session.calls[-1][0]


def test_an_error_text_never_lifts_read_only():
    fake = _Resp(status=500, text="Code: 164. Cannot modify 'readonly' setting in readonly mode")
    c = _ro_client("0", fake)
    with pytest.raises(RuntimeError):
        c.execute("SELECT throwIf(1, 'Cannot modify ''readonly'' setting')")
    queries = [u for u, d in c._session.calls if "getSetting" not in d]
    assert len(queries) == 1 and "readonly=1" in queries[0]


def test_quoted_table_function_name_is_refused():
    for sql in ('SELECT * FROM "url"(\'http://x\', CSV, \'a String\')',
                "SELECT * FROM `s3`('x')", "SELECT * FROM t JOIN merge('db', 'x') ON 1"):
        with pytest.raises(PermissionError):
            chsafe.read_only(sql)


def test_scalar_from_inside_functions_is_not_a_table_function():
    chsafe.read_only("SELECT EXTRACT(YEAR FROM DATE_TRUNC('month', d)), "
                     "SUBSTRING(s FROM length(s)) FROM t WHERE a IS NOT DISTINCT FROM lower(b)")
    chsafe.read_only("SELECT * FROM numbers(10)")


def test_run_sql_tool_refuses_a_second_statement():
    from twkit.server.app import register_all
    server = register_all()
    import asyncio
    out = asyncio.run(server.call_tool("run_sql", {"sql": "SELECT 1; DROP TABLE marts.t"}))
    text = str(out)
    assert "REFUSED" in text and "more than one statement" in text


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t, cosn('http://example/x')",
    "SELECT * FROM t AS a, oss('x') AS b",
    "SELECT a FROM t WHERE a IN url('http://example/', CSV, 'a String')",
    "SELECT * FROM t, newfn(1)",
])
def test_table_function_in_any_table_position_is_refused(sql):
    with pytest.raises(PermissionError):
        chsafe.read_only(sql)


def test_comma_lists_of_tables_and_scalar_calls_still_read():
    chsafe.read_only("SELECT a, round(c, 2) FROM t, u WHERE t.a = u.a AND x IN (1, 2)")
    chsafe.read_only("SELECT * FROM numbers(10), numbers(5)")


def test_create_view_needs_the_owners_permission(monkeypatch):
    import asyncio
    from twkit import config
    from twkit.server.app import register_all
    monkeypatch.setattr(config, "_section", lambda name: {})
    out = str(asyncio.run(register_all().call_tool(
        "create_view", {"view_name": "v", "select_sql": "SELECT 1"})))
    assert "REFUSED" in out and "allow_ddl" in out

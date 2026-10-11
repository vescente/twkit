import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from twkit import extract as EX

_TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource caption='P&amp;L' inline='true' name='federated.x' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='h' name='mysql.x'>
            <connection class='mysql' dbname='reports' port='3306' server='h'
                        username='tableau' />
          </named-connection>
        </named-connections>
        <relation connection='mysql.x' name='Custom SQL Query' type='text'>SELECT 1</relation>
        <metadata-records>
          <metadata-record class='column'>
            <parent-name>[Custom SQL Query]</parent-name>
          </metadata-record>
        </metadata-records>
      </connection>
      <column datatype='date' name='[Month]' role='dimension' type='ordinal' />
      <column datatype='real' name='[Money]' role='measure' type='quantitative' />
      <column datatype='integer' name='[Sort Order]' role='measure' type='quantitative' />
      <column datatype='string' name='[Line]' role='dimension' type='nominal' />
    </datasource>
  </datasources>
</workbook>
"""


def _book(tmp_path):
    p = tmp_path / "Book.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", _TWB)
    return str(p)


def test_types_from_book_declarations(tmp_path):
    types = EX.workbook_column_types(_book(tmp_path))
    assert types["Month"] == "date"
    assert types["Money"] == "double"
    assert types["Sort Order"] == "big_int"
    assert types["Line"] == "text"


def test_type_found_in_any_attribute_order(tmp_path):
    twb = _TWB.replace(
        "<column datatype='date' name='[Month]'",
        "<column datatype='date' default-format='*mmm yyyy' name='[Month]'")
    p = tmp_path / "Reordered.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", twb)
    types = EX.workbook_column_types(str(p))
    assert types["Month"] == "date"
    assert types["Money"] == "double"


def test_workbook_sql_found(tmp_path):
    assert EX.workbook_sql(_book(tmp_path)).strip() == "SELECT 1"


def test_book_without_custom_sql_refused(tmp_path):
    p = tmp_path / "Plain.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Plain.twb", "<workbook version='18.1'><datasources /></workbook>")
    res = EX.to_extract(str(p))
    assert res["ok"] is False
    assert "nothing to materialize" in res["why"]


_GRAPH = """      <object-graph>
        <objects>
          <object caption='Custom SQL Query' id='Custom SQL Query_0A1B'>
            <properties context=''>
              <relation connection='mysql.x' name='Custom SQL Query' type='text'>SELECT 1</relation>
            </properties>
          </object>
        </objects>
      </object-graph>
      <layout dim-ordering='alphabetic' measure-ordering='alphabetic' show-structure='true' />
    </datasource>"""


def _live_book(tmp_path):
    twb = _TWB.replace("""<metadata-record class='column'>
            <parent-name>[Custom SQL Query]</parent-name>
          </metadata-record>""", "".join(
        f"<metadata-record class='column'><remote-name>{n}</remote-name><remote-type>{rt}</remote-type>"
        f"<local-name>[{n}]</local-name><parent-name>[Custom SQL Query]</parent-name>"
        f"<remote-alias>{n}</remote-alias><ordinal>{i + 1}</ordinal><local-type>{lt}</local-type>"
        f"<aggregation>Sum</aggregation><contains-null>true</contains-null></metadata-record>"
        for i, (n, rt, lt) in enumerate((("Month", "133", "date"), ("Money", "5", "real")))))
    twb = twb.replace("\n    </datasource>", "\n" + _GRAPH, 1)
    p = tmp_path / "Live.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Live.twb", twb)
        z.writestr("Data/Extracts/old.hyper", b"stale")
    return str(p)


def test_extract_keeps_the_sql_underneath_like_desktop(tmp_path, monkeypatch):
    from twkit import safexml

    def fake_hyper(sql, out, table, types=None):
        assert sql.strip() == "SELECT 1"
        open(out, "wb").write(b"hyper")
        return {"rows": 7, "columns": 2}

    monkeypatch.setattr(EX, "build_hyper_from_sql", fake_hyper)
    out = str(tmp_path / "Live (extract).twbx")
    res = EX.to_extract(_live_book(tmp_path), out)
    assert res["ok"] and res["row_count"] == 7
    root = safexml.from_twbx(out)
    ds = root.find("datasources/datasource")
    live = ds.find("connection/relation[@type='text']")
    assert live is not None and live.text == "SELECT 1"
    assert ds.find("connection/named-connections/named-connection/connection").get("class") == "mysql"
    conn = ds.find("extract/connection")
    assert ds.find("extract").get("enabled") == "true" and conn.get("class") == "hyper"
    assert conn.find("relation").get("table") == "[Extract].[Extract]"
    assert conn.find("refresh/refresh-event").get("rows-inserted") == "7"
    recs = conn.findall("metadata-records/metadata-record")
    assert [r.findtext("remote-name") for r in recs] == ["Month", "Money"]
    assert {r.findtext("parent-name") for r in recs} == {"[Extract]"}
    assert {r.findtext("object-id") for r in recs} == {"[Custom SQL Query_0A1B]"}
    ctx = ds.find("object-graph/objects/object/properties[@context='extract']/relation")
    assert ctx is not None and ctx.get("table") == "[Extract].[Extract]"
    tags = [c.tag for c in ds]
    assert tags.index("extract") < tags.index("layout") < tags.index("object-graph")
    names = zipfile.ZipFile(out).namelist()
    assert conn.get("dbname") in names and "Live (extract).twb" in names
    assert "Data/Extracts/old.hyper" in names, "an unrelated packaged file is kept"


def test_extract_replaces_its_own_previous_extract(tmp_path, monkeypatch):
    from twkit import safexml
    monkeypatch.setattr(EX, "build_hyper_from_sql",
                        lambda sql, out, table, types=None: (open(out, "wb").write(b"h"),
                                                             {"rows": 1, "columns": 2})[1])
    first = str(tmp_path / "a.twbx")
    second = str(tmp_path / "b.twbx")
    EX.to_extract(_live_book(tmp_path), first)
    EX.to_extract(first, second)
    ds = safexml.from_twbx(second).find("datasources/datasource")
    assert len(ds.findall("extract")) == 1
    assert len(ds.findall("object-graph/objects/object/properties[@context='extract']")) == 1


_DESKTOP_SQL = "SELECT 1 WHERE a &gt;&gt;= 1 AND b &lt;&lt; 2"   # as Desktop saves `a >= 1 AND b < 2`


def _desktop_book(tmp_path):
    p = tmp_path / "Desktop.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", _TWB.replace(">SELECT 1<", f">{_DESKTOP_SQL}<"))
    return str(p)


def test_workbook_sql_undoes_desktop_doubling(tmp_path):
    assert EX.workbook_sql(_desktop_book(tmp_path)) == "SELECT 1 WHERE a >= 1 AND b < 2"


def test_extract_sends_plain_sql_and_keeps_desktop_form(tmp_path, monkeypatch):
    from twkit import safexml
    seen = []

    def fake_hyper(sql, out, table, types=None):
        seen.append(sql)
        open(out, "wb").write(b"hyper")
        return {"rows": 1, "columns": 1}

    monkeypatch.setattr(EX, "build_hyper_from_sql", fake_hyper)
    out = str(tmp_path / "Desktop (extract).twbx")
    assert EX.to_extract(_desktop_book(tmp_path), out)["ok"]
    assert seen == ["SELECT 1 WHERE a >= 1 AND b < 2"], seen
    rel = safexml.from_twbx(out).find(".//connection/relation[@type='text']")
    assert rel.text == "SELECT 1 WHERE a >>= 1 AND b << 2", "the SQL under the extract stays as Desktop wrote it"


def test_tsv_unescape_is_one_pass():
    from twkit.chclient import _unescape as u
    assert u(r"C:\\new") == "C:\\new"            # a backslash, then the letter n
    assert u(r"a\tb") == "a\tb" and u(r"O\'Brien") == "O'Brien" and u(r"x\0") == "x\0"
    assert u(r"\N") is None and u("") == ""


def test_workbook_types_keep_time_and_booleans(tmp_path):
    twb = _TWB.replace("<column datatype='date' name='[Month]'",
                       "<column datatype='datetime' name='[At]' role='dimension' type='ordinal' />"
                       "<column datatype='boolean' name='[Vip]' role='dimension' type='nominal' />"
                       "<column datatype='date' name='[Month]'")
    p = tmp_path / "Types.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", twb)
    types = EX.workbook_column_types(str(p))
    assert types["At"] == "timestamp" and types["Vip"] == "bool"


def test_hyper_keeps_empty_text_and_exact_integers(tmp_path, monkeypatch):
    pytest.importorskip("tableauhyperapi")
    from tableauhyperapi import Connection, HyperProcess, Telemetry
    from twkit import config

    class _Stream:
        def query_stream(self, sql, batch=50_000):
            return (["id", "name"], ["Int64", "String"],
                    iter([[["9007199254740993", ""], ["2", "Asia"], ["3", None]]]))

    monkeypatch.setattr(config, "clickhouse", lambda *a, **k: _Stream())
    out = str(tmp_path / "x.hyper")
    EX.build_hyper_from_sql("SELECT 1", out)
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp, Connection(hp.endpoint, out) as c:
        rows = c.execute_list_query('SELECT "id", "name" FROM "Extract"."Extract" ORDER BY "id"')
    assert rows == [[2, "Asia"], [3, None], [9007199254740993, ""]]

import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from twkit import extract as EX
from twkit import safexml

hyper = pytest.importorskip("tableauhyperapi")

_TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook><datasources>
  <datasource caption='Model' name='federated.m'>
    <connection class='federated'>
      <named-connections>
        <named-connection name='mysql.db'><connection class='mysql' dbname='marts'/></named-connection>
      </named-connections>
      <relation type='collection'>
        <relation connection='mysql.db' name='facts' type='text'>SELECT d, v FROM t WHERE v &gt;&gt; 0</relation>
        <relation connection='mysql.db' name='labels' type='text'>SELECT 'A' AS l</relation>
      </relation>
    </connection>
    <extract enabled='true'>
      <connection class='hyper' dbname='Data/Extracts/m.hyper' update-time='old'>
        <relation type='collection'>
          <relation name='_F1' table='[Extract].[_F1]' type='table'/>
          <relation name='labels_L1' table='[Extract].[labels_L1]' type='table'/>
        </relation>
      </connection>
    </extract>
    <object-graph><objects>
      <object caption='facts' id='_F1'>
        <properties context=''><relation connection='mysql.db' name='facts' type='text'>SELECT d, v FROM t WHERE v &gt;&gt; 0</relation></properties>
        <properties context='extract'><relation name='_F1' table='[Extract].[_F1]' type='table'/></properties>
      </object>
      <object caption='labels' id='labels_L1'>
        <properties context=''><relation connection='mysql.db' name='labels' type='text'>SELECT 'A' AS l</relation></properties>
        <properties context='extract'><relation name='labels_L1' table='[Extract].[labels_L1]' type='table'/></properties>
      </object>
    </objects></object-graph>
  </datasource>
</datasources></workbook>
"""


def _template(path):
    from tableauhyperapi import (Connection, CreateMode, HyperProcess, Inserter, SqlType,
                                 TableDefinition, TableName, Telemetry)
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp, \
            Connection(hp.endpoint, path, CreateMode.CREATE_AND_REPLACE) as c:
        c.catalog.create_schema("Extract")
        f = TableDefinition(TableName("Extract", "_F1"), [
            TableDefinition.Column("d", SqlType.date()), TableDefinition.Column("v", SqlType.double())])
        l_ = TableDefinition(TableName("Extract", "labels_L1"), [TableDefinition.Column("l", SqlType.text())])
        c.catalog.create_table(f)
        c.catalog.create_table(l_)
        with Inserter(c, f) as ins:
            ins.add_row([__import__("datetime").date(2026, 1, 1), 1.0])
            ins.execute()


class _FakeCH:
    def __init__(self):
        self.seen = []

    def query_stream(self, sql, batch=50_000):
        self.seen.append(sql)
        if "FROM t" in sql:
            return ["d", "v"], ["Date", "Float64"], iter([[["2026-11-20", "2.5"], ["2026-11-21", None]]])
        return ["l"], ["String"], iter([[["A"], ["B"], ["C"]]])


def test_multi_table_extract_gets_new_rows_and_keeps_its_xml(tmp_path, monkeypatch):
    tpl = tmp_path / "m.hyper"
    _template(str(tpl))
    book = tmp_path / "Book.twbx"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Book.twb", _TWB)
        z.write(tpl, "Data/Extracts/m.hyper")
        z.writestr("Data/Images/logo.png", b"png")
    fake = _FakeCH()
    from twkit import config
    monkeypatch.setattr(config, "clickhouse", lambda **k: fake)
    out = tmp_path / "Book (refreshed).twbx"
    res = EX.refresh_extract_data(str(book), str(out))
    assert res["ok"] and res["sources"][0]["rows"] == {"_F1": 2, "labels_L1": 3}, res
    assert any("v > 0" in s for s in fake.seen), "the SQL is unescaped from Desktop's >> form"
    names = zipfile.ZipFile(out).namelist()
    assert "Book.twb" in names and "Data/Images/logo.png" in names
    root = safexml.from_twbx(str(out))
    assert root.find(".//extract/connection").get("update-time") != "old"
    assert [o.get("id") for o in root.iter("object")] == ["_F1", "labels_L1"]
    from tableauhyperapi import Connection, HyperProcess, Telemetry
    got = tmp_path / "got.hyper"
    got.write_bytes(zipfile.ZipFile(out).read("Data/Extracts/m.hyper"))
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp, \
            Connection(hp.endpoint, str(got)) as c:
        assert c.execute_list_query('SELECT CAST("d" AS TEXT), "v" FROM "Extract"."_F1" ORDER BY 1') == \
            [["2026-11-20", 2.5], ["2026-11-21", None]]
        assert c.execute_scalar_query('SELECT COUNT(*) FROM "Extract"."labels_L1"') == 3


def test_a_file_table_is_refused():
    from lxml import etree
    ds = etree.fromstring(
        "<datasource><connection class='federated'><named-connections>"
        "<named-connection name='x'><connection class='excel-direct'/></named-connection>"
        "</named-connections><relation connection='x' name='r' table='[r$]' type='table'/></connection>"
        "<extract><connection dbname='a.hyper'><relation table='[Extract].[Extract]'/></connection></extract>"
        "</datasource>")
    with pytest.raises(ValueError, match="reads a file"):
        EX.extract_tables(ds)

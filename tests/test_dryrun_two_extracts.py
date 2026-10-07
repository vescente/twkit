import os
import zipfile

import pytest

from twkit import dryrun

pytest.importorskip("tableauhyperapi")

DS_A = "federated.aaaaaaaaaaaaaaaaaaaa"
DS_B = "federated.bbbbbbbbbbbbbbbbbbbb"


def _hyper(path, schema, table, columns, rows):
    from tableauhyperapi import (Connection, CreateMode, HyperProcess, Inserter,
                                 SqlType, TableDefinition, TableName, Telemetry)
    kind = {"text": SqlType.text(), "big_int": SqlType.big_int()}
    tdef = TableDefinition(TableName(schema, table),
                           [TableDefinition.Column(n, kind[t]) for n, t in columns])
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
        with Connection(endpoint=hp.endpoint, database=path,
                        create_mode=CreateMode.CREATE_AND_REPLACE) as c:
            c.catalog.create_schema(schema)
            c.catalog.create_table(tdef)
            with Inserter(c, tdef) as ins:
                ins.add_rows(rows)
                ins.execute()
    return path


def _records(table, columns):
    out = []
    for i, (name, kind) in enumerate(columns):
        local = "string" if kind == "text" else "integer"
        agg = "Count" if kind == "text" else "Sum"
        out.append(
            f"<metadata-record class='column'><remote-name>{name}</remote-name>"
            f"<remote-type>129</remote-type><local-name>[{name}]</local-name>"
            f"<parent-name>[{table}]</parent-name><remote-alias>{name}</remote-alias>"
            f"<ordinal>{i}</ordinal><local-type>{local}</local-type>"
            f"<aggregation>{agg}</aggregation><contains-null>true</contains-null>"
            "</metadata-record>")
    return "".join(out)


def _datasource(name, caption, arc, table, columns):
    cols = "".join(
        f"<column datatype='{'string' if k == 'text' else 'integer'}' name='[{n}]' "
        f"role='{'dimension' if k == 'text' else 'measure'}' "
        f"type='{'nominal' if k == 'text' else 'quantitative'}' />"
        for n, k in columns)
    conn = f"hyper.{name}"
    return (
        f"<datasource caption='{caption}' inline='true' name='{name}' version='18.1'>"
        f"<connection class='federated'><named-connections>"
        f"<named-connection caption='{os.path.basename(arc)}' name='{conn}'>"
        f"<connection class='hyper' dbname='{arc}' schema='Extract' "
        f"tablename='{table}' /></named-connection></named-connections>"
        f"<relation connection='{conn}' name='{table}' "
        f"table='[Extract].[{table}]' type='table' />"
        f"<metadata-records>{_records(table, columns)}</metadata-records>"
        f"</connection>{cols}</datasource>")


def _sheet(sheet, ds, caption, dim, measure):
    deps = (f"<column datatype='string' name='[{dim}]' role='dimension' type='nominal' />"
            f"<column datatype='integer' name='[{measure}]' role='measure' "
            f"type='quantitative' />"
            f"<column-instance column='[{dim}]' derivation='None' "
            f"name='[none:{dim}:nk]' pivot='key' type='nominal' />"
            f"<column-instance column='[{measure}]' derivation='Sum' "
            f"name='[sum:{measure}:qk]' pivot='key' type='quantitative' />")
    return (
        f"<worksheet name='{sheet}'><table><view><datasources>"
        f"<datasource caption='{caption}' name='{ds}' /></datasources>"
        f"<datasource-dependencies datasource='{ds}'>{deps}</datasource-dependencies>"
        f"<aggregation value='true' /></view>"
        f"<panes><pane><view><breakdown value='auto' /></view>"
        f"<mark class='Bar' /></pane></panes>"
        f"<rows>[{ds}].[none:{dim}:nk]</rows>"
        f"<cols>[{ds}].[sum:{measure}:qk]</cols></table></worksheet>")


def _book(tmp_path):
    a_cols = [("metric", "text"), ("val", "big_int")]
    b_cols = [("segment", "text"), ("moves", "big_int")]
    a = _hyper(str(tmp_path / "a.hyper"), "Extract", "Extract", a_cols,
               [["GGR", 10], ["NGR", 20]])
    b = _hyper(str(tmp_path / "b.hyper"), "Extract", "SegmentFlow", b_cols,
               [["Active", 5], ["Dormant", 7]])
    xml = (
        "<?xml version='1.0' encoding='utf-8' ?>"
        "<workbook xmlns:user='http://www.tableausoftware.com/xml/user' "
        "source-build='2026.1.2' version='18.1'><datasources>"
        + _datasource(DS_A, "A", "Data/Extracts/a.hyper", "Extract", a_cols)
        + _datasource(DS_B, "B", "Data/Extracts/b.hyper", "SegmentFlow", b_cols)
        + "</datasources><worksheets>"
        + _sheet("main sheet", DS_A, "A", "metric", "val")
        + _sheet("flow sheet", DS_B, "B", "segment", "moves")
        + "</worksheets></workbook>")
    out = str(tmp_path / "two.twbx")
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("two.twb", xml)
        z.write(a, "Data/Extracts/a.hyper")
        z.write(b, "Data/Extracts/b.hyper")
    return out


def test_each_sheet_uses_its_own_extract(tmp_path):
    res = {r.sheet: r for r in dryrun.dry_run(_book(tmp_path))}

    assert set(res) == {"main sheet", "flow sheet"}
    for name, r in res.items():
        assert r.status == "ok", f"{name}: {r.status} · {r.note}"
    assert 'SegmentFlow' in res["flow sheet"].sql, res["flow sheet"].sql
    assert '"Extract"."Extract"' in res["main sheet"].sql, res["main sheet"].sql


def test_extract_map_per_datasource(tmp_path):
    from twkit.lint import load
    book = load(_book(tmp_path))

    assert dryrun.hyper_map(book) == {DS_A: "Data/Extracts/a.hyper",
                                      DS_B: "Data/Extracts/b.hyper"}

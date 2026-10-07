"""Defects found by review of the builder, each pinned by a test."""
import os
import zipfile

import pytest

import _matrix_book as M
from twkit import chsafe, safexml
from twkit.book import Book


def _book(tmp_path):
    b = Book()
    b.set_csv_connection(M.write_csv(str(tmp_path / "sales.csv")), fields=[dict(f) for f in M.FIELDS])
    return b


def test_sniffed_csv_gets_tableau_datatypes(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("Owner's share;n;x;d\na;1;1.5;2026-01-01\nb;2;2.5;2026-01-02\n", encoding="utf-8")
    b = Book()
    b.set_csv_connection(str(p))
    got = {c.get("name"): c.get("datatype") for c in b.datasource.findall("column")
           if c.get("datatype") != "table"}
    assert got == {"[Owner's share]": "string", "[n]": "integer", "[x]": "real", "[d]": "date"}
    b.add_worksheet("s")
    b.configure_chart("s", mark_type="Bar", rows=["Owner's share"], columns=["SUM(x)"])
    out = b.save(str(tmp_path / "t.twbx"))
    with zipfile.ZipFile(out) as z:
        assert "t.csv" in z.namelist()


def test_sort_keeps_the_aggregation(tmp_path):
    b = _book(tmp_path)
    b.add_worksheet("s")
    b.configure_chart("s", mark_type="Bar", rows=["product"], columns=["COUNTD(country)"],
                      sort_descending="COUNTD(country)")
    sort = next(b.root.iter("shelf-sort-v2"))
    assert sort.get("measure-to-sort-by").endswith("[ctd:country:qk]"), sort.attrib


def test_filter_zone_on_a_date_keeps_the_sheet_instance(tmp_path):
    b = _book(tmp_path)
    b.add_worksheet("s")
    b.configure_chart("s", mark_type="Line", columns=["MONTH(date)"], rows=["SUM(sales)"])
    b.add_dashboard("D", layout={"type": "container", "direction": "vertical", "children": [
        {"type": "filter", "worksheet": "s", "field": "MONTH(date)", "fixed_size": 60},
        {"type": "worksheet", "name": "s"}]}, worksheet_names=["s"])
    zone = next(z for z in b.root.iter("zone") if z.get("type-v2") == "filter")
    assert zone.get("param").endswith("[mn:date:ok]"), zone.get("param")
    kinds = {ci.get("name") for ci in b.sheet("s").iter("column-instance") if ":date:" in ci.get("name")}
    assert kinds == {"[mn:date:ok]"}, kinds


def test_filter_action_link_names_the_source_like_tableau(tmp_path):
    b = _book(tmp_path)
    for n in ("A", "B"):
        b.add_worksheet(n)
        b.configure_chart(n, mark_type="Bar", rows=["country"], columns=["SUM(sales)"])
    b.add_dashboard("D", layout="horizontal", worksheet_names=["A", "B"])
    b.add_dashboard_action("D", "filter", "A", "B", fields=["country"])
    expr = next(b.root.iter("link")).get("expression")
    ds = b.datasource.get("name")
    assert expr.endswith(f"~s0=<[{ds}].[country]~na>"), expr


def test_calculation_referenced_elsewhere_is_not_removed(tmp_path):
    b = _book(tmp_path)
    b.add_calculated_field("Base", "SUM([sales])", datatype="real")
    b.add_calculated_field("Twice", "[Base] * 2", datatype="real")
    said = b.remove_calculated_field("Base")
    assert "still referenced" in said
    assert any(c.get("caption") == "Base" for c in b.datasource.findall("column"))


def test_caption_inside_a_string_literal_is_left_alone(tmp_path):
    b = _book(tmp_path)
    b.add_calculated_field("Total", "SUM([sales])", datatype="real")
    b.add_calculated_field("Label", "'[Total]' + STR([Total])", datatype="string")
    f = next(c for c in b.datasource.findall("column") if c.get("caption") == "Label")
    formula = f.find("calculation").get("formula")
    assert formula.startswith("'[Total]' + STR([Calculation_"), formula


def test_internal_name_taken_twice_is_refused(tmp_path):
    b = _book(tmp_path)
    b.add_calculated_field("A", "1", datatype="real", internal_name="calc_a")
    with pytest.raises(ValueError, match="already taken"):
        b.add_calculated_field("B", "2", datatype="real", internal_name="calc_a")


def test_a_sheet_keeps_its_second_data_source(tmp_path):
    from twkit import extract
    b = _book(tmp_path)
    extract.add_extract_source(b.root, "Second", "Data/Extracts/x.hyper", "T",
                               [{"name": "seg", "datatype": "string"},
                                {"name": "amount", "datatype": "real", "role": "measure"}])
    b.add_worksheet("s")
    b.configure_chart("s", mark_type="Bar", rows=["seg"], columns=["SUM(amount)"],
                      datasource="Second")
    b.configure_chart("s", mark_type="Bar", rows=["seg"], columns=["SUM(amount)"])
    names = [d.get("name") for d in b.sheet("s").iter("datasource")]
    assert names and all(n != b.datasource.get("name") for n in names), names


def test_extract_in_the_public_schema(tmp_path):
    hyperapi = pytest.importorskip("tableauhyperapi")
    hp = str(tmp_path / "p.hyper")
    with hyperapi.HyperProcess(hyperapi.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as h, \
            hyperapi.Connection(h.endpoint, hp, hyperapi.CreateMode.CREATE_AND_REPLACE) as c:
        c.catalog.create_table(hyperapi.TableDefinition(
            hyperapi.TableName("public", "T"),
            [hyperapi.TableDefinition.Column("a", hyperapi.SqlType.text())]))
    b = Book()
    b.set_hyper_connection(hp, table_name="T")
    assert {r.get("table") for r in b.root.iter("relation")} == {"[public].[T]"}


def test_reopened_book_streams_its_members(tmp_path):
    b = _book(tmp_path)
    p = b.save(str(tmp_path / "a.twbx"))
    again = Book.open(p)
    assert all(isinstance(v, tuple) for v in again.members.values())
    q = again.save(str(tmp_path / "b.twbx"))
    with zipfile.ZipFile(p) as a, zipfile.ZipFile(q) as c:
        assert a.read("sales.csv") == c.read("sales.csv")
    assert safexml.from_twbx(q) is not None


@pytest.mark.parametrize("sql", ["WITH t AS (SELECT 1) INSERT INTO x SELECT * FROM t",
                                 "WITH t AS (SELECT 1) DELETE FROM x"])
def test_write_behind_a_read_head_is_refused(sql):
    with pytest.raises(PermissionError):
        chsafe.read_only(sql)


def test_system_tables_stay_readable():
    chsafe.read_only("SELECT name FROM system.tables")


def test_parameter_action_declares_the_feature_in_the_manifest(tmp_path):
    b = _book(tmp_path)
    b.add_parameter("Metric", datatype="string", default_value="Sales", domain_type="list",
                    allowed_values=["Sales", "Cost"])
    b.add_worksheet("A")
    b.configure_chart("A", mark_type="Bar", rows=["product"], columns=["SUM(sales)"])
    b.add_dashboard("D", layout="vertical", worksheet_names=["A"])
    b.add_dashboard_action("D", "parameter", "A", source_field="product", target_parameter="Metric")
    flags = {c.tag for c in b.root.find("document-format-change-manifest")}
    assert {"ParameterAction", "ParameterActionClearSelection"} <= flags, flags


@pytest.mark.parametrize("name,folder", [("id_rsa", "keys"), ("data.csv", ".ssh"), ("x.hyper", ".aws")])
def test_secrets_never_go_into_a_workbook(tmp_path, name, folder):
    d = tmp_path / folder
    d.mkdir()
    p = d / name
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    b = Book()
    with pytest.raises(PermissionError):
        if name.endswith(".hyper"):
            b.set_hyper_connection(str(p))
        else:
            b.set_csv_connection(str(p))


def test_a_binary_file_named_csv_is_refused(tmp_path):
    p = tmp_path / "x.csv"
    p.write_bytes(b"\0\1\2binary")
    with pytest.raises(PermissionError, match="not text"):
        Book().set_csv_connection(str(p))

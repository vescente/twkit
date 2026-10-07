import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED

COLUMNS = [{"name": "Date", "datatype": "date"},
           {"name": "Amount", "datatype": "real"},
           {"name": "Acc Lv0", "datatype": "string"}]


def _book():
    root = etree.fromstring(
        "<workbook><datasources><datasource caption='old' name='federated.x'>"
        "<connection class='sqlproxy'/>"
        "<column datatype='string' name='[Segment]' role='dimension' type='nominal'/>"
        "<column datatype='real' name='[Sales]' role='measure' type='quantitative'/>"
        "<column caption='My calc' datatype='real' name='[Calc 1]' role='measure' type='quantitative'>"
        "<calculation class='tableau' formula='SUM(1)'/></column>"
        "<layout/><style/>"
        "</datasource></datasources></workbook>")
    return root


def _names(ds):
    return {(c.get("name") or "").strip("[]") for c in ds.findall("column")}


def test_query_columns_declared():
    root = _book()
    ED.to_live_sql(root, "SELECT 1", COLUMNS, server="h", port="3306",
                   dbname="db", username="u")
    ds = root.find("./datasources/datasource")
    assert {"Date", "Amount", "Acc Lv0"} <= _names(ds)


def test_foreign_columns_removed():
    root = _book()
    ED.to_live_sql(root, "SELECT 1", COLUMNS, server="h", port="3306",
                   dbname="db", username="u")
    ds = root.find("./datasources/datasource")
    assert "Segment" not in _names(ds) and "Sales" not in _names(ds)


def test_calculations_untouched():
    root = _book()
    ED.to_live_sql(root, "SELECT 1", COLUMNS, server="h", port="3306",
                   dbname="db", username="u")
    ds = root.find("./datasources/datasource")
    assert "Calc 1" in _names(ds)


def test_field_role_from_type():
    root = _book()
    ED.to_live_sql(root, "SELECT 1", COLUMNS, server="h", port="3306",
                   dbname="db", username="u")
    ds = root.find("./datasources/datasource")
    role = {(c.get("name") or "").strip("[]"): c.get("role") for c in ds.findall("column")}
    assert role["Amount"] == "measure"
    assert role["Acc Lv0"] == "dimension"
    assert role["Date"] == "dimension"


def test_column_inserted_per_schema():
    root = _book()
    ED.to_live_sql(root, "SELECT 1", COLUMNS, server="h", port="3306",
                   dbname="db", username="u")
    ds = root.find("./datasources/datasource")
    tags = [e.tag for e in ds]
    last_col = max(i for i, t in enumerate(tags) if t == "column")
    assert last_col < tags.index("layout"), tags
    assert last_col < tags.index("style"), tags


def test_system_fields_survive_schema_change():
    from lxml import etree

    from twkit.edit import sync_column_decls

    ds = etree.fromstring(
        "<datasource>"
        "<column datatype='string' name='[old_col]' role='dimension' type='nominal' />"
        "<column datatype='string' name='[:Measure Names]' role='dimension' "
        "type='nominal' />"
        "</datasource>")

    res = sync_column_decls(ds, [{"name": "new_col", "datatype": "string"}])

    names = [c.get("name") for c in ds.findall("column")]
    assert "[:Measure Names]" in names
    assert "[old_col]" not in names and "[new_col]" in names
    assert res == {"added": 1, "removed": 1}

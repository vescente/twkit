import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED

COLUMNS = [{"name": "user_id", "datatype": "integer"},
           {"name": "ggr", "datatype": "real"}]

SQL = "SELECT user_id, ggr FROM marts.daily_metrics"


def _book():
    return etree.fromstring(
        "<workbook><datasources>"
        "<datasource caption='Old Users' name='federated.x'>"
        "<connection class='federated'>"
        "<named-connections><named-connection name='hyper.dead'>"
        "<connection class='hyper' dbname='Data/x.hyper'/>"
        "</named-connection></named-connections>"
        "<relation name='Extract' table='[Extract].[Extract]' type='table'/>"
        "</connection>"
        "<object-graph><objects>"
        "<object caption='Extract' id='Extract_9BC5258A'>"
        "<properties context=''>"
        "<relation connection='hyper.dead' name='Extract' "
        "table='[Extract].[Extract]' type='table'/>"
        "</properties>"
        "<properties context='extract'>"
        "<relation name='Extract' table='[Extract].[Extract]' type='table'/>"
        "</properties>"
        "</object></objects></object-graph>"
        "</datasource></datasources></workbook>")


def _convert(root):
    return ED.to_live_sql(root, SQL, COLUMNS, server="h", port="3306",
                          dbname="marts", username="tableau")


def test_logical_layer_no_longer_points_to_extract():
    root = _book()
    _convert(root)
    og = root.find(".//object-graph")
    assert og is not None
    tables = [r.get("table") for r in og.iter("relation")]
    assert "[Extract].[Extract]" not in tables


def test_logical_layer_carries_same_query():
    root = _book()
    _convert(root)
    rels = list(root.find(".//object-graph").iter("relation"))
    assert len(rels) == 1
    rel = rels[0]
    assert rel.get("type") == "text" and rel.get("name") == "Custom SQL Query"
    assert (rel.text or "").strip() == SQL


def test_logical_layer_references_live_connection():
    root = _book()
    _convert(root)
    live = {nc.get("name") for nc in root.iter("named-connection")}
    rel = next(iter(root.find(".//object-graph").iter("relation")))
    assert rel.get("connection") in live
    assert not rel.get("connection").startswith("hyper.")


def test_extract_branch_removed():
    root = _book()
    _convert(root)
    ctx = [p.get("context") for p in root.find(".//object-graph").iter("properties")]
    assert "extract" not in ctx


def test_object_named_after_source():
    root = _book()
    _convert(root)
    obj = root.find(".//object-graph/objects/object")
    assert obj.get("caption") == "Old Users"
    assert obj.get("id", "").startswith("_")


def test_logical_layer_created_when_missing():
    root = etree.fromstring(
        "<workbook><datasources>"
        "<datasource caption='Segment flow' name='federated.y'>"
        "<connection class='federated'/>"
        "</datasource></datasources></workbook>")
    rep = _convert(root)
    assert rep["sources_switched"] == 1
    assert rep["object_graphs_rewritten"] == 1
    obj = root.find(".//object-graph/objects/object")
    assert obj is not None
    assert obj.get("caption") == "Segment flow"
    rel = obj.find("properties/relation")
    assert rel.get("type") == "text" and rel.text

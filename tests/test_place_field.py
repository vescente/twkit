import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED

_WB = """<workbook version='18.1'>
  <datasources>
    <datasource name='federated.x' version='18.1'>
      <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
      <column datatype='real' name='[NGR]' role='measure' type='quantitative' />
      <column datatype='string' name='[country]' role='dimension' type='nominal' />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet'><table>
      <view>
        <datasources><datasource name='federated.x' /></datasources>
        <datasource-dependencies datasource='federated.x'>
          <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
        </datasource-dependencies>
        <aggregation value='true' />
      </view>
      <style />
      <panes><pane><view /><mark class='Automatic' /></pane></panes>
      <rows />
      <cols />
    </table></worksheet>
    <worksheet name='Measures'><table>
      <view>
        <datasources><datasource name='federated.x' /></datasources>
        <datasource-dependencies datasource='federated.x'>
          <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
        </datasource-dependencies>
      </view>
      <style />
      <panes><pane><view /></pane></panes>
      <rows>[federated.x].[:Measure Names]</rows>
      <cols />
    </table></worksheet>
  </worksheets>
</workbook>
"""


def _root():
    return etree.fromstring(_WB.encode("utf-8"))


def _shelf(root, sheet, tag):
    ws = [w for w in root.iter("worksheet") if w.get("name") == sheet][0]
    node = ws.find(f"table/{tag}")
    return (node.text or "").strip() if node is not None else None


def test_measure_added_with_plus_dimension_nested_with_slash():
    root = _root()
    ED.place_field(root, "Sheet", "country", shelf="rows", derivation="None")
    r = ED.place_field(root, "Sheet", "GGR", shelf="rows")
    assert r["separator"] == "+"
    expr = _shelf(root, "Sheet", "rows")
    assert expr.startswith("(") and " + " in expr
    r2 = ED.place_field(root, "Sheet", "NGR", shelf="columns")
    assert r2["expression"] == "[federated.x].[sum:NGR:qk]"


def test_dimension_gets_role_instance_name():
    root = _root()
    r = ED.place_field(root, "Sheet", "country", shelf="columns", derivation="None")
    assert r["expression"] == "[federated.x].[none:country:nk]"


def test_repeat_does_not_duplicate_field():
    root = _root()
    ED.place_field(root, "Sheet", "GGR", shelf="rows")
    r = ED.place_field(root, "Sheet", "GGR", shelf="rows")
    assert r["set"] == 0
    assert _shelf(root, "Sheet", "rows").count("sum:GGR") == 1


def test_measure_table_not_built_by_shelf():
    root = _root()
    r = ED.place_field(root, "Measures", "GGR", shelf="rows")
    assert r["ok"] is False
    assert "add_measure" in r["why"]


def test_encoding_in_pane_one_per_shelf():
    root = _root()
    ED.place_field(root, "Sheet", "GGR", shelf="text")
    ED.place_field(root, "Sheet", "NGR", shelf="text")
    enc = [e for e in root.iter("encodings")][0]
    texts = enc.findall("text")
    assert len(texts) == 1
    assert texts[0].get("column").endswith("[sum:NGR:qk]")


def test_several_detail_fields_allowed():
    root = _root()
    ED.place_field(root, "Sheet", "country", shelf="detail", derivation="None")
    ED.place_field(root, "Sheet", "GGR", shelf="detail")
    enc = [e for e in root.iter("encodings")][0]
    assert len(enc.findall("lod")) == 2


def test_encodings_inserted_per_schema_not_appended():
    root = _root()
    pane = [p for p in root.iter("pane")][0]
    etree.SubElement(pane, "style")
    ED.place_field(root, "Sheet", "GGR", shelf="color")
    tags = [c.tag for c in pane]
    assert tags.index("encodings") < tags.index("style")


def test_shelf_created_in_place_in_table():
    root = _root()
    ws = [w for w in root.iter("worksheet") if w.get("name") == "Sheet"][0]
    table = ws.find("table")
    table.remove(table.find("rows"))
    ED.place_field(root, "Sheet", "GGR", shelf="rows")
    assert [c.tag for c in table] == ["view", "style", "panes", "rows", "cols"]


def test_missing_sheet_and_shelf_refused():
    root = _root()
    assert ED.place_field(root, "None", "GGR")["ok"] is False
    assert ED.place_field(root, "Sheet", "GGR", shelf="wing")["ok"] is False
    assert "rows" in ED.place_field(root, "Sheet", "GGR", shelf="wing")["shelves"]

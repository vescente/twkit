import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED
from twkit.edit import _drop_ref, _parse_shelf, _render_shelf

_WB = """<workbook version='18.1'>
  <datasources><datasource name='federated.x' version='18.1'>
    <column datatype='string' name='[country]' role='dimension' type='nominal' />
    <column datatype='string' name='[brand]' role='dimension' type='nominal' />
    <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
  </datasource></datasources>
  <worksheets>
    <worksheet name='Sheet'><table>
      <view>
        <datasources><datasource name='federated.x' /></datasources>
        <datasource-dependencies datasource='federated.x'>
          <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
        </datasource-dependencies>
      </view>
      <style /><panes><pane><encodings>
        <text column='[federated.x].[sum:GGR:qk]' />
        <lod column='[federated.x].[none:brand:nk]' />
      </encodings></pane></panes>
      <rows>([federated.x].[none:country:nk] / [federated.x].[none:brand:nk])</rows>
      <cols>[federated.x].[sum:GGR:qk]</cols>
    </table></worksheet>
  </worksheets>
</workbook>
"""


def _root():
    return etree.fromstring(_WB.encode("utf-8"))


def _shelf(root, tag):
    return ([w for w in root.iter("worksheet")][0].find(f"table/{tag}").text or "").strip()


def _circle(text):
    return _render_shelf(_parse_shelf(text)).replace(" ", "")


def test_parse_and_build_round_trip():
    for t in ("[d].[a]",
              "([d].[a] + [d].[b])",
              "([d].[a] / ([d].[b] / [d].[c]))",
              "([d].[a] * ([d].[b] + [d].[c]))",
              "([d].[a] / [d].[b] / [d].[c])"):
        assert _circle(t) == t.replace(" ", ""), t


def test_reference_can_have_three_parts():
    t = "([d].[__tableau_internal_object_id__].[cnt:File:qk] + [d].[usr:X:qk])"
    assert _circle(t) == t.replace(" ", "")


def test_nesting_survives_removal():
    tree = _parse_shelf("([d].[a] / ([d].[b] / [d].[c]))")
    assert _render_shelf(_drop_ref(tree, "[d].[b]")) == "([d].[a] / [d].[c])"


def test_last_field_leaves_empty_shelf():
    tree = _parse_shelf("[d].[a]")
    assert _render_shelf(_drop_ref(tree, "[d].[a]")) == ""


def test_operator_removed_with_its_term():
    tree = _parse_shelf("([d].[a] + [d].[b] + [d].[c])")
    assert _render_shelf(_drop_ref(tree, "[d].[b]")) == "([d].[a] + [d].[c])"


def test_removes_by_field_name_not_derivation():
    root = _root()
    res = ED.remove_field(root, "Sheet", "GGR", shelf="columns")
    assert res["ok"] and res["removed"] == 1
    assert _shelf(root, "cols") == ""


def test_removes_from_encodings_too():
    root = _root()
    res = ED.remove_field(root, "Sheet", "GGR", shelf="text")
    assert res["removed"] == 1
    assert not [e for e in root.iter("text")]


def test_without_shelf_removes_everywhere():
    root = _root()
    res = ED.remove_field(root, "Sheet", "brand")
    assert res["removed"] == 2
    assert _shelf(root, "rows") == "[federated.x].[none:country:nk]"


def test_field_not_on_shelves_refused():
    root = _root()
    res = ED.remove_field(root, "Sheet", "country", shelf="columns")
    assert res["ok"] is False and "would read as success" in res["why"]


def test_place_and_remove_restores_shelf():
    root = _root()
    before = _shelf(root, "rows")
    ED.place_field(root, "Sheet", "GGR", shelf="rows")
    assert _shelf(root, "rows") != before
    ED.remove_field(root, "Sheet", "GGR", shelf="rows")
    assert _shelf(root, "rows").replace(" ", "") == before.replace(" ", "")

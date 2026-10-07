import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED

_WB = """<workbook version='18.1'>
  <datasources><datasource name='federated.x' version='18.1'>
    <column datatype='string' name='[country]' role='dimension' type='nominal' />
    <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
    <column caption='ARPU' datatype='real' name='[Calculation_1]' role='measure'
            type='quantitative'>
      <calculation class='tableau' formula='SUM([GGR]) / COUNTD([uid])' />
    </column>
  </datasource></datasources>
  <worksheets>
    <worksheet name='Sheet'><table>
      <view>
        <datasources><datasource name='federated.x' /></datasources>
        <datasource-dependencies datasource='federated.x'>
          <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
        </datasource-dependencies>
      </view>
      <style /><panes><pane><view /><mark class='Automatic' />
        <style /></pane></panes><rows /><cols />
    </table></worksheet>
  </worksheets>
</workbook>
"""


def _root():
    return etree.fromstring(_WB.encode("utf-8"))


def _runs(root):
    tip = [t for t in root.iter("customized-tooltip")][0]
    return [(dict(r.attrib), r.text) for r in tip.find("formatted-text")]


def test_field_inserted_in_angle_brackets():
    root = _root()
    res = ED.set_tooltip(root, "Sheet", [{"label": "Country", "field": "country"}])
    assert res["ok"]
    runs = _runs(root)
    assert runs[0] == ({"fontcolor": "#757575"}, "Country:\t")
    assert runs[1] == ({"bold": "true"}, "<[federated.x].[none:country:nk]>")


def test_newline_is_ae_symbol():
    root = _root()
    ED.set_tooltip(root, "Sheet", [{"label": "A", "field": "GGR"},
                                  {"label": "B", "field": "country"}])
    breaks = [t for _, t in _runs(root) if t == "\u00c6\n"]
    assert len(breaks) == 2


def test_measure_and_calculation_get_different_derivations():
    root = _root()
    ED.set_tooltip(root, "Sheet", [{"label": "GGR", "field": "GGR"},
                                  {"label": "ARPU", "field": "ARPU"}])
    vals = [t for a, t in _runs(root) if a.get("bold")]
    assert vals == ["<[federated.x].[sum:GGR:qk]>",
                    "<[federated.x].[usr:Calculation_1:qk]>"]


def test_plain_text_line_without_field():
    root = _root()
    ED.set_tooltip(root, "Sheet", [{"text": "Data for the last 6 months"}])
    assert _runs(root)[0] == ({}, "Data for the last 6 months")


def test_plain_style_without_color_or_bold():
    root = _root()
    ED.set_tooltip(root, "Sheet", [{"label": "GGR", "field": "GGR"}], plain=True)
    assert all(a == {} for a, _ in _runs(root))


def test_missing_field_refused_not_skipped():
    root = _root()
    res = ED.set_tooltip(root, "Sheet", [{"label": "X", "field": "no_such"}])
    assert res["ok"] is False and "no_such" in res["why"]


def test_rebuild_replaces_tooltip():
    root = _root()
    ED.set_tooltip(root, "Sheet", [{"label": "A", "field": "GGR"}])
    ED.set_tooltip(root, "Sheet", [{"label": "B", "field": "country"}])
    assert len([t for t in root.iter("customized-tooltip")]) == 1
    assert _runs(root)[0][1] == "B:\t"


def test_tooltip_inserted_per_schema():
    root = _root()
    ED.set_tooltip(root, "Sheet", [{"label": "A", "field": "GGR"}])
    pane = [p for p in root.iter("pane")][0]
    tags = [c.tag for c in pane]
    assert tags.index("customized-tooltip") < tags.index("style")


def test_empty_list_and_foreign_sheet_refused():
    root = _root()
    assert ED.set_tooltip(root, "Sheet", [])["ok"] is False
    assert ED.set_tooltip(root, "None", [{"field": "GGR"}])["ok"] is False

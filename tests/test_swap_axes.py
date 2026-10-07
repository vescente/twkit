import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED

_WB = """<workbook version='18.1'>
  <datasources><datasource name='federated.x'>
    <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
  </datasource></datasources>
  <worksheets>
    <worksheet name='Sheet'><table>
      <view><datasources><datasource name='federated.x' /></datasources></view>
      <style><style-rule element='cell'>
        <format attr='font-size' scope='rows' value='9' />
        <format attr='color' scope='cols' value='#484848' />
      </style-rule></style>
      <panes><pane><encodings><text column='[federated.x].[sum:GGR:qk]' /></encodings>
        <encoding scope='rows' type='color' /></pane></panes>
      <rows onTop='true' total='true'>[federated.x].[none:Line:nk]</rows>
      <cols>[federated.x].[none:Month:ok]</cols>
    </table></worksheet>
    <worksheet name='Foreign'><table>
      <view />
      <style /><panes><pane /></panes>
      <rows>[federated.x].[none:A:nk]</rows><cols>[federated.x].[none:B:nk]</cols>
    </table></worksheet>
  </worksheets>
</workbook>
"""


def _root():
    return etree.fromstring(_WB.encode("utf-8"))


def _t(root, sheet, tag):
    ws = [w for w in root.iter("worksheet") if w.get("name") == sheet][0]
    return ws.find(f"table/{tag}")


def test_shelves_swap():
    root = _root()
    res = ED.swap_rows_cols(root, ["Sheet"])
    assert res["ok"] and res["sheets_swapped"] == 1
    assert _t(root, "Sheet", "rows").text == "[federated.x].[none:Month:ok]"
    assert _t(root, "Sheet", "cols").text == "[federated.x].[none:Line:nk]"


def test_formatting_moves_to_other_axis():
    root = _root()
    res = ED.swap_rows_cols(root, ["Sheet"])
    got = {(n.tag, n.get("attr") or n.get("type")): n.get("scope")
           for n in root.iter() if n.get("scope")}
    assert got == {("format", "font-size"): "cols",
                   ("format", "color"): "rows",
                   ("encoding", "color"): "cols"}
    assert res["sheets"][0]["formatting_moved"] == 3


def test_top_total_becomes_left_total():
    root = _root()
    ED.swap_rows_cols(root, ["Sheet"])
    rows, cols = _t(root, "Sheet", "rows"), _t(root, "Sheet", "cols")
    assert rows.get("total") is None and rows.get("onTop") is None
    assert cols.get("total") == "true" and cols.get("onLeft") == "true"


def test_foreign_sheet_untouched():
    root = _root()
    ED.swap_rows_cols(root, ["Sheet"])
    assert _t(root, "Foreign", "rows").text == "[federated.x].[none:A:nk]"


def test_without_list_swaps_all_non_empty():
    root = _root()
    assert ED.swap_rows_cols(root)["sheets_swapped"] == 2


def test_sheet_name_typo_refused():
    root = _root()
    res = ED.swap_rows_cols(root, ["Sheett"])
    assert res["ok"] is False and "Sheett" in res["why"]


def test_double_swap_restores():
    root = _root()
    rows = _t(root, "Sheet", "rows")
    before = (rows.text, dict(rows.attrib))
    ED.swap_rows_cols(root, ["Sheet"])
    ED.swap_rows_cols(root, ["Sheet"])
    rows = _t(root, "Sheet", "rows")
    assert (rows.text, dict(rows.attrib)) == before


def test_report_names_shelves_as_placed():
    root = _root()
    res = ED.swap_rows_cols(root, ["Sheet"])
    got = res["sheets"][0]
    assert got["rows"] == _t(root, "Sheet", "rows").text
    assert got["columns"] == _t(root, "Sheet", "cols").text
    assert got["rows"] == "[federated.x].[none:Month:ok]"

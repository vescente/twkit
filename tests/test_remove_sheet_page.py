import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

import pytest
from lxml import etree

from twkit import edit as ED

BOOK = """<workbook>
  <worksheets>
    <worksheet name='Keep'/>
    <worksheet name='Drop'/>
  </worksheets>
  <dashboards>
    <dashboard name='Page'>
      <zones><zone name='Keep'/><zone name='Drop'/></zones>
    </dashboard>
  </dashboards>
  <windows>
    <window class='worksheet' name='Keep'/>
    <window class='worksheet' name='Drop'/>
    <window class='dashboard' name='Page'>
      <viewpoints><viewpoint name='Drop'/></viewpoints>
    </window>
  </windows>
  <actions>
    <action name='a1'><source worksheet='Drop'/><target worksheet='Keep'/></action>
    <action name='a2'><source worksheet='Keep'/><target worksheet='Keep'/></action>
  </actions>
</workbook>"""


def _book():
    return etree.fromstring(BOOK)


def test_sheet_removed_entirely():
    root = _book()
    ED.remove_worksheet(root, "Drop")
    assert [w.get("name") for w in root.iter("worksheet")] == ["Keep"]
    assert [w.get("name") for w in root.iter("window") if w.get("class") == "worksheet"] == ["Keep"]
    assert [z.get("name") for z in root.iter("zone")] == ["Keep"]
    assert [v.get("name") for v in root.iter("viewpoint")] == []


def test_actions_on_removed_sheet_removed():
    root = _book()
    ED.remove_worksheet(root, "Drop")
    assert [a.get("name") for a in root.iter("action")] == ["a2"]


def test_neighbour_sheet_intact():
    root = _book()
    ED.remove_worksheet(root, "Drop")
    assert root.find(".//worksheet[@name='Keep']") is not None


def test_page_removed_with_window_sheets_kept():
    root = _book()
    ED.remove_dashboard(root, "Page")
    assert root.find(".//dashboard") is None
    assert [w.get("name") for w in root.iter("window") if w.get("class") == "dashboard"] == []
    assert {w.get("name") for w in root.iter("worksheet")} == {"Keep", "Drop"}


def test_missing_name_is_error_not_zero():
    root = _book()
    with pytest.raises(ValueError):
        ED.remove_worksheet(root, "No such")
    with pytest.raises(ValueError):
        ED.remove_dashboard(root, "No such")

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED


def _pane(order):
    kids = "".join(f"<{t}/>" for t in order)
    return etree.fromstring(f"<workbook><worksheets><worksheet><table><panes>"
                            f"<pane>{kids}</pane></panes></table></worksheet></worksheets></workbook>")


def _tags(root):
    return [c.tag for c in root.find(".//pane")]


def test_encodings_moved_before_style():
    root = _pane(["view", "mark", "style", "encodings"])
    assert ED.repair_node_order(root)["panes_fixed"] == 1
    assert _tags(root) == ["view", "mark", "encodings", "style"]


def test_correct_order_untouched():
    root = _pane(["view", "mark", "encodings", "style"])
    assert ED.repair_node_order(root)["panes_fixed"] == 0
    assert _tags(root) == ["view", "mark", "encodings", "style"]


def test_full_set_becomes_canonical():
    root = _pane(["view", "style", "customized-label", "encodings", "mark",
                  "mark-sizing", "customized-tooltip"])
    ED.repair_node_order(root)
    assert _tags(root) == ["view", "mark", "mark-sizing", "encodings",
                           "customized-tooltip", "customized-label", "style"]


def test_foreign_nodes_kept():
    root = _pane(["view", "mark", "style", "encodings"])
    root.find(".//pane").append(etree.Element("something-custom"))
    ED.repair_node_order(root)
    assert "something-custom" in _tags(root)

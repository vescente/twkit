import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED


def _book(attr):
    return etree.fromstring(
        f"<workbook><worksheets><worksheet><style><style-rule>"
        f"<format attr='{attr}' value='10'/></style-rule></style></worksheet></worksheets></workbook>")


def test_allowlist_taken_from_corpus():
    assert "font-size" in ED.FORMAT_ATTRS
    assert "font-weight" in ED.FORMAT_ATTRS
    assert "background-color" in ED.FORMAT_ATTRS
    assert "fontsize" not in ED.FORMAT_ATTRS
    assert "scope" not in ED.FORMAT_ATTRS


def test_invented_attribute_removed():
    root = _book("fontsize")
    assert ED.strip_invalid_formats(root)["removed"] == 1
    assert root.find(".//format") is None


def test_correct_attribute_kept():
    root = _book("font-size")
    assert ED.strip_invalid_formats(root)["removed"] == 0
    assert root.find(".//format") is not None


def test_bad_attribute_named():
    root = _book("fontname")
    assert ED.strip_invalid_formats(root)["attributes"] == ["fontname"]


def test_known_mistake_fixed_not_dropped():
    root = _book("font-color")
    assert ED.fix_format_attrs(root)["renamed"] == {"font-color": "color"}
    assert root.find(".//format").get("attr") == "color"


def test_hint_names_correct_name():
    assert ED.format_attr_hint("font-color") == "color"
    assert ED.format_attr_hint("line-width") == "stroke-size"
    assert ED.format_attr_hint("bordercolor") == "border-color"
    assert ED.format_attr_hint("not-an-attribute-at-all") == ""


def test_lint_prints_wrong_right_pair():
    from twkit import lint as LN

    class _B:
        pass

    b = _B()
    b.root = _book("line-width")
    (v,) = LN.r_format_attr(b)
    assert "line-width → stroke-size" in v.message
    assert "fix_format_attrs" in v.fix

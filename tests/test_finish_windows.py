import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

from lxml import etree

from twkit import edit as ED
from twkit import lint as LINT


def _tree(xml: str):
    return etree.fromstring(xml.encode()).getroottree().getroot()


def _draft():
    return _tree("""<workbook>
      <worksheets>
        <worksheet name='KPI - BAN'/>
        <worksheet name='KPI - spark'/>
        <worksheet name='Table'/>
      </worksheets>
      <dashboards>
        <dashboard name='OVERVIEW'><zones>
          <zone id='1' type-v2='layout-flow' param='vert'>
            <zone id='2' name='KPI - BAN'/>
            <zone id='3' name='KPI - spark'/>
          </zone></zones></dashboard>
        <dashboard name='REVENUE'><zones>
          <zone id='1' type-v2='layout-flow' param='vert'>
            <zone id='2' name='Table'/>
          </zone></zones></dashboard>
      </dashboards>
      <windows>
        <window class='worksheet' name='KPI - BAN'/>
        <window class='worksheet' name='KPI - spark'/>
        <window class='worksheet' name='Table'/>
        <window class='dashboard' name='OVERVIEW'/>
        <window class='dashboard' name='REVENUE'/>
      </windows></workbook>""")


def _names(root):
    return [(w.get("class"), w.get("name")) for w in root.find("windows")]


def test_dashboard_becomes_first_and_maximized():
    root = _draft()
    got = ED.finish_windows(root)

    assert got["first"] == "OVERVIEW"
    wins = list(root.find("windows"))
    assert wins[0].get("class") == "dashboard", _names(root)
    assert wins[0].get("maximized") == "true"
    assert wins[1].get("name") == "REVENUE"


def test_first_dashboard_can_be_named():
    root = _draft()
    got = ED.finish_windows(root, first_dashboard="REVENUE")

    assert got["first"] == "REVENUE"
    assert list(root.find("windows"))[0].get("name") == "REVENUE"
    dash = [w for w in root.find("windows") if w.get("class") == "dashboard"]
    assert [w.get("maximized") for w in dash].count("true") == 1


def test_only_page_sheets_hidden():
    root = _draft()
    etree.SubElement(root.find("worksheets"), "worksheet", name="Raw")
    etree.SubElement(root.find("windows"), "window", {"class": "worksheet", "name": "Raw"})

    got = ED.finish_windows(root)

    assert got["hidden"] == 3
    hidden = {x.get("name") for x in root.find("windows") if x.get("hidden") == "true"}
    assert hidden == {"KPI - BAN", "KPI - spark", "Table"}
    assert "Raw" not in hidden


def test_repeat_call_is_safe():
    root = _draft()
    ED.finish_windows(root)
    before = _names(root)
    got = ED.finish_windows(root)

    assert got["hidden"] == 0
    assert _names(root) == before


def test_book_without_dashboards_untouched():
    root = _tree("""<workbook><windows>
        <window class='worksheet' name='A'/></windows></workbook>""")
    got = ED.finish_windows(root)

    assert got["hidden"] == 0 and "why" in got
    assert list(root.find("windows"))[0].get("hidden") is None


class _B:

    def __init__(self, root):
        self.root = root


def _r33(root):
    return LINT.r33_opens_on_worksheet(_B(root))


def test_r33_detects_draft():
    got = _r33(_draft())
    assert len(got) == 1
    assert got[0].rule == "R33" and got[0].severity == LINT.WARN
    assert "KPI - BAN" in got[0].message, got[0].message


def test_r33_silent_after_fix():
    root = _draft()
    ED.finish_windows(root)
    assert _r33(root) == []


def test_r33_silent_on_corpus_books():
    a = _draft()
    [w for w in a.find("windows") if w.get("class") == "dashboard"][0].set("maximized", "true")
    assert _r33(a) == []

    b = _draft()
    wins = b.find("windows")
    d = [w for w in wins if w.get("class") == "dashboard"][0]
    wins.remove(d)
    wins.insert(0, d)
    assert _r33(b) == []


def test_axis_title_does_not_unhide_axis():
    root = _tree("""<workbook><worksheets><worksheet name='Spark'><table>
        <style>
          <style-rule element='axis'>
            <format attr='display' value='false'/>
          </style-rule>
        </style></table></worksheet></worksheets></workbook>""")

    assert ED.hide_axis_titles(root, ['Spark']) == 1

    rules = [r for r in root.iter('style-rule') if r.get('element') == 'axis']
    assert len(rules) == 1, 'one axis rule expected'
    attrs = {f.get('attr'): f.get('value') for f in rules[0].findall('format')}
    assert attrs.get('display') == 'false', 'axis hiding lost'
    assert attrs.get('title') == '', 'axis title not removed'

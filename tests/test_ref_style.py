import os
import sys

from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from twkit import style as S


class FakeEditor:

    def __init__(self):
        self.root = etree.Element("workbook")
        dss = etree.SubElement(self.root, "datasources")
        self.ds = etree.SubElement(dss, "datasource")
        self.ds.set("name", "federated.x")
        col = etree.SubElement(self.ds, "column", datatype="string", name="[region]",
                               role="dimension", type="nominal")
        del col
        wss = etree.SubElement(self.root, "worksheets")
        self.ws = etree.SubElement(wss, "worksheet")
        self.ws.set("name", "t")
        table = etree.SubElement(self.ws, "table")
        view = etree.SubElement(table, "view")
        etree.SubElement(view, "datasources")
        panes = etree.SubElement(table, "panes")
        etree.SubElement(panes, "pane")
        wsds = etree.SubElement(self.ws, "datasource")
        wsds.set("name", "federated.x")

    def sheet(self, name):
        return self.ws


def test_filter_card_lives_in_table_not_view():
    ed = FakeEditor()
    S.filter_cards(ed, "t", {"region": "Region"})
    assert ed.ws.find("table/style") is not None
    assert ed.ws.find("table/view/style") is None
    rule = ed.ws.find("table/style/style-rule")
    assert rule.get("element") == "quick-filter"
    attrs = {f.get("attr"): f.get("value") for f in rule.findall("format")}
    assert attrs["border-color"] == S.PARAM_CARD["border-color"]
    assert attrs["background-color"] == S.PARAM_CARD["background-color"]
    assert attrs["border-width"] == "2"


def test_period_title_references_parameters_in_angle_brackets():
    ed = FakeEditor()
    S.period_title(ed, "t", [("p_a", "p_b")], label="All segments")
    runs = [r.text for r in ed.ws.findall("layout-options/title/formatted-text/run")]
    assert runs[0].startswith("All segments")
    assert "<" in runs and ">" in runs
    assert "[Parameters].[p_a]" in runs and "[Parameters].[p_b]" in runs


def test_parameter_card_written_on_dashboard():
    ed = FakeEditor()
    dbs = etree.SubElement(ed.root, "dashboards")
    dash = etree.SubElement(dbs, "dashboard")
    dash.set("name", "D")
    etree.SubElement(dash, "zones")
    assert S.param_cards(ed, "D") == 4
    rule = dash.find("style/style-rule")
    assert rule.get("element") == "parameter-ctrl"
    tags = [c.tag for c in dash]
    assert tags.index("style") < tags.index("zones")


def test_value_color_set_in_encodings():
    ed = FakeEditor()
    assert S.trend_color(ed, "t") is True
    color = ed.ws.find("table/panes/pane/encodings/color")
    assert color.get("column") == "[federated.x].[Multiple Values]"


def test_muted_tones_not_traffic_light():
    for hexc in S.TREND_COLORS.values():
        r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
        assert max(r, g, b) - min(r, g, b) < 100, hexc
        assert max(r, g, b) < 200, hexc


def _text_ws():
    return etree.fromstring(
        "<worksheet name='t'><table><view/><style><style-rule element='cell'>"
        "<format attr='font-size' value='12'/></style-rule></style><panes/></table></worksheet>")


def test_row_bands_three_rules_scoped_to_rows_and_idempotent():
    ws = _text_ws()
    S.row_bands(ws)
    S.row_bands(ws, "#eef1f3")
    got = sorted((r.get("element"), f.get("attr"), f.get("scope"), f.get("value"))
                 for r in ws.iter("style-rule") for f in r.findall("format")
                 if f.get("attr") in ("band-color", "band-size"))
    assert got == [("header", "band-color", "rows", "#eef1f3"),
                   ("pane", "band-color", "rows", "#eef1f3"),
                   ("table", "band-size", "rows", "1")]


def test_uniform_type_one_family_and_size_first_in_every_rule():
    ws = _text_ws()
    S.uniform_type(ws)
    S.uniform_type(ws)
    for el in ("cell", "header", "label"):
        rule = next(r for r in ws.iter("style-rule") if r.get("element") == el)
        fonts = [(f.get("attr"), f.get("value")) for f in rule.findall("format")]
        assert fonts[:2] == [("font-family", "Tableau Book"), ("font-size", "10")], (el, fonts)
        assert len(fonts) == 2, (el, fonts)
    tbl = ws.find("table")
    assert [c.tag for c in tbl].index("style") < [c.tag for c in tbl].index("panes")

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import frame as FR


def test_tableau_masks():
    f = FR.fmt_mask
    assert f(0.756, "p0%") == "76%"
    assert f(4938, 'c"€ "#,##0,K;"€ "-#,##0,K') == "€ 5K"
    assert f(-0.12, "*↑ #,##0.0%;↓ #,##0.0%; ") == "↓ 12.0%"
    assert f(0, "*↑ #,##0.0%;↓ #,##0.0%; ") == ""
    assert f(-500, 'c"€ "#,##0;("€ "#,##0)') == "(€ 500)"
    assert f(1234567, "n#,##0;-#,##0") == "1,234,567"
    assert f(2.5, "n#,##0;-#,##0") == "3"
    assert f("abc", "p0%") is None


_WB = """<workbook><datasources>
  <datasource name='Parameters'><column caption='ListParam' name='[Parameter 1]' value='"ACT NOW"'/></datasource>
  <datasource name='federated.x'>
    <column caption='Swap A' name='[Calc_A]'><calculation class='tableau' formula="IF [Parameters].[Parameter 1] = 'ACT NOW' THEN 'show' ELSE 'hide' END"/></column>
    <column caption='Swap B' name='[Calc_B]'><calculation class='tableau' formula="IF [Parameters].[Parameter 1] = 'CRITICAL' THEN 'show' ELSE 'hide' END"/></column>
  </datasource></datasources>
  <dashboards><dashboard name='D'><size maxheight='400' maxwidth='600' minheight='400' minwidth='600'/>
   <zones><zone h='100000' id='1' type-v2='layout-flow' param='vert' w='100000' x='0' y='0'>
     <zone h='50000' id='2' name='A' w='100000' x='0' y='0'/>
     <zone h='50000' id='3' name='B' w='100000' x='0' y='50000'/>
   </zone></zones></dashboard></dashboards></workbook>"""


def test_sheet_swap_like_tableau():
    root = etree.fromstring(_WB.encode())
    assert FR._swap_state(root) == {"A": True, "B": False}
    html = FR._page_html("D", root.find(".//dashboard"), {}, {}, "t", root)
    assert "data-name='A'" in html and "data-name='B'" not in html
    assert "top:0px;width:600px;height:400px" in html


def test_page_has_model_stamp():
    root = etree.fromstring(_WB.encode())
    html = FR._page_html("D", root.find(".//dashboard"), {}, {}, "t", root)
    assert "a model, not Tableau" in html


def test_color_map_as_tableau_applies():
    from lxml import etree as ET
    from twkit.frame import color_map, _render_bars
    xml = b"""<workbook><datasources><datasource name='federated.x'>
      <column name='[Calc]' datatype='string' role='dimension' type='nominal'/>
      <style><style-rule element='mark'><encoding attr='color' field='[none:Calc:nk]' type='palette'>
        <map to='#4e79a7'><bucket>"In"</bucket></map><map to='#bab0ac'><bucket>"Out"</bucket></map>
      </encoding></style-rule></style></datasource></datasources>
      <worksheets><worksheet name='W'><table><panes><pane><encodings>
        <color column='[federated.x].[none:Calc:nk]'/></encodings></pane></panes></table></worksheet></worksheets></workbook>"""
    root = ET.fromstring(xml)
    ws = root.find(".//worksheet")
    assert color_map(root, ws) == {}
    rows = [["Australia", "In", 59], ["Rest", "Out", 25]]
    assert "#f28e2b" in _render_bars(rows, 2, "n", cmap=color_map(root, ws))
    ET.SubElement(root.find(".//datasource"), "column-instance", column="[Calc]",
                  derivation="None", name="[none:Calc:nk]", pivot="key", type="nominal")
    cm = color_map(root, ws)
    assert cm == {"In": "#4e79a7", "Out": "#bab0ac"}
    assert "#bab0ac" in _render_bars(rows, 2, "n", cmap=cm)


def test_manual_order_like_tableau():
    from lxml import etree as ET
    from twkit.frame import manual_order
    ws = ET.fromstring(b"""<worksheet name='S'><table><view><manual-sort column='[d].[none:dim_1:nk]'>
      <dictionary><bucket>"HIGH"</bucket><bucket>"CRITICAL"</bucket><bucket>"LOW"</bucket></dictionary>
      </manual-sort></view></table></worksheet>""")
    rows = [["CRITICAL", 1], ["LOW", 2], ["HIGH", 3]]
    assert [r[0] for r in manual_order(ws, rows, 1)] == ["HIGH", "CRITICAL", "LOW"]


def test_window_size_by_canvas():
    from twkit.frame import canvas_size, CSS
    page = f"<style>{CSS}</style><div class='canvas' data-page='P' style='width:1400px;height:1389px'>"
    m = canvas_size(page)
    assert (int(m.group(1)), int(m.group(2))) == (1400, 1389)


def test_zone_and_mark_text_like_tableau():
    from lxml import etree as ET
    from twkit.frame import _runs_html, _mark_text_color
    ze = ET.fromstring(b"<zone><formatted-text><run bold='true' fontalignment='1' "
                       b"fontcolor='#111e29' fontsize='12'>TITLE</run></formatted-text></zone>")
    h = _runs_html(ze)
    assert "text-align:center" in h and "font-size:16px" in h and "font-weight:700" in h
    ws = ET.fromstring(b"<worksheet><table><style><format attr='color' value='#000000'/></style>"
                       b"<panes><pane><customized-label><formatted-text><run fontcolor='#e15759'>x"
                       b"</run></formatted-text></customized-label></pane></panes></table></worksheet>")
    assert _mark_text_color(ws) == "#e15759"


def test_mask_with_divider_and_sheet_mask():
    from twkit.frame import fmt_mask
    assert fmt_mask(733215.4, 'c"$"#,##0,.0K;-"$"#,##0,.0K') == "$733.2K"
    assert fmt_mask(733215.4, 'c"€ "#,##0,K;"€ "-#,##0,K') == "€ 733K"
    assert fmt_mask(1234, "n#,##0;-#,##0") == "1,234"


def test_tableau_paragraph_marker_not_printed():
    from lxml import etree as ET
    from twkit.frame import _runs_html
    ze = ET.fromstring("<zone><formatted-text><run>SalesÆ\n</run></formatted-text></zone>".encode())
    assert "Æ" not in _runs_html(ze)


_FIT_WB = """<workbook><datasources><datasource name='federated.x'/></datasources>
<worksheets><worksheet name='T'><table><view/><panes><pane><mark class='Text'/><encodings>
<text column='[federated.x].[sum:v:qk]'/></encodings></pane></panes>
<rows>[federated.x].[none:d:nk]</rows><cols/></table></worksheet></worksheets>
<dashboards><dashboard name='D'><size maxheight='400' maxwidth='600' minheight='400' minwidth='600'/>
<zones><zone h='100000' id='1' type-v2='layout-flow' param='horz' w='100000' x='0' y='0'>
<zone h='100000' id='2' name='T' w='100000' x='0' y='0'/></zone></zones></dashboard></dashboards>
<windows><window class='dashboard' name='D'><viewpoints><viewpoint name='T'>%s</viewpoint></viewpoints>
</window><window class='worksheet' name='T'><viewpoint><zoom type='fit-width'/></viewpoint></window></windows></workbook>"""


def test_text_table_entire_view_splits_height():
    data = {"T": {"rows": [[f"r{i}", i] for i in range(80)], "ndims": 1, "captions": ["d", "v"],
                  "masks": ["", ""], "refs": ["[none:d:nk]"], "mrefs": ["[sum:v:qk]"]}}

    def page(zoom):
        root = etree.fromstring((_FIT_WB % zoom).encode())
        sheets = {"T": root.find(".//worksheet")}
        return root, FR._page_html("D", root.find(".//dashboard"), sheets, data, "t", root)
    root, html = page("<zoom type='entire-view'/>")
    assert FR.zone_fits(root, "D") == {"T": "entire-view"}
    assert "data-fit='entire-view'" in html and "class='fitv'" in html
    assert "--rh" in html and "squashed" in html
    for zoom, fit in (("", "standard"), ("<zoom type='fit-width'/>", "fit-width")):
        root, html = page(zoom)
        assert FR.zone_fits(root, "D") == {"T": fit}
        assert f"data-fit='{fit}'" in html and "class='fitv'" not in html
    assert FR.fit_rows("<div class='bar'></div>", "bar", "entire-view").startswith("<div class='bar'")
    assert FR.fit_rows("<table><tr><td>1</td></tr></table>", "mlist", "fit-height").startswith(
        "<div class='fitv' data-fit='fit-height'>")


def test_custom_tooltip_is_shown_on_hover_with_first_mark_values():
    tip = ("<customized-tooltip><formatted-text><run fontcolor='#757575'>Sales:\t</run>"
           "<run bold='true'>&lt;[federated.x].[sum:v:qk]&gt;</run><run>Æ\n</run>"
           "</formatted-text></customized-tooltip>")
    root = etree.fromstring((_FIT_WB % "").replace("</encodings></pane>", "</encodings>" + tip + "</pane>").encode())
    data = {"T": {"rows": [["a", 1234], ["b", 5]], "ndims": 1, "captions": ["d", "v"],
                  "masks": ["", ""], "refs": ["[none:d:nk]"], "mrefs": ["[sum:v:qk]"]}}
    html = FR._page_html("D", root.find(".//dashboard"), {"T": root.find(".//worksheet")}, data, "t", root)
    assert "data-tooltip='1'" in html
    assert re.search(r"title='Sales:\s+1,234'", html), re.findall(r"title='[^']*'", html)

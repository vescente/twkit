from lxml import etree

from twkit import frame as FR


def _button(index=None):
    b = etree.fromstring("<button action=''><toggle-action>tabdoc:toggle-button-click-action "
                         "zone-ids=[30]</toggle-action><button-visual-state/><button-visual-state/></button>")
    if index is not None:
        b.set("active-visual-state-index", index)
    return b


def test_show_hide_button_draws_tableau_icons():
    assert "✕" in FR._button_html(_button(), {})        # item shown: the button hides it
    assert "≡" in FR._button_html(_button("1"), {})     # item hidden: the button shows it


def test_button_caption_wins_over_icon():
    b = _button("1")
    etree.SubElement(b.findall("button-visual-state")[1], "caption").text = "Show chart"
    html = FR._button_html(b, {})
    assert "Show chart" in html and "≡" not in html


_WS = """<worksheet name='T'><table><style>
  <style-rule element='quick-filter'>
    <format attr='title' field='[ds].[none:Level 1 Dim:nk]' value='Filter Level 1'>
      <formatted-text><run>Filter Level 1</run></formatted-text>
    </format>
  </style-rule></style><view/></table></worksheet>"""


def test_filter_card_title_comes_from_the_sheet_style():
    ws = etree.fromstring(_WS)
    own = FR._quick_filter_title(ws, "[ds].[none:Level 1 Dim:nk]")
    assert own is not None and own.get("value") == "Filter Level 1"
    assert FR._quick_filter_title(ws, "[ds].[none:Level 2 Dim:nk]") is None


_BOOK = """<workbook><shared-views>
  <shared-view name='ds'>
    <filter class='relative-date' column='[ds].[none:dt:qk]' first-period='-4' include-future='true'
            last-period='0' period-type-v2='week'/>
  </shared-view>
  <shared-view name='other'>
    <filter class='relative-date' column='[other].[none:dt:qk]' first-period='0' last-period='0'
            period-type-v2='day'/>
  </shared-view></shared-views></workbook>"""


def test_relative_date_card_reads_the_shared_filter_of_its_source():
    root = etree.fromstring(_BOOK)
    ws = etree.fromstring(_WS)
    assert FR._filter_state(ws, "[ds].[none:dt:qk]", root) == "Last 5 weeks"
    assert FR._filter_state(ws, "[other].[none:dt:qk]", root) == "Today"


def test_relative_date_wording():
    f = lambda a, b, u: FR._relative_date_text(etree.fromstring(
        f"<filter first-period='{a}' last-period='{b}' period-type-v2='{u}'/>"))
    assert f(-2, 0, "month") == "Last 3 months"
    assert f(0, 0, "week") == "This week"
    assert f(-1, -1, "year") == "Previous year"
    assert f(-1, -1, "day") == "Yesterday"


_SORTED = """<worksheet name='T'><table><view>
  <computed-sort column='[ds].[none:Region:nk]' direction='DESC' using='[ds].[sum:Regs:qk]'/>
  <computed-sort column='[ds].[none:Source:nk]' direction='ASC' using='[ds].[sum:Regs:qk]'/>
</view></table></worksheet>"""


def test_sort_by_measure_orders_members_inside_their_parent():
    rows = [("Asia", "Organic", 5), ("Asia", "SEO", 1), ("CIS", "Organic", 9), ("CIS", "SEO", 4),
            ("Europe", "Organic", 2)]
    got = FR.computed_order(etree.fromstring(_SORTED), rows, 2,
                            ["[none:Region:nk]", "[none:Source:nk]"], ["[sum:Regs:qk]"])
    # regions by their total, descending: CIS 13, Asia 6, Europe 2; sources ascending inside each
    assert got == [("CIS", "SEO", 4), ("CIS", "Organic", 9), ("Asia", "SEO", 1),
                   ("Asia", "Organic", 5), ("Europe", "Organic", 2)]


def test_sort_by_a_measure_the_view_lacks_keeps_the_order():
    rows = [("b", 1), ("a", 2)]
    ws = etree.fromstring("<worksheet><table><view><computed-sort column='[ds].[none:X:nk]' "
                          "direction='DESC' using='[ds].[max:Other:qk]'/></view></table></worksheet>")
    assert FR.computed_order(ws, rows, 1, ["[none:X:nk]"], ["[sum:Y:qk]"]) == rows


from twkit import render as R


_DASH = """<dashboard name='D'><size maxheight='500' maxwidth='1000' minheight='500' minwidth='1000'/>
<zones><zone id='1' type-v2='layout-flow' param='horz' x='0' y='0' w='100000' h='100000'>
  <zone id='3' name='table' x='0' y='0' w='100000' h='100000'/>
  <zone id='30' type-v2='layout-flow' param='horz' hidden-by-user='true' x='50000' y='0' w='50000' h='100000'>
    <zone id='31' name='chart' hidden-by-user='true' x='50000' y='0' w='40000' h='100000'/>
    <zone id='33' name='chart' type-v2='color' hidden-by-user='true' x='90000' y='0' w='10000' h='100000'/>
  </zone></zone>
  <zone id='34' type-v2='dashboard-object' x='97000' y='0' w='2000' h='3000'>
    <button action='' active-visual-state-index='1'><toggle-action>tabdoc:toggle-button-click-action
      zone-id='34' zone-ids=[30]</toggle-action><button-visual-state/><button-visual-state/></button>
  </zone></zones></dashboard>"""


def test_clicked_show_button_opens_the_item_and_neighbours_share_the_rest():
    dash = etree.fromstring(_DASH)
    tree = R._build_tree(dash, 1000, 500)
    assert FR.expand_toggles(dash, tree) == {"34"}
    z = {n.id: n for t in tree for n in t.walk()}
    assert not z["30"].hidden and not z["31"].hidden and not z["33"].hidden
    assert (round(z["3"].x), round(z["3"].w)) == (0, 500)          # the table gives up half
    assert (round(z["30"].x), round(z["30"].w)) == (500, 500)      # the chart keeps its size
    assert (round(z["31"].x), round(z["33"].x)) == (500, 900)      # its legend moves with it


def test_clicked_button_draws_the_hide_icon():
    b = etree.fromstring(_DASH).find(".//button")
    assert "≡" in FR._button_html(b, {}) and "✕" in FR._button_html(b, {}, opened=True)


def test_empty_value_takes_the_null_colour():
    assert FR._CMap({"%null%": "#7fa6a8"}).get("None") == "#7fa6a8"


_ROOT = """<workbook><datasources><datasource name='ds'>
  <column name='[Period]' datatype='date'/><column name='[Level]' datatype='string'/>
  <style><style-rule element='mark'><encoding attr='color' field='[:Measure Names]' type='palette'>
    <map to='#9e3d22'><bucket>"[ds].[usr:line:qk]"</bucket></map></encoding></style-rule></style>
</datasource></datasources></workbook>"""
_TREND = """<worksheet name='T'><table><panes>
  <pane id='1' y-axis-name='[ds].[usr:bar:qk]'><mark class='Bar'/></pane>
  <pane id='2' y-axis-name='[ds].[usr:line:qk]'><mark class='Automatic'/>
    <encodings><color column='[ds].[:Measure Names]'/></encodings></pane>
</panes></table></worksheet>"""


def test_second_axis_takes_its_measure_colour():
    assert FR.measure_names_color(etree.fromstring(_ROOT), etree.fromstring(_TREND), "[usr:line:qk]") == "#9e3d22"
    assert FR.measure_names_color(etree.fromstring(_ROOT), etree.fromstring(_TREND), "[usr:bar:qk]") is None


def test_automatic_mark_over_a_date_is_a_line():
    root = etree.fromstring(_ROOT)
    assert FR._is_date_ref(root, None, "[none:Period:ok]")
    assert not FR._is_date_ref(root, None, "[none:Level:nk]")


def test_stacked_columns_read_the_bar_measure_not_the_last_column():
    rows = [["2026-10-01", "Asia", "289", "22.8"], ["2026-10-01", "CIS", "100", "18.0"]]
    html = FR._render_cols(rows, 2, "FTD", "", 300, color_i=1, stack=True, vi=2)
    assert ">289<" in html and ">22.8<" not in html


def test_grand_total_takes_the_sheet_label():
    ws = etree.fromstring("<worksheet><table><style><style-rule element='header'>"
                          "<format attr='total-label' data-class='total' field='[ds].[none:A:nk]' "
                          "value='Total'/></style-rule></style></table></worksheet>")
    assert FR.total_label(ws) == "Total"
    assert FR.total_label(etree.fromstring("<worksheet/>")) == "Grand Total"


def test_dashboard_title_zone_shows_the_dashboard_name():
    assert ">GEO<" in FR._dashboard_title_html(etree.fromstring("<dashboard name='GEO'/>"), "GEO")


class _Z:
    def __init__(self, kind, param="", name="S", h=80.0):
        self.kind, self.param, self.name, self.h = kind, param, name, h


def test_control_modes():
    root = etree.fromstring("""<workbook><datasources><datasource name='Parameters'>
      <column caption='Period' name='[p]' param-domain-type='list' datatype='string'><members>
        <member value='&quot;daily&quot;'/><member value='&quot;weekly&quot;'/></members></column>
      </datasource></datasources></workbook>""")
    z = _Z("paramctrl", "[Parameters].[p]")
    lst = FR._control_html(z, etree.fromstring("<zone mode='list'/>"), root, {}, "weekly", 80)
    assert "&#9675; daily" in lst and "&#9673; weekly" in lst
    assert "▾" not in FR._control_html(z, etree.fromstring("<zone mode='type_in'/>"), root, {}, "5", 40)
    assert "border-radius:50%" in FR._control_html(z, etree.fromstring("<zone mode='slider'/>"), root, {}, "5", 40)
    assert "▾" in FR._control_html(z, etree.fromstring("<zone/>"), root, {}, "daily", 40)


def test_card_style_from_sheet_and_dashboard():
    ws = etree.fromstring("<worksheet><table><style><style-rule element='quick-filter'>"
                          "<format attr='background-color' value='#f0f7fa'/><format attr='border-style' value='solid'/>"
                          "<format attr='border-width' value='2'/><format attr='border-color' value='#75a1c7'/>"
                          "</style-rule></style></table></worksheet>")
    dash = etree.fromstring("<dashboard><style><style-rule element='parameter-ctrl'>"
                            "<format attr='background-color' value='#eeeeee'/></style-rule></style></dashboard>")
    assert FR._card_css("filter", ws, dash) == "background:#f0f7fa;border:2px solid #75a1c7;"
    assert FR._card_css("paramctrl", ws, dash) == "background:#eeeeee;"


def test_table_borders_from_sheet_style():
    ws = etree.fromstring("<worksheet><table><style>"
                          "<style-rule element='header'><format attr='border-style' value='none'/></style-rule>"
                          "<style-rule element='cell'><format attr='border-style' value='solid'/>"
                          "<format attr='border-color' value='#d0d0d0'/>"
                          "<format attr='border-color' scope='cols' value='#eeeeee'/></style-rule>"
                          "</style></table></worksheet>")
    assert FR.border_css(ws, ("header",)) == "border-bottom:none;"
    assert FR.border_css(ws, ("cell", "pane")) == "border-bottom:1px solid #d0d0d0;border-right:1px solid #eeeeee;"

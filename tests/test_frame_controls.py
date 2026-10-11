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

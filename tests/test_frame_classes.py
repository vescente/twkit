import re
import xml.etree.ElementTree as ET  # noqa: S405

from twkit import dryrun as D
from twkit import frame as F
from twkit import render as R


def _ws(xml: str):
    return ET.fromstring(xml)  # noqa: S314


KPI = """<worksheet name='k'><table><view/><style>
<style-rule element='cell'><format attr='font-size' field='[ds].[usr:v:qk]' value='48'/>
<format attr='font-family' field='[ds].[usr:v:qk]' value='Tableau Bold'/></style-rule>
<style-rule element='label'><format attr='display' field='[ds].[none:a:nk]' value='false'/>
<format attr='display' field='[ds].[none:b:nk]' value='false'/></style-rule></style>
<panes><pane><mark class='Automatic'/><encodings><text column='[ds].[usr:v:qk]'/></encodings>
</pane></panes><rows>([ds].[none:a:nk] / [ds].[none:b:nk])</rows><cols/></table></worksheet>"""


def test_hidden_headers_make_kpi_bigtext():
    ws = _ws(KPI)
    assert F._all_headers_hidden(ws)
    html = F._render_bigtext(ws, [["Senior", "Ed", "1.284"]], 2, ["", "", "p0.0%"],
                             ["[usr:v:qk]"])
    assert "128.4%" in html and "font-size:64px" in html and "Tableau Bold" in html


def test_icu_month_letter_and_number():
    assert F.fmt_date("7", "iLLLLL") == "J"
    assert F.fmt_date("2025-07-01 00:00:00", "iMMM yy") == "Jul 25"


def test_axis_measure_moved_last():
    ws = _ws("<worksheet><table><rows>([ds].[usr:p:qk] + [ds].[usr:q:qk])</rows>"
             "<cols>[ds].[my:d:ok]</cols></table></worksheet>")
    rows, caps, _ = F.axis_measure_last([["2025-07", "0.59", "True"]], 1, ["d", "p", "flag"],
                                        ["", "", ""], ["[usr:p:qk]", "[usr:flag:nk]"], ws)
    assert rows[0][-1] == "0.59" and caps[-1] == "p"


def test_hidden_zone_subtree_not_walked():
    dash = _ws("<dashboard><zones><zone id='1' x='0' y='0' w='100000' h='100000'>"
               "<zone id='2' hidden-by-user='true' x='0' y='0' w='100' h='100'>"
               "<zone id='3' type-v2='text' x='0' y='0' w='10' h='10'/></zone>"
               "<zone id='4' type-v2='text' x='0' y='0' w='10' h='10'/></zone></zones></dashboard>")
    tree = R._build_tree(dash, 100, 100)
    ids = [z.id for top in tree for z, _ in F._walk_parent(top)]
    assert ids == ["1", "4"]


def test_date_part_dimension_not_raw_date():
    assert D.date_part_sql("hyper", D._PART_SQL["yr"], '"d"') == 'CAST(EXTRACT(YEAR FROM "d") AS BIGINT)'
    assert D._DISCRETE_TRUNC["my"] == "month"


def test_sheet_title_visible_by_default():
    shown = R.RZone(_ws("<zone id='1' name='Sales' x='0' y='0' w='10' h='10'/>"), 100, 100)
    hidden = R.RZone(_ws("<zone id='2' name='Sales' show-title='false' x='0' y='0' w='10' h='10'/>"),
                     100, 100)
    text = R.RZone(_ws("<zone id='3' type-v2='text' x='0' y='0' w='10' h='10'/>"), 100, 100)
    assert shown.title and not hidden.title and not text.title


def test_title_runs_substitute_parameter_and_sheet_name():
    ws = _ws("<worksheet name='w'><layout-options><title><formatted-text>"
             "<run fontsize='12'>Top States by &lt;[Parameters].[Parameter 2]&gt; · &lt;Sheet Name&gt;</run>"
             "</formatted-text></title></layout-options></worksheet>")
    html = F._title_html(ws, "w", {"Parameter 2": "Sales"}, {})
    assert "Top States by Sales · w" in html and "font-size:16px" in html


def test_default_date_by_renderer_locale():
    F._SEP["locale"] = "en_US"
    try:
        assert F._fmt("2025-12-18 08:00:00") == "12/18/2025 8:00:00 AM"
        assert F._fmt("2025-12-01 00:00:00") == "12/1/2025"
    finally:
        F._SEP["locale"] = ""
    assert F._fmt("2025-12-18 08:00:00") == "18/12/2025 08:00:00"


def test_mask_groups_digits_only_when_pattern_has_them():
    assert F.fmt_mask("2022", "n0;-0") == "2022"
    assert F.fmt_mask("733215.4", "n#,##0;-#,##0") == "733,215"


def test_control_custom_title_and_filter_caption():
    root = _ws("<workbook><datasources><datasource name='ds'><column name='[Category]' caption='Item'/>"
               "</datasource></datasources></workbook>")
    z = R.RZone(_ws("<zone id='9' type-v2='filter' name='w' param='[ds].[none:Category:nk]' "
                    "x='0' y='0' w='1' h='1'/>"), 10, 10)
    title, cur = F._control_text(z, None, root, {}, {}, {}, {})
    assert ">Item<" in title and cur == "(All)"
    ze = _ws("<zone custom-title='true'><formatted-text><run>Select a Month</run></formatted-text></zone>")
    zp = R.RZone(_ws("<zone id='8' type-v2='paramctrl' param='[Parameters].[P]' x='0' y='0' w='1' h='1'/>"), 10, 10)
    title, cur = F._control_text(zp, ze, root, {}, {"P": "p"}, {"P": "2024-09-01"}, {"P": "*MMM, YYYY"})
    assert "Select a Month" in title and cur == "Sep, 2024"


def test_navigation_button_caption_and_font():
    btn = _ws("<button action='tabdoc:goto-sheet' button-type='text'><button-visual-state>"
              "<caption>Overview</caption><button-caption-font-style fontcolor='#898989' "
              "fontname='Tableau Regular'/></button-visual-state></button>")
    html = F._button_html(btn, {})
    assert ">Overview<" in html and "#898989" in html and "Tableau Regular" in html


def test_axis_ticks_auto_units():
    assert [F.axis_tick(v, 150e6, "n#,##0") for v in (0, 50e6, 150e6)] == ["0M", "50M", "150M"]
    assert F.axis_tick(10000, 20000, 'c"$"#,##0') == "$10K"


def test_geodata_states_and_projection():
    from twkit import geodata as G
    assert G.us_state("California")[0] == "CA" and G.us_state("tx")[0] == "TX"
    assert G.us_state("Atlantis") is None
    x_ca, _ = G.project(*G.us_state("California")[1:], 400, 200)
    x_ny, _ = G.project(*G.us_state("New York")[1:], 400, 200)
    assert x_ca < x_ny


def test_null_blank_and_mask_locale_tag():
    assert F._fmt("None") == "" and F._fmt(None) == ""
    assert F.fmt_mask("96000", 'c!en_US!"$"#,##0,K') == "$96K"


def test_axis_rounds_up_to_nice_tick():
    t = F.axis_ticks(18000, 2)
    assert t[-1] >= 18000 and t[0] == 0


def test_color_map_case_insensitive_bool():
    cm = F._CMap({"true": "#7e7dbc", "false": "#ffffff"})
    assert cm.get("True") == "#7e7dbc" and cm.get("x", "d") == "d"


def test_lcid_currency_mask():
    assert F.fmt_mask("147.2129", "C1033%") == "$147.21"
    assert F.fmt_mask("-1234.5", "C1031%") == "-1.234,50 €"


def test_automatic_axis_measure_is_bar_even_with_label_dim():
    ws = _ws("<worksheet name='r'><table><view/><panes><pane><mark class='Automatic'/>"
             "<encodings><text column='[ds].[none:b:nk]'/></encodings></pane></panes>"
             "<rows>[ds].[none:a:nk]</rows>"
             "<cols>[ds].[__tableau_internal_object_id__].[cnt:T_FCECB5DFE2154D7591D4523AD48CE39E:qk]</cols>"
             "</table></worksheet>")
    rows = [["X", "X", "3"], ["Y", "Y", "5"]]
    assert F._shelf_refs(ws, "cols") == ["[cnt:T_FCECB5DFE2154D7591D4523AD48CE39E:qk]"]
    assert F._sheet_kind(ws, rows, 2, ["[cnt:T_FCECB5DFE2154D7591D4523AD48CE39E:qk]"]) == "bar"


def test_measure_values_label_is_table_not_card():
    ws = _ws("<worksheet name='t'><table><view/><panes><pane><mark class='Automatic'/>"
             "<encodings><text column='[ds].[Multiple Values]'/></encodings>"
             "<customized-label><formatted-text><run>&lt;</run><run>[ds].[Multiple Values]</run>"
             "<run>&gt;</run></formatted-text></customized-label></pane></panes>"
             "<rows>[ds].[none:Order Date:ok]</rows><cols>[ds].[:Measure Names]</cols>"
             "</table></worksheet>")
    assert F._sheet_kind(ws, [["2025-12-22", "21", "165"]], 1, ["[usr:a:qk]", "[usr:b:qk]"]) != "card"


def test_bar_value_and_color_columns_by_refs():
    ws = _ws("<worksheet name='c'><table><view/><panes><pane><mark class='Automatic'/>"
             "<encodings><color column='[ds].[usr:mx:nk:3]'/><text column='[ds].[none:b:nk]'/>"
             "</encodings></pane></panes><rows>[ds].[none:a:nk]</rows>"
             "<cols>[ds].[cnt:r:qk]</cols></table></worksheet>")
    vi, ci = F._bar_indices(ws, ["[none:a:nk]", "[none:b:nk]"], ["[cnt:r:qk]", "[usr:mx:nk:3]"], 2)
    assert (vi, ci) == (2, 3)
    html = F._render_bars([["P", "P", "30", "max"], ["W", "W", "7", "min"]], 2, "", "", 100,
                          cmap={"max": "#b0ccff", "min": "#e5e5e5"}, vi=vi, ci=ci)
    assert "#b0ccff" in html and "#e5e5e5" in html and ">P<" in html


def test_axis_pick_prefers_continuous_measure():
    ws = _ws("<worksheet name='c'><table><view/><panes><pane><mark class='Bar'/></pane></panes>"
             "<rows>([ds].[none:ch:nk] / [ds].[usr:pct:ok])</rows>"
             "<cols>([ds].[sum:cy:qk] + [ds].[sum:py:qk])</cols></table></worksheet>")
    rows = [["Organic", "0.57", "20341", "12934"]]
    mrefs = ["[usr:pct:ok]", "[sum:cy:qk]", "[sum:py:qk]"]
    assert F._axis_pick(rows, 1, mrefs, ws) == 1
    assert F._mrefs_axis_last(rows, 1, mrefs, ws) == ["[usr:pct:ok]", "[sum:py:qk]", "[sum:cy:qk]"]


def test_pie_wedge_pane_and_donut():
    ws = _ws("<worksheet name='p'><table><view/><panes>"
             "<pane><mark class='Pie'/></pane>"
             "<pane id='1'><mark class='Pie'/><encodings><color column='[ds].[none:t:nk]'/>"
             "<wedge-size column='[ds].[sum:v:qk]'/></encodings></pane>"
             "<pane id='2'><mark class='Circle'/></pane></panes>"
             "<rows>([ds].[usr:z:qk] + [ds].[usr:z:qk])</rows><cols/></table></worksheet>")
    sp = F._pie_spec(ws, ["[none:t:nk]"], ["[usr:z:qk]", "[sum:v:qk]"], 1)
    assert sp == {"wi": 2, "ci": 0, "donut": True}
    assert F._sheet_kind(ws, [["a", "0", "5"]], 1, ["[usr:z:qk]", "[sum:v:qk]"]) == "pie"


def test_measure_values_wedge_is_not_pie_yet():
    ws = _ws("<worksheet name='d'><table><view/><panes><pane><mark class='Pie'/><encodings>"
             "<wedge-size column='[ds].[Multiple Values]'/><text column='[ds].[usr:a:qk]'/>"
             "</encodings><customized-label><formatted-text><run>&lt;[ds].[usr:a:qk]&gt;</run>"
             "</formatted-text></customized-label></pane></panes>"
             "<rows>[ds].[none:dev:nk]</rows><cols/></table></worksheet>")
    assert F._sheet_kind(ws, [["Tablet", "0.29", "0.71"]], 1, ["[usr:a:qk]", "[usr:b:qk]"]) == "card"


def test_plate_color_by_sign_and_transparency():
    ws = _ws("<worksheet name='m'><table><view/><style><style-rule element='mark'>"
             "</style-rule></style><panes><pane><mark class='Automatic'/><encodings>"
             "<color column='[ds].[usr:mom:qk]'/><text column='[ds].[usr:mom:qk]'/></encodings>"
             "<style><style-rule element='mark'><format attr='mark-transparency' value='52'/>"
             "</style-rule></style></pane></panes><rows/><cols>[ds].[usr:one:qk]</cols></table>"
             "<encoding attr='color' center='0.0' field='[ds].[usr:mom:qk]' num-steps='2' "
             "type='custom-interpolated'><color-palette><color>#c78ca6</color>"
             "<color>#24693d</color></color-palette></encoding></worksheet>")
    mrefs = ["[usr:one:qk]", "[usr:mom:qk]"]
    assert F._plate(ws, None, [["1", "23.4"]], 0, [], mrefs) == "rgba(36,105,61,0.20)"
    assert F._plate(ws, None, [["1", "-7.7"]], 0, [], mrefs) == "rgba(199,140,166,0.20)"


def test_line_y_axis_fixed_range_and_zero():
    ws = _ws("<worksheet name='o'><table><view/><style><style-rule element='axis'>"
             "<encoding attr='space' scope='rows' range-type='fixed' min='0' max='23000'/>"
             "</style-rule></style></table></worksheet>")
    y0, y1, ticks = F._y_axis(ws, 15000, 22000, 700)
    assert (y0, y1) == (0, 23000) and ticks[0] == 0 and ticks[-1] <= 23000 and len(ticks) >= 10
    y0, y1, ticks = F._y_axis(None, 6000, 9500, 190)
    assert y0 == 0 and y1 >= 9500 and ticks == [0, 5000.0, 10000.0][:len(ticks)]


def test_param_ref_by_name_not_caption():
    from lxml import etree
    from twkit import edit as E
    from twkit import lint as L
    root = etree.fromstring(
        "<workbook><datasources><datasource name='Parameters'>"
        "<column caption='ListParam' name='[Parameter 2]' param-domain-type='list' value='\"A\"'/>"
        "</datasource></datasources></workbook>")
    assert E._param_ref(root, "ListParam") == "[Parameters].[Parameter 2]"
    assert E._param_ref(root, "[Parameters].[Parameter 2]") == "[Parameters].[Parameter 2]"
    txt = etree.tostring(root, encoding="unicode") + "IF [Parameters].[ListParam] = 'A' THEN 1 END"
    b = L.Book(path="t.twb", raw=txt.encode(), root=root, is_twbx=False)
    assert L.r41_param_ref_by_caption(b)
    b = L.Book(path="t.twb", raw=txt.replace("[ListParam]", "[Parameter 2]").encode(), root=root,
               is_twbx=False)
    assert not L.r41_param_ref_by_caption(b)


def test_quoted_percent_is_literal():
    assert F.fmt_mask("100", '#,##0"%"') == "100%"
    assert F.fmt_mask("0.5", "p0%") == "50%"


RANK_ROOT = """<workbook><datasources><datasource name='ds'>
<column-instance column='[f]' derivation='None' name='[none:f:nk]' pivot='key' type='nominal'/>
<style><style-rule element='mark'><encoding attr='color' field='[none:f:nk]' type='palette'>
<map to='#59a14f'><bucket>"1"</bucket></map><map to='#1f1f1f'><bucket>"REST"</bucket></map>
</encoding></style-rule></style></datasource></datasources></workbook>"""
RANK_WS = """<worksheet name='r'><table><view/><style>
<style-rule element='worksheet'><format attr='display-field-labels' scope='rows' value='false'/></style-rule>
</style><panes><pane><mark class='Text'/><encodings><color column='[ds].[none:f:nk]'/>
<text column='[ds].[usr:v:qk]'/></encodings></pane></panes>
<rows>[ds].[none:m:nk]</rows><cols/></table></worksheet>"""


def test_color_only_dimension_colors_text():
    ws, root = _ws(RANK_WS), _ws(RANK_ROOT)
    rows = [["2025-8", "1", 2800.0], ["2025-10", "REST", 2796.0]]
    t = F._table_view(ws, root, rows, 2, ["[none:m:nk]", "[none:f:nk]"],
                      ["m", "f", "FTD's #"], ["", "", ""])
    assert t[0] == [["2025-8", 2800.0], ["2025-10", 2796.0]] and t[1] == 1
    assert t[5] == ["#59a14f", "#1f1f1f"]
    html = F._render_table(t[0], t[1], t[2], t[3], heads=t[4], tint=t[5])
    assert "<thead>" not in html and "REST" not in html
    assert "color:#59a14f" in html


def test_color_off_shelf_stacks_bars():
    rows = [["2025-10", "New", 2615.0], ["2025-10", "Retained", 2133.0],
            ["2025-11", "New", 2715.0], ["2025-11", "Retained", 2355.0]]
    html = F._render_cols(rows, 2, "Actives #", "", 300, color_i=1, stack=True)
    assert html.count("class='col'") == 2
    assert "2,615" in html and "2,133" in html


def test_crosstab_month_rows_masked_without_field_label():
    ws = _ws("""<worksheet name='t'><table><view/><style><style-rule element='worksheet'>
<format attr='display-field-labels' scope='rows' value='false'/></style-rule></style>
<panes><pane><mark class='Text'/><encodings><text column='[ds].[sum:v:qk]'/></encodings></pane></panes>
<rows>[ds].[none:Calculation_1:ok]</rows><cols>[ds].[none:t:nk]</cols></table></worksheet>""")
    rows = [["2025-09-01 00:00:00", "ND", 33.0], ["2025-09-01 00:00:00", "New", 1994.0]]
    html = F._render_crosstab(ws, rows, 2, ["[none:Calculation_1:ok]", "[none:t:nk]"],
                              ["Month", "t", "v"], ["*mmm-yy", "", ""])
    assert "Sep-25" in html and "00:00:00" not in html and "Month" not in html


def test_negative_columns_go_down_with_value_axis():
    rows = [["00", 3100.0], ["01", -5249.0], ["02", 447.0]]
    m = 'c"€ "#,##0;"€ "-#,##0'
    html = F._render_cols(rows, 1, "GGR €", m, 200, amask=m)
    assert "€ -5,249" in html and "€ -5,000" in html and "€ 0<" in html
    assert "class='vzero'" in html
    tops = [float(x) for x in re.findall(r"<i style='top:([\d.]+)px", html)]
    zero = float(re.search(r"class='vzero' style='top:([\d.]+)px", html).group(1))
    assert tops[1] == zero and tops[0] < zero
    assert "top:" in re.findall(r"class='lbl vval' style='([^']+)'", html)[1]
    assert "vaxis" not in F._render_cols(rows, 1, "GGR €", m, 200, amask=None)


def test_axis_ticks_like_tableau():
    px = 189
    for lo, hi, want in ((0, 16, [0, 5, 10, 15]), (0, 54, [0, 20, 40, 60]), (0, 23, [0, 10, 20]),
                         (0, 38, [0, 10, 20, 30, 40]), (0, 17887, [0, 5000, 10000, 15000, 20000]),
                         (0, 48727, [0, 20000, 40000]), (-5249, 3100, [-5000, 0]),
                         (-105, 173, [-100, 0, 100, 200]), (-1707, 448, [-2000, -1000, 0]),
                         (0, 6750, [0, 2000, 4000, 6000])):
        assert F.nice_axis(lo, hi, px, integer=True)[2] == want, (lo, hi)
    assert F.nice_axis(0, 1, px, integer=True)[2] == [0, 1]


def test_axis_mask_from_field_label_or_auto():
    ws = _ws("""<worksheet><table><style><style-rule element='cell'>
<format attr='text-format' field='[ds].[sum:Profit:qk]' value='c"$"#,##0,.0K'/></style-rule>
<style-rule element='label'><format attr='text-format' field='[ds].[sum:Rev:qk]' value='c"£"#,##0,,M'/>
</style-rule><style-rule element='axis'><format attr='display' field='[ds].[sum:Profit:qk]' scope='rows'
value='false'/></style-rule></style></table></worksheet>""")
    assert F.axis_mask(ws, "[sum:Rev:qk]", {}) == 'c"£"#,##0,,M'
    assert F.axis_mask(ws, "[sum:Profit:qk]", {}) == ""
    assert F.axis_mask(ws, "[usr:Calculation_1:qk:2]", {"[Calculation_1]": "n#,##0"}) == "n#,##0"
    assert F.axis_hidden(ws, "[sum:Profit:qk]") and not F.axis_hidden(ws, "[sum:Rev:qk]")
    assert F.axis_label(6e6, [0, 6e6, 12e6], 'c"£"#,##0,,M') == "£6M"
    assert F.axis_label(20000, [0, 20000, 200000], "") == "20K"


def test_dimension_by_derivation_and_mask_like_tableau():
    assert F.fmt_dim(4, "[qr:Order Date:ok]") == "Q4"
    assert F.fmt_dim("10", "[mn:d:ok]") == "October"
    assert F.fmt_dim("2025-10-01 00:00:00", "[my:d:ok]") == "October 2025"
    assert F.fmt_dim("2025-10-01 00:00:00", "[tmn:d:ok]", "*mmm-yy") == "Oct-25"
    assert F.fmt_dim(1, "[wd:d:ok]") == "Sunday"
    assert F.fmt_dim(2020.0, "[none:Year:ok]") == "2020" and F.fmt_dim(None) == "Null"


def test_parameter_and_date_masked_in_text_and_tile():
    assert F.param_text("2022-07-21", "L") == "Thursday, July 21, 2022"
    assert F.param_text("2024-09-01", "*MMM, YYYY") == "Sep, 2024"
    assert F.param_text("2021", "*") == "2021"
    assert F._fmt("2026-10-01 00:00:00", "", "*mmm d, yyyy") == "Oct 1, 2026"
    t = F.card_text("<[ds].[none:Year:ok]>", ["2020", 5.0], 1, ["", ""], ["[none:Year:ok]"],
                    ["[sum:v:qk]"], {})
    assert t == "2020"


def test_bar_label_is_shelf_dimension_not_detail():
    ws = _ws("<worksheet><table><rows>[ds].[sum:v:qk]</rows>"
             "<cols>([ds].[yr:d:ok] / [ds].[qr:d:ok])</cols></table></worksheet>")
    refs = ["[yr:d:ok]", "[qr:d:ok]", "[none:Customer:nk]"]
    assert F.dim_labels(ws, refs, [[2011, 1, "Troy", 5.0]], 3) == ["Q1"]


def test_negative_bars_go_left_of_zero():
    rows = [["A", 300.0], ["B", -100.0]]
    html = F._render_bars(rows, 1, "v", 'c"€ "#,##0;"€ "-#,##0')
    assert "flex:0 0 30.8%" in html
    neg = html.split("class='bar'")[2]
    assert neg.index("€ -100") < neg.index("class='fill'")
    assert "flex:0 0" not in F._render_bars([["A", 3.0], ["B", 1.0]], 1, "v")


def test_hidden_dual_axis_hides_one():
    ws = _ws("""<worksheet><table><style><style-rule element='axis'>
<format attr='display' field='[ds].[sum:Sales:qk]' scope='rows' value='false'/></style-rule></style>
<rows>([ds].[sum:Sales:qk] + [ds].[sum:Sales:qk])</rows><cols>[ds].[tmn:Date:qk]</cols></table></worksheet>""")
    assert not F.axis_hidden(ws, "[sum:Sales:qk]")
    ws2 = _ws("""<worksheet><table><style><style-rule element='axis'>
<format attr='display' field='[ds].[sum:Sales:qk]' scope='rows' value='false'/></style-rule></style>
<rows>[ds].[sum:Sales:qk]</rows><cols>[ds].[tmn:Date:qk]</cols></table></worksheet>""")
    assert F.axis_hidden(ws2, "[sum:Sales:qk]")


_SCAT = """<worksheet name='s'><table><view/><style><style-rule element='refline'>
<format attr='text-format' id='refline1' value='n#,##0.0'/></style-rule></style>
<panes><pane><mark class='Circle'/><encodings><text column='[ds].[none:Region:nk]'/></encodings></pane></panes>
<rows>[ds].[sum:Profit:qk]</rows><cols>[ds].[sum:Sales:qk]</cols>
<reference-line axis-column='[ds].[sum:Profit:qk]' formula='average' id='refline1' label='Avg: &lt;Value&gt;'
 label-type='custom' scope='per-table'/></table></worksheet>"""


def test_scatter_measure_by_measure_with_axes_and_average():
    ws = _ws(_SCAT)
    rows = [["West", 250000.0, 44000.0], ["East", 210000.0, 33000.0], ["South", 120000.0, 9000.0]]
    mrefs = ["[sum:Sales:qk]", "[sum:Profit:qk]"]
    assert F._sheet_kind(ws, rows, 1, mrefs) == "scatter"
    html = F._render_scatter(ws, rows, 1, ["[none:Region:nk]"], mrefs, ["Region", "Sales", "Profit"],
                             ["", "", ""], ["", ""], 600, 400, None)
    assert html.count("<circle") == 3 and "West" in html
    assert "Avg: 28,666.7" in html and "stroke-dasharray" in html
    assert ">Sales<" in html and ">Profit<" in html
    assert "100K" in html and "40K" in html


def test_measures_as_rows_column_per_week_hidden_labels():
    ws = _ws("""<worksheet><table><style><style-rule element='label'>
<format attr='display' field='[ds].[:Measure Names]' value='false'/></style-rule>
<style-rule element='worksheet'><format attr='display-field-labels' scope='cols' value='false'/>
</style-rule></style><rows>[ds].[:Measure Names]</rows><cols>[ds].[none:Week:nk]</cols></table></worksheet>""")
    rows = [["Week 38", 1766.0, 327.0], ["Week 37", 3124.0, 439.0]]
    html = F._render_mlist(rows, 1, ["Week", "NRC's #", "FTD #"], ["", "n#,##0", "n#,##0"], ws,
                           ["[none:Week:nk]"])
    assert "Week 38" in html and "Week 37" in html and "3,124" in html and "439" in html
    assert "NRC" not in html
    assert html.count("<tr>") == 3


def test_measure_palette_like_tableau():
    def enc(attrs):
        return _ws(f"<worksheet><table><style><style-rule element='mark'><encoding attr='color' "
                   f"field='[ds].[sum:p:qk]' type='interpolated' {attrs}/></style-rule></style></table>"
                   f"</worksheet>")
    named = F.measure_palette(None, enc("palette='red_green_diverging_10_0'"), "[sum:p:qk]")
    assert named["diverging"] and F.measure_color(named, -641, -641, 2726) != \
        F.measure_color(named, 2726, -641, 2726)
    assert F.measure_color(named, 4744, -641, 4744) == "#24693d"
    steps = F.measure_palette(None, enc("palette='red_green_diverging_10_0' num-steps='2'"), "[sum:p:qk]")
    assert F.measure_color(steps, -5.68, -641, 4744) == "#ae123a"
    assert F.measure_color(steps, 56.9, -641, 4744) == "#24693d"
    rev = F.measure_palette(None, enc("palette='red_green_diverging_10_0' reverse='true' "
                                      "symmetric='false'"), "[sum:p:qk]")
    assert F.measure_color(rev, -641, -641, 4744) == "#24693d"
    assert F.measure_color({}, -4744, -4744, 641) == "#9e3d22"
    assert F.measure_color({}, -641, -641, 4744) != "#9e3d22"
    assert F.measure_color({}, 10, 0, 10) == "#2a5783"


def test_measure_table_with_measure_colors():
    ws = _ws("""<worksheet><table><panes><pane><mark class='Square'/><encodings>
<color column='[ds].[Multiple Values]' separate-domains='true'/><text column='[ds].[Multiple Values]'/>
</encodings><style><style-rule element='mark'><encoding attr='color' field='[ds].[sum:profit:qk]'
type='interpolated' palette='red_green_diverging_10_0'/></style-rule></style></pane></panes>
<rows>[ds].[none:region:nk]</rows><cols>[ds].[:Measure Names]</cols></table></worksheet>""")
    assert F._sheet_kind(ws, [["A", 1.0, -2.0]], 1, ["[sum:sales:qk]", "[sum:profit:qk]"]) == "table"
    cc = F.cell_colors(ws, None, [["A", 1.0, -2.0], ["B", 3.0, 5.0]], 1, ["[sum:sales:qk]", "[sum:profit:qk]"])
    assert set(cc) == {1, 2} and cc[2][3] is True
    html = F._render_table([["A", 1.0, -2.0], ["B", 3.0, 5.0]], 1, ["r", "s", "p"], ccolor=cc)
    assert "background:#24693d" in html


_DUAL = """<worksheet><table><style><style-rule element='axis'>
<encoding attr='space' class='1' field='[ds].[sum:sales:qk]' fold='true' scope='rows' synchronized='true' type='space'/>
<encoding attr='space' class='0' field='[ds].[sum:profit:qk]' fold='true' scope='rows' synchronized='true' type='space'/>
</style-rule></style><panes><pane><mark class='Automatic'/></pane>
<pane id='1' y-axis-name='[ds].[sum:sales:qk]'><mark class='Bar'/></pane>
<pane id='2' y-axis-name='[ds].[sum:profit:qk]'><mark class='Line'/><style><style-rule element='mark'>
<format attr='mark-labels-show' value='true'/></style-rule></style></pane></panes>
<rows>([ds].[sum:sales:qk] + [ds].[sum:profit:qk])</rows><cols>[ds].[none:region:nk]</cols></table></worksheet>"""


def test_dual_axis_bars_with_line_on_top():
    ws = _ws(_DUAL)
    fold, sync = F.folded(ws, "rows")
    assert fold == [("[sum:sales:qk]", "Bar", False), ("[sum:profit:qk]", "Line", True)] and sync
    rows = [["Central", 37636.0, -471.0], ["West", 67009.0, 4744.0]]
    assert F._sheet_kind(ws, rows, 1, ["[sum:sales:qk]", "[sum:profit:qk]"]) == "bar"
    html = F._render_cols(rows, 1, "sales", "", 300, amask="", vi=1,
                          overlay=[(2, "Line", True, "")], sync=True)
    assert "<polyline" in html and "4,744" in html and "67,009" in html
    assert html.index("class='vcol'") < html.index("<polyline")


def test_dual_axis_of_one_measure_not_merged():
    ws = _ws("""<worksheet><table><style><style-rule element='axis'>
<encoding attr='space' class='1' field='[ds].[sum:Sales:qk]' fold='true' scope='rows' type='space'/>
</style-rule></style><rows>([ds].[sum:Sales:qk] + [ds].[sum:Sales:qk])</rows><cols/></table></worksheet>""")
    assert F.folded(ws, "rows") == ([], False)


def test_month_labels_by_width():
    rows = [[f"2019-{m:02d}-01", 100.0 + m] for m in range(1, 13)]
    ws = _ws("<worksheet><table><rows>[ds].[sum:Sales:qk]</rows><cols>[ds].[tmn:Date:qk]</cols>"
             "</table></worksheet>")
    html = F._render_line(rows, 1, "Sales", 467, 255, ws=ws, refs=["[tmn:Date:qk]"])
    assert all(f">{m}<" in html for m in ("Jan", "Feb", "Mar", "Dec"))


def test_two_measures_on_rows_lines_as_panes():
    root = etree_root = None
    ws = _ws("<worksheet name='S'><table><panes><pane><mark class='Line'/></pane></panes>"
             "<rows>([ds].[sum:qty:qk] + [ds].[usr:Running sales:qk])</rows>"
             "<cols>[ds].[tmn:d:qk]</cols></table></worksheet>")
    dash = _ws("<dashboard name='D'><size maxheight='400' maxwidth='600' minheight='400' minwidth='600'/>"
               "<zones><zone h='100000' id='2' name='S' w='100000' x='0' y='0'/></zones></dashboard>")
    rows = [[f"2025-{m:02d}-01", 10.0 * m, 100.0 * m * m] for m in range(1, 7)]
    data = {"S": {"rows": rows, "ndims": 1, "captions": ["d", "qty", "Running sales"], "masks": ["", "", ""],
                  "refs": ["[tmn:d:qk]"], "mrefs": ["[sum:qty:qk]", "[usr:Running sales:qk]"]}}
    html = F._page_html("D", dash, {"S": ws}, data, "t", root)
    assert html.count("class='line'") == 2


def test_treemap_squarified_with_measure_palette():
    boxes = F.squarify([6, 6, 4, 3, 2, 2, 1], 0, 0, 600, 400)
    areas = [bw * bh for _, _, bw, bh in boxes]
    assert abs(sum(areas) - 600 * 400) < 1 and abs(areas[0] / areas[-1] - 6) < 0.01
    assert max(max(bw / bh, bh / bw) for _, _, bw, bh in boxes) < 3
    ws = _ws("<worksheet><table><panes><pane><mark class='Square'/><encodings>"
             "<size column='[ds].[sum:s:qk]'/><color column='[ds].[sum:s:qk]'/></encodings></pane></panes>"
             "<rows/><cols/></table></worksheet>")
    html = F._render_treemap([["A", 10.0], ["B", 5.0]], 1, ["d", "s"], ["", ""], 300, 200, ws, None,
                             ["[none:d:nk]"], ["[sum:s:qk]"])
    assert "#2a5783" in html and html.count("position:absolute") == 2


def test_comparison_uses_reference_capture_date(tmp_path):
    import datetime as dt
    import os as _os
    from twkit import dryrun as D_, framecmp as FC
    png = tmp_path / "ref.png"
    png.write_bytes(b"x")
    t = dt.datetime(2026, 10, 1, 16, 15).timestamp()
    _os.utime(png, (t, t))
    assert FC.ref_date({"P": str(png)}) == "2026-10-01"
    keep = dict(D_.DIALECTS["hyper"])
    try:
        FC._freeze_today("2026-10-01")
        assert D_.DIALECTS["hyper"]["today"] == "DATE '2026-10-01'"
        FC._freeze_today("not a date")
        assert D_.DIALECTS["hyper"]["today"] == "DATE '2026-10-01'"
    finally:
        D_.DIALECTS["hyper"].clear()
        D_.DIALECTS["hyper"].update(keep)


def test_combo_pane_color_right_axis_no_labels():
    ws = _ws("""<worksheet><table><panes><pane><mark class='Automatic'/></pane>
<pane y-axis-name='[ds].[usr:bet:qk]'><mark class='Bar'/><style><style-rule element='mark'>
<format attr='mark-color' value='#bab0ac'/><format attr='mark-labels-show' value='false'/></style-rule></style></pane>
<pane y-axis-name='[ds].[usr:ngr:qk]'><mark class='Line'/><style><style-rule element='mark'>
<format attr='mark-color' value='#f28e2b'/></style-rule></style></pane></panes>
<rows>([ds].[usr:bet:qk] + [ds].[usr:ngr:qk])</rows><cols>[ds].[none:p:ok]</cols></table></worksheet>""")
    assert F.pane_style(ws, "[usr:ngr:qk]")["color"] == "#f28e2b"
    assert not F.marks_shown(ws, "[usr:bet:qk]")
    rows = [["2025-09-01", 72e6, 1.1e6], ["2025-10-01", 50e6, 2.0e6]]
    html = F._render_cols(rows, 1, "bet", "", 300, amask="", vi=1, sync=False, marks_on=False,
                          overlay=[(2, "Line", False, "", "#f28e2b", "")])
    assert "stroke='#f28e2b'" in html and "vaxr" in html and "2M" in html
    assert "class='lbl vval'" not in html


def test_reference_line_on_constant_measure():
    from lxml import etree as LET
    root = LET.fromstring(b"""<workbook><datasources><datasource name='ds'>
<column name='[Tgt]' caption='Target'><calculation class='tableau' formula='{ FIXED : AVG(7)}'/></column>
</datasource></datasources></workbook>""")
    assert F.const_measure(root, "[sum:Tgt:qk]") == 7.0
    ws = _ws("""<worksheet><table><rows>[ds].[usr:v:qk]</rows><cols>[ds].[tmn:d:qk]</cols>
<reference-line axis-column='[ds].[usr:v:qk]' formula='average' id='r0' label='Target: &lt;Value&gt;'
 label-type='custom' value-column='[ds].[sum:Tgt:qk]'/></table></worksheet>""")
    cols = F.ref_line_columns(root, ws, ["[usr:v:qk]"])
    assert F.ref_lines(ws, "[usr:v:qk]", [7.8, 7.9], "n#,##0.0", cols) == [(7.0, "Target: 7.0")]
    html = F._render_cols([["2023-04-01", 7.8], ["2023-05-01", 7.9]], 1, "v", "n#,##0.0", 150,
                          amask=None, ws=ws, aref="[usr:v:qk]", mrefs=["[usr:v:qk]"], consts=cols,
                          marks_on=False)
    assert "Target: 7.0" in html and "class='vref'" in html


def test_icon_without_dimensions_and_month_letter():
    ws = _ws("<worksheet><table><panes><pane><mark class='Shape'/></pane></panes><rows/><cols/></table></worksheet>")
    assert F._sheet_kind(ws, [[1.0]], 0, ["[usr:c:qk]"]) == "glyph"
    assert F.fmt_date("2023-07-01", "*mmmmm") == "J" and F.fmt_date("2023-07-01", "*mmm YYYY") == "Jul 2023"


def test_shape_over_an_empty_dimension_is_an_icon():
    ws = _ws("<worksheet><table><panes><pane><mark class='Shape'/></pane></panes>"
             "<rows>[ds].[none:c:nk]</rows><cols/></table></worksheet>")
    assert F._sheet_kind(ws, [[""]], 1, []) == "glyph"
    assert F._sheet_kind(ws, [["Dublin"]], 1, []) != "glyph"


def test_column_widths_from_style_and_content():
    ws = _ws("""<worksheet><table><style><style-rule element='header'>
<format attr='width' field='[ds].[none:Game:nk]' value='220'/></style-rule></style>
<rows>[ds].[none:Game:nk]</rows><cols/></table></worksheet>""")
    assert F.xml_width(ws, "header", "[none:Game:nk]") == 220 and F.xml_width(ws, "cell") is None
    rows = [["Gates of Olympus", 1.0], ["Sugar Rush", 22.0]]
    html = F._render_table(rows, 1, ["Game", "Bets"], ["", "n#,##0"], refs=["[none:Game:nk]"],
                           ws=ws, fit="standard", sized=True)
    assert "data-src='xml' data-px='220'" in html and "data-src='auto'" in html
    assert "data-cols='px'" in html and "class='lbl h2'" in html
    fit = F._render_table(rows, 1, ["Game", "Bets"], ["", ""], refs=["[none:Game:nk]"], ws=ws,
                          fit="fit-width", sized=True)
    assert "data-cols='fit'" in fit and "%'" in fit


def test_custom_label_from_dimensions_one_line_tile():
    ws = _ws("""<worksheet><table><panes><pane><mark class='Text'/><customized-label><formatted-text>
<run fontsize='18'>Regional Performance Overview </run><run>&lt;[ds].[none:y:ok]&gt;</run>
<run> vs</run></formatted-text></customized-label></pane></panes><rows/><cols/></table></worksheet>""")
    dash = _ws("<dashboard name='D'><size maxheight='100' maxwidth='600' minheight='100' minwidth='600'/>"
               "<zones><zone h='100000' id='2' name='H' show-title='false' w='100000' x='0' y='0'/></zones></dashboard>")
    data = {"H": {"rows": [["2022"]], "ndims": 1, "captions": ["y"], "masks": [""], "refs": ["[none:y:ok]"],
                  "mrefs": [], "synthetic": True}}
    html = F._page_html("D", dash, {"H": ws}, data, "t", None)
    assert "data-form='card'" in html and "Regional Performance Overview" in html


def test_line_labels_ends_and_range():
    ws = _ws("""<worksheet><table><panes><pane><mark class='Line'/><style><style-rule element='mark'>
<format attr='mark-labels-show' value='true'/><format attr='mark-labels-mode' value='line-ends'/>
<format attr='mark-labels-line-first' value='false'/></style-rule></style></pane></panes>
<rows>[ds].[sum:v:qk]</rows><cols>[ds].[tmn:d:qk]</cols></table></worksheet>""")
    spec = F.line_labels(ws)
    assert spec["mode"] == "line-ends" and not spec["first"] and spec["last"]
    pts = [(0, 5.0), (1, 9.0), (2, 1.0), (3, 4.0)]
    assert F.pick_labels(pts, spec) == [3]
    assert F.pick_labels(pts, {"mode": "range", "min": True, "max": True}) == [1, 2]
    rows = [[f"2025-{m:02d}-01", float(v)] for m, (_, v) in enumerate(pts, 1)]
    html = F._render_line(rows, 1, "v", 400, 200, ws=ws, refs=["[tmn:d:qk]"], mask="n#,##0")
    assert html.count("class='lbl lnl'") == 1 and ">4<" in html


def test_frame_measure_returns_table_title_and_overlaps():
    for key in ("item.title", "first:", "pitch:", "head_need", "src:", "item.overlaps", "item.inks",
                "squashed"):
        assert key in F.PROBE_JS, key


def test_stacked_horizontal_bars_by_color():
    rows = [["East", "Furniture", 100.0], ["East", "Office", 50.0], ["West", "Furniture", 200.0],
            ["West", "Office", -40.0]]
    html = F._render_hstack(rows, 2, 1, "sales", "", 200, None, [], True)
    assert html.count("class='bar'") == 2 and html.count("class='seg lbl'") == 4
    assert F.stack_sums(rows, 2, 1) == [(150.0, 0.0), (200.0, -40.0)]


def test_crosstab_grand_totals_for_sum():
    ws = _ws("""<worksheet><table><panes><pane><mark class='Text'/><encodings><text column='[ds].[sum:s:qk]'/>
</encodings></pane></panes><rows total='true' onTop='true'>[ds].[none:r:nk]</rows>
<cols total='true'>[ds].[none:c:nk]</cols></table></worksheet>""")
    rows = [["East", "A", 1.0], ["East", "B", 2.0], ["West", "A", 3.0], ["West", "B", 4.0]]
    refs = ["[none:r:nk]", "[none:c:nk]"]
    html = F._render_crosstab(ws, rows, 2, refs, ["r", "c", "s"], ["", "", "n#,##0"], mref="[sum:s:qk]")
    assert html.count("Grand Total") == 2 and ">10<" in html
    assert html.index("Grand Total</td>") < html.index("East")
    avg = F._render_crosstab(ws, rows, 2, refs, ["r", "c", "s"], ["", "", ""], mref="[avg:s:qk]")
    assert "Grand Total" not in avg


def test_points_instead_of_bars_for_circle_shape():
    rows = [["East", "Furniture", 100.0], ["East", "Office", 50.0], ["West", "Furniture", 200.0]]
    html = F._render_hdots(rows, 2, 1, "sales", "", 200, None, [], False, "Circle")
    assert html.count("class='bar'") == 2 and html.count("border-radius:50%") == 3
    assert "class='fill'" not in html


def test_stacked_segments_unlabeled_when_labels_off():
    rows = [["Jan", "New", 120.0], ["Jan", "Retained", 300.0], ["Feb", "New", 90.0]]
    on = F._render_cols(rows, 2, "Actives", "#,##0", 300, color_i=1, stack=True)
    off = F._render_cols(rows, 2, "Actives", "#,##0", 300, color_i=1, stack=True, marks_on=False)
    assert ">300<" in on and ">300<" not in off


def test_table_drops_columns_with_hidden_header():
    ws = ET.fromstring(
        "<worksheet><table><style><style-rule element='label'>"
        "<format attr='display' field='[ds].[none:key:nk]' value='false'/></style-rule></style>"
        "<rows>([ds].[none:key:nk] / [ds].[none:name:nk])</rows><cols/></table></worksheet>")
    rows = [["1 - A", "A", 5.0], ["2 - B", "B", 7.0]]
    out = F._table_view(ws, None, rows, 2, ["[none:key:nk]", "[none:name:nk]"], ["key", "name", "v"],
                        ["", "", ""])
    assert out[0] == [["A", 5.0], ["B", 7.0]] and out[1] == 1 and out[6] == ["[none:name:nk]"]


def test_lines_split_by_detail_and_use_color_map():
    ws = ET.fromstring(
        "<worksheet><table><rows>[ds].[sum:v:qk]</rows><cols>[ds].[none:m:ok]</cols>"
        "<panes><pane><mark class='Line'/><encodings><color column='[ds].[none:top:nk]'/>"
        "<lod column='[ds].[none:who:nk]'/></encodings></pane></panes></table></worksheet>")
    refs = ["[none:m:ok]", "[none:top:nk]", "[none:who:nk]"]
    rows = [["1", "Other", "a", 1.0], ["2", "Other", "a", 2.0], ["1", "Other", "b", 5.0],
            ["2", "Other", "b", 6.0], ["1", "x", "x", 3.0], ["2", "x", "x", 4.0]]
    html = F._render_line(rows, 3, "v", 300, 200, ws=ws, refs=refs,
                          cmap={"x": "#e15759", "Other": "#cfcfcf"})
    assert html.count("<polyline") == 3
    assert html.count("stroke='#cfcfcf'") == 2 and "stroke='#e15759'" in html
    assert html.index("#cfcfcf") < html.index("#e15759")


def test_line_label_at_right_edge_stays_inside():
    ws = _ws("""<worksheet><table><panes><pane><mark class='Line'/>
<encodings><color column='[ds].[none:c:nk]'/></encodings><style><style-rule element='mark'>
<format attr='mark-labels-show' value='true'/><format attr='mark-labels-mode' value='line-ends'/>
</style-rule></style></pane></panes>
<rows>[ds].[sum:v:qk]</rows><cols>[ds].[tmn:d:qk]</cols></table></worksheet>""")
    rows = [["2025-01-01", "a", 1.0], ["2025-02-01", "a", 2.0], ["2025-03-01", "a", 3.0],
            ["2025-03-01", "b", 2070007.0]]
    html = F._render_line(rows, 2, "v", 400, 200, ws=ws, refs=["[tmn:d:qk]", "[none:c:nk]"],
                          mask="n#,##0")
    spans = re.findall(r"<span class='lbl lnl' style='([^']+)'>([^<]+)<", html)
    lone = [st for st, t in spans if t == "2,070,007"]
    assert lone and "translateX(-100%)" in lone[0]


def test_header_height_allows_more_lines():
    ws = _ws("""<worksheet><table><style><style-rule element='header'>
<format attr='height' field='[ds].[:Measure Names]' value='52'/></style-rule></style>
<rows/><cols>[ds].[:Measure Names]</cols></table></worksheet>""")
    html = F._table_html([("Cancelled / Pending Bonus #", "lbl num")], [[("1", "lbl num", "")]], ws=ws)
    assert "-webkit-line-clamp:3" in html
    plain = F._table_html([("Cancelled / Pending Bonus #", "lbl num")], [[("1", "lbl num", "")]],
                          ws=_ws("<worksheet><table><rows/><cols>[ds].[:Measure Names]</cols></table></worksheet>"))
    assert "-webkit-line-clamp" not in plain


def _row_ws(extra: str = ""):
    return _ws("<worksheet name='T'><table><style>" + extra + "</style>"
               "<rows>[ds].[none:d:nk]</rows><cols/></table></worksheet>")


def test_tall_rows_do_not_wrap_row_labels_as_in_tableau():
    body = [[("Alpha Beta Gamma Delta", "lbl", ""), ("12", "lbl num", "")]]
    kinds = [("dim", "[none:d:nk]"), ("num", "[sum:v:qk]")]
    tall = "<style-rule element='cell'><format attr='height' field='[ds].[none:d:nk]' value='40'/></style-rule>"
    html = F._table_html([("d", "lbl"), ("v", "lbl num")], body, kinds, _row_ws(tall))
    # Desktop, 35 px rows with header/cell/label wrap on: the label stays one line with an ellipsis
    assert "<td class='lbl' style='height:40px;'>Alpha Beta Gamma Delta</td>" in html


def test_line_chart_draws_its_reference_line():
    ws = _ws("""<worksheet><table><rows>[ds].[usr:v:qk]</rows><cols>[ds].[tmn:d:qk]</cols>
<panes><pane><mark class='Line'/></pane></panes>
<reference-line axis-column='[ds].[usr:v:qk]' formula='average' id='r0' label='Avg: &lt;Value&gt;'
 label-type='custom' value-column='[ds].[usr:v:qk]'/></table></worksheet>""")
    html = F._render_line([["2023-04-01", 6.0], ["2023-05-01", 8.0]], 1, "v", 300, 160, ws=ws,
                          refs=["[tmn:d:qk]"], mask="n#,##0.0")
    assert "class='vref'" in html and "Avg: 7.0" in html

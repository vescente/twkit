import xml.etree.ElementTree as ET  # noqa: S405

from twkit import frame as F


def _x(xml: str):
    return ET.fromstring(xml)  # noqa: S314


ALIAS_BOOK = """<workbook><datasources><datasource name='ds'>
<column name='[Status]' datatype='string' role='dimension' type='nominal'><aliases>
<alias key='&quot;CLOSED&quot;' value='Closed'/><alias key='%null%' value='—'/></aliases></column>
<column name='[Flag]' datatype='boolean' role='dimension' type='nominal'><aliases>
<alias key='true' value='Upsell'/><alias key='false' value='Sale'/></aliases></column>
<column name='[Lvl]' datatype='integer' role='dimension' type='ordinal'><aliases>
<alias key='1' value='First'/></aliases></column>
<column name='[:Measure Names]'><aliases>
<alias key='&quot;[ds].[sum:Calculation_1:qk]&quot;' value='Sales Volume'/></aliases></column>
</datasource><datasource name='Parameters'><column name='[P]'><aliases>
<alias key='1' value='One'/></aliases></column></datasource></datasources></workbook>"""


def test_value_and_measure_name_aliases():
    F._ALIAS.clear()
    F._ALIAS.update(F.column_alias_map(_x(ALIAS_BOOK)))
    try:
        assert F.fmt_dim("CLOSED", "[none:Status:nk]") == "Closed"
        assert F.fmt_dim(None, "[none:Status:nk]") == "—"
        assert F.fmt_dim("OPEN", "[none:Status:nk]") == "OPEN"
        assert F.fmt_dim(True, "[none:Flag:nk]") == "Upsell"
        assert F.fmt_dim("False", "[none:Flag:nk]") == "Sale"
        assert F.fmt_dim(1, "[none:Lvl:ok]") == "First" and F.fmt_dim("1.0", "[none:Lvl:ok]") == "First"
        assert F.measure_alias("[sum:Calculation_1:qk]") == "Sales Volume"
        assert "P" not in F._ALIAS
    finally:
        F._ALIAS.clear()


def test_hidden_bar_row_headers_not_printed():
    ws = _x("<worksheet><table><style><style-rule element='label'>"
            "<format attr='display' field='[ds].[none:region:nk]' value='false'/></style-rule></style>"
            "<rows>[ds].[none:region:nk]</rows><cols>[ds].[sum:sales:qk]</cols></table></worksheet>")
    rows = [["East", 5.0], ["West", 7.0]]
    assert F.row_headers(ws, ["[none:region:nk]"], ["[sum:sales:qk]"], rows, 1, ["", ""]) == ["", ""]
    html = F._render_bars(rows, 1, "sales", labels=["", ""])
    assert ">East<" not in html and ">West<" not in html


STYLED = """<worksheet name='S'><table><style>
<style-rule element='cell'><format attr='text-align' value='center'/><format attr='font-weight' value='bold'/>
<format attr='font-size' value='12'/></style-rule>
<style-rule element='label'><format attr='font-size' field='[ds].[none:region:nk]' value='10'/>
<format attr='color' field='[ds].[none:region:nk]' value='#e15759'/></style-rule>
<style-rule element='table-div'><format attr='line-visibility' scope='rows' value='off'/></style-rule>
</style><panes><pane><mark class='Text'/><encodings><text column='[ds].[Multiple Values]'/></encodings></pane></panes>
<rows>[ds].[none:region:nk]</rows><cols>[ds].[:Measure Names]</cols></table></worksheet>"""


def test_table_size_and_alignment_from_style():
    ws = _x(STYLED)
    assert F.text_css(ws, "cell", "[sum:sales:qk]") == "font-size:16.0px;font-weight:700;text-align:center"
    assert F.text_css(ws, "label", "[none:region:nk]") == "font-size:13.3px;color:#e15759"
    html = F._render_table([["East", 1234.0]], 1, ["region", "sales"], ws=ws,
                           refs=["[none:region:nk]"], mrefs=["[sum:sales:qk]"], sized=True)
    assert "font-size:16.0px;font-weight:700;text-align:center" in html
    assert "color:#e15759" in html and "class='nodiv'" in html
    narrow = F.col_widths(None, [("v", "")], [], [["1,234,567.89"]], "")
    wide = F.col_widths(None, [("v", "")], [], [["1,234,567.89"]], "", pts=[12.0])
    assert wide[0] > narrow[0]


def test_measure_names_order_from_manual_source_sort():
    root = _x("""<workbook><datasources><datasource name='ds'><default-sorts>
<manual-sort column='[:Measure Names]' direction='ASC'><dictionary>
<bucket>"[ds].[sum:qty:qk]"</bucket><bucket>"[ds].[sum:profit:qk]"</bucket><bucket>"[ds].[sum:sales:qk]"</bucket>
</dictionary></manual-sort></default-sorts></datasource></datasources></workbook>""")
    ws = _x("<worksheet><table><view><datasources><datasource name='ds'/></datasources></view>"
            "<rows>[ds].[none:region:nk]</rows><cols>[ds].[:Measure Names]</cols></table></worksheet>")
    d = {"rows": [["East", 1.0, 2.0, 3.0]], "ndims": 1, "captions": ["region", "sales", "profit", "qty"],
         "masks": ["", "a", "b", "c"], "mrefs": ["[sum:sales:qk]", "[sum:profit:qk]", "[sum:qty:qk]"]}
    out = F.measure_order(root, ws, d)
    assert out["captions"] == ["region", "qty", "profit", "sales"]
    assert out["rows"] == [["East", 3.0, 2.0, 1.0]] and out["masks"] == ["", "c", "b", "a"]
    assert out["mrefs"] == ["[sum:qty:qk]", "[sum:profit:qk]", "[sum:sales:qk]"]
    assert F.measure_order(root, _x("<worksheet><table><rows/><cols/></table></worksheet>"), d) is d


def test_table_title_in_standard_wraps_to_table_width():
    body = F._render_table([["A", 1.0]], 1, ["", "v"], heads=["", ""], refs=["[none:a:nk]"],
                           mrefs=["[sum:v:qk]"], sized=True)
    w = F.title_width(body, "table", "standard")
    assert w and w < 120
    assert F.title_width(body, "table", "entire-view") is None
    assert F.title_width(body, "bar", "standard") is None


def test_hide_filter_cuts_rows_after_calc():
    from lxml import etree
    from twkit import frame
    ws = etree.fromstring(
        "<worksheet name='k'><table><view>"
        "<filter class='categorical' column='[ds].[none:show:nk]' kind='hide'>"
        "<groupfilter function='except'><groupfilter function='level-members' level='[none:show:nk]'/>"
        "<groupfilter function='member' level='[none:show:nk]' member='false'/></groupfilter></filter>"
        "</view></table></worksheet>")
    rows = [["2026-08-01", "False", None], ["2026-09-01", "False", "491009"], ["2026-10-01", "True", "-1079140"]]
    out = frame.hide_filtered(ws, rows, ["[none:m:ok]", "[none:show:nk]"])
    assert out == [["2026-10-01", "True", "-1079140"]]

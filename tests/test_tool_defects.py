import csv
import json
import os

import pytest
from lxml import etree

from twkit import blocks as BL
from twkit import edit as ED

FIELDS = [
    {"name": "region", "datatype": "string", "role": "dimension", "field_type": "nominal"},
    {"name": "state", "datatype": "string", "role": "dimension", "field_type": "nominal"},
    {"name": "order_date", "datatype": "date", "role": "dimension", "field_type": "ordinal"},
    {"name": "sales", "datatype": "real", "role": "measure", "field_type": "quantitative"},
    {"name": "profit", "datatype": "real", "role": "measure", "field_type": "quantitative"},
]


@pytest.fixture
def wb(tmp_path):
    from twkit.book import Book

    path = tmp_path / "sales.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([x["name"] for x in FIELDS])
        w.writerow(["East", "New York", "2026-01-01", 100.5, -20.1])
        w.writerow(["West", "California", "2026-02-01", 300.0, 45.0])
    e = Book()
    e.set_csv_connection(str(path), fields=FIELDS)
    return e


class _Tools:

    def __init__(self):
        self.fns = {}

    def tool(self, *a, **k):
        def deco(fn):
            self.fns[fn.__name__] = fn
            return fn
        return deco


def _mcp_tool(monkeypatch, register: str, name: str, editor):
    from twkit.server import session, tools_twkit

    monkeypatch.setattr(session, "_active", {"book": editor})
    t = _Tools()
    getattr(tools_twkit, register)(t)
    return t.fns[name]


def _ws(e, name):
    return e.root.find(f".//worksheet[@name='{name}']")


def _measure_table(wb):
    wb.add_worksheet("S")
    wb.configure_chart("S", mark_type="Text", rows=["region"],
                       measure_values=["SUM(sales)", "SUM(profit)"])
    return wb


def test_edit_sign_color_mcp_wrapper_reaches_xml(wb, monkeypatch):
    e = _measure_table(wb)
    tool = _mcp_tool(monkeypatch, "register_chart_edit_tools", "edit_sign_color", e)
    out = json.loads(tool("S", "sum:profit:qk:red_green_diverging_10_0, sum:sales:qk:Just black"))
    assert out == {"S": 2}, out
    encs = {en.get("field").rsplit(".", 1)[-1]: en
            for en in _ws(e, "S").iter("encoding") if en.get("attr") == "color"}
    assert encs["[sum:profit:qk]"].get("palette") == "red_green_diverging_10_0"
    assert encs["[sum:profit:qk]"].get("center") == "0"
    assert encs["[sum:sales:qk]"].get("palette") == "Just black"


def test_edit_sign_color_color_instead_of_palette_refused_without_edit(wb, monkeypatch):
    e = _measure_table(wb)
    before = etree.tostring(e.root)
    tool = _mcp_tool(monkeypatch, "register_chart_edit_tools", "edit_sign_color", e)
    out = json.loads(tool("S", "sum:profit:qk:#e15759:#59a14f"))
    assert out["applied"] == 0 and "palette name" in out["why"]
    assert etree.tostring(e.root) == before


def test_sign_color_color_pair_raises_valueerror(wb):
    e = _measure_table(wb)
    with pytest.raises(ValueError, match="palette NAME"):
        ED.sign_color(e.root, ["S"], {"sum:profit:qk": ("#e15759", "#59a14f")})


def test_spec_parse_palette_last_segment():
    assert ED.parse_sign_color_spec("sum:Δ %:qk:red_green, usr:# FTD:qk:Just black") == {
        "sum:Δ %:qk": "red_green", "usr:# FTD:qk": "Just black"}
    with pytest.raises(ValueError):
        ED.parse_sign_color_spec("profit")


def _params(wb):
    wb.add_parameter("p_metric", datatype="string", default_value="Sales",
                     domain_type="list", allowed_values=["Sales", "Profit"])
    wb.add_parameter("p_from", datatype="date", default_value="2026-01-01", domain_type="any")
    wb.add_parameter("p_n", datatype="integer", default_value="5", domain_type="range",
                     min_value="1", max_value="10")
    return wb


def _decl(e, caption):
    return {(c.get("value"), c.find("calculation").get("formula"))
            for c in e.root.iter("column")
            if c.get("caption") == caption and c.get("param-domain-type")}


def test_string_parameter_quoted(wb):
    e = _params(wb)
    assert ED.set_param_value(e.root, "p_metric", "Profit") >= 1
    assert _decl(e, "p_metric") == {('"Profit"', '"Profit"')}
    ED.set_param_value(e.root, "p_from", "2026-03-01")
    assert _decl(e, "p_from") == {("#2026-03-01#", "#2026-03-01#")}
    ED.set_param_value(e.root, "p_n", "7")
    assert _decl(e, "p_n") == {("7", "7")}
    ED.set_param_value(e.root, "p_metric", '"Sales"')
    assert _decl(e, "p_metric") == {('"Sales"', '"Sales"')}


def test_parameter_literal_doubles_quote():
    assert ED.param_literal("string", 'He said "hi"') == '"He said ""hi"""'
    assert ED.param_literal("datetime", "#2026-01-01 00:00:00#") == "#2026-01-01 00:00:00#"
    assert ED.param_literal("boolean", "true") == "true"


def test_edit_set_param_mcp_wrapper_quotes_value(wb, monkeypatch):
    e = _params(wb)
    tool = _mcp_tool(monkeypatch, "register_edit_tools", "edit_set_param", e)
    assert tool("p_metric", "Profit").endswith(": 1")
    assert _decl(e, "p_metric") == {('"Profit"', '"Profit"')}


def _space(e, sheet):
    return [en for en in _ws(e, sheet).iter("encoding") if en.get("attr") == "space"]


def test_fixed_axis_references_instance(wb):
    wb.add_worksheet("A")
    wb.configure_chart("A", mark_type="Bar", rows=["region"], columns=["SUM(sales)"],
                       axis_fixed_range={"field": "SUM(sales)", "min": 0, "max": 200000})
    (enc,) = _space(wb, "A")
    ds = wb.root.find(".//datasources/datasource[@caption='sales']").get("name")
    assert enc.get("field") == f"[{ds}].[sum:sales:qk]"
    assert (enc.get("min"), enc.get("max"), enc.get("range-type")) == ("0", "200000", "fixed")


def test_axis_without_field_takes_shelf_measure(wb):
    wb.add_worksheet("B")
    wb.configure_chart("B", mark_type="Bar", columns=["region"], rows=["SUM(sales)"],
                       axis_fixed_range={"min": 0, "max": 5, "scope": "rows"})
    (enc,) = _space(wb, "B")
    assert enc.get("field").endswith("[sum:sales:qk]") and enc.get("scope") == "rows"


def test_axis_field_on_wrong_shelf_refused(wb):
    wb.add_worksheet("C")
    with pytest.raises(ValueError, match="axis_fixed_range"):
        wb.configure_chart("C", mark_type="Bar", rows=["region"], columns=["SUM(sales)"],
                           axis_fixed_range={"field": "SUM(profit)", "min": 0, "max": 1})


def test_text_writes_label_template(wb):
    wb.add_worksheet("T")
    wb.configure_chart("T", mark_type="Text", label="SUM(sales)",
                       customized_label="Total sales: <SUM(sales)>",
                       text_format={"SUM(sales)": 'c"$"#,##0'})
    runs = [r.text for r in _ws(wb, "T").iter("run")]
    assert runs[:2] == ["Total sales: ", "<"] and runs[2].endswith("[sum:sales:qk]") \
        and runs[3] == ">", runs
    fmts = [f for f in _ws(wb, "T").iter("format") if f.get("attr") == "text-format"]
    assert len(fmts) == 1 and fmts[0].get("value") == 'c"$"#,##0'
    cells = [r for r in _ws(wb, "T").find("table/style") if r.get("element") == "cell"]
    assert len(cells) == 1


def test_label_template_without_field_refused(wb):
    wb.add_worksheet("T2")
    with pytest.raises(ValueError, match="customized_label"):
        wb.configure_chart("T2", mark_type="Text", label="SUM(sales)",
                           customized_label="Profit: <SUM(profit)>")


def test_foreign_builder_option_not_dropped(wb):
    wb.add_worksheet("P")
    with pytest.raises(ValueError, match="text_format"):
        wb.configure_chart("P", mark_type="Pie", color="region", wedge_size="SUM(sales)",
                           text_format={"SUM(sales)": "#,##0"})


def _lods(e, sheet):
    return [en.get("column") for en in _ws(e, sheet).find("table/panes/pane/encodings")
            if en.tag == "lod"]


def _country_values(e):
    return [v.get("value") for v in e.datasource.iter("semantic-value")
            if v.get("key") == "[Country].[Name]"]


def test_map_block_sets_geography_by_default(wb):
    BL.geo_map(wb, "Geo", "state", "SUM(sales)", country="United States")
    ws = _ws(wb, "Geo")
    assert ws.findtext("table/rows").endswith("[Latitude (generated)]")
    assert ws.findtext("table/cols").endswith("[Longitude (generated)]")
    assert any(c.endswith("[none:state:nk]") for c in _lods(wb, "Geo"))


def test_states_without_country_refused(wb):
    with pytest.raises(ValueError, match="country context"):
        BL.geo_map(wb, "Geo", "state", "SUM(sales)")
    assert _ws(wb, "Geo") is None


def test_country_parameter_in_semantic_values(wb):
    BL.geo_map(wb, "Geo", "state", "SUM(sales)", country="United States")
    assert _country_values(wb) == ['"United States"']
    from twkit import order
    kids = [c.tag for c in wb.datasource if isinstance(c.tag, str)]
    assert "semantic-values" in kids
    assert not order.normalize_datasource(wb.datasource), kids


def test_country_column_goes_on_detail(tmp_path):
    from twkit.book import Book

    path = tmp_path / "geo.csv"
    path.write_text("country,state,sales\nUnited States,Texas,10\nCanada,Ontario,5\n",
                    encoding="utf-8")
    e = Book()
    e.set_csv_connection(str(path), fields=[
        {"name": "country", "datatype": "string", "role": "dimension", "field_type": "nominal",
         "semantic_role": "[Country].[Name]"},
        {"name": "state", "datatype": "string", "role": "dimension", "field_type": "nominal"},
        {"name": "sales", "datatype": "real", "role": "measure", "field_type": "quantitative"}])
    BL.geo_map(e, "Geo", "state", "SUM(sales)")
    lods = _lods(e, "Geo")
    assert any(c.endswith("[none:state:nk]") for c in lods)
    assert any(c.endswith("[none:country:nk]") for c in lods), lods


def test_map_block_with_non_map_mark_refused_early(wb):
    with pytest.raises(ValueError, match="geo_map"):
        BL.geo_map(wb, "Geo2", "state", "SUM(sales)", mark="Circle")
    assert _ws(wb, "Geo2") is None


def _two_sheet_page(wb):
    for n in ("S", "T"):
        wb.add_worksheet(n)
        wb.configure_chart(n, mark_type="Bar", rows=["region"], columns=["SUM(sales)"])
    wb.add_dashboard("Page", width=900, height=600, worksheet_names=["S", "T"], layout="auto")
    return wb


def test_dimension_nested_without_source_column(wb):
    _two_sheet_page(wb)
    out = ED.place_field(wb.root, "S", "state", "rows", derivation="None")
    assert out["separator"] == "/", out
    assert ED.place_field(wb.root, "S", "profit", "columns")["separator"] == "+"


def test_hide_button_finds_engine_page_sheet(wb):
    _two_sheet_page(wb)
    out = ED.zone_hide_button(wb.root, "Page", hide=["T"], keep=["S"])
    assert out["behind_button"] == ["T"] and out["stays_visible"] == ["S"]


def test_hide_button_not_nav_button_template(wb):
    _two_sheet_page(wb)
    ED.zone_hide_button(wb.root, "Page", hide=["T"], keep=["S"])
    assert ED.add_nav_buttons(wb.root, ["Page"]) == 0
    hybrids = [b for b in wb.root.iter("button")
               if b.find("toggle-action") is not None and "goto-sheet" in (b.get("action") or "")]
    assert not hybrids
    assert "no navigation button to copy" in ED.nav_buttons_absent_reason(wb.root, ["Page"])


def test_color_steps_on_default_palette_reported(wb):
    _two_sheet_page(wb)
    out = ED.set_color_steps(wb.root, ["S", "None"], 2)
    assert out["sheet_count"] == 0
    assert out["no_color_encoding"] == ["S"] and out["missing_sheets"] == ["None"]
    assert ED.set_color_range(wb.root, ["S"])["no_color_encoding"] == ["S"]

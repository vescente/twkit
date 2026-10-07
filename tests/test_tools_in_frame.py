"""The frame interprets the toolkit: every MCP tool that changes the look changes the frame.

Each tool that changes a workbook is either VISIBLE (applied to a small CSV workbook through the MCP
server, it must change the XML and the frame's HTML), NOT_IN_FRAME (nothing on the page changes by
nature) or NOT_ON_FIXTURE (needs what the fixture does not have). Tools named like READ_ONLY only
read. A new tool fails the suite until it is put in one of these.
"""
import asyncio
import os
import re

import pytest
from lxml import etree

import _matrix_book as M
from twkit import frame as FR
from twkit import safexml

pytest.importorskip("mcp")
from twkit.server.app import register_all  # noqa: E402

server = register_all()

FILTER = ("edit_apply_filter", dict(sheets="Bars", field="product", member="Casino"))
HEAT = ("edit_heat_columns", dict(sheet="Table"))
CLONE = ("edit_clone_dashboard", dict(source="Overview", name="Copy", sheet_map_json="{}", with_button=False))

VISIBLE = [
    (*CLONE, []),
    ("edit_set_param", dict(caption="Metric", value="Cost"), []),
    ("edit_retune_filter", dict(field="product", values="Casino,Sport"), [FILTER]),
    ("edit_column_width", dict(sheet="Table", field="country", px=220), []),
    ("edit_row_height", dict(sheet="Table", px=40), []),
    ("edit_fit_column_width", dict(sheet="Table", field="country", labels=M.COUNTRIES), []),
    ("edit_grand_total", dict(sheet="Table"), []),
    ("edit_number_format", dict(field="Margin", mask='c"€ "#,##0'), []),
    ("edit_apply_house_format", dict(field="Margin", kind="money"), []),
    ("edit_drop_case_branches", dict(values="Sales", calcs="Chosen Value"), []),
    ("edit_add_case_branches", dict(calcs="Chosen Value", branches="Orders = SUM([orders])"),
     [("edit_add_param_members", dict(params="Metric", values="Orders")),
      ("edit_set_param", dict(caption="Metric", value="Orders"))]),
    ("edit_zone_hide_button", dict(dashboard="Overview", hide="Bars", keep="Table"), []),
    ("edit_zone_text", dict(dashboard="Overview", text="Notes for the reader"), []),
    ("edit_set_formula", dict(calc="Margin", formula="SUM([sales]) - 2 * SUM([cost])"), []),
    ("edit_zone_title", dict(dashboard="Overview", titles="@PARAMZONE = Pick a metric"), []),
    ("edit_rename_dashboard", dict(old="Overview", new="Summary"), []),
    ("edit_remove_field", dict(sheet="Bars", field="country"), []),
    ("edit_tooltip", dict(sheet="Bars", lines="Country=country; Sales=sales"), []),
    ("edit_range_filter", dict(sheet="Bars", field="sales", low="300000"), []),
    ("edit_relative_date_filter", dict(sheet="Trend", field="date", period="month", first=-1, last=0), []),
    ("edit_sort_by_measure", dict(sheet="Bars", dimension="country", by="sales", direction="asc"), []),
    ("edit_top_n", dict(sheet="Bars", dimension="country", by="sales", count="3"), []),
    ("edit_exclude_members", dict(sheet="Bars", field="country", members="Germany"), []),
    ("edit_swap_axes", dict(sheets="Bars"), []),
    ("edit_place_field", dict(sheet="Bars", field="product", shelf="rows", derivation="None"), []),
    ("edit_sheet_swap", dict(param="Metric", mapping="Bars=Sales,Chosen=Cost"), []),
    (*HEAT, []),
    ("edit_dual_axis", dict(sheet="Trend", field="Margin"), []),
    ("edit_kpi_tile", dict(sheet="KPI", caption="Sales"), []),
    ("edit_text_card", dict(sheet="KPI", column="product",
                            lines='[{"field": "[sales]", "size": "18", "bold": true}]'), []),
    ("edit_mark_color", dict(sheet="Bars", color="#e15759"), []),
    ("edit_show_zone_title", dict(dashboard="Overview", sheets="Bars", show=True), []),
    ("edit_add_measure", dict(sheet="Table", field="orders"), []),
    ("edit_order_measures", dict(sheet="Table", fields="Margin, cost, sales"), []),
    ("edit_color_range", dict(sheets="Table", reversed_scale=True), [HEAT]),
    ("edit_color_steps", dict(sheets="Table", steps=2), [HEAT]),
    ("edit_copy_color_encoding", dict(donor="Palette", sheets="Table"),
     [("edit_heat_columns", dict(sheet="Palette"))]),
    ("edit_sign_color", dict(sheets="Table", measures="usr:Margin:qk:red_green_diverging_10_0, "
                             "sum:sales:qk:Just black, sum:cost:qk:Just black"), []),
    ("edit_stack_page", dict(dashboard="Overview", items='[{"kind":"sheet","name":"Table","h":300},'
                             '{"kind":"row","sheets":["Bars","Trend"],"h":300}]'), []),
    ("edit_zone_fit", dict(dashboard="Overview", sheets="Table", mode="stretch"), []),
    ("edit_zone_style", dict(dashboard="Overview", sheets="Bars", background="#fff3e0"), []),
    (*FILTER, []),
    ("edit_control_column", dict(dashboard="Overview", refs="Bars|[@DS].[none:product:nk]"), [FILTER]),
    ("edit_transpose_flow", dict(dashboard="Grid", zone_id="@GRIDZONE"), []),
    ("configure_chart", dict(worksheet_name="Bars", mark_type="Circle", rows=["country"],
                             columns=["SUM(sales)"]), []),
    ("configure_dual_axis", dict(worksheet_name="Trend", mark_type_1="Line", mark_type_2="Bar",
                                 columns=["MONTH(date)"], rows=["SUM(sales)", "SUM(cost)"]), []),
    ("configure_worksheet_style", dict(worksheet_name="Bars", background_color="#fff3e0"), []),
    ("add_reference_line", dict(worksheet_name="Trend", axis_field="SUM(sales)", value_field="SUM(sales)",
                                formula="average"), []),
    ("add_dashboard", dict(dashboard_name="Second", worksheet_names=["Bars"]), []),
    ("rename_worksheet", dict(old="Bars", new="Sales bars"), []),
    ("set_caption", dict(name="Margin", caption="Profit margin"), []),
    ("remove_worksheet", dict(name="Bars"), []),
    ("remove_dashboard", dict(name="Copy"), [CLONE]),
    ("set_csv_connection", dict(filepath="@CSV2", fields=M.FIELDS), []),
]
NOT_IN_FRAME = {
    "edit_folder_canon": "data pane folders",
    "edit_fit_to_extract": "data source mapping",
    "edit_to_live_sql": "connection",
    "edit_drop_fields": "fields no sheet uses",
    "edit_rename_fields": "internal names; the page shows captions (set_caption)",
    "edit_repair_dashboards": "repair: viewpoints, zone ids, repeated shelf fields",
    "edit_repair_node_order": "repair: node order",
    "edit_fix_format_attrs": "repair: attribute names",
    "edit_dedupe_style_rules": "repair: repeated style rules",
    "edit_finish_windows": "window state of the file",
    "edit_reorder_pages": "tab order",
    "edit_add_sheet": "a sheet is drawn once it is placed on a page",
    "edit_filter_context": "context changes nothing without a dependent filter",
    "edit_drop_param_members": "a compact parameter control shows only the current value",
    "edit_add_param_members": "a compact parameter control shows only the current value",
    "edit_sheet_fit": "on a page the zone's viewpoint decides the fit (edit_zone_fit)",
    "edit_table_calc": "declares a field; drawn once placed, see the running total test",
    "edit_fit_tables": "frame-driven itself; needs Chrome (test_fit_tables_once)",
    "add_calculated_field": "declares a field; drawn once placed",
    "add_parameter": "declares a parameter; drawn as a control once placed",
    "add_worksheet": "a sheet is drawn once it is placed on a page",
    "clone_worksheet": "a sheet is drawn once it is placed on a page",
    "add_dashboard_action": "acts on click or hover",
    "set_worksheet_hidden": "the sheet tab, not the page",
    "save_as_extract": "writes another file with the same data",
    "install_palette": "declares palettes in Preferences.tps; drawn once a sheet uses one",
    "create_view": "a database object, not the workbook",
    "remove_calculated_field": "removes only a field no sheet uses; refuses otherwise",
    "set_worksheet_caption": "shown only where the caption is switched on",
}
NOT_ON_FIXTURE = {
    "edit_put_controls_over": "needs a layout-basic parent; dash.add builds flow layouts",
    "edit_align_left_column": "needs a left column in a layout-basic parent (absolute coordinates)",
    "set_mysql_connection": "needs a database server",
    "set_hyper_connection": "needs a .hyper extract",
}
READ_ONLY = ("list_", "check_", "describe", "show_", "get_", "lint", "validate", "dry_run", "frame",
             "look", "view", "tableau_", "screenshot", "preflight", "style_score", "table_schema",
             "metric_canon", "run_sql", "palette", "number_formats", "spec_reference", "story_reference",
             "param_recipe", "sizing_recipe", "switcher_formula", "table_calc_recipes", "house_style",
             "design_rules", "naming_rules", "report_doc", "file_format", "find_idiom", "diff_",
             "profile_", "preview_", "propose_", "inspect_", "analyze_", "selfcheck", "build_reports",
             "sketch", "verify_data", "layout_", "generate_", "open_workbook", "save_workbook",
             "create_workbook", "owner_")


def _call(tool: str, kw: dict) -> str:
    r = asyncio.run(server.call_tool(tool, kw))
    blocks = r[0] if isinstance(r, tuple) else r
    return " ".join(getattr(b, "text", str(b)) for b in blocks)


@pytest.fixture(scope="module")
def book(tmp_path_factory):
    folder = str(tmp_path_factory.mktemp("matrix"))
    path = M.build(folder)
    root = safexml.from_twbx(path)
    marks = {
        "@DS": next(d.get("name") for d in root.iter("datasource")
                    if (d.get("name") or "").startswith("federated")),
        "@PARAMZONE": next(z.get("id") for z in root.iter("zone") if z.get("type-v2") == "paramctrl"),
        "@CSV2": os.path.join(folder, "sales_doubled.csv"),
        "@GRIDZONE": next(z.get("id") for d in root.iter("dashboard") if d.get("name") == "Grid"
                          for z in d.iter("zone") if z.get("param") == "horz"),
    }
    return {"folder": folder, "path": path, "marks": marks, "base": {}}


def _fill(book, kw: dict) -> dict:
    out = {}
    for k, v in kw.items():
        if isinstance(v, str):
            for m, val in book["marks"].items():
                v = v.replace(m, val)
        out[k] = v
    return out


def _state(book, tag: str, steps: list) -> str:
    _call("open_workbook", {"file_path": book["path"]})
    said = ""
    for tool, kw in steps:
        said = _call(tool, _fill(book, kw))
    dst = os.path.join(book["folder"], tag + ".twbx")
    saved = _call("save_workbook", {"output_path": dst})
    assert os.path.exists(dst), f"not saved after {steps[-1][0] if steps else 'open'}: {saved} | {said}"
    return dst


def _html(path: str) -> dict:
    out = FR.publish(path, out_dir=os.path.join(os.path.dirname(path), "frame_" + os.path.basename(path)))
    pages = {}
    for pg in out["pages"]:
        with open(pg["file"], encoding="utf-8") as f:
            h = f.read()
        h = re.sub(r"<title>.*?</title>", "", h).replace(os.path.basename(path)[:-5], "BOOK")
        pages[pg["page"]] = re.sub(r"(file://|/var/|/private/|/tmp/)[^'\"\s)]*", "", h)
    return pages


def _xml(path: str) -> bytes:
    return re.sub(rb"\{[0-9A-F-]{36}\}", b"", etree.tostring(safexml.from_twbx(path)))


def test_every_tool_that_changes_a_workbook_is_classified():
    tools = {t.name for t in asyncio.run(server.list_tools()) if not t.name.startswith(READ_ONLY)}
    known = {t for t, _, _ in VISIBLE} | set(NOT_IN_FRAME) | set(NOT_ON_FIXTURE)
    assert tools - known == set(), "classify the new tool in tests/test_tools_in_frame.py"
    assert known - tools == set(), "a classified tool no longer exists"


@pytest.mark.parametrize("tool,kw,pre", VISIBLE, ids=[f"{t}-{i}" for i, (t, _, _) in enumerate(VISIBLE)])
def test_visible_tool_changes_the_frame(book, tool, kw, pre):
    key = repr(pre)
    if key not in book["base"]:
        p0 = _state(book, f"base{len(book['base'])}", pre)
        book["base"][key] = (_xml(p0), _html(p0))
    x0, h0 = book["base"][key]
    p1 = _state(book, f"{tool}-{len(pre)}", pre + [(tool, kw)])
    assert _xml(p1) != x0, f"{tool} changed nothing in the XML: the recipe is stale"
    assert _html(p1) != h0, f"{tool} changed the workbook but the frame drew the same page"


def test_running_total_is_computed_in_frame(book):
    p = _state(book, "running", [
        ("edit_table_calc", dict(caption="Running Sales", kind="running total", field="sales",
                                 sheets="Table", direction="down")),
        ("edit_add_measure", dict(sheet="Table", field="Running Sales", derivation="User"))])
    text = re.sub(r"<[^>]+>", "|", _html(p)["Overview"])
    totals: dict = {}
    import csv
    with open(os.path.join(book["folder"], "sales.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            totals[r["country"]] = totals.get(r["country"], 0.0) + float(r["sales"])
    acc = 0.0
    for c in sorted(totals):
        acc += totals[c]
        assert f"{acc:,.0f}" in text, (c, acc)

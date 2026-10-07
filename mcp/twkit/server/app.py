"""The FastMCP server instance, its instructions and the entry point."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

INSTRUCTIONS = (
    "HOW TO BUILD A DASHBOARD (follow the order, do not skip steps).\n"
    "\n"
    "STEP 1: LEARN THE STYLE. house_style_rules (house style, overrides generic design advice), "
    "then design_rules (composition, choice of form, depth of analysis).\n"
    "\n"
    "STEP 2: LEARN THE DATA. list_tables, table_schema (available tables and columns), "
    "metric_canon (HOW to compute a metric; outside the canon numbers are silently wrong).\n"
    "\n"
    "STEP 3: BUILD. Preferred: spec_reference + validate_spec, describe the dashboard as a "
    "YAML spec and build it from tested blocks (list_blocks: KPI, thresholds, top-N, trend, "
    "heatmap, map). Freely generated XML regularly produces files Tableau will not open. "
    "Parameters: param_recipe + switcher_formula; formats: number_formats; colors: palette; "
    "control panel: layout_control_panel; stretching: sizing_recipe. Always save as .twbx "
    "(file_format_rule).\n"
    "\n"
    "STEP 4: CHECK. One call: preflight runs every channel and says whether to deliver. Read "
    "the whole output including 'not checked': a check that could not run does NOT mean fine. "
    "Verdict 'DO NOT hand over': fix and rebuild.\n"
    "Individual channels: lint_workbook (will the file open), check_metric_canon (are formulas "
    "right), dry_run_workbook (will there be data), check_dead_dimensions (do filters have "
    "values), check_visual (do labels fit, are small values visible), style_score (style "
    "fit), check_workbook_columns (references to removed columns make Tableau show nothing).\n"
    "\n"
    "STEP 5: LOOK. None of the checks above sees what Tableau DREW. frame_publish renders a "
    "model of the workbook without Tableau; screenshot_workbook opens the workbook and "
    "captures the window; open the image with Read and look. tableau_log: what Tableau "
    "itself logged on opening. view_thumbnails: previews embedded at save time.\n"
    "\n"
    "DO NOT publish workbooks or upload to Tableau Cloud: that is the human's quality gate. "
    "Do not treat a check as passed if the tool could not run.\n"
    "\n"
    "STYLE: a dashboard without parameters is not self-service. Minimum: a date pair, "
    "granularity, a metric switcher and dimension switchers.\n"
    "\n"
    "SESSION: create_workbook or open_workbook makes a workbook active; the build tools "
    "(set_*_connection, add_*, configure_*) and edit tools change it in memory; save_workbook "
    "is the only tool that writes it to disk. Call tools directly; if the tool list looks "
    "empty, ask the user to reconnect the MCP client."
)

server = FastMCP("twkit", instructions=INSTRUCTIONS)
_registered = {"done": False}


def register_all() -> FastMCP:
    """Import every tool module once so its tools land on `server`."""
    if not _registered["done"]:
        from . import tools_book, tools_twkit  # noqa: F401
        _registered["done"] = True
    return server


def main() -> None:
    register_all()
    server.run()

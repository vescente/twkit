"""Build tools: create, connect, add sheets and dashboards, configure charts, save."""
from __future__ import annotations

import json
import os

from ..book import Book
from .app import server
from .session import active, current, use


def _err(exc: Exception) -> str:
    return f"ERROR: {type(exc).__name__}: {exc}"


def _run(fn, *a, **k) -> str:
    try:
        out = fn(*a, **k)
    except Exception as exc:                  # noqa: BLE001 — the client reads the reason
        return _err(exc)
    return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2)


def save_checked(book: Book, output_path: str, force: bool = False) -> str:
    """Save, refusing a blocker (columns missing from the extract, a format error) unless forced."""
    from ..owner import check_write
    try:
        check_write(str(output_path))
    except PermissionError as exc:
        return f"REFUSED: {exc}"
    if not str(output_path).lower().endswith(".twbx"):
        return "REFUSED: save as .twbx only (file_format_rule)"
    base, ext = os.path.splitext(str(output_path))
    tmp = f"{base}.checking{ext}"
    book.save(tmp)
    problems, note = [], ""
    try:
        from ..extract import stale_extract_refs
        from ..lint import lint
        dead = stale_extract_refs(tmp).get("dead") or []
        if dead:
            problems.append("missing from the extract: " + ", ".join(dead[:5])
                            + "; Tableau will show NOTHING on every sheet")
        errs = [v for v in lint(tmp) if v.severity == "error"]
        if errs:
            problems.append("format: " + errs[0].message[:100])
    except Exception as exc:                  # noqa: BLE001 — said, not hidden
        note = (f"\n! CHECKS NOT RUN ({type(exc).__name__}: {str(exc)[:70]}); "
                f"blockers NOT ruled out")
    if problems and not force:
        os.unlink(tmp)
        return ("NOT SAVED: the workbook has a blocker:\n  - " + "\n  - ".join(problems)
                + "\n\nFix it (edit_fit_to_extract / edit_drop_fields) and save again, "
                  "or save_workbook(..., force=True) if intended.")
    os.replace(tmp, output_path)
    book.path = str(output_path)
    out = f"Saved {output_path}"
    try:
        from ..extract import drop_packaged_extracts, packaged_extracts
        extra = packaged_extracts(output_path)["extra"]
        if extra:
            freed = drop_packaged_extracts(output_path)["bytes_freed"]
            out += (f"\nremoved unreachable extracts ({len(extra)}, {freed // 1024} KB): "
                    f"no relation points to them")
    except Exception as exc:                  # noqa: BLE001
        out += f"\n! unreachable extracts NOT checked ({type(exc).__name__})"
    out += note
    if problems:
        return out + f"\n! saved with a blocker (force): {'; '.join(problems)}"
    return out if note else out + "\nchecked: source and format are clean"


@server.tool()
def get_mcp_status() -> dict:
    """Server state: the active workbook and the rules every session follows."""
    b = active()
    return {
        "server": "twkit",
        "active_workbook": (b.path or "(new, not saved)") if b is not None else None,
        "worksheets": b.list_worksheets() if b is not None else [],
        "rules": ["save .twbx only", "never publish", "the owner's workbooks are written only "
                  "through owner_install", "preflight before handing a workbook over"],
    }


@server.tool()
def create_workbook(template_path: str = "", workbook_name: str = "") -> str:
    """Start a new workbook in memory. `template_path`: start from a file's data sources,
    without its sheets and dashboards."""
    try:
        if template_path:
            b = Book.open(template_path)
            for tag in ("worksheets", "dashboards", "windows", "actions", "thumbnails"):
                for el in b.root.findall(tag):
                    b.root.remove(el)
            b.path = ""
        else:
            b = Book()
    except Exception as exc:                  # noqa: BLE001
        return _err(exc)
    use(b)
    return f"Created workbook {workbook_name or '(unnamed)'}; connect a data source next"


@server.tool()
def open_workbook(file_path: str) -> str:
    """Open a .twb or .twbx as the active workbook (edits stay in memory until save_workbook)."""
    try:
        b = use(Book.open(file_path))
    except Exception as exc:                  # noqa: BLE001
        return _err(exc)
    return (f"Opened {file_path}: {len(b.list_worksheets())} worksheets, "
            f"{len(b.list_dashboards())} dashboards")


@server.tool()
def list_fields() -> str:
    """Fields of the active workbook: caption, role, datatype, formula."""
    return _run(lambda: current().list_fields())


@server.tool()
def list_worksheets() -> str:
    """Worksheet names of the active workbook."""
    return _run(lambda: current().list_worksheets())


@server.tool()
def list_dashboards() -> str:
    """Dashboards of the active workbook with the sheets each one shows."""
    return _run(lambda: current().list_dashboards())


@server.tool()
def add_calculated_field(field_name: str, formula: str, datatype: str = "real", role: str = "",
                         field_type: str = "", table_calc: str | dict | None = None,
                         default_format: str = "", internal_name: str = "") -> str:
    """A calculated field. Reference fields as `[name]`, other calculations and parameters by
    caption (`[Parameters].[Metric]`); they are stored under their internal names. A caption
    another field already has is refused (lint R42)."""
    return _run(lambda: current().add_calculated_field(
        field_name, formula, datatype=datatype, role=role or None, field_type=field_type or None,
        table_calc=table_calc, default_format=default_format, internal_name=internal_name or None))


@server.tool()
def remove_calculated_field(field_name: str) -> str:
    """Remove a calculated field no sheet uses; a field still on a sheet is refused."""
    return _run(lambda: current().remove_calculated_field(field_name))


@server.tool()
def add_parameter(name: str, datatype: str = "real", default_value: str = "0",
                  domain_type: str = "range", min_value: str = "", max_value: str = "",
                  granularity: str = "", allowed_values: list[str] | None = None,
                  default_format: str = "", internal_name: str = "", alias: str = "",
                  allowed_aliases: dict[str, str] | None = None) -> str:
    """A parameter: `domain_type` range (min/max/granularity), list (allowed_values, optional
    allowed_aliases) or any. Dates are written as `#YYYY-MM-DD#`."""
    return _run(lambda: current().add_parameter(
        name, datatype=datatype, default_value=default_value, domain_type=domain_type,
        min_value=min_value, max_value=max_value, granularity=granularity,
        allowed_values=allowed_values, default_format=default_format,
        internal_name=internal_name or None, alias=alias or None,
        allowed_aliases=allowed_aliases))


@server.tool()
def add_worksheet(worksheet_name: str) -> str:
    """An empty worksheet; configure_chart fills it."""
    return _run(lambda: current().add_worksheet(worksheet_name))


@server.tool()
def clone_worksheet(source_worksheet: str, target_worksheet: str) -> str:
    """A copy of a worksheet under a new name."""
    return _run(lambda: current().clone_worksheet(source_worksheet, target_worksheet))


@server.tool()
def set_worksheet_caption(worksheet_name: str, caption: str) -> str:
    """The sheet caption (shown where the caption is switched on)."""
    return _run(lambda: current().set_worksheet_caption(worksheet_name, caption))


@server.tool()
def set_worksheet_hidden(worksheet_name: str, hidden: bool = True) -> str:
    """Hide or show a worksheet's tab."""
    return _run(lambda: current().set_worksheet_hidden(worksheet_name, hidden))


@server.tool()
def configure_chart(worksheet_name: str, mark_type: str = "Automatic",
                    columns: list[str] | None = None, rows: list[str] | None = None,
                    color: str | None = None, size: str | None = None, label: str | None = None,
                    detail: str | list[str] | None = None, wedge_size: str | None = None,
                    sort_descending: str | None = None, tooltip: str | list[str] | None = None,
                    filters: list[dict] | None = None, geographic_field: str | None = None,
                    measure_values: list[str] | None = None, mark_sizing_off: bool = False,
                    axis_fixed_range: dict | None = None, customized_label: str | None = None,
                    color_map: dict[str, str] | None = None,
                    text_format: dict[str, str] | None = None,
                    label_extra: list[str] | None = None, map_country: str | None = None,
                    datasource: str = "") -> str:
    """Build a worksheet's chart; replaces what was there.

    Fields: `country`, `SUM(sales)`, `AVG(x)`, `COUNTD(id)`, `MONTH(date)`, `MONTHTRUNC(date)`
    (continuous), a calculation by caption. A bare measure is summed; a bare date is the exact
    date (name it MONTH(x) or MONTHTRUNC(x) for months).
    mark_type: Automatic, Bar, Line, Area, Circle, Square, Shape, Text, Pie, Tree Map, Map.
    filters: `{"column": f, "values": [...]}`, `{"column": f, "top": 10, "by": "SUM(x)",
    "direction": "DESC"}`, `{"column": f, "min": a, "max": b}`.
    sort_descending: a measure (sorts the innermost dimension by it) or a dimension (sorted by
    the first measure). measure_values: a measure table (Measure Names on columns).
    geographic_field + map_country: a map; states and cities need a country context.
    customized_label: text with `<SUM(x)>` placeholders of fields already on the label.
    color_map: fixed colors of a color dimension's values. text_format: number masks per field.
    datasource: name or caption of another data source; by default the sheet keeps its own.
    """
    return _run(lambda: current().configure_chart(
        worksheet_name, mark_type=mark_type, columns=columns, rows=rows, color=color, size=size,
        label=label, detail=detail, wedge_size=wedge_size, sort_descending=sort_descending,
        tooltip=tooltip, filters=filters, geographic_field=geographic_field,
        measure_values=measure_values, mark_sizing_off=mark_sizing_off,
        axis_fixed_range=axis_fixed_range, customized_label=customized_label,
        color_map=color_map, text_format=text_format, label_extra=label_extra,
        map_country=map_country, datasource=datasource))


@server.tool()
def configure_dual_axis(worksheet_name: str, mark_type_1: str = "Bar", mark_type_2: str = "Line",
                        columns: list[str] | None = None, rows: list[str] | None = None,
                        dual_axis_shelf: str = "rows", color_1: str | None = None,
                        size_1: str | None = None, label_1: str | None = None,
                        detail_1: str | None = None, color_2: str | None = None,
                        size_2: str | None = None, label_2: str | None = None,
                        detail_2: str | None = None, synchronized: bool = True,
                        sort_descending: str | None = None, filters: list[dict] | None = None,
                        show_labels: bool = True, hide_axes: bool = False,
                        hide_zeroline: bool = False, mark_color_1: str | None = None,
                        mark_color_2: str | None = None,
                        color_map_1: dict[str, str] | None = None) -> str:
    """Two measures on one shelf (rows by default), each with its own mark, on a dual axis."""
    return _run(lambda: current().configure_dual_axis(
        worksheet_name, mark_type_1=mark_type_1, mark_type_2=mark_type_2, columns=columns,
        rows=rows, dual_axis_shelf=dual_axis_shelf, color_1=color_1, size_1=size_1,
        label_1=label_1, detail_1=detail_1, color_2=color_2, size_2=size_2, label_2=label_2,
        detail_2=detail_2, synchronized=synchronized, sort_descending=sort_descending,
        filters=filters, show_labels=show_labels, hide_axes=hide_axes,
        hide_zeroline=hide_zeroline, mark_color_1=mark_color_1, mark_color_2=mark_color_2,
        color_map_1=color_map_1))


@server.tool()
def configure_worksheet_style(worksheet_name: str, background_color: str | None = None,
                              hide_axes: bool = False, hide_gridlines: bool = False,
                              hide_zeroline: bool = False, hide_borders: bool = False,
                              hide_band_color: bool = False, hide_row_label: str | None = None,
                              hide_col_field_labels: bool = False,
                              hide_row_field_labels: bool = False, disable_tooltip: bool = False,
                              label_formats: list[dict] | None = None,
                              cell_formats: list[dict] | None = None,
                              header_formats: list[dict] | None = None) -> str:
    """Sheet formatting: background, axes, grid, zero line, borders, bands, field labels,
    a row header to hide, tooltips off, label/cell/header formats (`[{"font-size": "9"}]`)."""
    return _run(lambda: current().configure_worksheet_style(
        worksheet_name, background_color=background_color, hide_axes=hide_axes,
        hide_gridlines=hide_gridlines, hide_zeroline=hide_zeroline, hide_borders=hide_borders,
        hide_band_color=hide_band_color, hide_row_label=hide_row_label,
        hide_col_field_labels=hide_col_field_labels, hide_row_field_labels=hide_row_field_labels,
        disable_tooltip=disable_tooltip, label_formats=label_formats, cell_formats=cell_formats,
        header_formats=header_formats))


@server.tool()
def add_reference_line(worksheet_name: str, axis_field: str, value_field: str,
                       scope: str = "per-pane", formula: str = "average",
                       label_type: str = "value", tooltip: str = "",
                       pane_index: int = 0) -> str:
    """A reference line on a measure axis: formula average, median, max, min, sum, total."""
    return _run(lambda: current().add_reference_line(
        worksheet_name, axis_field=axis_field, value_field=value_field, scope=scope,
        formula=formula, label_type=label_type, tooltip=tooltip, pane_index=pane_index))


@server.tool()
def set_csv_connection(filepath: str, delimiter: str = "", charset: str = "utf-8-sig",
                       fields: list[dict] | None = None) -> str:
    """A CSV file as the data source, packaged into the .twbx. `fields`:
    `[{"name", "datatype", "role", "field_type", "semantic_role"}]`; read from the file when
    omitted."""
    return _run(lambda: current().set_csv_connection(filepath, delimiter=delimiter,
                                                     charset=charset, fields=fields))


@server.tool()
def set_hyper_connection(filepath: str, table_name: str = "Extract",
                         tables: list[dict] | None = None) -> str:
    """A .hyper extract as the data source, packaged under Data/Extracts. Several `tables`
    (`[{"name", "columns"}]`) are related on their first shared column."""
    return _run(lambda: current().set_hyper_connection(filepath, table_name=table_name,
                                                       tables=tables))


@server.tool()
def set_mysql_connection(server: str, dbname: str, username: str, table_name: str,
                         port: str = "3306", custom_sql: str = "") -> str:
    """A live MySQL-protocol connection to a table, or to `custom_sql`. Tableau asks for the
    password when the workbook opens; no password is stored."""
    return _run(lambda: current().set_mysql_connection(server, dbname, username, table_name,
                                                       port=port, custom_sql=custom_sql))


@server.tool()
def add_dashboard(dashboard_name: str, worksheet_names: list[str] | None = None,
                  width: int = 1200, height: int = 800, layout: str | dict = "auto") -> str:
    """A dashboard. `layout`: auto, vertical, horizontal, grid-2x2, a JSON/YAML file, or a tree
    of nodes: container (direction, children), worksheet (name, show_title, fit), text (text,
    font_size, bold), title, paramctrl (parameter), filter (worksheet, field), color
    (worksheet, field), empty. Any node takes `weight` or `fixed_size` (px)."""
    return _run(lambda: current().add_dashboard(dashboard_name, width=width, height=height,
                                                layout=layout, worksheet_names=worksheet_names))


@server.tool()
def add_dashboard_action(dashboard_name: str, action_type: str, source_sheet: str,
                         target_sheet: str = "", fields: list[str] | None = None,
                         event_type: str = "on-select", caption: str = "", url: str = "",
                         source_field: str = "", target_parameter: str = "",
                         aggregation: str = "attr", clear_behavior: str = "keep-current",
                         clear_value: str = "") -> str:
    """A dashboard action: filter (fields), highlight, url, or parameter (source_field,
    target_parameter, clear_value such as `s:LROOT:All`)."""
    return _run(lambda: current().add_dashboard_action(
        dashboard_name, action_type, source_sheet, target_sheet=target_sheet, fields=fields,
        event_type=event_type, caption=caption, url=url, source_field=source_field,
        target_parameter=target_parameter, aggregation=aggregation,
        clear_behavior=clear_behavior, clear_value=clear_value))


@server.tool()
def save_workbook(output_path: str, force: bool = False) -> str:
    """Write the active workbook to a .twbx: the only tool that writes it. A blocker (columns
    missing from the extract, a format error) refuses the save unless `force`; the owner's
    workbooks are refused (owner_install writes them)."""
    try:
        return save_checked(current(), output_path, force=force)
    except Exception as exc:                  # noqa: BLE001
        return _err(exc)


@server.tool()
def validate_workbook(file_path: str = "") -> str:
    """XSD check of the active workbook or a file; informational, Tableau accepts more."""
    from .. import safexml, xsd
    try:
        root = safexml.from_twbx(file_path) if file_path else current().root
        res = xsd.validate(root)
    except Exception as exc:                  # noqa: BLE001
        return _err(exc)
    if not res["available"]:
        return "XSD not found: check skipped"
    state = "valid" if res["ok"] else f"{len(res['errors'])} notes"
    head = f"{res['schema']}: {state}"
    return "\n".join([head] + res["errors"][:20])

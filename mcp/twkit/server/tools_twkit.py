"""Toolkit tools: house style, tables and metric canon, checks, edits, views, the owner's workbook."""
from __future__ import annotations

import json
import os

from twkit import blocks as BL
from twkit import canon as CANON
from twkit import dryrun as DRY
from twkit import lint as LINT
from twkit import schema as SC
from twkit import style as S

from .app import server

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))



@server.tool()
def house_style_rules() -> str:
    """House dashboard style measured from a corpus of working workbooks. Read FIRST.

    Takes priority over generic design advice. Key point: a dashboard without parameters is
    off-style (median 7 distinct parameters per workbook).
    """
    path = os.path.join(_ROOT, "docs", "STYLE_GUIDE.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return "STYLE_GUIDE.md not found"

@server.tool()
def edit_folder_canon(path: str, datasource: str = "",
                      dims: str = "", dates: str = "") -> str:
    """Sort data pane fields into the canonical folders: Fields, Date, Measures, Calcs, System.

    `dims` / `dates`: comma-separated fields forced into Fields and Date when the column type
    cannot tell. The file is rewritten in place; run lint_workbook (R35) afterwards.
    """
    from twkit import safexml
    from twkit.edit import apply_folder_canon
    from twkit import order as ORD
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    root = safexml.from_twbx(path)
    got = apply_folder_canon(
        root, datasource=datasource,
        dims=tuple(x.strip() for x in dims.split(",") if x.strip()),
        dates=tuple(x.strip() for x in dates.split(",") if x.strip()))
    ORD.normalize_workbook(root)
    safexml.to_twbx(path, root, path)
    return json.dumps({"sorted": got}, ensure_ascii=False, indent=2)

@server.tool()
def report_doc_standard() -> str:
    """Standard for a dashboard description document (e.g. for Confluence).

    Read BEFORE writing a report description. Facts only: what it shows and how it is computed;
    no caveats, no justifications. Gives the required sections, rules per section and a checklist.
    """
    path = os.path.join(_ROOT, "docs", "REPORT_DOC_STANDARD.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return "REPORT_DOC_STANDARD.md not found"

@server.tool()
def naming_rules() -> str:
    """Naming and data pane folders: how to name fields, sheets, parameters and where to put them.

    Read together with house_style_rules before building. Checked by the linter (R35).
    """
    path = os.path.join(_ROOT, "docs", "NAMING_RULES.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return "NAMING_RULES.md not found"

@server.tool()
def design_rules() -> str:
    """How to build a clear, insightful dashboard: composition, choice of form, depth of analysis.

    Read second, after house_style_rules: skeleton, form per task, color by data role,
    techniques that make a number readable without its author, and a delivery checklist.
    """
    path = os.path.join(_ROOT, "docs", "DESIGN_KB.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return "DESIGN_KB.md not found"

@server.tool()
def file_format_rule() -> str:
    """Project rule: always save workbooks as .twbx, never .twb."""
    return json.dumps({
        "rule": "save_workbook always with the .twbx extension",
        "why": "one format for every workbook; Tableau saves .twbx itself "
               "once an extract exists",
        "note": ".twbx = ZIP of the .twb plus data. With a live connection it holds no data "
                "(just the zipped .twb); that is fine",
        "example": 'save_workbook("out/Dashboard.twbx")',
    }, ensure_ascii=False, indent=2)

@server.tool()
def palette() -> str:
    """House palette (Tableau 20) and utility colors, as JSON."""
    return json.dumps({
        "palette": S.PALETTE,
        "series": S.SERIES, "accent": S.ACCENT,
        "negative": S.NEGATIVE, "neutral": S.NEUTRAL,
        "band_color": S.BAND_COLOR, "surface": S.SURFACE, "transparent": S.TRANSPARENT,
        "rule": "color encodes identity, NOT rank: color ranked bars with one tone, "
                "otherwise the survivors change color when filtered",
    }, ensure_ascii=False, indent=2)

@server.tool()
def number_formats() -> str:
    """House default_format strings, ordered by frequency in the corpus, as JSON."""
    return json.dumps({
        "formats": S.FMT, "font_sizes": S.FONT_SIZES,
        "usage": "add_calculated_field(default_format=...)",
        "hint": "delta_arrow gives ↑/↓ and hides zero",
    }, ensure_ascii=False, indent=2)

@server.tool()
def switcher_formula(param_name: str, mapping_json: str,
                            default: str = "NULL") -> str:
    """Switcher formula IF [Parameters].[p]='X' THEN expr ELSEIF ... END.

    One view serves N metrics or dimensions.

    Args:
        param_name: parameter name, e.g. 'p_metric'
        mapping_json: JSON {"label": "expression"},
            e.g. '{"NGR": "SUM([ngr])", "FTD count": "SUM([ftd_count])"}'
        default: the ELSE branch
    """
    try:
        mapping = json.loads(mapping_json)
    except json.JSONDecodeError as exc:
        return f"ERROR: mapping_json is not valid JSON: {exc}"
    if not isinstance(mapping, dict) or not mapping:
        return "ERROR: a non-empty object {label: expression} is required"
    return S.switcher(param_name, mapping, default)

@server.tool()
def param_recipe(dims_csv: str = "", metrics_csv: str = "",
                        date_from: str = "2026-07-01",
                        date_to: str = "2026-07-31") -> str:
    """A ready set of self-service dashboard parameters in the house style.

    Returns the add_parameter calls and the names for the control panel.

    Args:
        dims_csv: comma-separated dimension columns ('traffic_source,traffic_geo,model')
        metrics_csv: comma-separated metric labels ('NGR,FTD count,Dep sum')
    """
    dims = [d.strip() for d in dims_csv.split(",") if d.strip()]
    metrics = [m.strip() for m in metrics_csv.split(",") if m.strip()]
    calls = [
        {"tool": "add_parameter", "args": {
            "name": S.PARAM_DATE_FROM, "datatype": "date", "domain_type": "any",
            "default_value": date_from, "default_format": S.FMT["date"]}},
        {"tool": "add_parameter", "args": {
            "name": S.PARAM_DATE_TO, "datatype": "date", "domain_type": "any",
            "default_value": date_to, "default_format": S.FMT["date"]}},
        {"tool": "add_parameter", "args": {
            "name": S.PARAM_PERIOD, "datatype": "string", "domain_type": "list",
            "default_value": "day", "allowed_values": S.PERIOD_VALUES}},
    ]
    names = [S.PARAM_DATE_FROM, S.PARAM_DATE_TO, S.PARAM_PERIOD]
    if metrics:
        calls.append({"tool": "add_parameter", "args": {
            "name": S.PARAM_METRIC, "datatype": "string", "domain_type": "list",
            "default_value": metrics[0], "allowed_values": metrics}})
        names.append(S.PARAM_METRIC)
    if dims:
        for i in (1, 2, 3):
            nm = S.PARAM_DIM.format(i)
            calls.append({"tool": "add_parameter", "args": {
                "name": nm, "datatype": "string", "domain_type": "list",
                "default_value": dims[0] if i == 1 else S.NO_DIM,
                "allowed_values": [S.NO_DIM] + dims}})
            names.append(nm)
    return json.dumps({
        "add_parameter_calls": calls,
        "param_names_for_control_panel": names,
        "companion_calcs": {"Period": S.period_trunc("event_date"),
                            "date_filter": S.date_filter("event_date")},
        "note": "the first dimension list item is a space ' ' meaning no breakdown",
    }, ensure_ascii=False, indent=2)

@server.tool()
def layout_control_panel(param_names_csv: str, width: int = 250) -> str:
    """JSON node of a control panel (paramctrl zones) for the add_dashboard layout."""
    params = [p.strip() for p in param_names_csv.split(",") if p.strip()]
    if not params:
        return "ERROR: no parameters given"
    return json.dumps(S.control_panel(params, width=width), ensure_ascii=False, indent=2)

@server.tool()
def sizing_recipe() -> str:
    """How to make a dashboard stretch with the window (most corpus dashboards are not fixed)."""
    return json.dumps({
        "default_mode": S.SIZING, "range": S.SIZE_RANGE,
        "corpus": {"range": 27, "automatic": 24, "fixed": 10},
        "how": "book.dashboard_sizing='range'; book.dashboard_size_range={...} "
               "BEFORE add_dashboard",
    }, ensure_ascii=False, indent=2)


@server.tool()
def list_tables() -> str:
    """ClickHouse tables readable by the Tableau user, with row counts and descriptions.

    A table without a grant still builds into a workbook, but Tableau shows nothing and no clear
    error. Only tables actually readable are listed.
    """
    try:
        import pymysql

        from twkit import config
        conn = pymysql.connect(host=config.get("host"),
                               port=int(config.get("port") or 3306),
                               user=config.get("user"),
                               password=config.get("password"),
                               connect_timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT database, name, total_rows, comment FROM system.tables "
                    "WHERE database NOT IN "
                    "('system','information_schema','INFORMATION_SCHEMA') "
                    "ORDER BY database, name")
        rows = cur.fetchall()
        conn.close()
        out = [{"table": f"{d}.{n}", "rows": r, "comment": (c or "")[:200]}
               for d, n, r, c in rows]
        return json.dumps({"accessible": out, "count": len(out)},
                          ensure_ascii=False, indent=2)
    except Exception as exc:
        cached = ([f[:-5] for f in os.listdir(SC.catalog_dir()) if f.endswith(".json")]
                  if os.path.isdir(SC.catalog_dir()) else [])
        return json.dumps({
            "error": f"{type(exc).__name__}: {str(exc)[:200]} (is the VPN up?)",
            "cached_schemas_offline": cached,
        }, ensure_ascii=False, indent=2)

@server.tool()
def table_schema(db: str, table: str, refresh: bool = False) -> str:
    """Table columns as Tableau fields: type, role (dimension/measure), description from COMMENT.

    The role comes from the TYPE, not the name; is_*/has_* flags and *_id columns are dimensions.

    Args:
        refresh: True forces a live read. Required after the table changed, otherwise the
            workbook references a missing column and Tableau shows nothing.
    """
    try:
        fields = SC.fetch_schema(db, table, use_cache=not refresh)
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {str(exc)[:300]}"
    return json.dumps({
        "table": f"{db}.{table}", "total": len(fields),
        "dimensions": [f for f in fields if f["role"] == "dimension"],
        "measures": [f for f in fields if f["role"] == "measure"],
        "hint": "dimension switchers use dimension names; metric switchers use SUM([<measure>])",
    }, ensure_ascii=False, indent=2)

@server.tool()
def metric_canon(topic: str = "") -> str:
    """Metric definitions: how to compute numbers correctly. Read before writing calculations.

    Built-in rules are domain-neutral. Domain rules and deeper documents come from
    the JSON file at `config.path("canon")`: {"rules": {name: text}, "docs": [path]}.

    Args:
        topic: substring to search for in the deeper documents
    """
    from twkit import config as _cfg
    rules = {
        "shares_and_rates":
            "Compute shares and rates from sums, never as an average of daily shares "
            "(Simpson's paradox): SUM([num]) / NULLIF(SUM([den]), 0).",
    }
    docs: list = []
    canon_file = _cfg.path("canon")
    if canon_file and os.path.exists(canon_file):
        with open(canon_file, encoding="utf-8") as f:
            user = json.load(f)
        rules.update(user.get("rules") or {})
        docs = [os.path.expanduser(d) for d in user.get("docs") or []
                if os.path.exists(os.path.expanduser(d))]
    result: dict = {"rules": rules, "deeper_docs": docs}
    if topic:
        hits: dict = {}
        for path in docs:
            try:
                with open(path, encoding="utf-8") as f:
                    found = [ln.strip() for ln in f.read().splitlines()
                             if topic.lower() in ln.lower()][:12]
                if found:
                    hits[path] = found
            except OSError:
                continue
        result["search_hits"] = hits or f"nothing found for '{topic}'"
    return json.dumps(result, ensure_ascii=False, indent=2)

@server.tool()
def run_sql(sql: str, limit: int = 50) -> str:
    """Run a read-only query (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN) in ClickHouse and return rows.

    For checking data before building: do totals match, are there rows in the period, what do
    dimension values look like.

    Args:
        sql: the query
        limit: maximum rows returned
    """
    from twkit import chsafe
    try:
        chsafe.read_only(sql)
    except PermissionError as exc:
        return f"REFUSED: {exc}. Use create_view to create a view."
    try:
        from twkit import config
        body = sql.strip().rstrip(";")
        rows = config.clickhouse(read_only=True).execute(
            chsafe.read_only(f"SELECT * FROM ({body}) LIMIT {int(limit)}"))
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {str(exc)[:400]}"
    return json.dumps({"rows": len(rows), "data": [list(map(str, r)) for r in rows]},
                      ensure_ascii=False, indent=2)

@server.tool()
def create_view(view_name: str, select_sql: str, db: str = "reports",
                replace: bool = False) -> str:
    """Create a ClickHouse VIEW for a dashboard and check it is readable.

    DDL needs the owner's permission: it runs only with `allow_ddl = true` in `[settings]` of
    `~/.twkit/config.toml`. An existing object is replaced only with `replace=True`.

    Use when a source needs a join of several tables. After creation the view is read as the
    Tableau user, so a missing grant is caught before the workbook is built.

    Args:
        view_name: name without schema, e.g. 'self_service_general'
        select_sql: the SELECT part (no CREATE VIEW)
        db: schema, `reports` by default
    """
    from twkit import config as _cfg
    if str(_cfg._section("settings").get("allow_ddl", "")).lower() not in ("1", "true", "yes"):
        return ("REFUSED: DDL needs the owner's permission; set allow_ddl = true in [settings] "
                "of ~/.twkit/config.toml, or ask the owner to create the view")
    if not view_name.replace("_", "").isalnum():
        return "ERROR: a view name may contain only letters, digits and underscores"
    if not db.replace("_", "").isalnum():
        return "ERROR: a database name may contain only letters, digits and underscores"
    from twkit import chsafe
    try:
        chsafe.read_only(select_sql)
    except PermissionError as exc:
        return f"ERROR: select_sql {exc}"
    full = f"{db}.{view_name}"
    try:
        from twkit import config
        ch = config.clickhouse()
        verb = "CREATE OR REPLACE VIEW" if replace else "CREATE VIEW"
        ch.execute(f"{verb} {full} AS {select_sql.rstrip(';')}")
        cnt = ch.execute(f"SELECT count() FROM {full}")[0][0]
    except Exception as exc:
        return f"ERROR creating the view: {type(exc).__name__}: {str(exc)[:400]}"
    access = _tableau_can_read(full)
    return json.dumps({
        "view": full, "rows": cnt,
        "tableau_user_access": access,
        "next": f"table_schema('{db}', '{view_name}', refresh=True), then build the workbook",
    }, ensure_ascii=False, indent=2)

def _tableau_can_read(full_table: str) -> dict:
    """Check reading exactly the way Tableau reads (MySQL protocol, the Tableau user)."""
    try:
        import pymysql

        from twkit import config
        conn = pymysql.connect(host=config.get("host"),
                               port=int(config.get("port") or 3306),
                               user=config.get("user"),
                               password=config.get("password"),
                               connect_timeout=10)
        cur = conn.cursor()
        cur.execute(f"SELECT count() FROM {full_table}")
        rows = cur.fetchone()[0]
        conn.close()
        return {"ok": True, "rows_visible_to_tableau": rows}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "fix": f"GRANT SELECT ON {full_table} TO tableau;"}

@server.tool()
def verify_data(db: str, table: str, date_column: str = "event_date") -> str:
    """Check that data will actually reach Tableau: access, volume, period, freshness.

    Reads the way Tableau does (MySQL protocol, the Tableau user), so a missing grant is caught.
    Run after building the workbook.
    """
    import re as _re
    if not all(_re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x or "")
               for x in (db, table, date_column)):
        return "ERROR: db, table and date_column must be plain identifiers"
    full = f"{db}.{table}"
    access = _tableau_can_read(full)
    result: dict = {"table": full, "tableau_access": access}
    if not access.get("ok"):
        result["verdict"] = "NO DATA WILL ARRIVE: the Tableau user has no access"
        return json.dumps(result, ensure_ascii=False, indent=2)
    try:
        import pymysql

        from twkit import config
        conn = pymysql.connect(host=config.get("host"),
                               port=int(config.get("port") or 3306),
                               user=config.get("user"),
                               password=config.get("password"),
                               connect_timeout=15)
        cur = conn.cursor()
        cur.execute(f"SELECT count() FROM {full}")
        rows = cur.fetchone()[0]
        result["rows"] = rows
        try:
            cur.execute(f"SELECT min({date_column}), max({date_column}) FROM {full}")
            lo, hi = cur.fetchone()
            result["period"] = {"from": str(lo), "to": str(hi), "column": date_column}
        except Exception:
            result["period"] = f"no column {date_column}; period not checked"
        conn.close()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        result["verdict"] = "PROBLEM while reading"
        return json.dumps(result, ensure_ascii=False, indent=2)
    result["verdict"] = ("OK: data will arrive" if result.get("rows")
                         else "EMPTY: the table is readable but has no rows")
    return json.dumps(result, ensure_ascii=False, indent=2)

@server.tool()
def list_blocks() -> str:
    """Ready dashboard building blocks; each is tested to open in Tableau.

    Build dashboards FROM these rather than inventing markup: freely generated XML regularly
    produces files that do not open.
    """
    import inspect
    out = {}
    for name, why in BL.CATALOG.items():
        fn = getattr(BL, name, None)
        out[name] = {
            "purpose": why,
            "signature": f"{name}{inspect.signature(fn)}" if fn else "",
            "doc": (inspect.getdoc(fn) or "").split("\n\n")[0] if fn else "",
        }
    return json.dumps({
        "usage": "from twkit import blocks as B; call on a Book (twkit.book); a block "
                 "returns the names of the fields/sheets it created",
        "blocks": out,
    }, ensure_ascii=False, indent=2)

@server.tool()
def view_thumbnails(path: str, out_dir: str = "") -> str:
    """Extract the previews Tableau embedded in the workbook when it was saved.

    Open the extracted files with Read and look. Freshness is reported with them: previews are
    rendered at save time, so if our layer edited the workbook afterwards they show the OLD view.
    Values: fresh, stale, unknown; unknown is not "fine". An empty result means the workbook
    was never saved from Tableau.
    """
    from twkit import preview as PV
    thumbs = PV.extract_thumbnails(path, out_dir)
    state = PV.thumbs_state(path)
    return json.dumps({
        "file": os.path.basename(path), "previews": len(thumbs),
        "freshness": state["verdict"],
        "next": ("open the listed PNGs with Read and look"
                  if thumbs else
                  "no previews: ask to open the workbook in Tableau and save it (Cmd+S)"),
        "files": [t.as_dict() for t in thumbs],
    }, ensure_ascii=False, indent=2)

@server.tool()
def story_reference() -> str:
    """How to build a story (story points): a presentation of steps with conclusions.

    Each step caption states a CONCLUSION, not a chart name.
    """
    from twkit import story as ST
    return json.dumps({
        "how": "from twkit import story as ST; ST.add_story(wb, name, steps, title=...)",
        "step": {"sheet": "an existing sheet name",
                 "caption": "what this step proves (the caption readers see)"},
        "nav_type": list(ST.NAV_TYPES),
        "in a spec": "key 'story': {name, title, steps: [{sheet, caption}]}",
        "rule": "each step sheet must exist and each step needs a caption",
    }, ensure_ascii=False, indent=2)

@server.tool()
def spec_reference() -> str:
    """The declarative dashboard spec format (YAML): what a spec may contain.

    Building from a spec restricts the result to tested blocks; preferred over free XML.
    """
    from twkit import spec as SP
    return json.dumps(SP.describe(), ensure_ascii=False, indent=2)

@server.tool()
def validate_spec(yaml_text: str) -> str:
    """Validate a spec before building. Takes YAML text, returns problems with what and where to fix."""
    from twkit import spec as SP
    try:
        import yaml
        data = yaml.safe_load(yaml_text) or {}
    except Exception as exc:
        return json.dumps({"parse_error": f"{type(exc).__name__}: {exc}"},
                          ensure_ascii=False, indent=2)
    problems = SP.validate(data)
    return json.dumps({"valid": not problems, "problems": problems},
                      ensure_ascii=False, indent=2)

@server.tool()
def dry_run_workbook(path: str, db: str = "", table: str = "") -> str:
    """Main pre-delivery check: will the sheets have data?

    Translates every sheet to SQL and runs it on the workbook's real source: the packaged
    .hyper extract when present, otherwise ClickHouse db/table. Zero rows on a sheet means do
    not hand the workbook over. LOD and table calculations are not translated; such sheets are
    reported as skipped, not as checked.
    """
    res = DRY.dry_run(path, db, table)
    by = {}
    for r in res:
        by[r.status] = by.get(r.status, 0) + 1
    return json.dumps({
        "file": os.path.basename(path), "result": by,
        "verdict": ("DO NOT DELIVER: empty sheets" if by.get("empty")
                    else "SQL ERRORS: check" if by.get("error")
                    else "data will arrive"),
        "sheets": [r.as_dict() for r in res],
    }, ensure_ascii=False, indent=2)

@server.tool()
def check_metric_canon(path: str) -> str:
    """Check workbook formulas against the metric canon: meaning, not syntax.

    `SUM([ngr]) - SUM([rs_cost])` is valid syntax but computes profit, not NGR.
    """
    f = CANON.check_workbook(path)
    errs = sum(1 for x in f if x.severity == "error")
    return json.dumps({
        "file": os.path.basename(path), "error_count": errs, "total": len(f),
        "verdict": "canon respected" if not errs else "WRONG METRICS",
        "discrepancies": [x.as_dict() for x in f],
    }, ensure_ascii=False, indent=2)

@server.tool()
def style_score(path: str) -> str:
    """How close the workbook is to reference corpora: a 0-100 score with per-metric detail.

    About taste, not errors (lint_workbook, check_metric_canon and dry_run_workbook catch
    errors). Each metric is shown next to the three corpora: a miss can mean "worse than all"
    or "stricter than all".
    """
    from twkit import stylescore as SS
    pts, metrics, vals = SS.score(path)
    profile, dist = SS.closest_profile(vals)
    return json.dumps({
        "file": os.path.basename(path), "score": pts,
        "closest_profile": profile, "distances": dist,
        "metrics": [m.as_dict() for m in metrics],
        "references": SS.PROFILES,
        "report": SS.format_report(path),
    }, ensure_ascii=False, indent=2)

@server.tool()
def lint_workbook(path: str, db: str = "", table: str = "") -> str:
    """Check a workbook before delivery; required after save_workbook.

    Catches format errors that make Tableau refuse the file, open it empty or compute wrong.
    Each rule comes from a real defect and is calibrated not to flag working workbooks.
    severity: error = do not deliver; warn = convention or suspicious; info = reference.

    Args:
        path: .twb or .twbx path
        db, table: optional; enables R09, the check of columns against the live table
    """
    v = LINT.lint(path, db, table)
    c = LINT.counts(v)
    return json.dumps({
        "file": os.path.basename(path),
        "errors": c["error"], "warnings": c["warn"], "info": c["info"],
        "verdict": ("OK to deliver" if not c["error"]
                    else "DO NOT DELIVER: the workbook is broken"),
        "violations": [x.as_dict() for x in v],
    }, ensure_ascii=False, indent=2)

@server.tool()
def check_workbook_columns(twb_path: str, db: str, table: str) -> str:
    """Check that the workbook references no columns missing from the table.

    Catches the renamed-table trap: Tableau opens the workbook and silently shows nothing.
    """
    if not os.path.exists(twb_path):
        return f"ERROR: file not found: {twb_path}"
    try:
        live = {f["name"] for f in SC.fetch_schema(db, table, use_cache=False)}
    except Exception as exc:
        return f"ERROR reading the live schema: {type(exc).__name__}: {str(exc)[:200]}"
    from twkit import safexml
    root = safexml.from_twbx(twb_path)
    used = set()
    for col in root.iter("column"):
        if col.find("calculation") is None and not col.get("param-domain-type"):
            used.add((col.get("name") or "").strip("[]"))
    stale = sorted(c for c in used
                   if c and c not in live and not c.startswith("Calculation_"))
    return json.dumps({
        "table": f"{db}.{table}", "live_columns": len(live), "stale_references": stale,
        "verdict": "OK: no dead references" if not stale else
                   "PROBLEM: the workbook references missing columns; Tableau "
                   "will show nothing",
    }, ensure_ascii=False, indent=2)

@server.tool()
def check_dead_dimensions(path: str, db: str = "", table: str = "") -> str:
    """Check that dimensions shown as filters actually have values.

    Separates a dead dimension (0 values) from a constant metric (1 value, role=measure); the
    second is often legitimate, the first is almost always a mapping error. Run after building,
    together with dry_run_workbook.
    """
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    return json.dumps(DRY.dead_dimensions(path, db, table),
                      ensure_ascii=False, indent=2)

@server.tool()
def screenshot_workbook(path: str, out_path: str = "",
                        reopen: bool = True) -> str:
    """Open the workbook in Tableau Desktop and capture its window.

    The returned image must be opened with Read and looked at. Only one window is captured, by
    id; if a different workbook's window was captured, the result says so.

    `reopen=False` leaves the Tableau session alone and captures the window already open (use
    when someone works in Tableau in parallel); the image then shows the version on screen,
    not the file on disk. Requires macOS, Tableau Desktop and the Screen Recording permission.
    Desktop selection frames can look like misplaced floating zones: confirm a defect in the XML
    or the data before fixing it.
    """
    from twkit import shot as SHOT
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    res = SHOT.shoot(path, out_path, reopen=reopen)
    res["next"] = ("open the file with Read and look"
                    if res.get("ok") else
                    "the screen is locked: capture after unlocking, check opening "
                    "with tableau_log" if res.get("screen") == "locked" else
                    "capture failed: check the Screen Recording permission")
    return json.dumps(res, ensure_ascii=False, indent=2)

@server.tool()
def screenshot_param_states(path: str, param: str, values: str = "",
                            out_dir: str = "") -> str:
    """Capture a dashboard in EVERY state of a switcher, not only the saved one.

    The parameter value is set in a temporary copy of the file and the copy is reopened, so
    the result is deterministic. `values`: comma-separated; empty = all declared values. Open
    each screenshot with Read.
    """
    from twkit import shot as SHOT
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    vals = [v.strip() for v in values.split(",") if v.strip()] if values else None
    return json.dumps(SHOT.shoot_states(path, param, vals, out_dir),
                      ensure_ascii=False, indent=2)

@server.tool()
def save_as_extract(path: str, out_path: str = "") -> str:
    """Materialize the workbook's live Custom SQL into a packaged .hyper extract.

    With an extract the workbook opens without a password or VPN. Column types come from the
    workbook declarations, not from guessing. The source workbook is untouched; the result is
    written next to it as "<name> (extract).twbx".
    """
    from twkit import extract as EX
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    return json.dumps(EX.to_extract(path, out_path), ensure_ascii=False, indent=2)

@server.tool()
def tableau_dialog(dismiss: bool = True) -> str:
    """Read and close a Tableau error dialog: the details are neither in the log nor in the XML.

    The dialog is modal, so it is closed by default. Progress windows (Processing Request) are
    not dialogs: the tool waits for them. Requires the Accessibility permission for the terminal
    and says so plainly when it is missing.
    """
    from twkit import shot as SHOT
    prog = SHOT.wait_progress()
    titles = SHOT._real_dialogs()
    if not titles:
        return json.dumps({"dialog_count": 0,
                           "waited_progress_sec": prog.get("waited_sec", 0)},
                          ensure_ascii=False, indent=2)
    res = SHOT.dismiss_dialog() if dismiss else {"text": SHOT.read_dialog(),
                                                 "dialogs": titles}
    return json.dumps(res, ensure_ascii=False, indent=2)

@server.tool()
def tableau_sign_in() -> str:
    """Sign in to the data source when Tableau asks for a password.

    The password comes from the twkit settings (config) and is never returned. If Tableau shows
    the Dashboard Unavailable banner instead of a sign-in window, the tool clicks its Edit
    Connection link.
    """
    from twkit import shot as SHOT
    return json.dumps(SHOT.ensure_signed_in(), ensure_ascii=False, indent=2)

@server.tool()
def frame_publish(path: str, out_dir: str = "", limit: int = 300) -> str:
    """FRAME: publish a workbook as a local HTML page to view in Chrome.

    Works without Tableau and with a locked screen. Zones come from XML pixels, sheets from
    real data (dry run), numbers from `default-format` masks, sheet swaps from the current
    parameter value. It is a MODEL (stamped on the page): a difference from a real render is a
    finding about the model, not the workbook. To measure, open the file in Chrome and run
    `PROBE_JS` (returned here) for clipped labels and overflowing zones.
    """
    from twkit import frame as FR
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    res = FR.publish(path, out_dir=out_dir, limit=limit)
    res["PROBE_JS"] = FR.PROBE_JS
    return json.dumps(res, ensure_ascii=False, indent=2)

@server.tool()
def tableau_open_check(paths: str, timeout: float = 150.0, only_changed: bool = True) -> str:
    """Whether workbooks open in Tableau, judged by the log without screenshots (13-60 s each).

    `paths`: one path per line. For each: quit Tableau, open it, wait for the document window or
    an error/warning dialog (its text comes from the log). Tableau is quit at the end.
    Result: opened, warning dialog, error dialog or timeout. Make sure no owner documents are
    open first. `only_changed` (default): a workbook whose content fingerprint already opened
    cleanly is not reopened.
    """
    from twkit import shot as SHOT
    books = [p.strip() for p in paths.splitlines() if p.strip()]
    missing = [b for b in books if not os.path.exists(b)]
    if missing:
        return f"ERROR: files not found: {missing}"
    return json.dumps(SHOT.check_open(books, timeout=timeout, only_changed=only_changed),
                      ensure_ascii=False, indent=2)

@server.tool()
def tableau_log(path: str = "") -> str:
    """What Tableau itself logged when opening a workbook.

    An independent channel: the linter judges the XML, the dry run the data, this one the
    product's verdict ("field not found", "connection failed", format damage). The view itself
    is not in the log. Needs no macOS permissions.
    """
    from twkit import tablog as TL
    return TL.format_report(path)

@server.tool()
def check_visual(path: str, db: str = "", table: str = "") -> str:
    """Check the view by data: will labels fit, are small values visible.

    Combines zone geometry from the XML with dry-run statistics (category count, label length,
    value spread). Catches R24 (a spread that collapses small bars) and R26 (a label three times
    wider than its column gets an ellipsis). Sheets with LOD or table calculations are reported
    as skipped, not as checked.
    """
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    return json.dumps(DRY.visual_check(path, db, table), ensure_ascii=False, indent=2)

@server.tool()
def describe_render(path: str, page: str = "", db: str = "",
                    table: str = "") -> str:
    """Text snapshot of a page: the zone tree in pixels instead of a window screenshot.

    Call it INSTEAD of screenshot_workbook until it says a screenshot is needed. It answers what
    sits where and how large, how the area is split between sheets and controls, what a button
    hides, how many categories each sheet gets and whether they fit, and which sheets are on no
    page. The last line ("SCREENSHOT: ...") says whether a screenshot is needed. db/table are
    optional; without them categories and label lengths are reported as unknown.
    """
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    from twkit import render as RD
    stats = None
    if RD.has_local_data(path, db, table):
        try:
            stats = DRY.visual_stats(path, db, table)
        except Exception:
            stats = None
    return RD.format_report(RD.describe(path, page, stats))

@server.tool()
def look_page(path: str, page: str = "", db: str = "", table: str = "",
              out_dir: str = "") -> str:
    """Show a page through the cheapest channel that can answer.

    Order: the embedded preview (a real Tableau render when Tableau saved last), then the text
    snapshot of the layout, and only if it says "look", a window screenshot.
    """
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    from twkit import render as RD
    return RD.format_look(RD.look(path, page, db, table, out_dir))

@server.tool()
def diff_render(before: str, after: str, page: str = "") -> str:
    """How the LAYOUT changed between two versions of a workbook, in words.

    Names the zone that moved, shrank, was hidden or appeared. A previous version is the
    rollback snapshot written by owner_install, or any copy. Differences of 1-2 px are ignored
    (coordinate rounding).
    """
    for p in (before, after):
        if not os.path.exists(p):
            return f"ERROR: file not found: {p}"
    from twkit import render as RD
    return RD.format_diff(RD.diff(before, after, page))

@server.tool()
def preflight(path: str, db: str = "", table: str = "",
              want_shot: bool = False) -> str:
    """Before delivery: run every check at once and get a verdict.

    Replaces lint_workbook, check_metric_canon, dry_run_workbook, check_dead_dimensions,
    check_visual and style_score, and separately lists what could NOT be checked, so that
    "no VPN" never reads as "data is fine".

    Verdicts:
      OK to hand over       every channel ran and found nothing
      NOT fully checked     no blockers, but some channels did not run
      DO NOT hand over      a blocker: broken format, empty sheet, dead filter, canon violation

    want_shot=True also opens the workbook in Tableau and captures the window (it takes over the
    screen, so it is off by default); open the screenshot with Read.
    """
    from twkit import preflight as PF
    return PF.format_report(PF.preflight(path, db, table, want_shot))

@server.tool()
def selfcheck() -> str:
    """Check the toolkit itself, not a workbook: is it consistent after edits.

    Is every new channel wired into preflight, is every module classified, is any module
    imported by nobody, does every documented defect have an actionable rule, is one piece of
    knowledge split across two documents. Run after any change to twkit or its documents.
    """
    from twkit import selfcheck as SC
    return SC.format_report(SC.selfcheck())

@server.tool()
def sketch_workbook(path: str, out_dir: str = "", db: str = "",
                    table: str = "") -> str:
    """Draw a sketch of EVERY sheet from its real data.

    A screenshot shows only the sheet Tableau opens; the sketch covers the rest. It is OUR model
    (stamped SKETCH), not a Tableau render, and is for catching breakage: forty categories where
    ten fit, clipped or identical labels, a spread that flattens small bars, a table wider than
    its zone. Returns PNG paths and text observations readable without opening the images.
    """
    from twkit import sketch as SK
    if not os.path.exists(path):
        return f"ERROR: file not found: {path}"
    return json.dumps(SK.sketch_workbook(path, out_dir, db, table),
                      ensure_ascii=False, indent=2)


def register_edit_tools(server) -> None:
    """Editing an existing workbook: report-independent operations."""
    import json as _json

    from .session import current as get_editor
    from twkit import edit as ED

    @server.tool()
    def edit_fit_to_extract(path: str, out_path: str = "",
                            rename_json: str = "", fallback_dim: str = "") -> str:
        """Point the workbook's references at the columns of its own extract.

        Fixes the costliest defect: the workbook opens without errors but draws no sheet, because
        one reference names a column missing from the extract and Tableau disables the whole source.
        rename_json: {"old_name": "new_name"} for renames instead of removals.
        fallback_dim: replacement dimension when the removed one was a sheet's only axis.
        Empty out_path edits in place.
        """
        import shutil
        import zipfile

        from lxml import etree as _et
        res = ED.fit_to_extract(path, _json.loads(rename_json) if rename_json else {},
                                fallback_dim)
        dst = out_path or path
        from twkit.owner import check_write
        try:
            check_write(dst)
        except PermissionError as exc:
            return f"REFUSED: {exc}"
        raw = _et.tostring(res["root"], xml_declaration=False, encoding="utf-8")
        if not raw.lstrip().startswith(b"<?xml"):
            raw = b"<?xml version='1.0' encoding='utf-8' ?>\n\n" + raw
        tmp = dst + ".tmp"
        with zipfile.ZipFile(path) as z, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as o:
            twb = [n for n in z.namelist() if n.endswith(".twb")][0]
            o.writestr(twb, raw)
            for n in z.namelist():
                if n != twb:
                    o.writestr(n, z.read(n))
        shutil.move(tmp, dst)
        return _json.dumps({"file": dst, **res["report"]}, ensure_ascii=False, indent=2)

    @server.tool()
    def edit_drop_fields(fields: str, keep_on_shelves: str = "") -> str:
        """Remove fields (comma-separated) from the open workbook with ALL their references.

        A field is referenced in many places: shelves, filters, zones, sorts, folders, legends,
        label texts. Missing one gives "There is no field named ..." and Tableau drops the sheet.
        keep_on_shelves: replacement field when the removed one is a sheet's only axis.
        """
        ed = get_editor()
        got = ED.drop_fields(ed.root, [f.strip() for f in fields.split(",") if f.strip()],
                             keep_on_shelves)
        return _json.dumps(got, ensure_ascii=False)

    @server.tool()
    def edit_clone_dashboard(source: str, name: str, sheet_map_json: str,
                             with_button: bool = True) -> str:
        """Copy a dashboard, remapping its sheets.

        sheet_map_json: {"template_sheet": "new_sheet"}; null removes the zone (with its color
        legend). The copy gets its own window, unique zone ids, viewpoints for its actual sheets
        and no phone layout (otherwise Tableau fails with Internal Error 2805CF18 on navigation).
        with_button: add a navigation button to every page.
        """
        ed = get_editor()
        res = ED.clone_dashboard(ed.root, source, name, _json.loads(sheet_map_json))
        if not res:
            return f"page '{name}' already exists"
        if with_button:
            res["buttons_added"] = ED.add_nav_buttons(ed.root, [name])
            if not res["buttons_added"]:
                res["why_no_button"] = ED.nav_buttons_absent_reason(ed.root, [name])
        return _json.dumps(res, ensure_ascii=False)

    @server.tool()
    def edit_put_controls_over(dashboard: str, anchor_sheet: str, params: str,
                               height: int = 5200) -> str:
        """A strip of parameter controls ABOVE a sheet zone (comma-separated captions).

        Placed only when the parent is `layout-basic`, where coordinates are absolute; in
        `layout-flow` Tableau computes the layout and editing coordinates breaks the page.
        """
        ed = get_editor()
        dash = next((d for d in ed.root.find("dashboards").findall("dashboard")
                     if d.get("name") == dashboard), None)
        if dash is None:
            return f"no page {dashboard}"
        refs = []
        for cap in [c.strip() for c in params.split(",") if c.strip()]:
            for d in ed.root.iter("datasource"):
                if d.get("name") != "Parameters":
                    continue
                for c in d.findall("column"):
                    if (c.get("caption") or "") == cap:
                        refs.append("[Parameters]." + (c.get("name") or ""))
        if not refs:
            return "no parameters found by caption"
        return ED.put_controls_over(dash, anchor_sheet, refs, height)

    @server.tool()
    def edit_set_param(caption: str, value: str, is_date: bool = False) -> str:
        """Set a parameter value by caption; `value` is bare (`Profit`, `2026-06-01`).

        Quoting follows the parameter type: strings in quotes, dates in #...#, numbers as is.
        is_date=True forces #...#.
        """
        n = ED.set_param_value(get_editor().root, caption, value,
                               "#" if is_date else "")
        return f"parameters updated: {n}"

    @server.tool()
    def edit_retune_filter(field: str, values: str) -> str:
        """Rebuild the value list of a categorical filter (comma-separated values).

        A filter inherited from other data lists foreign values and silently hides rows.
        """
        n = ED.retune_categorical_filter(get_editor().root, field,
                                         [v.strip() for v in values.split(",") if v.strip()])
        return f"filters rebuilt: {n}"

    @server.tool()
    def edit_repair_dashboards() -> str:
        """Preventive repair of all dashboards: viewpoints, zone ids, repeated shelf fields.

        Out-of-sync viewpoints cause Internal Error 2805CF18 on navigation; duplicate zone ids stop a
        copied zone from drawing; a repeated shelf field shows two identical columns.
        """
        ed = get_editor()
        root = ed.root
        dmap = {d.get("name"): d for d in root.find("dashboards").findall("dashboard")}
        vp = ids = 0
        for w in root.find("windows").findall("window"):
            if w.get("class") == "dashboard" and w.get("name") in dmap:
                vp += 1 if ED.sync_viewpoints(w, dmap[w.get("name")]) else 0
        for d in dmap.values():
            ids += ED.unique_zone_ids(d)
        return _json.dumps({"windows_synced": vp, "zone_ids_separated": ids,
                            "shelf_repeats_removed": ED.dedupe_shelves(root)},
                           ensure_ascii=False)


register_edit_tools(server)


def register_sheet_tools(server) -> None:
    """Building a new sheet in an existing workbook."""
    import json as _json

    from .session import current as get_editor
    from twkit import edit as ED

    @server.tool()
    def edit_add_sheet(name: str, rows: str = "", columns: str = "",
                       mark: str = "Automatic", color: str = "",
                       label: str = "", sort_descending: str = "") -> str:
        """Build a NEW sheet in the open workbook. Fields are comma-separated.

        Fields may be given as table column names (`payment_system`) or workbook captions
        (`Payment system`). A bare measure is wrapped in SUM. mark: Bar / Line / Area / Circle /
        Square / Text / Automatic. Anything that could not be resolved is NAMED in the result.
        Run preflight afterwards.
        """
        ed = get_editor()
        if name in ed.list_worksheets():
            return f"sheet '{name}' already exists"
        res_r = ED.resolve_fields(ed.root, [x for x in rows.split(",") if x.strip()])
        res_c = ED.resolve_fields(ed.root, [x for x in columns.split(",") if x.strip()])
        missing = res_r["not_found"] + res_c["not_found"]
        if missing:
            return _json.dumps({"REFUSED": "fields not found in the workbook", "fields": missing,
                                "hint": "list_fields shows the available ones"},
                               ensure_ascii=False)
        ed.add_worksheet(name)
        kw = {}
        for key, val in (("color", color), ("label", label),
                         ("sort_descending", sort_descending)):
            if val:
                got = ED.resolve_fields(ed.root, [val])
                if got["fields"]:
                    kw[key] = got["fields"][0]
        out = ed.configure_chart(name, mark_type=mark, rows=res_r["fields"],
                                 columns=res_c["fields"], **kw)
        return _json.dumps({"sheet": name, "rows": res_r["fields"],
                            "columns": res_c["fields"], "built": out},
                           ensure_ascii=False)

    @server.tool()
    def list_field_names() -> str:
        """Workbook fields: column name, caption and role, i.e. how to address a field when building."""
        root = get_editor().root
        rows = []
        for ds in root.find("datasources").findall("datasource"):
            if ds.get("name") == "Parameters":
                continue
            for c in ds.findall("column"):
                nm = (c.get("name") or "").strip("[]")
                if not nm or nm.startswith((":", "__tableau")):
                    continue
                rows.append({"column": nm, "label": c.get("caption") or nm,
                             "role": c.get("role") or "", "type": c.get("datatype") or "",
                             "calculated": c.find("calculation") is not None})
        return _json.dumps(rows, ensure_ascii=False, indent=2)


register_sheet_tools(server)


def register_style_tools(server) -> None:
    """Style and formats of a built workbook."""
    import json as _json

    from .session import current as get_editor
    from twkit import edit as ED
    from twkit import style as _S

    @server.tool()
    def edit_column_width(sheet: str, field: str, px: int,
                          element: str = "header") -> str:
        """Column width in pixels. element: header (labels) or cell (values).

        Tableau reads label width ONLY from `header`; a width written to `cell` is silently ignored
        for labels. Use check_visual to see which labels do not fit.
        """
        n = ED.set_column_width(get_editor().root, sheet, field, px, element)
        return (f"columns set: {n}" if n else
                "field not found on the sheet shelves; width not applied")

    @server.tool()
    def edit_fit_column_width(sheet: str, field: str, labels: list,
                              max_px: int = 400, element: str = "header") -> str:
        """Find a column width at which labels stay DISTINGUISHABLE after clipping (fixes R27).

        Bisects for the width at which the contested label pairs separate. `labels`: the real
        dimension values (check_visual returns them). If the needed width exceeds `max_px`, the tool
        says how much is needed and sets nothing.
        """
        got = ED.fit_column_width(get_editor().root, sheet, field, labels,
                                  max_px=max_px, element=element)
        return got["verdict"]

    @server.tool()
    def edit_row_height(sheet: str, px: int) -> str:
        """Row height of a text table in pixels (a `cell` height on the innermost row field).

        Tableau draws taller rows but does NOT wrap row labels in them (checked in Desktop with
        header/cell/label `wrap` on): a long label still needs a wider column or a shorter text.
        Tables side by side should share the row height (edit_fit_tables does), or rows drift.
        """
        n = ED.set_row_height(get_editor().root, sheet, px)
        return f"row height {px} px on {n} reference(s)" if n else \
            f"no discrete field on the rows of '{sheet}'; nothing set"

    @server.tool()
    def edit_fit_tables(path: str, passes: int = 3) -> str:
        """Size text tables from what the frame measures (fixes critic K3 and K4).

        Header bands grow to the lines their headers wrap into, equal across tables side by side;
        a narrow table's first column widens so a long title takes two lines. Measures, applies and
        repeats until a pass changes nothing (at most `passes`). Never shrinks a size. The file is
        rewritten in place; look at it with frame_publish afterwards.
        """
        if not os.path.exists(path):
            return f"ERROR: file not found: {path}"
        return json.dumps(ED.fit_tables(path, passes=passes), ensure_ascii=False, indent=2)

    @server.tool()
    def edit_grand_total(sheet: str, rows: bool = True, cols: bool = False,
                         on_top: bool = True, on_left: bool = False) -> str:
        """Grand total row/column in a table.

        Written as shelf attributes (`<rows onTop='true' total='true'>`, `<cols total='true'>`);
        Tableau draws the "Total" label itself. Not configure_subtotals, which adds subtotals inside
        dimensions. on_top=True by default.
        """
        return ED.set_grand_total(get_editor().root, sheet, rows=rows, cols=cols,
                                  on_top=on_top, on_left=on_left)["verdict"]

    @server.tool()
    def edit_number_format(field: str, mask: str) -> str:
        """Number format of a field across the workbook (Tableau mask).

        House masks: number_formats. Common: `n#,##0` (counts), `p0.0%` (shares), `c"€ "#,##0`
        (money), `*↑ #,##0.0%;↓ #,##0.0%; ` (delta with arrow, zero hidden).
        """
        n = ED.set_number_format(get_editor().root, field, mask)
        return f"fields formatted: {n}" if n else "field not found by caption"

    @server.tool()
    def edit_apply_house_format(field: str, kind: str) -> str:
        """Field format by ROLE: count / money / percent / delta / date, using the house masks."""
        masks = {"count": _S.FMT.get("int"), "money": _S.FMT.get("eur"),
                 "percent": _S.FMT.get("pct"), "delta": _S.FMT.get("delta_arrow"),
                 "date": _S.FMT.get("date")}
        mask = masks.get(kind)
        if not mask:
            return f"unknown role {kind}; available: {', '.join(masks)}"
        n = ED.set_number_format(get_editor().root, field, mask)
        return _json.dumps({"field": field, "mask": mask, "applied": n},
                           ensure_ascii=False)


def register_layout_tools(server) -> None:
    """Page geometry: the same left column on every page."""
    import json as _json

    from .session import current as get_editor
    from twkit import edit as ED

    @server.tool()
    def layout_column_report() -> str:
        """Measure the left control column on every page: position, content, pinning.

        Look BEFORE editing: spread in x/w/y/h is what makes controls jump between pages.
        """
        return _json.dumps(ED.column_report(get_editor().root), ensure_ascii=False,
                           indent=1, default=str)

    @server.tool()
    def edit_align_left_column(item_px: str = "", rect: str = "",
                               pin_children: bool = True, pages: str = "") -> str:
        """Put the left column in one place on every page and pin its items.

        Edits only what Tableau reads: container coordinates in `layout-basic`/`<zones>` (absolute)
        and the `fixed-size` declaration. Coordinates inside `layout-flow` are left alone.
        `item_px`: height overrides as JSON, e.g. `{"dashboard-object": 32, "filter": 58}`; when the
        declared sizes do not fit, nothing is written and the result says what fits.
        `rect`: a fixed rectangle `[x,y,w,h]`, any item may be null. `pages`: comma-separated, empty
        = all.
        """
        heights = _json.loads(item_px) if item_px else None
        box = tuple(_json.loads(rect)) if rect else None
        only = [p.strip() for p in pages.split(",") if p.strip()] if pages else None
        r = ED.align_left_column(get_editor().root, rect=box, heights=heights,
                                 pin_children=pin_children, pages=only)
        r["measured"] = r["measured"]["spread"]
        return _json.dumps(r, ensure_ascii=False, indent=1, default=str)


def register_dimension_tools(server) -> None:
    """Remove a dimension that no longer has data, everywhere it lives."""
    import json as _json

    from .session import current as get_editor
    from twkit import edit as ED
    from twkit.extract import orphan_formula_refs

    @server.tool()
    def list_dependent_calcs(fields: str) -> str:
        """Which calculations read these fields, including through other calculations.

        Look BEFORE removing a field: some dependants must be rewritten, not dropped.
        `fields`: comma-separated names.
        """
        want = [f.strip() for f in fields.split(",") if f.strip()]
        got = ED.dependent_calcs(get_editor().root, want)
        cap = {}
        for c in get_editor().root.iter("column"):
            nm = (c.get("name") or "").strip("[]")
            if nm:
                cap[nm] = c.get("caption") or nm
        return _json.dumps({"dependency_order": [cap.get(g, g) for g in got],
                            "column_names": got}, ensure_ascii=False, indent=1)

    @server.tool()
    def edit_drop_param_members(values: str, params: str = "") -> str:
        """Remove items from parameter value lists and fix the default value.

        `values`: comma-separated items. `params`: comma-separated parameter captions (empty = all).
        """
        want = [v.strip() for v in values.split(",") if v.strip()]
        only = [v.strip() for v in params.split(",") if v.strip()]
        return _json.dumps(ED.drop_param_members(get_editor().root, want, only),
                           ensure_ascii=False)

    @server.tool()
    def edit_drop_case_branches(values: str, calcs: str = "") -> str:
        """Remove formula branches for these values and items inside `IN (...)`.

        Companion of edit_drop_param_members. Handles both `CASE ... WHEN 'x' THEN` and
        `IF/ELSEIF ... = 'x' THEN`.
        """
        want = [v.strip() for v in values.split(",") if v.strip()]
        only = [v.strip() for v in calcs.split(",") if v.strip()]
        return _json.dumps(ED.drop_case_branches(get_editor().root, want, only),
                           ensure_ascii=False)

    @server.tool()
    def edit_add_param_members(params: str, values: str) -> str:
        """Add items to parameter value lists; companion of edit_drop_param_members.

        A dimension switcher is a PAIR: an item in the parameter domain and a branch in the formula.
        `params`: comma-separated captions (empty = all list parameters); `values`: comma-separated
        items. Existing items are skipped.
        """
        ps = [v.strip() for v in params.split(",") if v.strip()]
        vs = [v.strip() for v in values.split(",") if v.strip()]
        return _json.dumps(ED.add_param_members(get_editor().root, ps, vs),
                           ensure_ascii=False)

    @server.tool()
    def edit_add_case_branches(calcs: str, branches: str) -> str:
        """Add `WHEN 'item' THEN expression` branches to formulas; companion of edit_drop_case_branches.

        `calcs`: comma-separated captions (empty = all with `CASE ... END`); `branches`: lines
        "item = expression". A branch goes before the closing `END`; existing ones are not
        duplicated.
        """
        cs = [v.strip() for v in calcs.split(",") if v.strip()]
        br = {}
        for line in branches.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                br[k.strip()] = v.strip()
        if not br:
            return _json.dumps({"ERROR": "branches is empty: lines 'item = expression' are required"},
                               ensure_ascii=False)
        return _json.dumps(ED.add_case_branches(get_editor().root, cs, br),
                           ensure_ascii=False)

    @server.tool()
    def edit_zone_hide_button(dashboard: str, hide: str, keep: str) -> str:
        """Hide zones behind a hide/show button, giving their space to the neighbours.

        Tableau draws the button itself for a `layout-flow` container with `hidden-by-user='true'`.
        The operation puts `keep` and a collapsed container with `hide` into one horizontal flow
        with an even split. `hide` and `keep`: comma-separated zones as `name` (the sheet) or
        `name:kind` (`chart1:color` is its legend). All zones must sit in ONE page container.
        """
        h = [v.strip() for v in hide.split(",") if v.strip()]
        k = [v.strip() for v in keep.split(",") if v.strip()]
        return _json.dumps(ED.zone_hide_button(get_editor().root, dashboard, h, k),
                           ensure_ascii=False)

    @server.tool()
    def edit_zone_text(dashboard: str, text: str, zone_id: str = "",
                       font_size: int = 11, color: str = "#1b1b1b") -> str:
        """Rewrite the text of a TEXT zone on a page (description, note, legend).

        Not edit_text_card, which edits a text mark inside a sheet. Pass ordinary newlines; a line
        starting with `# ` becomes bold (the hash is not printed). `zone_id` is needed only when the
        page has several text zones.
        """
        return _json.dumps(ED.zone_text(get_editor().root, dashboard, text,
                                        zone_id=zone_id, font_size=font_size,
                                        color=color), ensure_ascii=False)

    @server.tool()
    def edit_rename_fields(mapping: str) -> str:
        """Rename fields in bulk, refusing unsafe pairs.

        `mapping`: lines "old = new", names without brackets. Before the first replacement it
        checks that no old name is a substring of another, no new name is taken and every old name
        exists; any violation refuses the whole batch. Captions are changed by set_caption.
        """
        m = {}
        for line in mapping.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                m[k.strip()] = v.strip()
        if not m:
            return _json.dumps({"ERROR": "mapping is empty: lines 'old = new' are required"},
                               ensure_ascii=False)
        try:
            return _json.dumps(ED.rename_fields(get_editor().root, m), ensure_ascii=False)
        except ValueError as exc:
            return _json.dumps({"REFUSED": str(exc)}, ensure_ascii=False)

    @server.tool()
    def edit_set_formula(calc: str, formula: str) -> str:
        """Rewrite the whole formula of a calculated field.

        Branches are edited with edit_add_case_branches / edit_drop_case_branches. `calc`: caption or
        column name. Every copy of the declaration is updated, including sheet dependencies.
        """
        try:
            return _json.dumps(ED.set_formula(get_editor().root, calc, formula),
                               ensure_ascii=False)
        except ValueError as exc:
            return _json.dumps({"REFUSED": str(exc)}, ensure_ascii=False)

    @server.tool()
    def edit_zone_title(dashboard: str, titles: str) -> str:
        """Custom title of a control on a page (filter, parameter, legend).

        `titles`: lines "zone id = title". Zones are addressed by ID because filter zones carry the
        sheet name (see analyze_twb or list_dashboards).
        """
        m = {}
        for line in titles.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                m[k.strip()] = v.strip()
        if not m:
            return _json.dumps({"ERROR": "titles is empty: lines 'id = title' are required"},
                               ensure_ascii=False)
        try:
            return _json.dumps(ED.zone_title(get_editor().root, dashboard, m),
                               ensure_ascii=False)
        except ValueError as exc:
            return _json.dumps({"REFUSED": str(exc)}, ensure_ascii=False)

    @server.tool()
    def check_orphan_formulas() -> str:
        """Formulas that read fields no longer in the workbook.

        Not a blocker by itself (such formulas exist in many working workbooks): compare before and
        after your edit and fail on NEW ones.
        """
        return _json.dumps(orphan_formula_refs(get_editor().root),
                           ensure_ascii=False, indent=1)


def register_page_tools(server) -> None:
    """Workbook pages: names and tab order."""
    import json as _json

    from .session import current as get_editor
    from twkit import edit as ED

    @server.tool()
    def edit_rename_dashboard(old: str, new: str) -> str:
        """Rename a dashboard (tab) in every node at once: `<dashboard>`, `<window>` and actions.

        Navigation buttons address the window uuid and survive, but their caption text is updated
        too.
        """
        return _json.dumps(ED.rename_dashboard(get_editor().root, old, new),
                           ensure_ascii=False)

    @server.tool()
    def rename_worksheet(old: str, new: str) -> str:
        """Rename a sheet in every node at once: `<worksheet>`, `<window>`, page zones, actions, references."""
        return _json.dumps(ED.rename_worksheet(get_editor().root, old, new),
                           ensure_ascii=False)

    @server.tool()
    def set_caption(name: str, caption: str) -> str:
        """Caption of a field or parameter: what people see in the data pane.

        The column name is untouched, so formulas and shelves stay intact. `name`: column name or
        current caption.
        """
        return _json.dumps({"nodes_updated": ED.set_caption(get_editor().root, name, caption)},
                           ensure_ascii=False)

    @server.tool()
    def edit_repair_node_order() -> str:
        """Reorder node children per the schema where a builder appended them at the end.

        Tableau refuses a file whose pane children are out of order (`<encodings>` after
        `<style>`); a hand edit can leave them so. Call after editing, before saving.
        """
        return _json.dumps(ED.repair_node_order(get_editor().root), ensure_ascii=False)

    @server.tool()
    def edit_remove_field(sheet: str, field: str, shelf: str = "") -> str:
        """Remove a field from a sheet shelf; the reverse of edit_place_field.

        Shelf expressions are trees (`/` nests, `+` places side by side, `*` crosses); the field is
        removed structurally. The derivation does not matter: "remove GGR" removes `sum:GGR` and
        `usr:GGR`. Empty `shelf` removes it from every shelf and encoding; if the field is not there,
        the tool refuses.
        """
        return _json.dumps(
            ED.remove_field(get_editor().root, sheet, field, shelf=shelf),
            ensure_ascii=False, indent=2)

    @server.tool()
    def edit_tooltip(sheet: str, lines: str, plain: bool = False) -> str:
        """Build a sheet tooltip from "label = field" lines.

        `lines`: separated by `;`, each `Label=field` or plain text, e.g.
        `Country=country; GGR=GGR; Data for 6 months`. House style by default: grey label with a tab,
        bold value; `plain=true` disables it. A field missing from the workbook is reported, not
        silently skipped.
        """
        items = []
        for part in lines.split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                label, field = part.split("=", 1)
                items.append({"label": label.strip(), "field": field.strip()})
            else:
                items.append({"text": part})
        return _json.dumps(ED.set_tooltip(get_editor().root, sheet, items, plain=plain),
                           ensure_ascii=False, indent=2)

    @server.tool()
    def edit_range_filter(sheet: str, field: str, low: str = "", high: str = "",
                          context: bool = False) -> str:
        """Range filter: "GGR from 100", "date from ... to ...".

        Both bounds are optional. Dates are wrapped in #...# automatically; without them Tableau
        reads the bound as a string and the filter silently does nothing.
        """
        return _json.dumps(
            ED.range_filter(get_editor().root, sheet, field,
                            low if low != "" else None,
                            high if high != "" else None, context=context),
            ensure_ascii=False, indent=2)

    @server.tool()
    def edit_relative_date_filter(sheet: str, field: str, period: str = "month",
                                  first: int = -5, last: int = 0,
                                  include_future: bool = True,
                                  context: bool = False) -> str:
        """Relative date filter "last N periods": it does not go stale.

        `period`: day, week, month, quarter, year. `first=-5, last=0` is the last six months
        including the current one.
        """
        return _json.dumps(
            ED.relative_date_filter(get_editor().root, sheet, field, period=period,
                                    first=first, last=last,
                                    include_future=include_future, context=context),
            ensure_ascii=False, indent=2)

    @server.tool()
    def edit_filter_context(sheets: str, field: str = "", on: bool = True) -> str:
        """Make a filter a CONTEXT filter, applied before the others.

        Required for a correct edit_top_n: top-N sees data BEFORE regular filters, so "top 10
        countries" with one brand selected ranks across ALL brands until the brand filter is in
        context. Empty `field` = every filter of the sheet; if none is found the tool refuses.
        """
        return _json.dumps(
            ED.set_filter_context(get_editor().root,
                                  [x.strip() for x in sheets.split(",") if x.strip()],
                                  field, on=on),
            ensure_ascii=False, indent=2)

    @server.tool()
    def edit_sort_by_measure(sheet: str, dimension: str, by: str,
                             direction: str = "desc") -> str:
        """Sort a dimension BY A MEASURE, e.g. countries by GGR descending.

        Sorting belongs to the sheet; a second sort of the same dimension replaces the first.
        `direction`: desc or asc.
        """
        return _json.dumps(
            ED.sort_by_measure(get_editor().root, sheet, dimension, by, direction),
            ensure_ascii=False, indent=2)

    @server.tool()
    def edit_top_n(sheet: str, dimension: str, by: str, count: str,
                   direction: str = "desc") -> str:
        """Top-N filter by a measure: keep only the best N values of a dimension.

        `count`: a number OR a parameter name; if the named parameter does not exist the tool
        refuses. `direction`: desc (top N) or asc (bottom N). Afterwards check edit_filter_context:
        top-N ranks BEFORE regular filters.
        """
        return _json.dumps(
            ED.top_n_filter(get_editor().root, sheet, dimension, by, count, direction),
            ensure_ascii=False, indent=2)

    @server.tool()
    def edit_exclude_members(sheet: str, field: str, members: str,
                             datatype: str = "") -> str:
        """Exclude specific dimension values (right click > Exclude).

        Unlike listing the kept values, an exclusion does not freeze the domain, so new values keep
        appearing. `members`: comma-separated values, no quoting needed. `datatype`: integer/real
        when numeric values arrive as strings. The exclusion stays even when the field leaves the
        shelves.
        """
        vals = [v.strip() for v in str(members).split(",") if v.strip()]
        return _json.dumps(
            ED.exclude_members(get_editor().root, sheet, field, vals, datatype),
            ensure_ascii=False, indent=2)

    @server.tool()
    def edit_swap_axes(sheets: str = "") -> str:
        """Swap rows and columns (Swap Rows and Columns).

        Formatting, encodings and totals bound to an axis are swapped too. Table calculation
        directions are relative to the drawn table, so review them afterwards. `sheets`:
        comma-separated; empty = every sheet with non-empty shelves.
        """
        return _json.dumps(
            ED.swap_rows_cols(get_editor().root,
                              [x.strip() for x in sheets.split(",") if x.strip()]),
            ensure_ascii=False, indent=2)

    @server.tool()
    def tableau_reload(book: str = "") -> str:
        """Reload a workbook from disk without quitting Tableau.

        Tableau reads a file only when opening it; quitting would also drop the data source
        sign-in. Empty Book N windows are closed as well.
        """
        b = book or get_editor().path
        if not b:
            return "ERROR: no workbook given to reload"
        from twkit import shot as _shot
        return _json.dumps(_shot.reload_book(b), ensure_ascii=False, indent=2)

    @server.tool()
    def edit_place_field(sheet: str, field: str, shelf: str = "rows",
                         derivation: str = "Sum", separator: str = "") -> str:
        """Put a field on a sheet shelf: rows, columns, text, color, size, detail, tooltip.

        The shelf separator matters: `/` nests a dimension one level down, `+` places a measure
        side by side on the same axis. By default it follows the field role (dimensions nest,
        measures are added); set `separator` only when you need otherwise. `derivation`: Sum,
        CountD, Avg, Min, Max, User (a calculation), None (dimension as is), Year/Month/Day.
        """
        return _json.dumps(
            ED.place_field(get_editor().root, sheet, field, shelf=shelf,
                           derivation=derivation, separator=separator),
            ensure_ascii=False, indent=2)

    @server.tool()
    def edit_table_calc(caption: str, kind: str, field: str,
                        direction: str = "down", ordering_field: str = "",
                        window: int = 2, agg: str = "SUM", fmt: str = "",
                        sheets: str = "") -> str:
        """Table calculation: running total, share, rank, difference, moving average.

        The key is the DIRECTION: a table function computes over the DRAWN table, and without a
        direction Tableau computes across, so a running total meant to go down the months
        accumulates across the columns. The dry run does not translate table calculations; check
        with screenshot_param_states.

        `direction`: down, across, across in pane, pane, table, cell, by field (then
        `ordering_field` is required). Raw `rows`/`columns` are rejected because the XML names are
        inverted. Recipes: table_calc_recipes. The field is only declared; edit_add_measure puts it
        on a shelf. `sheets`: comma-separated sheets that receive the declaration.
        """
        return _json.dumps(
            ED.table_calc(get_editor().root, caption, kind=kind, field=field,
                          direction=direction, ordering_field=ordering_field,
                          window=window, agg=agg, fmt=fmt,
                          sheets=[x.strip() for x in sheets.split(",") if x.strip()]),
            ensure_ascii=False, indent=2)

    @server.tool()
    def table_calc_recipes() -> str:
        """Table calculation recipes and directions, as JSON."""
        return _json.dumps({
            "recipes": {k: {"formula": v[0], "type": v[1],
                           "format": v[2] or "(default)", "meaning": v[3]}
                       for k, v in ED.TABLE_CALCS.items()},
            "aliases": ED._TC_ALIASES,
            "directions": ED._TC_PROVEN,
            "directions": ED._TC_DIRECTIONS,
            "caution": "the XML value names the PARTITION, not the direction: "
                       "Columns accumulates down, Rows across.",
            "corpus_frequency": {"Columns": 130, "Rows": 98, "Field": 43,
                                  "ColumnInPane": 12, "Table": 3, "Pane": 2,
                                  "CellInPane": 1},
            "check": "data cannot verify the direction, only eyes "
                     "(screenshot_param_states); the linter catches only its ABSENCE (R30/R31)",
        }, ensure_ascii=False, indent=2)

    @server.tool()
    def edit_sheet_swap(param: str, mapping: str, wide: str = "") -> str:
        """Sheet swap: one switcher shows different matrices in the same place.

        Does all four steps; skipping any gives a silent defect: a gate calculation and filter on
        EACH sheet, a copy of the parameter declaration in each sheet's dependencies, a viewpoint
        for every sheet of the page (without it Tableau fails with HasVisualDoc), and no
        fit-to-view for sheets in `wide` (it squeezes columns into #####).
        `mapping`: "Sheet=value,Sheet=value". `wide`: comma-separated sheets.
        """
        pairs = {}
        for part in mapping.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                pairs[k.strip()] = v.strip()
        wides = [w.strip() for w in wide.split(",") if w.strip()]
        return _json.dumps(ED.sheet_swap(get_editor().root, param, pairs, wides),
                           ensure_ascii=False, indent=2)

    @server.tool()
    def remove_worksheet(name: str) -> str:
        """Delete a sheet with its window, page zones and actions."""
        return _json.dumps(ED.remove_worksheet(get_editor().root, name), ensure_ascii=False)

    @server.tool()
    def remove_dashboard(name: str) -> str:
        """Delete a dashboard with its window and actions. Sheets stay."""
        return _json.dumps(ED.remove_dashboard(get_editor().root, name), ensure_ascii=False)

    @server.tool()
    def edit_finish_windows(first_dashboard: str = "") -> str:
        """Finish the workbook for opening: the dashboard first and maximized, helper sheets hidden.

        Only sheets placed as zones on dashboards are hidden; a standalone sheet tab is a
        legitimate deliverable.
        """
        return _json.dumps(ED.finish_windows(get_editor().root, first_dashboard),
                           ensure_ascii=False)

    @server.tool()
    def edit_reorder_pages(order: str) -> str:
        """Tab order. `order`: comma-separated page names, left to right; unnamed pages follow."""
        want = [v.strip() for v in order.split(",") if v.strip()]
        return _json.dumps(ED.reorder_pages(get_editor().root, want),
                           ensure_ascii=False)


def register_chart_edit_tools(server) -> None:
    """Reshaping a built sheet: heat fill, second axis."""
    import json as _json

    from .session import current as get_editor
    from twkit import edit as ED

    @server.tool()
    def edit_heat_columns(sheet: str) -> str:
        """Heat fill of the columns of an indicator table, one scale per measure.

        Uses `separate-domains`; the mark becomes Square so the cell is filled, numbers stay.
        The sheet must be a Measure Names table.
        """
        return _json.dumps(ED.heat_columns(get_editor().root, sheet),
                           ensure_ascii=False)

    @server.tool()
    def edit_dual_axis(sheet: str, field: str, mark: str = "Line",
                       color: str = "", derivation: str = "User",
                       labels: bool = False) -> str:
        """Add a second measure on the SAME axis (combo: bars + line).

        `field`: column name without brackets, already declared in the workbook. `derivation`: User
        for a calculation, Sum/CountD for a plain measure. Labels of the second measure are off by
        default.
        """
        return _json.dumps(
            ED.dual_axis(get_editor().root, sheet, field, derivation=derivation,
                         mark=mark, color=color, labels=labels),
            ensure_ascii=False)

    @server.tool()
    def edit_kpi_tile(sheet: str, caption: str, value_size: str = "22",
                      caption_size: str = "9", value_color: str = "#1f1f1f",
                      caption_color: str = "#757575",
                      caption_below: bool = True) -> str:
        """KPI tile: a LARGE number and a small caption in one mark label (`<customized-label>`).

        Turn the sheet title off on the page afterwards (edit_show_zone_title), or the caption
        appears twice.
        """
        return _json.dumps(
            ED.kpi_tile(get_editor().root, sheet, caption, value_size=value_size,
                        caption_size=caption_size, value_color=value_color,
                        caption_color=caption_color, caption_below=caption_below),
            ensure_ascii=False)

    @server.tool()
    def edit_fix_format_attrs() -> str:
        """Rename `<format attr=...>` values that miss the Tableau schema.

        `font-color` -> `color`, `line-width` -> `stroke-size`, `fontsize` -> `font-size` and other
        corpus-verified pairs; the formatting is kept. Unknown names are left for the linter (R31).
        """
        return _json.dumps(ED.fix_format_attrs(get_editor().root), ensure_ascii=False)

    @server.tool()
    def edit_text_card(sheet: str, column: str, lines: str,
                       align: str = "left", divider: str = "#d4d4d4") -> str:
        """A row of KPI cards from one sheet: a dimension across, metrics as lines.

        `column`: the dimension that yields the cards (one per value). `lines`: JSON label lines
        top to bottom, e.g.
          `[{"field": "[Calculation_...]", "size": "18", "bold": true, "color": "#2c3a47"},
            {"field": "[Calculation_...]", "caption": "Net ", "size": "10", "color": "#6b7a8c"}]`
        Do not put a color encoding on such a sheet (it colors the whole label); color by line.
        Turn the sheet title off on the page (edit_show_zone_title).
        """
        try:
            parsed = _json.loads(lines)
        except _json.JSONDecodeError as exc:
            return f"ERROR: lines is not valid JSON: {exc}"
        if not isinstance(parsed, list) or not parsed:
            return "ERROR: a non-empty list of card lines is required"
        return _json.dumps(
            ED.text_card(get_editor().root, sheet, column, parsed,
                         align=align, divider=divider),
            ensure_ascii=False)

    @server.tool()
    def edit_mark_color(sheet: str, color: str) -> str:
        """Solid mark color of a sheet: color encodes the BLOCK, not the rank within it."""
        return _json.dumps({"pane_count": ED.set_mark_color(get_editor().root, sheet, color)},
                           ensure_ascii=False)

    @server.tool()
    def edit_show_zone_title(dashboard: str, sheets: str, show: bool = False) -> str:
        """Whether a sheet title is shown in its page zone (`show-title`)."""
        return _json.dumps(
            {"zone_count": ED.show_zone_title(get_editor().root, dashboard,
                                       [s.strip() for s in sheets.split(",") if s.strip()],
                                       show)},
            ensure_ascii=False)

    @server.tool()
    def edit_add_measure(sheet: str, field: str, derivation: str = "Sum") -> str:
        """Add a measure to the COLUMNS of a Measure Names table.

        The column set comes from the `[:Measure Names]` filter, not a shelf. `derivation`: Sum,
        CountD or User (a calculation).
        """
        return _json.dumps(ED.add_measure(get_editor().root, sheet, field, derivation),
                           ensure_ascii=False)

    @server.tool()
    def edit_order_measures(sheet: str, fields: str, derivations: str = "") -> str:
        """Column order of a measure table; without it Tableau sorts alphabetically.

        `fields` and `derivations`: comma-separated, pairwise. The order is stored on the data
        source, i.e. once per workbook.
        """
        cols = [s.strip() for s in fields.split(",") if s.strip()]
        devs = [s.strip() for s in derivations.split(",") if s.strip()] or None
        return _json.dumps(ED.order_measures(get_editor().root, sheet, cols, devs),
                           ensure_ascii=False)

    @server.tool()
    def edit_sheet_fit(sheets: str, mode: str = "stretch") -> str:
        """How a sheet fills its space: stretch (Entire View), by width, by height, standard.

        A property of the SHEET stored in `<window>`, not of the page zone.
        """
        return _json.dumps(
            {"sheet_count": ED.set_sheet_fit(get_editor().root,
                                        [s.strip() for s in sheets.split(",") if s.strip()],
                                        mode)}, ensure_ascii=False)

    @server.tool()
    def edit_dedupe_style_rules(sheets: str) -> str:
        """Merge repeated `<style-rule>` elements of a sheet into one rule per element.

        Two rules for one element conflict silently: the second is ignored with everything in it.
        The last value wins.
        """
        return _json.dumps(
            ED.dedupe_style_rules(get_editor().root,
                                  [s.strip() for s in sheets.split(",") if s.strip()]),
            ensure_ascii=False)

    @server.tool()
    def find_idiom(query: str = "", samples: int = 2) -> str:
        """Ask working workbooks how a technique is done in Tableau.

        Returns the FORM from a real workbook: the XML node, workbook and sheet names, and how many
        corpus workbooks use it (frequency = how canonical it is). An empty query lists the whole
        catalog. Connection strings are scrubbed from the output.
        """
        from twkit import idiom as ID
        return _json.dumps(ID.search(query, samples=samples), ensure_ascii=False)

    @server.tool()
    def edit_color_range(sheets: str, full_range: bool = True,
                         reversed_scale: bool = False) -> str:
        """`Use Full Color Range` and `Reversed` for a sheet's colour encodings.

        On a diverging palette Tableau otherwise scales as if the range were
        symmetric around zero, so the side with smaller absolute values washes out
        to the neutral tone — the usual cause of "one side looks dull". Tableau's
        own docs show `-858` grey without it, dark red with it.

        ⚠️ Stored as `symmetric`, inverted: the option ON is `symmetric='false'`.
        """
        return _json.dumps(
            ED.set_color_range(get_editor().root,
                               [s.strip() for s in sheets.split(",") if s.strip()],
                               full_range, reversed_scale), ensure_ascii=False)

    @server.tool()
    def install_palette(name: str, colors: str, kind: str = "ordered-diverging",
                        apply: bool = False) -> str:
        """Declare a custom named colour palette in `Preferences.tps`.

        A palette bound to one measure has to be NAMED, and Tableau ships a fixed
        set — an orange-to-green diverging pair is not among them. This is how a
        specific colour becomes available at all.

        ⚠️ The file belongs to the person, so nothing is written unless
        `apply=True`; by default you get a snippet to paste. Writing takes a
        timestamped backup first and refuses to replace a palette of the same name.
        Tableau reads the file at startup — it needs a restart afterwards.
        """
        from twkit import palette as PAL
        try:
            return _json.dumps(
                PAL.install(name, [c.strip() for c in colors.split(",") if c.strip()],
                            kind, apply=apply), ensure_ascii=False, indent=1)
        except ValueError as exc:
            return _json.dumps({"refused": str(exc)}, ensure_ascii=False)

    @server.tool()
    def show_config() -> str:
        """Where database settings come from. Secrets are reported as a flag only.

        Settings resolve in order: `TWKIT_DB_*` environment variables, then
        `~/.twkit/config.toml`, then the settings module (`[settings]`).
        Nothing configured is a normal state and says so.
        """
        from twkit import config as CFG
        return _json.dumps(CFG.describe(), ensure_ascii=False, indent=1)

    @server.tool()
    def edit_color_steps(sheets: str, steps: int = 2) -> str:
        """Stepped color: `num-steps` on the sheet's color encodings.

        A continuous diverging scale passes through its neutral middle; `steps=2` removes the
        intermediate tones, `steps=0` removes stepping.
        """
        return _json.dumps(
            ED.set_color_steps(get_editor().root,
                               [s.strip() for s in sheets.split(",") if s.strip()], steps),
            ensure_ascii=False)

    @server.tool()
    def edit_copy_color_encoding(donor: str, sheets: str) -> str:
        """Copy the coloring of a donor sheet onto other sheets exactly.

        Copies the pane `<color>` (with `separate-domains`) and every color encoding with its own
        palette.
        """
        return _json.dumps(
            ED.copy_color_encoding(get_editor().root, donor,
                                   [s.strip() for s in sheets.split(",") if s.strip()]),
            ensure_ascii=False)

    @server.tool()
    def edit_sign_color(sheets: str, measures: str) -> str:
        """Text color of a measure table BY SIGN, with its own scale per measure.

        `measures`: comma-separated `measure-instance:PALETTE-NAME`, e.g.
        `sum:Δ %:qk:red_green_diverging_10_0, sum:P1:qk:Just black`. A diverging palette colors by
        sign (center set to zero); `Just black` keeps a constant color. List EVERY measure of the
        sheet. `#...` colors are not accepted: only palette names work per measure. Puts
        `[Multiple Values]` on Color instead of `[:Measure Names]` and enables separate legends.
        """
        try:
            spec = ED.parse_sign_color_spec(measures)
            out = ED.sign_color(get_editor().root,
                                [s.strip() for s in sheets.split(",") if s.strip()], spec)
        except ValueError as exc:
            return _json.dumps({"applied": 0, "why": str(exc)}, ensure_ascii=False)
        return _json.dumps(out, ensure_ascii=False)

    @server.tool()
    def edit_transpose_flow(dashboard: str, zone_id: str) -> str:
        """Transpose a container grid: N columns of M items -> M rows of N items.

        `fixed-size` changes meaning (height <-> width) and moves from the item to the row; outer
        column backgrounds disappear and are listed in the result.
        """
        return _json.dumps(ED.transpose_flow(get_editor().root, dashboard, zone_id),
                           ensure_ascii=False)

    @server.tool()
    def edit_stack_page(dashboard: str, items: str, size: str = "") -> str:
        """Rebuild a page as ONE vertical column: a long scrolling page.

        `items`: JSON list top to bottom:
          `{"kind":"keep","id":"4"}`                  keep a zone as is
          `{"kind":"sheet","name":"Sheet","h":300}`    a sheet
          `{"kind":"row","sheets":["A","B"],"h":300}` a row of sheets, equal widths
          `{"kind":"text","h":200,"runs":[{"text":"...","bold":true,"size":12}]}`
          `{"kind":"gap","h":12}`                     spacing
        `h`: height in pixels (`fixed-size` of the flow). `size`: page size JSON, e.g.
        `{"sizing-mode":"range","minwidth":1200,"maxwidth":2400,"minheight":2600,"maxheight":4200}`;
        a long page needs a height larger than the screen. Zones not listed in `items` are removed
        and listed in the result.
        """
        spec = _json.loads(items)
        box = _json.loads(size) if size else None
        return _json.dumps(ED.stack_page(get_editor().root, dashboard, spec, box),
                           ensure_ascii=False)

    @server.tool()
    def edit_zone_fit(dashboard: str, sheets: str, mode: str = "stretch") -> str:
        """How a sheet fills its ZONE on a PAGE: stretch (Entire View), by width, by height, standard.

        Not edit_sheet_fit (the sheet tab): on a page the dashboard window `<viewpoint>` decides. An
        empty viewpoint is Standard, and a table wider than its zone gets its own horizontal scroll.
        """
        return _json.dumps(
            {"zone_count": ED.set_zone_fit(get_editor().root, dashboard,
                                    [s.strip() for s in sheets.split(",") if s.strip()],
                                    mode)}, ensure_ascii=False)

    @server.tool()
    def edit_zone_style(dashboard: str, sheets: str, background: str = "",
                        padding: str = "", margin: str = "",
                        controls: bool = False) -> str:
        """Zone styling: background, padding and margin (`<zone-style>`).

        `padding` eats width. By default only SHEET zones are styled, because filter cards carry the
        sheet name; `controls=True` includes them.
        """
        fmt = {}
        if background:
            fmt["background-color"] = background
        if padding:
            fmt["padding"] = padding
        if margin:
            fmt["margin"] = margin
        return _json.dumps(
            {"zone_count": ED.set_zone_style(get_editor().root, dashboard,
                                      [s.strip() for s in sheets.split(",") if s.strip()],
                                      fmt, controls)}, ensure_ascii=False)

    @server.tool()
    def edit_apply_filter(sheets: str, field: str, derivation: str = "None",
                          member: str = "", context: bool = False) -> str:
        """Apply one filter to ALL listed sheets.

        "Apply to all worksheets" is not a single object in Tableau: a `<filter>` sits in EACH
        sheet, otherwise the page card filters nothing. `member="true"` for a boolean period
        calculation.
        """
        return _json.dumps(
            ED.apply_filter(get_editor().root,
                            [s.strip() for s in sheets.split(",") if s.strip()],
                            field, derivation=derivation, member=member,
                            context=context), ensure_ascii=False)

    @server.tool()
    def edit_control_column(dashboard: str, refs: str, width: int = 17000,
                            item_h: int = 5300) -> str:
        """A column of controls on the RIGHT of a page, built from a vertical flow.

        `refs`: comma-separated `[Parameters].[...]` for a parameter or `Sheet|[ds].[none:Field:nk]`
        for a filter. Card modes are set automatically (`checkdropdown` for filters, `compact` for
        parameters). The structure is edited, not coordinates.
        """
        dash = next((d for d in get_editor().root.iter("dashboard")
                     if d.get("name") == dashboard), None)
        if dash is None:
            return _json.dumps({"column": 0, "why": f"no page {dashboard!r}"},
                               ensure_ascii=False)
        items = [s.strip() for s in refs.split(",") if s.strip()]
        return _json.dumps(ED.add_control_column(dash, items, width=width,
                                                 item_h=item_h), ensure_ascii=False)


def register_guide_tools(server) -> None:
    """Report guide: one document per workbook, built from the workbook itself."""
    import json as _json

    from twkit import docs as DOC

    @server.tool()
    def describe_report(book_path: str) -> str:
        """Description of ONE report for colleagues: sections, what is shown, metrics. Markdown."""
        p = DOC.passport(book_path)
        return DOC.render(p)

    @server.tool()
    def build_reports_guide(workbooks_dir: str = "", out_dir: str = "") -> str:
        """Rebuild the guide for ALL workbooks in a directory, plus an index.

        A human-written "Description" paragraph is kept. Takes no screenshots; existing
        `shots/<workbook>/<section>.png` files are picked up.
        """
        import os as _os
        wb = workbooks_dir or _os.path.expanduser(
            "~/Documents/My Tableau Repository/Workbooks")
        return _json.dumps(DOC.build_all(wb, out_dir), ensure_ascii=False)


def register_idiom_tools(server) -> None:
    """Reference pairs: what Tableau writes for one real action."""
    import json as _json
    import os as _os

    from twkit import idiom as ID

    @server.tool()
    def diff_reference(pair_dir: str) -> str:
        """Difference of a `before`/`after` pair: the exact idiom of ONE Desktop action.

        Noise (uuids, zone ids, extract timestamps) is dropped.
        """
        b, a = ID.find_pair(pair_dir)
        if not (b and a):
            return _json.dumps(
                {"verdict": f"{pair_dir} needs before and after (.twb or .twbx)"},
                ensure_ascii=False)
        return _json.dumps(ID.diff_books(b, a), ensure_ascii=False, indent=1)

    @server.tool()
    def list_reference_pairs(ref_dir: str = "") -> str:
        """Which reference pairs are complete and which are missing a side."""
        from twkit import config as _cfg
        d = ref_dir or _cfg.path("reference")
        return _json.dumps(ID.list_pairs(d), ensure_ascii=False, indent=1)


def register_source_tools(server) -> None:
    """Workbook source: a live connection instead of an extract."""
    import json as _json

    from .session import current as get_editor
    from twkit import edit as ED

    @server.tool()
    def edit_to_live_sql(sql: str, columns: str, server_host: str, dbname: str,
                         username: str, port: str = "3306",
                         driver: str = "mysql", datasource: str = "") -> str:
        """Switch the workbook to a LIVE Custom SQL connection and REMOVE the extract.

        A live connection with an extract on top reads the EXTRACT, so the extract is removed.
        `columns`: JSON `[{"name": "Date", "datatype": "date"}, ...]` in query order; types:
        integer, real, date, datetime, boolean, string. `datasource`: which source (caption or name);
        required when the workbook has several. Test the query first as Tableau will wrap it:
        `SELECT * FROM (<sql>) "Custom SQL Query" LIMIT 0`.
        """
        cols = _json.loads(columns)
        return _json.dumps(
            ED.to_live_sql(get_editor().root, sql, cols, server=server_host,
                           port=port, dbname=dbname, username=username, driver=driver,
                           datasource=datasource),
            ensure_ascii=False)


def register_owner_tools(server) -> None:
    """Editing the owner's workbook without rolling back their work."""
    import json as _json

    from .session import current as get_editor
    from twkit import owner as OW

    @server.tool()
    def owner_check_source(book_path: str) -> str:
        """FIRST call before editing someone's workbook: did they edit it after our last install.

        Edits always start from this current file, never from our own snapshot.
        """
        return _json.dumps(OW.guard_source(book_path), ensure_ascii=False, indent=1)

    @server.tool()
    def owner_snapshot(book_path: str, tag: str = "") -> str:
        """Rollback point: a copy of the owner's current file in `_ai/<workbook>/<time>-<md5>.twbx`."""
        return OW.snapshot(book_path, tag)

    @server.tool()
    def owner_inventory(book_path: str = "") -> str:
        """What the workbook contains: sheets, pages, calculations, parameters, fields, zones.

        Without `book_path`, the open workbook. Take it BEFORE editing and compare AFTER.
        """
        from twkit import safexml
        root = safexml.from_twbx(book_path) if book_path else get_editor().root
        return _json.dumps(OW.inventory(root), ensure_ascii=False, indent=1)

    @server.tool()
    def owner_prune(book_path: str, keep: int = 10, dry_run: bool = False) -> str:
        """Rollback folder hygiene: keep the last `keep` snapshots of a workbook.

        Files with `original` or `keep` in the name are never deleted.
        """
        return _json.dumps(OW.prune(book_path, keep=keep, dry_run=dry_run),
                           ensure_ascii=False, indent=1)

    @server.tool()
    def owner_plan(built_path: str, book_path: str) -> str:
        """Before owner_install: what the build would lose, and what the facts explain. Read-only.

        Suggests renames (same formula, same parameter members; zones follow sheets) and harmless
        losses with reasons (calculations no sheet uses, builder debris, unnamed layout containers).
        Nothing is applied: pass what you accept to owner_install as `renames` / `allowed_losses`.
        An owner's unused calculation may be work in progress: ask before dropping it.
        """
        from twkit import safexml
        if not os.path.exists(book_path):
            return f"ERROR: file not found: {book_path}"
        rb, ra = safexml.from_twbx(book_path), safexml.from_twbx(built_path)
        ib, ia = OW.inventory(rb), OW.inventory(ra)
        got = OW.suggest(rb, ra)
        return _json.dumps({"lost": OW.regressions(ib, ia),
                            "suggested_renames": got["renames"], "harmless": got["harmless"],
                            "lost_after_suggestions": OW.regressions(ib, ia, got["harmless"], got["renames"])},
                           ensure_ascii=False, indent=1)

    @server.tool()
    def owner_install(built_path: str, book_path: str, allowed_losses: str = "",
                      renames: str = "", force: bool = False) -> str:
        """Install a build over the owner's file: snapshot, diff guard, write, manifest.

        The diff guard compares the inventory of their current file with our result; anything lost
        that is not in `allowed_losses` (comma-separated) refuses the write. `renames`: renamed items
        as `old=new` pairs; without them a rename looks like a loss. Declare renames instead of using
        `force`.
        """
        from twkit import safexml
        allowed = [a.strip() for a in allowed_losses.split(",") if a.strip()]
        ren = dict(p.split("=", 1) for p in
                   (x.strip() for x in renames.split(",")) if "=" in p)
        ren = {k.strip(): v.strip() for k, v in ren.items()}
        before = OW.inventory(safexml.from_twbx(book_path)) if os.path.exists(book_path) else None
        after = OW.inventory(safexml.from_twbx(built_path))
        return _json.dumps(
            OW.install(built_path, book_path, allowed_losses=allowed,
                       inventory_before=before, inventory_after=after,
                       renames=ren, force=force),
            ensure_ascii=False, indent=1)


def register_shot_tools(server) -> None:
    """See every page of a workbook as Tableau drew it."""
    import json as _json

    from twkit import shot as SH

    @server.tool()
    def list_pages(book_path: str) -> str:
        """Pages of a workbook: what can be captured."""
        return _json.dumps(SH.pages(book_path), ensure_ascii=False)

    @server.tool()
    def screenshot_all_pages(book_path: str, out_dir: str = "", only: str = "",
                             settle: int = 45) -> str:
        """Capture EVERY page of a workbook and build an index.html gallery.

        The active tab is switched in the FILE (`maximized`), so no UI control permissions are
        needed. Slow and takes over the screen (about a minute per page); `only` (comma-separated)
        limits the pages. Open the screenshots with Read. The workbook must open without a dialog.
        """
        picked = [p.strip() for p in only.split(",") if p.strip()] or None
        return _json.dumps(SH.shoot_all_pages(book_path, out_dir=out_dir,
                                              only=picked, settle=settle),
                           ensure_ascii=False, indent=1)


register_style_tools(server)
register_layout_tools(server)
register_dimension_tools(server)
register_page_tools(server)
register_chart_edit_tools(server)
register_guide_tools(server)
register_idiom_tools(server)
register_source_tools(server)
register_owner_tools(server)
register_shot_tools(server)

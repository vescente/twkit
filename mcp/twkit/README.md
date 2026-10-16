# mcp/twkit: the toolkit layer

The whole toolkit: it builds the XML (`book`, `conn`, `fields`, `sheet`, `dash`), edits, checks
and renders it. MCP tools in `server/` are thin wrappers over these modules.

## Modules

`selfcheck` reads this table: every module must be listed, and every `channel` must be called
from `preflight`. Add a row when you add a module.

| module | role | responsibility |
|---|---|---|
| `blocks.py` | build | dashboard constructions known to open |
| `book.py` | build | the workbook being built: skeleton (locale `en_IE`), open and save, calculations, parameters, sheets |
| `canon.py` | channel: metrics | metric definitions as executable checks on formulas and SQL |
| `cdp.py` | view | one persistent headless Chrome for the frame, over CDP (own port and profile) |
| `chclient.py` | data | the ClickHouse HTTP client, the only way twkit reaches ClickHouse; `explain_ast` returns the server's parse tree; read-only queries carry server limits (time, 3 GB memory, external GROUP BY, cancel on disconnect) placed before `readonly=1` |
| `chsafe.py` | security | keep secrets out of ClickHouse tracebacks; SQL from a workbook or a tool runs only as one read statement: `ReadOnlyClient` checks it lexically (`read_only`), then by ClickHouse's own parse (`EXPLAIN AST`, `ast_read_only`) of the exact statement that runs (`SELECT * FROM (<sql>)`, as Tableau runs Custom SQL), with `readonly=1`; the output format is pinned and the parse tree must be complete; text that ClickHouse and Hyper would read differently (nested comments, a lone `\r`, backslash quotes, `$`, `#`, curly quotes and any non-ASCII outside a string) is refused; table functions are checked in every table position, inside `view(SELECT ...)` and bracketed `FROM (...)` too; a call is a name directly followed by a bracket (`a + (b)` is arithmetic, `EXTRACT(YEAR FROM (CAST(...)))` is a scalar) |
| `contentfit.py` | build | sizes from content: table column widths, header bands, title room; layout rows that keep tables at content height |
| `conn.py` | build | data source connections: CSV, Hyper (several tables related on a shared column), MySQL table or Custom SQL |
| `config.py` | settings | where settings come from: connections and secrets from the environment or `~/.twkit/.env` (template `example.env`); paths and guards from `~/.twkit/config.toml` |
| `csvcheck.py` | channel: csv | will Tableau's text connector read the CSV dates and numbers, or Null |
| `dash.py` | build | dashboards from a layout tree: zones, controls, legends, actions |
| `docs.py` | output | workbook passport for colleagues: pages, sheets, formulas |
| `dryrun.py` | channel: data | sheets translated to SQL and executed before handover; shared-view filters only on sheets of their source; exclusions as Tableau writes them (`NOT COALESCE(...)`, Null rows kept), the Null member as `IS NULL`, boolean filters with `false` and `except`; `why_empty` removes only date conditions before blaming the period and reads each sheet's own source; rows are ordered by the dimensions before the limit; filters it cannot apply are listed per sheet (`untranslated`) and reported by preflight as not checked |
| `edit.py` | edit | operations on an existing workbook: fields, sheets, pages, zones, filters, format; a field is resolved in the sheet's own source; `rename_field` replaces delimited names only (`[old]`, `:old:`), never captions or SQL; `set_caption` also updates the caption's text copies (action `field-captions`, filter card and legend titles, tooltip labels); Custom SQL is written as Desktop stores it (`escape_sql`) |
| `extract.py` | channel: source | database table to `.hyper` extract; extract references; `to_extract` packages the workbook's Custom SQL as an extract with the SQL kept underneath (refreshable on a server); the SQL is sent with Tableau's doubled `<<` / `>>` undone; empty strings stay strings, integers exact, `datetime` → timestamp, `boolean` → bool |
| `frame.py` | view | the workbook's dashboards rendered as HTML and measured in Chrome (`frame_publish`); workbook colours and fonts reach CSS only after a strict check, and each page runs only its own script (CSP); `expand=True` draws the pages after the show/hide clicks |
| `fields.py` | build | field expressions (`SUM(sales)`, `MONTH(date)`) and their sheet instances; what aggregates |
| `framecmp.py` | calibration | frame images against Tableau Public renders, per zone (OCR and ink) |
| `geodata.py` | view | US state centroids for the frame map model |
| `idiom.py` | analysis | how real workbooks do a technique; the diff of two workbooks as one action |
| `layoutmodel.py` | geometry | layout and text widths from XML, without pixels |
| `lint.py` | channel: format | will the file open: format, meaning, geometry |
| `order.py` | format | child order Tableau demands on save |
| `owner.py` | edit | the owner's workbook: inventory, snapshot, diff guard, install; a build from an older owner's file is refused (`source_md5`, else file times); protected paths compared by file identity |
| `palette.py` | color | custom named palettes in `Preferences.tps` |
| `preflight.py` | runner | runs every channel and lists what did not run |
| `preview.py` | view | thumbnails Tableau embeds on save |
| `render.py` | channel: layout | a page described in text: zone tree in px, shares, overflow |
| `safexml.py` | format | the single XML parsing point (`from_twbx` / `to_twbx`) |
| `schema.py` | data | table schema to Tableau fields |
| `selfcheck.py` | runner | invariants of the toolkit itself |
| `server/app.py` | server | the FastMCP instance, its instructions, the `twkit-mcp` entry point |
| `server/session.py` | server | the active workbook of one server process |
| `server/tools_book.py` | server | build tools over `Book`; `save_workbook` refuses blockers |
| `server/tools_twkit.py` | server | toolkit tools: style, data, checks, edits, views, the owner's workbook |
| `sheet.py` | build | a worksheet's chart: marks, shelves, encodings, filters, sorts, axes, labels, maps, style |
| `shot.py` | channel: eyes | capture of the Tableau Desktop window; window titles reach AppleScript only as escaped literals |
| `sketch.py` | channel: sketch | every sheet drawn from real data, stamped "SKETCH" |
| `spec.py` | build | a dashboard described as a YAML spec |
| `story.py` | build | story points from sheets |
| `style.py` | build | house style measured from a corpus |
| `stylecritic.py` | channel: critic | what the frame drew and where it reads badly; content needs |
| `stylescore.py` | channel: taste | distance from the corpus style |
| `tablecalc.py` | data | table calculations as window functions over the aggregated query |
| `tablog.py` | view | what Tableau logged when it opened the workbook |
| `xsd.py` | format | validation against the vendored Tableau schema (`vendor/tableau-document-schemas`) |

## Check channels

`preflight` runs all of them except window captures and lists what it could not run.
"Not checked" is never "fine".

| channel | sees | does not see |
|---|---|---|
| `lint_workbook` | format, meaning, geometry | data and look |
| `check_metric_canon` | wrong metric formulas | everything else |
| `dry_run_workbook` | whether sheets get data | LOD and table calculations |
| `dry_run_states` | data in every switcher state | look |
| `check_dead_dimensions` | empty filters | look |
| `check_visual` | clipped and merged labels, invisible magnitudes | the real render |
| `style_score` | match with the corpus style | meaning |
| `describe_render` | layout in words: zone tree, shares, overflow | color, font |
| `frame_publish` + critic | **every dashboard drawn and measured** (main layout): clipping, drift, empty space, color | what the model does not draw (below) |
| `view_thumbnails` | Tableau's render embedded at save time | the look after our edit |
| `screenshot_workbook` | what Tableau drew, one page | other pages; needs the screen |

**The frame is the primary view.** `frame.check(book)` publishes the workbook as HTML, renders it in
headless Chrome and measures the DOM; `stylecritic.critique` turns the measurements into findings
(codes `K*` clipping, `E*` empty space, `R1` row drift, `C*` color);
`stylecritic.content_needs` returns the height and width each sheet's content needs, so a builder
can size zones from content. A page measurement that fails is retried once (`stylecritic.probe`);
then the critic lists the page under `not_checked` and `content_needs` raises instead of dropping sheets.
A measure must describe the content, not what a builder did to it, or build and measure chase each other:
a stretched table (Entire View) is measured by its natural row height (`data-natrh`, taken before the
stretch), and title lines do not count trailing blank lines (padding that aligns neighbours). A difference between the frame and Tableau is a defect of the frame
model: fix it in `frame.py` with a test. `tools/frame_corpus.py` is the regression gate: no zone may
get worse against the Tableau Public baseline.

**The frame interprets every tool.** `tests/test_tools_in_frame.py` applies each MCP tool that changes a
workbook through the server to a CSV workbook: a visible change must change the XML and the drawn page,
and a new tool fails the suite until it is classified as visible, invisible by nature, or out of the
fixture's reach. The test proves that the page changes, not that it matches Tableau.

**What the frame reads as Tableau does.** Zones hidden by the author (`hidden-by-user`) are not drawn;
show/hide buttons carry Tableau's icons (✕ while the item is shown, ≡ while it is hidden) and `expand=True` draws the page
after their clicks, the item at its stored size and its flow neighbours sharing the rest. Filter card
titles come from the sheet style (`quick-filter`), card background and border from the sheet or
dashboard style (`quick-filter`, `parameter-ctrl`); a relative date card shows its period (Last 5
weeks); filters of a shared view apply to sheets of its source. Controls follow their mode (drop-down,
typed value, slider, list of parameter values). Sorting by a measure (`computed-sort`) orders members
inside their parent; a dual axis draws the second measure as a line (Automatic over a date) in its
Measure Names colour, an empty value takes the `%null%` colour; the grand total row takes the sheet's
`total-label`; cell and header borders follow the sheet style; the dashboard `title` zone shows its
title or the dashboard name.

**What the frame does not draw** (Tableau capture is the check there):

| what | effect in the frame |
|---|---|
| a second axis while the bars are split by a colour dimension (several members) | stacked bars, no line |
| filter list modes for filter cards (`checklist`, `radiolist`) | drawn as a drop-down |
| formatting of totals and subtotals (`data-class`), `fontname` in text runs | bold total, default font |
| mark labels "on selection" outside line panes | labels drawn |
| reference lines on horizontal bars, `scope` per pane or cell, bands | only on columns, lines and scatter |
| vertical alignment of text zones, text rotation, divider style, sheet title background, dashboard fill | default look |
| phone layouts, stories (placeholders), single worksheets | main layout of each dashboard only |
| a legend's own title (`edit_zone_title` on a legend) | the field caption |
| rows beyond the dry run limit (300) | the first 300 rows in dimension order |
Hover-only content is drawn too: a custom tooltip becomes the zone's `title`, filled from the first mark.
Row labels follow Tableau: one line with an ellipsis, even in a taller row (`cell` height) and with
`wrap` on (checked in Desktop).

**Half a workbook lives behind a switcher.** A sheet empty in one state is normal (sheet swap);
empty in all states is a blocker.

## Editing the owner's workbook: surgically

The owner edits their workbooks between our runs. **The source of an edit is always their current
file; our snapshot is only a rollback point.**

```
owner_check_source(book)   edited after us? say it out loud
open_workbook(book)        returns source_md5 of the file the edit starts from
owner_inventory(book)      inventory before the edit
… edits …
owner_plan(built, book)    what would be lost; renames and harmless losses the facts explain
owner_install(built, book, allowed_losses="…", renames="old=new,…", source_md5="…")
```

`owner_install` snapshots, compares sheets, pages, calculations, parameters, fields and zones, and on
any loss not listed in `allowed_losses` **refuses and writes nothing**. It also refuses when the owner's
file changed since the edit started (`source_md5`; without it, when their file is newer than the build):
the comparison is by names, so a formula they changed meanwhile would be reverted silently. Declare renames with
`renames`; `force` would hide a real loss together with the renames. `owner_plan` (`owner.suggest`)
derives them from facts (same formula, same parameter members, zones follow sheets; a builder may
add its own sheet identity) and names harmless losses with reasons, but applies nothing: an unused
calculation in the owner's file may be their work in progress.

Every other write is refused (`owner.check_write`, called by `safexml.to_twbx`, `save_workbook` and the
extract writers): a book with an install record, and any path in `[guard] protected` of
`~/.twkit/config.toml` outside its `[guard] writable` subfolders. Snapshots go to
`Workbooks/_ai/<book>/<time>-<md5>.twbx`. Do exactly what was asked; never replace their file
wholesale. A missing operation goes into `edit.py` as a tool for all workbooks, not into a
per-workbook script.

## Editing rules learned the hard way

- **A raw field of a text or extract source is declared only in `<relation><columns>`**, without
  brackets or role. Look fields up through `_instance_ref` / datasource columns, never the first
  `root.iter("column")` hit: copying that one blocks the save (unbracketed name), reading its role
  sums a dimension.
- **A field is addressed by its caption**, not its column name: `configure_chart` with the column
  name gives `Unknown field`; `edit_add_sheet` accepts both.
- **Declaring a field does not place it.** `edit_add_measure` handles measure tables only;
  everything else uses `edit_place_field`.
- **A measure table's column order can live on the sheet.** Desktop writes `<view><manual-sort>`
  on `[:Measure Names]` when columns are dragged, and it overrides the data source's
  `default-sorts`. `order_measures` edits the sheet's own order when there is one; `add_measure`
  appends the new column to it.
- **Technical columns are hidden, not dropped.** A column only calculations read (a sort key,
  a row-kind flag) still shows in the data pane and in every Measure Names list;
  `hide_fields` sets `hidden='true'` and refuses a field a view shows.
- **Removing a dimension absent from the data** takes four steps: `list_dependent_calcs` →
  `edit_drop_fields` → `edit_drop_param_members` → `edit_drop_case_branches`.
- **A filter that was set is not yet a filter.** A relative date filter can save, open and still not
  filter; only data in the view proves it.
- **Table calculations are about direction.** The attribute names the partition, so it reads
  backwards (`Columns` accumulates down the rows). Only `down`, `across`, `by field` are accepted.
- **`save_workbook` refuses a blocker** (extract references, format); `force=True` saves anyway.
- **The Tableau window is shared.** Captures lock it (`shot.acquire_window`), open a working copy
  under their own name, close it afterwards, and never quit Tableau.

Order: `open_workbook` → `edit_*` → `preflight` → `save_workbook`.

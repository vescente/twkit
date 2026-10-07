# mcp/twkit: the toolkit layer

The whole toolkit: it builds the XML (`book`, `conn`, `fields`, `sheet`, `dash`), edits, checks
and renders it. MCP tools in `server/` are thin wrappers over these modules.

## Modules

`selfcheck` reads this table: every module must be listed, and every `channel` must be called
from `preflight`. Add a row when you add a module.

| module | role | responsibility |
|---|---|---|
| `blocks.py` | build | dashboard constructions known to open |
| `book.py` | build | the workbook being built: skeleton, open and save, calculations, parameters, sheets |
| `canon.py` | channel: metrics | metric definitions as executable checks on formulas and SQL |
| `cdp.py` | view | one persistent headless Chrome for the frame, over CDP (own port and profile) |
| `chclient.py` | data | minimal ClickHouse HTTP client when no settings module provides one |
| `chsafe.py` | security | keep secrets out of ClickHouse tracebacks; SQL from a workbook or a tool runs only as one read statement (`read_only`), with `readonly=1` on the built-in client |
| `contentfit.py` | build | sizes from content: table column widths, header bands, title room; layout rows that keep tables at content height |
| `conn.py` | build | data source connections: CSV, Hyper (several tables related on a shared column), MySQL table or Custom SQL |
| `config.py` | settings | where connection parameters and data paths come from (`~/.twkit/config.toml`) |
| `csvcheck.py` | channel: csv | will Tableau's text connector read the CSV dates and numbers, or Null |
| `dash.py` | build | dashboards from a layout tree: zones, controls, legends, actions |
| `docs.py` | output | workbook passport for colleagues: pages, sheets, formulas |
| `dryrun.py` | channel: data | sheets translated to SQL and executed before handover |
| `edit.py` | edit | operations on an existing workbook: fields, sheets, pages, zones, filters, format |
| `extract.py` | channel: source | database table to `.hyper` extract; extract references |
| `frame.py` | view | the workbook rendered as HTML and measured in Chrome (`frame_publish`) |
| `fields.py` | build | field expressions (`SUM(sales)`, `MONTH(date)`) and their sheet instances; what aggregates |
| `framecmp.py` | calibration | frame images against Tableau Public renders, per zone (OCR and ink) |
| `geodata.py` | view | US state centroids for the frame map model |
| `idiom.py` | analysis | how real workbooks do a technique; the diff of two workbooks as one action |
| `layoutmodel.py` | geometry | layout and text widths from XML, without pixels |
| `lint.py` | channel: format | will the file open: format, meaning, geometry |
| `order.py` | format | child order Tableau demands on save |
| `owner.py` | edit | the owner's workbook: inventory, snapshot, diff guard, install |
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
| `shot.py` | channel: eyes | capture of the Tableau Desktop window |
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
| `frame_publish` + critic | **the whole workbook drawn and measured**: clipping, drift, empty space, color | Tableau's own quirks the model lacks |
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
fixture's reach.
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
owner_inventory(book)      inventory before the edit
… edits …
owner_plan(built, book)    what would be lost; renames and harmless losses the facts explain
owner_install(built, book, allowed_losses="…", renames="old=new,…")
```

`owner_install` snapshots, compares sheets, pages, calculations, parameters, fields and zones, and on
any loss not listed in `allowed_losses` **refuses and writes nothing**. Declare renames with
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

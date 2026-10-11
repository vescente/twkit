# twkit

An MCP server that builds, edits, checks and renders Tableau Desktop workbooks (`.twbx`).
Agents call its tools as `mcp__twkit__*`; a person opens and publishes the result.

## Features

- **Build**: data sources (CSV, Hyper extracts with related tables, MySQL tables or Custom SQL),
  calculated fields, parameters, worksheets (bars, lines, areas, text and measure tables, pies,
  treemaps, maps, dual axes), dashboards with parameter controls, filter cards, legends and
  actions. A dashboard can be described as a YAML spec and assembled from tested blocks.
- **Edit**: fields, formulas, filters, sorts, table calculations, number formats, colours, zones
  and page layouts of existing workbooks. A person's own workbook is written only through
  `owner_install`: snapshot first, any unlisted loss refused.
- **Check**: `preflight` runs every channel at once (file format and schema, metric formulas,
  data dry run, empty filters, label fit, house style) and lists what it could not check.
- **Render**: every page is drawn as HTML in headless Chrome and measured for clipping, empty
  space, row alignment and colour, without opening Tableau.
- **Safe data access**: SQL from a workbook or a tool runs as a single read statement.

## Install

```bash
python -m venv .venv && .venv/bin/pip install -e ".[data,view,dev]"
```

Register the server in the MCP client (`.mcp.json`):

```json
{"mcpServers": {"twkit": {"command": "/path/to/twkit/.venv/bin/twkit-mcp"}}}
```

## Configure

Connections and secrets live only in the environment or `~/.twkit/.env` (copy `example.env`,
`chmod 600`); `~/.twkit/config.toml` holds paths and guards and never a connection. `show_config`
reports what resolved, a password only as present or absent. The environment overrides the file:

| what | variables (environment or `~/.twkit/.env`) |
|---|---|
| ClickHouse (data checks, extracts) | `TWKIT_CH_HOST`, `_PORT`, `_USER`, `_DB`, `_PASSWORD`, `_CERT` |
| workbook database (Tableau sign-in) | `TWKIT_DB_HOST`, `_PORT`, `_USER`, `_NAME`, `_PASSWORD` |

SQL from a workbook or a tool reaches ClickHouse only as one read: it passes a lexical check, then
ClickHouse's own parse (`EXPLAIN AST`, which runs nothing) of the exact statement that runs, a
subquery as Tableau runs Custom SQL, with `readonly=1`.

Folders protected from every write except `owner_install`:

```toml
[guard]
protected = ["~/Documents/My Tableau Repository/Workbooks"]
writable = ["~/Documents/My Tableau Repository/Workbooks/_ai"]
```

## Requirements

- Python 3.10+; Chrome for the page renders.
- Tableau Desktop only for window captures and open checks (macOS, Screen Recording permission).

Development: `CLAUDE.md` (also `AGENTS.md`).

## Licence

Proprietary: all rights reserved (`LICENSE`). The Tableau document schemas in
`vendor/tableau-document-schemas/` are Tableau's files under the Apache License 2.0
(`LICENSE.txt` alongside), used only to validate workbooks.

# House dashboard style, extracted from a corpus

Not design theory but **facts from 25 working workbooks**. Code: `mcp/twkit/style.py`. When a
generic best practice contradicts this file, **this file wins**.

**Corpus:** 25 workbooks · 311 sheets · 61 dashboards · 7345 calculations · 222 LODs.
Parameters: median 7 DISTINCT per workbook.

---

## 1. Parameters are the core of the style, not decoration

**Median 7 DISTINCT parameters per workbook** (up to 14 in large ones). Count unique parameters,
not `<column param-domain-type>` occurrences: Tableau repeats a parameter declaration in every
sheet's `<datasource-dependencies>`, which inflates raw counts six-fold. No dashboard in the
corpus has zero parameters. This is self-service: one view serves N metrics and dimensions, and the
user switches.

Canonical names (by corpus frequency):

| Parameter | Count | Type | Values |
|---|---:|---|---|
| `p_start_dt` / `p_end_dt` | 107 / 107 | date, any | a date pair, **in every workbook** |
| `Year` / `Month` | 53 / 53 | list | alternative to the date pair |
| `p_cohort_period` | 43 | list | day / week / month / year |
| `Level 1..3` | 40/40/30 | list | drill-down hierarchy |
| `p_dim1..3` | 38/34/28 | list | dimension switchers |
| `p_period_granuality` | 35 | list | day / week / month / quarter / year |
| `p_main_date_level` | 26 | list | main axis granularity |
| `p_romi_metric`, `p_ca_metric`, `p_retention_metric` | 26+ | list | metric choice |
| `p_date_format` | 25 | list | date label format |
| `p_visibility` | — | list | Percent / Fact view switch |

Types: `list` 1223, `any` 348, `range` 6 → **lists dominate**, sliders are rarely needed.

Conventions:
- prefix **`p_`** (snake_case) for working parameters; `Level N`, `Metric` for user-facing ones
- the first item of a dimension list is **an empty string `" "`** = "no split"
- metric values are human captions (`'Dep sum'`, `'FTD count'`), not column names

## 2. Switcher: the main calculation pattern

```
IF [Parameters].[p_metric] = 'NGR' THEN SUM([ngr])
ELSEIF [Parameters].[p_metric] = 'FTD count' THEN SUM([ftd_count])
...
END
```

Metrics, dimensions (`Dim 1/2/3`) and comparisons (fact / plan / prior) are all built this way.
Helper: `style.switcher(param, {value: expression})`.

Companions:
- granularity: `DATE(DATETRUNC([Parameters].[p_period_granuality], [event_date]))`
- period filter: `[event_date] >= [Parameters].[p_start_dt] AND [event_date] <= [Parameters].[p_end_dt]`

### Fact / plan / prior triplet
In KPI workbooks a metric comes in three versions: `_fact`, `_plan` (target), `_prior` (previous
period), plus derived `_mtd`, `_kpi`, `_vs_target`. Data arrives in **long format** (a `metric`
column + `valfact`/`valplan`/`valfact_prior`); the pivot happens in Tableau:
`IF [metric] = 'ggr' THEN [valfact] END`.

### LOD
202 `{ FIXED ... }` expressions: used freely, not exotic.
Example: `{ FIXED [country], [metric], DATETRUNC('month', [event_date]) : MAX([valplan_month]) }`

## 3. Palette

**Tableau 20 as is.** Each color appears 478–578 times in the corpus, evenly: the stock palette is
used whole, with no custom picks.

```
#4e79a7 #f28e2b #e15759 #76b7b2 #59a14f #edc948 #b07aa1 #ff9da7 #9c755f #bab0ac
#a0cbe8 #ffbe7d #8cd17d #86bcb6 #f1ce63 #d37295 #fabfd2 #b6992d #499894 #79706e
```

Auxiliary: table bands `#eef1f3` (corpus measure; builds use the warm `#f6f1ef`), "no fill"
`#00000000` (transparent, the Tableau way).

## 4. Number formats

Corpus measurements. Masks the vendor ships but the corpus does not use are in
`TABLEAU_APP_NOTES.md` section 3.

| Format | Count | Use |
|---|---:|---|
| `p0.0%` | 461 | shares, **the main one** |
| `n#,##0;-#,##0` | 330 | counts |
| `n#,##0.0;-#,##0.0` | 287 | sums |
| `*dd.mm.yyyy` | 240 | dates |
| `*d mmmm yyyy` | 145 | dates in words |
| `p0.00%` | 112 | finer shares |
| `*↑ #,##0.0%;↓ #,##0.0%; ` | 98 | **deltas with arrows**, the signature technique |
| `c"€ "#,##0;"€ "-#,##0` | 86 | money (euro) |
| `*+0.0%;-0.0%` | 73 | signed deltas |
| `n#,##0,K;-#,##0,K` | 6 | thousands |

The empty third segment in `↑…;↓…; ` means zero is not drawn at all.

## 5. Dashboard size

| sizing-mode | Count |
|---|---:|
| `range` (min/max, stretches) | 27 |
| `automatic` | 24 |
| `fixed` | 10 |

**Stretching is the norm, fixed is the exception.** Typical range:
`minwidth 1100 / maxwidth 3200 / minheight 800 / maxheight 1900`.

`add_dashboard` writes `fixed` unless `style.apply_sizing(wb)` sets `range` (or `automatic`)
before it.

## 6. Layout: controls on the dashboard

| Zone type | Count |
|---|---:|
| `filter` | 956 |
| `container` | 617 |
| `paramctrl` | 549 |
| `layout-flow` | 370 |
| `layout-basic` | 166 |
| `text` | 42 |

There are more controls than containers. A parameter and filter panel is a required part of a
dashboard, usually a separate container on the left or top. Helper: `style.control_panel([...])`.

### Left column item height, px

Measured over 57 working workbooks: only zones with `is-fixed="true"` inside a vertical flow, where
`fixed-size` is the declared height in pixels.

| item | n | median | mode | use |
|---|---:|---:|---:|---:|
| `dashboard-object` (navigation button) | 81 | 42 | 39 | **40** |
| `paramctrl` | 35 | 47 | 47 | **47** |
| `filter` | 36 | 58 | 24 | **58** |

The filter mode of 24 is a degenerate single compact filter, so the median is used. The numbers
live in `edit.COLUMN_ITEM_PX`; their sum is checked against the container height at the MINIMUM
canvas height.

Column position drifting between pages is taste, not breakage: three working workbooks drift by
Δy 15 000…64 000 of 100 000. Hence `R28` is info.

## 7. Mark types

`Automatic` 216 · `Bar` 49 · `Area` 46 · `Line` 44 · `Shape` 36 · `Text` 33 · `Square` 32 ·
`Circle` 6 · `Pie` 5.

`Automatic` dominates (Tableau picks by shelves). `Square` is for cohort heatmaps, `Text` for KPI
tiles and tables, `Shape` for status icons. Pies are almost never used.

## 8. Sheet formatting

Top attributes: `border-style/width/color` (~2800 each, almost always `none`/`0`), `margin` 2451,
`padding` 1134, `line-visibility` 714, `stroke-size` 657, `background-color` 571,
`mark-labels-show` 451.

So: **borders are removed, padding is tuned by hand, mark labels are turned on selectively.**
Corpus fonts: `Google Sans Text`, `Benton Sans Book`, `Tableau Light/Medium`, `Arial`.
Sizes: 22 (KPI), 16 (title), 11 (labels), 10 (body).

**Tables:** one typeface and one size for the whole table, zebra rows `#f6f1ef`, deltas with an
arrow and colored by sign (green up, red down). Details: DESIGN_KB section 5, "Tables: three
required traits".

## 9. What the corpus never does

Measured with `tools/study_workbooks.py` (re-measured 2026-10-05): ~50 zones per dashboard, nesting up
to 11; sizing `range` 27 / `automatic` 24 / `fixed` 9; table calculations 122; parameter-driven
formulas 1247; a grand total row, where present, is on top (3 of 3).

| technique | count |
|---|---|
| mark type left `Automatic` | 46% |
| reference lines | **2** |
| annotations | **0** |
| customized tooltips | **0** |
| top-N filters | **0** |
| custom palettes | **0** |
| device layouts | **0** |

The zeros are unfinished work, not the style: close them while keeping the house parameters and
palette (`DESIGN_KB.md` section 9).

---

## Why a generic dashboard looks thin here

| Style trait | Generic build | Corpus |
|---|---|---|
| Parameters | **0** | median 7 distinct per workbook |
| Switcher calculations | 0 | the basis of everything |
| Controls on the dashboard | 0 | 1915 zones |
| sizing-mode | fixed | range/automatic (51 of 61) |
| Palette | custom "validated" | Tableau 20 |
| Number formats | `$#,##0,K` by hand | `p0.0%`, `€`, `↑↓` from the set |
| LOD | 0 | 222 |

Generic design discipline is not the house style; measure the corpus instead.

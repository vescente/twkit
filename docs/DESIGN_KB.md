# Tableau Dashboard Design Playbook

Read BEFORE building, together with the house style (`house_style_rules`). This file is what `design_rules`
returns.

| file | answers |
|---|---|
| `STYLE_GUIDE.md` | **how the house does it**: palette, number formats, parameters (measured) |
| `DESIGN_KB.md` (this file) | **how to do it well**: composition, choice of form, analytical depth |
| `NAMING_RULES.md` | how to name fields and sheets, which folder they go in |

Conflict rule: the house style is mandatory; this file decides what goes inside it.

**Corpora.** "Measured" below always refers to one of these, profiled with `tools/study_workbooks.py` or by
targeted XML inspection; anything without a corpus number is practice. **Calibration law:** a rule that flags
working workbooks of the corpus is wrong, not the workbooks.

| name | contents |
|---|---|
| house corpus | 25 working workbooks of the reference author: 311 sheets, 61 dashboards |
| public corpus | 25 Tableau Public / Viz of the Day workbooks: 595 sheets, 55 dashboards |
| vendor corpus | 21 vendor reference workbooks |
| production corpus | 37 reports of a production Tableau Server deployment and its live KPI overview |

## 1. Question first, charts second

A dashboard is an answer to a question, not a shelf of metrics. Settle four things before the first line of
XML:

1. **Who looks and what they decide.** A traffic manager and a CFO read the same revenue with different eyes.
2. **Which question:** "how much", "how is it changing", "where is the skew", "why did it drop".
3. **What counts as normal:** the comparison base. A number without one is useless.
4. **What action follows.** If none, drop the metric. No answer to all four → too early to build; clarify
   first.

Then fix the reading mode, because it sets density:

| reader | mode | page shape |
|---|---|---|
| executive | monitor: "are we fine?" | 4–6 KPI tiles, one trend, no detail table on page one |
| analyst | explore: "why?" | parameters, switchable breakdowns, drill to detail |
| operator | act: "what do I handle now?" | sorted table with thresholds, filters on top |

Write the page purpose as one sentence ("Is deposit volume on plan this month, and which countries drive the
gap?"). Every view serves that sentence; a view that serves none is cut.

## 2. Composition: top to bottom, decreasing abstraction

A proven skeleton that fits almost any report:

```
[ control column ]   date parameters, granularity, breakdown switches
──────────────────────────────────────────────────────────────────────
[ KPI row ]          4–6 hero numbers + delta to the prior period (↑↓)
[ trend ]            1 main measure over time, granularity by parameter
[ breakdowns ]       2–3 bars by dimension (geo, source, segment)
[ detail ]           table, only under a filter — never load everything
```

Row rules:
- **One row, one thought.** Do not mix "how much money" and "how many people" in one row.
- **Left to right: from the main to the particular.** The eye follows an F-pattern.
- **Detail always at the bottom and always last.** Never at the top.
- **Empty space is a design element.** An `empty` zone as a spacer is more honest than a stretched chart. The
  house corpus has 20 such zones; use them more.
- **One control column for the whole workbook:** menus and filters occupy the same rectangle on every page, so
  nobody hunts for a button after switching pages. Measure with `layout_column_report`, fix with
  `edit_align_left_column`; limits: inside `layout-flow` coordinates are a cache; size is set only through
  `fixed-size`.
- **Every block gets a title text zone:** 422 `text` zones in the public corpus against 42 in the house; a
  block without a caption is not understood. The spec builder puts a 24 px bold 11 pt text zone above each
  sheet and hides the sheet's own title.

### Information hierarchy

- **5-second test.** Show the page for five seconds, then hide it. The viewer must name the main number, its
  direction and whether that is good. If not, the KPI row is wrong: too many tiles, no deltas, or the hero is
  not the largest thing on the page.
- **Top-left anchor.** The most important number sits top-left of the content area (the control column is
  chrome, not content). Never spend that spot on a logo or a filter.
- **Summary → trend → breakdown → detail:** each level answers the question the level above raises. A second
  question gets its own page and a navigation button, not a fifth row.
- **Size encodes importance:** the hero number is the largest type on the page; the main trend gets at least
  half the content width.

### Grid, spacing, sizing

- Tiled containers; float only deliberate overlays (the view critic flags a floating zone over sheet labels).
  Shallow nesting: depth 11 (house corpus) is overload. Size zones from the data (§14).
- **One spacing rhythm:** the spec builder uses 24 px block-title zones, 12 px after the KPI row, 10 px
  between blocks. Siblings in a row share edges and header height (§21).
- **Padding eats width** (`edit_zone_style`): a 24 pt KPI with `padding=12` was clipped right on the number.
- Default `sizing-mode="range"` (house: range 27 / automatic 24 / fixed 9; `STYLE_GUIDE.md` §5,
  `sizing_recipe`); check at the range **minimum**. `fixed` only for image-like pages (email snapshots). Phone
  layouts only for a real phone audience (the house corpus has none).

## 3. Choosing the form

The data task chooses the form, not taste:

| task | form | why not something else |
|---|---|---|
| one number now | hero text | a single value has no shape; a chart of it is junk |
| change over time | line | area only when the accumulated volume matters |
| contribution of parts over time | stacked area | a pie cannot show dynamics |
| magnitude by category | horizontal bar | labels stay readable, many categories fit |
| share of a whole, 2–4 parts | 100% stacked bar | a pie is acceptable for 2–3 shares only |
| two measures per object | scatter | never two axes on one chart |
| density period × segment | square (heat map) | a table of numbers hides the hot spot |
| cohort | triangular table + color | lines per cohort merge into one |
| funnel | horizontal bars per step + step conversion % | a funnel shape lies by area |
| top-N ranking | bar + direct labels | no legend needed; the value sits by its bar |
| actual vs target per item | bullet: bar + target reference line | a gauge wastes space and hides the gap |
| exact lookup, many units per row | text table (§5) | a chart cannot carry six units in a row |

Hard rules:
- **`Automatic` mark type is not a choice.** 46% of marks in the house corpus are automatic: Tableau decided.
  Set the form deliberately (lint R17).
- **Dual axis is off by default** (lint R19 reports it as an error). Different scales → two charts stacked
  with a shared X axis. The one exception is a rate line over its own volume bars when a reference design
  calls for it (§19): `edit_dual_axis`, with the R19 finding stated as a deliberate decision.
- **At most one pie per dashboard. One shelf, one measure** unless magnitudes are within ×50 (§18).

### Chart rules that prevent misreading

- **Bars and areas start at zero.** Length is the encoding; a truncated bar axis lies. Lines and dot plots may
  zoom to the data range, and then the axis must show where it starts.
- **Sort by value** (`edit_sort_by_measure`), largest on top. Otherwise Tableau sorts by label and a ranking
  reads as a list. Ordinal categories keep their natural order: months, age bands, D1/D7/D30.
- **Direct labels beat legends.** Label bar ends; label line ends or the last point; drop the legend once
  every series is labeled in place. Never label every point.
- **Put the comparison on the chart** as a reference line (`add_reference_line`; `blocks.trend` adds an
  average line by default); a "normal range" is a reference band, e.g. min–max of the prior four weeks.
- **Annotate anomalies:** one short note with the cause ("payment outage 12 Mar") on the mark itself.
- **Mark or exclude the incomplete period.** A partial current day, week or month always looks like a
  collapse: filter to complete periods, or draw the last one lighter and label it partial.
- **Five lines at most.** More series → color one, grey the rest, or small multiples on one shared axis (§20,
  recipe 5).
- **Stacks:** four segments at most; only the bottom segment and the total compare across bars.
- **Maps** only when location itself is the insight; for "which country is biggest" a sorted bar wins.
  **Scatter:** median reference lines make quadrants; label outliers only.

## 4. Color

Color encodes the role of the data; it does not decorate:

- **magnitude** → one hue, gradient by lightness;
- **identity** (source, geo, provider) → categorical palette slots in order, never cycled; otherwise the
  survivors of a filter get repainted;
- **state** (good/bad) → only together with a label; color alone tells a colorblind reader nothing;
- **never color by rank.** Color belongs to the entity; the top-1 must not change color when it is overtaken.

Palette: Tableau 20 as is (`style.PALETTE`); no custom palettes. The house corpus has zero custom palettes
across 25 workbooks; the stock palette reads well and everyone knows it.

Service colors in the house corpus (by frequency): text `#000000`, grey grid `#b4b4b4`, background `#ffffff`,
table bands `#eef1f3` (builds use the warm `#f6f1ef`, `style.BAND_WARM`), light accent background `#f0f7fa`.

### Semantic color stays apart from categorical color

- Fixed roles in `style.py`: `SERIES` `#4e79a7` main series, `ACCENT` `#f28e2b` comparison or prior period,
  `NEGATIVE` `#e15759`, `NEUTRAL` `#bab0ac` for "Other" and background series.
- If red and green mean bad and good anywhere on a page, no category on that page is red or green.
- **Color means good/bad, not up/down.** For metrics where growth is bad (churn, cost, bonus share, CPA)
  reverse the sign scale (`edit_color_range`, `Reversed`).
- **Ordered states take an ordered scale.** Risk or health levels (Low / Medium / High / Critical, risk
  buckets, tiers) go green → amber → red in their order: `#8cd17d`, `#ffbe7d`, `#ff9da7`, `#e15759` from
  Tableau 20. Tableau's default assigns hues alphabetically (High blue, Low orange), which reads as noise.
- A measure or member keeps one color on every sheet. A color map lives on the datasource and needs a
  column instance there, or it is silently dead.

### Highlight: one accent, grey the rest

Pre-attentive attributes (hue, intensity, size, position) are read before conscious attention; spend them on
one thing per view.
- Paint the series that matters in `SERIES` or `ACCENT`, every other series `NEUTRAL`. "Which line is ours?"
  disappears, and so can the legend. A highlight action does the same on click.
- About **7 categorical hues** per view at most; beyond that, top N in color and a grey "Other"
  (`blocks.top_n_with_other`), or a table. The view critic flags more than 12 colors, pairs with ΔE2000 < 5 in
  one legend, and text contrast below 3.
- Many lines, one chart: color the five largest series, put the rest in a grey "Other" color while the series
  field stays on Detail, so each grey line keeps its own path instead of summing into one.
- **Color key in the title** instead of a legend zone: a colored ■ and a dark label per series
  (`edit.set_sheet_title(..., legend={label: color})`). It costs no layout space and sits where the eye starts;
  the label stays dark, since a light hue as text fails contrast.
- Stack only quantities that add up (counts, money). Ratios and per-unit averages (`%`, ARPU, per player) per
  segment are lines: a stacked margin reads as a sum that does not exist.

### Sequential versus diverging

- **Sequential** (one hue, light → dark) for magnitude: heat columns, cohorts, density. **Stepped** color for
  status (`num-steps`, `edit_color_steps`).
- **Diverging** only around a meaningful midpoint, set explicitly: `center='0'` for deltas, 1 (100%) for "% to
  target". One side washed out → `Use Full Color Range` (§16).
- Heat columns keep **Include Totals** off, or the total row takes the darkest shade and every cell fades.

### Colorblind safety and contrast

- Never carry good/bad by red versus green alone (about 1 man in 12 cannot separate them): add the sign, an
  arrow (↑↓ or ▲▼) or position. Without a good/bad meaning prefer `orange_blue_diverging_10_0`.
- WCAG 2.1 AA: text ≥ 4.5:1; large text (≥ 18 pt, or 14 pt bold) and marks ≥ 3:1. `#757575` passes on white;
  lighter than `#767676` fails. The light half of Tableau 20 (`#a0cbe8`, `#ffbe7d`, `#8cd17d`, `#f1ce63`,
  `#fabfd2`) is for fills only, never text.

## 5. Typography and density

Measured sizes in the house corpus: `22` hero numbers, `16` titles, `11` labels, `10` body, `8` footnotes.
Bold only in titles and KPI values.

- Set every sheet title by hand (213 cases in the house corpus); never leave `Sheet 1`. Hide an axis that the
  title already explains. Grid quiet or off; no borders. Bands (`band`) only in tables; in charts they are
  noise.

### Type scale

| role | size, pt | weight | color |
|---|---|---|---|
| hero KPI value | 22 (18 in card rows, §15) | bold | `#1f1f1f` |
| page title | 16 | bold | text |
| block title (text zone) | 11 | bold | text |
| labels, axes | 11 | regular | text |
| table body and headers | 10, `Tableau Book` | regular | text |
| KPI caption | 9 | regular | `#757575` |
| footnote, source, freshness | 8 | regular | grey |

One font family per workbook. Nothing a reader needs goes below 9 pt (the view critic flags < 7 pt). A default
sheet title is 15 pt and wraps (§21): replace it with a text zone or set it.

### Numbers: alignment and format

- **Right-align numbers, left-align text,** each header aligned like its column. Digits must be fixed-width:
  `1,111` above `8,888` ends on the same pixel, or change the table font.
- **Same decimals** within a column and for a metric across the workbook: counts 0, shares `p0.0%` (house
  default), two decimals only for rates under about 1%.
- **One place for the unit per column:** the header (`GGR, €` over plain `n#,##0` cells, preferred in dense
  tables) or the house money mask with `€` in every cell. Never both.
- **Abbreviate** in KPI tiles and on axes (`style.FMT` `thousands`, `eur_k`, `eur_m`, `eur_fin_b`). Never
  `Display Units: Automatic`: it mixes K and M within one column.
- **Percent versus percentage points.** 3.4% → 3.9% is +0.5 pp, or +14.7% relative; head the column `Δ pp` or
  `Δ %`. For pp compute `([rate] - [rate_prior]) * 100` with a custom mask such as `+0.0" pp";-0.0" pp"`.
- **Deltas carry sign and arrow:** `style.FMT["delta_arrow"]` `*↑ #,##0.0%;↓ #,##0.0%; ` (98 uses in the house
  corpus) or `["delta_sign"]` `*+0.0%;-0.0%` (73). The empty third section of `delta_arrow` hides zero
  entirely; use `delta_sign` where a real `0.0%` must stay visible.
- **Negatives:** a minus or parentheses (`eur_fin`), one convention per workbook. **No color codes in masks:**
  Tableau ignores `[Red]`; color goes through the Marks card. Set formats by role:
  `edit_apply_house_format`, masks in `number_formats`.

### Tables: three required traits

A text table missing any of these looks like a draft, visibly, before anyone reads a number. The view critic
reports each missing trait as `T1`, `T2`, `T3`.

| code | trait | rule | tool |
|---|---|---|---|
| T1 | one typography | one family and one size for cells, row headers and column headers: `Tableau Book` 10. The first column is not larger and not in another font | `style.uniform_type(ws)` |
| T2 | zebra rows | every other row filled with `BAND_WARM` `#f6f1ef`: rules on `header` and `pane` (`band-color`) and on `table` (`band-size`), all three with `scope='rows'`. Only for tables with a dimension or `Measure Names` on Rows; a one-row KPI strip needs none | `style.row_bands(ws)` |
| T3 | deltas by sign | Δ, `% Change`, `vs prior`, `DoD/WoW/MoM/QoQ/YoY %`: arrow ↑↓ in the format and text colored by sign — growth green, decline red; absolute values black | `edit_sign_color` (measure table); one measure's color: §16 |

Adjacent sheets assembled into one table (a reconciliation block) get the same size and the same bands;
otherwise rows of different sheets differ in height and fill.

**Column width: truncation is not the defect; indistinguishability is.** Truncated labels appear in 31% of
house corpus sheets and are acceptable: `Partners_North…` and `Partners_South…` still read as different rows.
The failure is a surviving shared prefix: `Partners…` and `Partners…` are two identical rows with different
numbers. So widen a column not "until it fits" but until the **contested pairs** separate, usually far
narrower than full width. Eyeballing fails (in one production game table names did not separate at 92 px or at
210 px): `edit_fit_column_width` computes it by bisection on the sheet's real font, never below the full
labels or the ≈ 68 px Tableau itself keeps for a row header. **A taller row is not a third way:**
Tableau draws the row taller but keeps the row label on one line with an ellipsis, even with `wrap`
on for header, cell and label (checked in Desktop). Tables side by side share the row height, or their
rows drift (critic R1); `edit_fit_tables` aligns it. When width cannot help, do
not inflate the column: **move the distinguishing part to the start of the label** or change the breakdown;
the tool says so and sets no width.

**Header bands and titles follow the frame's measure.** A header that wraps into three or more lines at its
column width gets a band tall enough for them, and tables side by side share the tallest band, or their rows
drift apart. A narrow table under a long title widens its first column so the title takes two lines, not
three. `edit_fit_tables` measures in the frame, applies, and repeats until a pass changes nothing; it never
shrinks a size already set.

### Table discipline beyond the three traits

- **Choose a table over a chart** when the reader needs exact values to act, when rows carry measures in
  different units, when members run into the hundreds, or when magnitudes differ by more than ×1000.
- **Grand total on top** (§9): `edit_grand_total`.
- **Column order is logic, not alphabet:** volume → money → ratio, each delta right after its measure. Tableau
  sorts measure columns alphabetically unless told (`edit_order_measures`).
- **Conditional color on one or two key columns,** not all; heat fill via `edit_heat_columns`.
- **Row budget:** past about 50 rows it is a detail table (bottom, behind a filter, or top-N). Headers wrap to
  two lines rather than widen a numeric column.

## 6. What makes a dashboard smart

Beautiful and smart are different things. Smart means a number can be interpreted without the author in the
room. Techniques, in increasing order of value:

1. **Comparison base on the chart itself.** Prior period, plan, portfolio average as a reference line. The
   house corpus has **2 on 61 dashboards**: a gap, not a style. Add them (lint R18 reports a workbook with
   neither reference lines nor deltas).
2. **Delta with an arrow** next to each KPI: `*↑ #,##0.0%;↓ #,##0.0%; ` is `style.FMT["delta_arrow"]`, 98 uses
   in the house corpus. A signature idiom; keep it. Block: `blocks.delta_vs_prior`.
3. **Normalization.** Absolutes by geo cannot be compared; put a share or a per-player value next to them.
   Compute shares FROM SUMS, never as an average of daily shares (Simpson's paradox).
4. **LOD where another level is needed:** `{FIXED [user_id]: MIN([ftd_date])}` for a cohort,
   `{FIXED [partner_id]: SUM(...)}` for a partner's contribution while broken down by player. 222 LODs in the
   house corpus: the technique is mastered, use it more widely.
5. **Table calculations** for share of total, running total, rank (122 in the house corpus). The direction
   matters more than the formula: `edit_table_calc`, `table_calc_recipes`.
6. **Top-N + "Other".** Twenty bars do not read: top 10 plus an aggregated `Other` (`edit_top_n`,
   `blocks.top_n_with_other`). The house corpus has **zero** top-N filters.
7. **Actions between sheets** (filter / highlight) instead of a tenth side filter: a click on a bar filters
   the rest. 31 actions across 25 house workbooks is too few.
8. **A tooltip that explains the number.** The house corpus has zero customized tooltips. A good tooltip says
   what the metric is, how it is computed and what to compare it with (`edit_tooltip`).

Further levers:

9. **Explicit thresholds:** good / okay / bad as a visible formula (`blocks.threshold_status`,
   `blocks.split_by_status`; §20, recipes 3–4).
10. **Like-for-like windows:** last 7 days against the prior 7, month-to-date against the prior month to the
    same day. A full prior month against a partial current one is always "down".
11. **Pairs, not singles:** the denominator next to the absolute (§19).
12. **Small bases:** show N next to a rate; grey out or suppress rates below a stated minimum base.

KPI tile anatomy (value, comparison, period, sparkline): §14.

## 7. Self-service: parameters instead of ten sheets

The core of the house style: one view serves N metrics and breakdowns through parameters (median of 7 distinct
parameters per workbook; 1247 formulas depend on a parameter). Minimal set:

| parameter | gives |
|---|---|
| `p_start_dt` / `p_end_dt` | the period (present in every house workbook) |
| `p_period_granuality` | day / week / month / quarter / year |
| `p_metric` | metric switch on one chart |
| `p_dim1..3` | up to three breakdowns; the first item blank = "no breakdown" |

Built with `style.date_range_params / period_param / dim_param / switcher` (MCP: `param_recipe`,
`switcher_formula`). Controls go on the dashboard as a separate panel (`layout_control_panel`): the house
corpus has 1915 `paramctrl` zones, and without the panel a dashboard is not self-service.

The flip side: 50 zones per dashboard on average and container nesting up to 11 is overload. Do not copy that
density: **parameters yes, a dump of controls no.** 6–10 controls is reasonable; the rest go into a
collapsible panel (`edit_zone_hide_button`). Project rule: parameters from the house, analytical depth from
the vendor corpus, density from nobody.

Parameter hygiene:
- **Defaults must render;** the states channel (`dry_run_states`) blocks a sheet empty in all states.
- **Group switchable metrics by unit.** One calculation carries one number format: a switcher flipping between
  € and % shows one of them wrong. One switcher for money, one for rates, or swap sheets (§17).
- **Echo the choice** in the title (`<[Parameters].[p_metric]>`), so a screenshot still says what it shows.
- Metric items are readable labels (`'FTD count'`), not column names; controls get their own titles
  (`edit_zone_title`) so a parameter and a filter on the same field do not share a caption.

## 8. Pre-delivery checklist

- [ ] date and granularity parameters are on the dashboard; the control panel is visible
- [ ] every number has a comparison base (prior period / plan / average)
- [ ] the 5-second test passes: main number, direction, good or bad
- [ ] mark types set by hand, no `Automatic`; no dual axis (or the stated §19 exception)
- [ ] shares computed from sums, not averaged across rows; sheet titles meaningful, duplicate axes hidden
- [ ] number formats from `style.FMT`; money with `€`, shares `p0.0%`; no mixed K/M in a column
- [ ] color encodes the entity, not the rank; red/green always with an arrow or sign
- [ ] text contrast ≥ 4.5:1; nothing a reader needs below 9 pt
- [ ] the incomplete current period excluded or marked
- [ ] tables: T1–T3 clean, total on top, columns in logical order
- [ ] detail at the bottom and under a filter
- [ ] at most 5–6 filters visible; the active period stated in text on the page
- [ ] data freshness shown; tooltips explain the key metrics
- [ ] no `Null` categories and no internal calculation names on screen
- [ ] `sizing-mode=range`; the page checked at its minimum size
- [ ] **lint: `lint_workbook` → 0 errors**; `preflight` says deliverable; the file is `.twbx`

## 9. Closing the corpus gaps

The house corpus is measured in `STYLE_GUIDE.md` (numbers live only there). Its zeros (no reference
lines, annotations, custom tooltips, top-N filters, custom palettes or device layouts) are unfinished
work, not the style. Close them while staying in style: **parameters and palette as in the house,
deeper analytics.**

**A table total is a shelf attribute, not a node:** `<rows onTop='true' total='true'>`, `<cols total='true'>`
(`onLeft='true'` puts the column total on the left). Tableau draws the "Total" label itself: the corpus has no
`totals-*` formats, there is nothing to set. Use `edit_grand_total`. Do not confuse it with
`configure_subtotals`, which handles subtotals inside breakdowns and supports only average and minimum.

---

## 10. Filters and interactivity

- **Placement:** global controls in one column (§2), the same rectangle on every page: left in the house,
  right equally valid (`edit_control_column`). A control for one view sits directly above it
  (`edit_put_controls_over`). Order: period, granularity, breakdown, narrowing filters.
- **At most 5–6 visible filters,** 6–10 controls in total (§7); the rest behind a hide/show button
  (`edit_zone_hide_button`) or replaced by actions.
- **Types:** lists dominate among house parameters (`STYLE_GUIDE.md` §1); sliders are rarely needed. No
  multi-value list boxes (they eat height). Long member lists (players, games, campaign IDs): wildcard or
  type-in filter, or a parameter, never a multi-select list of thousands.
- **Defaults:** the last complete period via a relative date filter (`edit_relative_date_filter`); hard dates
  show the past six months later. Default breakdown: none (§7).
- **Active state on screen:** the period in words (§14) and a non-default filter in the subtitle ("Country: 3
  selected"). Navigation buttons link only to OTHER pages (§18).
- **Actions:** filter action from summary bar to detail table; highlight action for one member against the
  rest. On clear, a detail table uses `Exclude all values` (empty until a click: faster, forces intent),
  summaries use `Show all values`.
- Top-N under a dimension filter needs that filter in context (`edit_filter_context`). A filter that "applied"
  can still fail to filter: confirm the row set changes between states
  (`screenshot_param_states`).

## 11. Performance

A slow dashboard is a broken dashboard: readers stop opening it.

| lever | rule |
|---|---|
| extracts | Ship a `.hyper` extract: `save_as_extract` materializes the live Custom SQL inside the package, so the workbook opens without a password or VPN and the source is not queried on every open. Hide unused fields first; aggregate to the visible grain where possible |
| fewer sheets | Every sheet is a query. One parameterized view beats five toggled sheets (§7) |
| fewer marks | Hundreds of marks per view, not tens of thousands. A text table with thousands of rows is slow and unreadable: detail goes behind a filter or an action |
| context filters | Put the narrowing filter in context (`edit_filter_context`); dependent filters and top-N then work on the smaller set |
| quick filters | "Only relevant values" re-queries every filter on each change; prefer "All values in database" or "All values in context". No multi-select lists on high-cardinality fields. Show the Apply button on multi-select filters |
| calculations | Numbers and booleans over strings. Push heavy row-level logic, `COUNTD` over huge fields and wide `FIXED` LODs into the SQL or mart layer |
| dates | Filter on the real date column, not a calculated date: faster, and checks can read it (§14) |
| diagnosis | Tableau Desktop: Help → Settings and Performance → Start Performance Recording; fix the slowest query first |

## 12. Accessible to every reader

- Contrast per WCAG 2.1 AA and color never the only carrier (§4); 9 pt minimum for anything a reader needs.
- **Nothing only on hover.** The conclusion and the key number read without tooltips, on touch screens and in
  exports.
- **Titles state content** ("GGR by month, last 12 complete months", not "Chart 3"): assistive technology
  reads titles and captions, not pixels. No text inside images.
- **Reading order = layout order:** tab order follows the layout tree (Item hierarchy).

## 13. Trust: freshness, definitions, consistency

- **Freshness on the page.** A small text line, "Data through 3 Oct 2026, refreshed daily", built from
  `MAX([event_date])`, never typed. Check freshness before delivery with `verify_data`.
- **Definitions at hand.** Each key metric has its definition in a tooltip ("NGR = GGR − bonuses; excludes
  test accounts") or on an "About" panel behind a hide/show button.
- **Canonical metrics.** Formulas come from `metric_canon` and are checked by `check_metric_canon`; names
  follow `NAMING_RULES.md` (`naming_rules`, lint R35). A metric has one name, one format and one color across
  the workbook.
- **Numbers reconcile:** a KPI tile equals the table total under the same filters; shares add up to 100%.
  Where scopes differ, the subtitle says so.
- **Missing is not zero:** reveal gaps (Show Missing Values; Special Values → Hide (Break Lines)) instead of a
  line that dives to zero.
- **No internal labels** on screen (§18). **State the scope:** currency, timezone, exclusions (test players,
  internal traffic) in a footnote.

## 14. KPI cards

Reference: a production KPI overview dashboard (acquisition and retention tabs) that people open every day.
Not taste: a working product.

**A card has four tiers, top to bottom, in exactly this order:**

| tier | what | why |
|---|---|---|
| 1 | METRIC NAME in small caps (`NRC'S #`, `D1 RET %`) | without a name a big number is unreadable: "1 694" says nothing |
| 2 | the number, large (`1,192`, `€47K`, `14.7%`) | what the reader came for |
| 3 | delta with sign and a named BASE (`-9.8% vs Prev 7D`) | a number without a base means nothing; the base is spelled out |
| 4 | filled area over the period | shape beats points: rising or falling at a glance |

Color carries meaning: delta and area are green on growth, red on decline. The card has a border and rounded
corners: eight cards read as a row, not as one continuous strip.

**Comparison base: the previous 7 days** (`vs Prev 7D`), not month-to-date and not all time. Consequence for
the build: the default period window must leave the PRIOR window inside the data too; otherwise the delta is
NULL and the arrow slot is empty.

**Lines.** No point labels on any line. At most the last point, or the end of each line in a set, is labeled
(`CHURN % - TOP 4 COUNTRIES`). Sparse date axis (`Aug 20 · Aug 22 · …`), no axis titles, a dashed trend line.
Labeling EVERY value turns a chart into mush. **Bars:** the number sits at the bar end (`102,585`, `57%`).
**The period is printed as text** on the dashboard (`Date: August 26, 2026 until September 1, 2026`).

General rule: **a label is part of the data, not decoration.** Metric name, comparison base and period bounds
must be on screen; labels on every point are the opposite: noise.

### Building cards

- **Two ways.** (a) Micro-sheets per element (number, delta, header, sparkline) stacked in one container (§20,
  recipe 1). (b) One sheet with `edit_kpi_tile`: value and caption in one `<customized-label>` (defaults:
  value 22 pt `#1f1f1f`, caption 9 pt `#757575`, caption below); then hide the sheet title
  (`edit_show_zone_title(..., show=False)`) or the caption doubles.
- **Caption above or below,** one choice per workbook: above in the production card, below in the casino
  reference overview (§19). **4–6 cards per row,** 8 at most when framed.
- **Color the delta, not the hero number;** sign color follows metric polarity (§4). Formats: `eur_k` /
  `eur_m` / `thousands` for the value, `delta_arrow` for the delta.
- **Sparkline:** the comparison window or longer; no axes, no axis titles, at most a last-point label. One
  card per BREAKDOWN VALUE is a different build: §15.

### Details that make a card look like a draft

Each one was caught by a screenshot; no automatic channel sees them.

| what shows on screen | cause | fix |
|---|---|---|
| a "1 null" badge in the corner of a card | rows of OTHER metrics leaked into the sheet: their formula gives NULL | narrow the sheet to its own metric with a filter |
| a `Null` category on the time axis | rows without a date in the data | range filter on the REAL date column (`edit_range_filter`), not on a calculated flag: checks cannot read that |
| scrollbars inside the card | the sheet took more than its zone | Fit: Entire View (`edit_sheet_fit`, `edit_zone_fit`) |
| axis labels on a 100 px strip | a sparkline needs no axes at all | Show Header off; `edit.hide_axis_titles` |
| an empty band under a table | zone height set by eye, fewer rows than space | compute the height from the ROW COUNT |
| metric name cut to "Deposits € .." | default row-header width | `edit_column_width` on the metric column |

**A zone takes its size from the data,** not from a round number: emptiness and scrolling always mean a
mismatch between zone size and sheet content.

## 15. A card row from ONE sheet (breakdown → cards, metrics → lines)

A different task from §14: there, one tile per metric; here, one card per BREAKDOWN VALUE with several metrics
inside. Typical block: "for each geo group: ROI, Net, Contribution, Overhead, NGR, number of countries".

**A measure table cannot build this.** `Measure Names` on a shelf puts each measure into its own column:
instead of four cards you get a 4×6 matrix. The right form is a `Text` mark with the measures on Text ONE BY
ONE (`<text column=…>` per measure, no `Measure Names`), rendered by a `<customized-label>`. Tool:
`edit_text_card`.

| shelf | contents |
|---|---|
| Columns | the breakdown (gives the cards) |
| Rows | empty |
| Text | every measure of the card, one `<text>` per measure |
| label | `<customized-label>`: lines top to bottom |

**Color is set PER LABEL LINE, not through a color encoding.** On a text mark the mark color paints the WHOLE
label: "large number colored by class, captions grey" arrives single-colored, and the grey captions turn red
with the number. Checks miss it (valid XML, data present, the difference exists only on screen); lint R38
catches it.

Consequence: conditional color (green / yellow / red by threshold) is not available in such a card. Either the
card is single-colored and health reads from the number itself, or the class goes into a SEPARATE element.
Never promise both.

**Tableau has no gaps between cards:** panes stand edge to edge. A column divider draws the boundary:
`table-div`, `line-visibility=on`, `stroke-color`, `stroke-size`. Without it the row reads as one solid block.

**Left alignment, small type.** Working scale: breakdown value (column header) 10 bold, main number 18 bold,
second line 10, caption lines 9 grey `#6b7a8c` (about 4.4:1 on white, just under AA: keep it for captions,
never for numbers). Centered, such a block looks like a poster; left-aligned, like a card. **Hide the sheet
title** when a text zone above the block carries the caption (`edit_show_zone_title(..., show=False)`).

**Drop groups without a denominator.** When the card metric is a ratio (ROI = contribution / overhead), a
breakdown value without a denominator gives an empty big number and the card reads as broken. Filter it out
(`{FIXED [breakdown] : SUM([denominator])} > 0`) instead of leaving it empty.

### Pie shares: EXCLUDE LOD, not WINDOW_SUM

Shares on segments (`55%`, `17%`) through `COUNTD(x) / WINDOW_SUM(COUNTD(x))` fail: without explicit
addressing the window equals ONE segment and every segment shows `100%`; in XML the addressing is a
`<table-calc>` with an `ordering-type` tied to one specific shelf layout.

A LOD computed AFTER the sheet's filters is more reliable:

```
COUNTD([GEO]) / MAX({ EXCLUDE [Stage] : COUNTD([GEO]) })
```

`EXCLUDE` removes only the pie's breakdown from the context and keeps every view filter: the denominator
equals what is on screen and the shares add up to 100%. Check: the status bar shows `SUM of AGG(share): 100%`.

## 16. Conditional color in a measure table (`Measure Names` × `Measure Values`)

Task: "P1/P2 in one color, deltas by sign". Tools: `edit_sign_color` (sign color), `edit_heat_columns` (cell
fill, same mechanics). Four rules, each of which cost a debugging round:

**1. Put `[Multiple Values]` on Color, not `[:Measure Names]`.**

| on Color | encoding | what gets colored |
|---|---|---|
| `[:Measure Names]` | categorical | the whole COLUMN; the sign has no effect |
| a flag calculation | categorical | the whole ROW (`[Multiple Values]` cannot be addressed in formulas) |
| `[Multiple Values]` | quantitative | THE NUMBER itself: what you want |

**2. `separate-domains="true"` on the color encoding itself** — the "Use Separate Legends" option. Without it
all measures share ONE scale, `Δ %` next to `Turnover` lands near zero, and the whole table comes out dull.

**3. A measure-level palette may be named or custom.** Named: `palette='<name>' type='interpolated'`. Custom:
`type='custom-interpolated'` with a nested `<color-palette>` (a production sheet colored by hand carries 13
shades of a custom palette on `P1`/`P2`). Dull color comes from a missing `separate-domains` (rule 2), not
from a custom palette. `edit_sign_color` takes palette NAMES only; a pair of hex colors is not its contract.

**4. Stepped color: `num-steps`.** A continuous scale passes through the MIDDLE of the palette, and on a
diverging palette the middle is neutral: dark blue fades to grey on `P1`/`P2`. `num-steps='2'` splits the
range into two bins and removes the intermediate shades; on a diverging palette with `center='0'` that is
exactly "minus in one color, plus in the other". Tool: `edit_color_steps`.

**Hand-picked color is not rebuilt.** The author tunes shades in Desktop, where the result is visible;
replicate THAT sheet with `edit_copy_color_encoding` (`copy_color_encoding(root, "donor sheet", sheets)`): it
transfers the pane `<color>` and every color encoding with its palettes.

```xml
<encodings>
  <color column='[ds].[Multiple Values]' separate-domains='true'/>
  <text  column='[ds].[Multiple Values]'/>
</encodings>
<style-rule element='mark'>
  <!-- umbrella: shared mode, a custom palette works here -->
  <encoding attr='color' field='[ds].[Multiple Values]' symmetric='false' type='custom-interpolated'>…</encoding>
  <!-- one encoding per measure, by palette name (what edit_sign_color writes) -->
  <encoding attr='color' field='[ds].[usr:P1:qk]'  palette='Just black' type='interpolated'/>
  <encoding attr='color' field='[ds].[usr:Δ %:qk]' palette='red_green_diverging_10_0'
            center='0' type='interpolated'/>
</style-rule>
```

Palette names by frequency in the corpus: `orange_blue_diverging_10_0` 182 · `tableau-blue-light` 88 ·
`red_green_diverging_10_0` 78 · `Just black` 75 (custom, in `Preferences.tps`) · `red_black_10_0` 73 ·
`blue_10_0` 48 · `red_green` 27.

A color no named palette offers → a custom palette in `Preferences.tps`, next to `Workbooks/` in the Tableau
repository folder (that is how `Just black` is made; `install_palette` returns the snippet; limits in
`TABLEAU_APP_NOTES.md`, color section). There is NO stock "orange + green" pair: the closest are
`red_green_diverging_10_0` and `orange_blue_diverging_10_0`.

**A washed-out side of the scale is `Use Full Color Range`.** Without it Tableau treats a diverging range as
symmetric around zero, and the side with smaller absolute values fades to the neutral tone. The Tableau docs
example: `-858` renders grey without the option and dark red with it. Tool: `edit_color_range`. In XML the
attribute is `symmetric` and INVERTED: option on = `symmetric='false'`.

## 17. Sheet swap: one switch, different matrices

When the views differ in SHAPE (one column per month versus three: Plan · Actual · Δ), one matrix cannot
express it: Tableau cannot hide a `Measure Names` member by parameter. The professional answer: several sheets
in one container; the unneeded one is emptied by a filter on a parameter-driven calculation, and an empty
sheet collapses by itself.

Tool: `edit_sheet_swap`. It does four steps at once because skipping any one gives a silent defect (each one
was observed on a live build):

| step | what happens without it |
|---|---|
| gate calculation + filter ON EVERY sheet | both sheets visible at once |
| a copy of the parameter declaration in each sheet's dependencies | the gate formula points into nothing |
| a `<viewpoint>` for every sheet on the page | Tableau fails with `HasVisualDoc`; the workbook does not open |
| "fit entire view" removed from the wide sheet | columns squeeze; sums turn into `#####` |

Verify with `dry_run_states` (a sheet empty in ALL states is a blocker; empty in one state is normal for a
swap) and `screenshot_param_states` (how each state looks).

### Rejected rule: "fit + set column width"

A lint rule suggested itself: "a zone with `entire-view` plus a sheet with explicit column widths = `#####`
defect". **Measured on the corpus: 37 of 50 working workbooks do exactly that.** By the calibration law the
rule is wrong, not the workbooks: `entire-view` hurts only with many columns (24 across eight months); on a
normal sheet it helps. No rule; the warning in the table above and `screenshot_param_states` instead.

## 18. The sheet NAME chooses the form, not cardinality

Measured on the production corpus (37 reports of a Tableau Server deployment, read through the Embedding API).

Inferring chart type from numbers alone (how many dates, how many breakdowns, how wide the spread) yields
workbooks that resemble each other and nothing in the source: rows of identical bars where the original has a
KPI card with a big number and a sparkline, a cohort heat map or a treemap.

**Sheet names in working workbooks are descriptive, and they are the strongest signal of form.** In the
production corpus they cover almost everything:

| in the sheet name | form |
|---|---|
| `treemap` | Tree Map (breakdown on `detail`, measure on `size`) |
| `cohort`, `retention cohort` | heat map: breakdown × breakdown, color = measure |
| `KPI`, `BAN`, `big kpi`, `consolidated` | tile: big number + delta + sparkline |
| `MULTI METRIC`, `L3M`, `metrics` | table: rows = metrics, columns = period |
| `TOP`, `BOTTOM`, `winners`, `losers` | top-N bar |
| `Line Graph`, `Trendline`, `Dynamic Graph` | line over time |
| `Table`, `breakdown`, `detail` | text table |

Cardinality stays as the FALLBACK when the name is silent, and as a feasibility check: `cohort` without a
second breakdown cannot be built, nor can `trend` without a date.

**Helper calculations are not metrics.** A view export returns them mixed with the real ones
(`Conditional Format % RETENTION`, `MARGIN Trend Direction`, `Calculation_<hex>`, `… (copy)`); in a metric
table they make the draft look. Filter them with ONE rule for the whole build: banner, tables and the choice
of a sheet's dominant measure. A sheet whose metrics are all helpers is auxiliary and has nothing to show.

**One shelf, one measure.** Euros next to a counter flatten the line to zero at the axis. Combine metrics only
at close magnitudes (margin ×50); with a spread over ×1000 the form changes to a table: a number next to its
label always reads.

**Navigation buttons link only to OTHER pages.** The target page's `simple-id` is written AFTER the layout is
drawn, so a self-link fails with "Target dashboard has no window id". Build pages in two passes: the first
creates them without buttons, the second rebuilds them with buttons.

## 19. Executive overview page: a domain example (iGaming)

The structure generalizes to any business: **money → volume → people → efficiency**, in that order. iGaming
metrics serve as the example.

| layer | metrics | purpose |
|---|---|---|
| money | **GGR** = bets − wins · **NGR** = GGR − bonuses − costs | what was earned |
| volume | **Turnover** (sum of bets) · **Bet count** | scale of play |
| people | **Active players** · **ARPU** = GGR / players · **ATPU** = turnover / players | how many people, how much per person |
| efficiency | **Margin (hold)** = 1 − wins/bets · **RTP** = wins/bets · **Avg bet** | how the product pays back |

Exact formulas (including what NGR deducts) come from `metric_canon`, not from this table. **Read metrics in
pairs, not one by one;** that is the whole value of an overview page:
- GGR grows while active players stand still → not the business is growing but the dependence on high-value
  players;
- turnover grows while GGR stands still → RTP moved up or bonuses ate the margin;
- average bet falls while active players grow → cheap traffic arrived.

Hence the composition rule: **next to an absolute, always place its denominator** (GGR with active players,
turnover with average bet). A tile with one number and no pair invites a false conclusion.

**Workbook structure:** three levels as in §2, one page each:
1. **Overview**: KPI tiles + main-measure trend + top 5 providers and games. Answers "how are we doing" in
   seconds, without a click.
2. **Performance**: a table with switchable breakdown levels (`Level 1/2/3`). Answers "driven by what".
3. **Detail**: player, game, bet slip. Answers "what exactly happened".

**Breakdowns a casino report needs:** provider, game, product type (casino / sport), country and region,
player lifecycle segment, VIP / regular, acquisition partner.

### Reference overview layout (a production casino report)

```
┌ KPI row ─────────────────────────────────────────────────────────────┐
│ ##.#M       ###.#M        #.#%      #,###,###    ###.#M      ##.#K   │
│ GGR, USD    Turnover,USD  Margin    Users        Spins       Games   │
└──────────────────────────────────────────────────────────────────────┘
┌ GGR, USD ── bars × month ────────────┐ ┌ Turnover, USD ── bars ───────┐
│ + Margin % LINE on a second axis     │ │ value labels on the bars     │
└──────────────────────────────────────┘ └──────────────────────────────┘
┌ Count of spins ──────────────────────┐ ┌ Count of users ──────────────┐
└──────────────────────────────────────┘ └──────────────────────────────┘
┌ Provider indicators ─ table ─────────┐ ┌ Game indicators ─ table ─────┐
│ provider × GGR/Turnover/Margin/      │ │ game × the same metrics,     │
│ spins/users, heat fill per column    │ │ heat fill                    │
└──────────────────────────────────────┘ └──────────────────────────────┘
                                             filters in a right-hand column
```

Take literally:
1. **KPI = large number + small caption UNDER it.** Not six bare numbers in a line, but a value / meaning
   pair. Compact format: `12.3M`, `4.5K`.
2. **Dynamics as BARS per period, not a line,** with a value label on every bar. The line stays only for the
   percentage (Margin) on a second axis: the one case where two axes are justified — different units, one
   thought (§3).
3. **Each block its own color** (blue GGR · green Turnover · teal spins · pink users) via `edit_mark_color`.
   Color encodes the BLOCK here, not a rank inside it.
4. **Breakdowns as TABLES with heat fill, not bars** (`edit_heat_columns`). Providers and games number in the
   hundreds; a filled table reads, a hundred bars do not. This overrides the top-N bar for this place.
5. Filters in a vertical column on the right (`edit_control_column`).

Result: KPI row (6) + 4 bar blocks by period + 2 indicator tables (providers, games).

## 20. Lessons from the public corpus

Profiled with `tools/study_workbooks.py` plus targeted XML reading: 25 workbooks, 595 sheets, 55 dashboards,
6018 calculations. Only what differs from the house corpus and can be adopted.

### What they do and the house does not

| technique | public | house | conclusion |
|---|---|---|---|
| reference lines | **105** | 2 | every number has a comparison base |
| annotations on charts | **49** | 0 | the chart explains itself |
| top-N filters | **45** | 0 | the tail is cut, not drawn |
| `text` zones | **422** | 42 | titles, subtitles, notes as separate zones |
| `empty` zones | **303** | 20 | air as a layout element, 15× more |
| image zones | **127** | 10 | icons, logos, dividers (116 PNGs inside the packages) |
| viz extensions | **71** | 0 | third-party forms (sankey, bullet) |
| table calculations | **336** | 122 | shares, ranks, running totals |
| actions | **64** | 31 | a click on a chart filters the rest |
| named fonts | Arial, Tableau Bold/Light/Book, Poppins, Century Gothic | default | typography chosen, not inherited |
| mark `Automatic` | 18% | 46% | form chosen deliberately |
| dynamic zone visibility | 42 | 17 | tabs / blocks switched by parameter |

The reverse holds too: **50 of 55 public dashboards are `fixed`** (canvas 1400×900, 1000×600, 1300×1020). Not
superiority but a different job: Public draws a picture for a screenshot, the house builds a working tool for
different monitors. **Keep `range`.** Their density is higher (12.3 sheets per dashboard against 10.1, 61
zones against 50), but their zones hold text and air, the house's hold controls (1049 `paramctrl` against
1915, with fewer workbooks). Theirs are read; the house's are operated.

### Recipes taken from their workbooks

**1. A KPI card = separate micro-sheets.** In a Tableau Public regional sales scorecard each region has
`<Region> - BAN - CQ` (the number) and `<Region> - BAN - Difference` (the delta to target), stacked in a
container with a `- Header` sheet and a sparkline: several simple sheets, each formatted separately.

**2. A delta format with a triangle arrow.**
```
*▲"$"#,##0;▼"$"#,##0        (house equivalent: *↑ #,##0.0%;↓ #,##0.0%; )
c"$"#,##0,K;("$"#,##0,K)     compact thousands for a hero number
```
The same idiom as the house, with ▲▼ instead of ↑↓ and with currency. Keep the house version, **plus a compact
K format for KPIs** (`style.FMT["eur_k"]`): long numbers in a hero tile do not read.

**3. Status by threshold instead of "paint it red".**
```
% to Target := SUM([Sales]) / SUM([Target])
Color       := IF [% to Target] >= 1    THEN 'GOOD'
               ELSEIF [% to Target] >= .95 THEN 'OKAY'
               ELSE 'BAD' END
Size        := IF ... THEN 1 ELSEIF ... THEN 2 ELSE 3 END
```
The threshold is explicit and visible in the formula. Color and size derive from one rule, so the legend reads
unambiguously. Block: `blocks.threshold_status`.

**4. Split a measure by status instead of coloring by value.**
```
Sales - Target - Good := IF [Color] = 'GOOD' THEN SUM([Sales]) - SUM([Target]) ELSE NULL END
Sales - Target - Okay := ...
Sales - Target - Bad  := ...
```
Three separate measures on one axis. A diverging bar is then colored stably: color is bound to the rule, not
to rank, and nothing repaints under a filter. Block: `blocks.split_by_status`.

**5. A shared axis for small multiples: padding calculations.**
```
Fixed Max + Padding := { FIXED : MAX( { FIXED [Region],[Category],DATETRUNC('quarter',[Order Month]): SUM([Sales]) } ) } * 1.1
Sales with Padding  := WINDOW_MAX(SUM([Sales])) * 1.2
```
A reference line with `formula="max"` on this field aligns the scales of all panes; without it each pane has
its own axis and small multiples lie. Blocks: `blocks.shared_axis_max`, `blocks.add_shared_axis_line`.

**6. Layout helper calculations.** `min(0.1)`, `AVG(1)`, `'Overall'`, `-([Sales with Padding]/5)`: dummy axes
that pin labels, reserve a margin for text, or build a shared "Total" row. Cheap and effective.

### Adopt

A reference line to plan / prior period **by default** in KPIs and trends; GOOD/OKAY/BAD thresholds as
explicit calculations plus the measure split by status; `{FIXED : MAX(...)} * 1.1` + `formula="max"` for a
shared axis in small multiples; top-N + "Other" in bar charts; `text` zones for block titles and `empty` zones
for air (blocks never edge to edge); the compact `c"€ "#,##0,K` format for hero numbers; mark type set by
hand; an annotation wherever a number needs explaining.

### Do not adopt
- **a fixed canvas:** keep `range`; a dashboard is a tool, not a picture;
- **images and icons in bulk:** 116 PNGs across 25 workbooks make files heavy and fragile; one logo at most;
- **viz extensions:** an external dependency that has to be allowed separately on Cloud;
- **exotic forms** (sankey, bump, waffle): pretty in a portfolio, costly to maintain and slow to read. The
  form comes from the table in §3, not from a showcase.

## 21. View critic: broken reading versus taste

The `stylecritic` channel (the critic section of `preflight`) reads the frame render with a designer's eyes.
One boundary: **is READING broken?** Broken → do not deliver; not broken but ugly → a remark.

| broken reading (do not deliver) | taste (remark) |
|---|---|
| a number does not fit: Tableau prints `#####` | a column header is cut above short values |
| values of a squeezed column are cut (`Provid..`, `New Zeal..`) | a single long label beyond the width ceiling (`Long Game Title: Hold..`) |
| two different labels became identical after truncation | the table is wider than its zone: horizontal scroll |
| neighbouring tables in one row start their rows at different heights | scrolling for 1–3 rows |
| rows or category labels overlap | more than 12 colors, ΔE2000 < 5 within one legend, contrast < 3 |
| | an empty band under a table or across the page; type < 7 pt |

How Tableau allots width in a text table (Standard): each column by its values, but no narrower than its
header up to about 90 px and no wider than about 170 px. If the sum does not fit, the table scrolls sideways
and row-header columns shrink (a provider column measured ≈ 68 px). Fit Width / Entire View squeezes
everything into the zone. Type size follows the sheet style (`label`, `cell`; px = pt × 96/72). The sheet
title defaults to 15 pt and Tableau WRAPS it: a long title in a narrow zone pushes the table down, and the
rows of neighbouring tables misalign. For an even row of tables: titles of equal length (or one block title as
a text zone) and the same header on all neighbours.

Table rules T1–T3: §5.

## 22. Anti-patterns

| anti-pattern | do instead |
|---|---|
| KPI tile with no comparison; number with no unit or period | delta against a named base (§14); unit in header or mask; period in words |
| `Automatic` mark type | choose the form (§3) |
| dual axis for unrelated scales | two charts with a shared X axis |
| pie with more than 3 slices, two pies, gauges, 3D, sankey / bump / waffle for routine KPIs | sorted bar, 100% stacked bar, bullet, line |
| truncated bar axis; ranking sorted alphabetically | bars from zero; `edit_sort_by_measure` |
| legend for 2–5 series; a label on every point | direct labels at bar and line ends |
| partial last period drawn as a drop; average of daily ratios | exclude or mark it partial; ratio of sums |
| rainbow of 10+ hues; color by rank | top-N in color, the rest a grey "Other"; color by entity |
| red/green as the only signal | arrow or sign plus color |
| ten visible filters; multi-select list on a high-cardinality field | 5–6 visible, rest collapsed, actions; type-in, wildcard or parameter |
| detail table at the top, unfiltered | bottom of the page, behind a filter or an action |
| `Display Units: Automatic` (K and M mixed in a column) | one unit per column |
| mixed fonts and sizes in a table | `style.uniform_type` |
| `Sheet 1`, `Calculation_…`, `(copy)`, `Null` on screen | real titles; filter out helpers and nulls |
| scrollbars inside small zones; fixed canvas for a working tool | zones sized from the data; `sizing-mode=range` |
| copied density (50 zones, nesting 11); images and icons in bulk | 6–10 controls, shallow containers; one logo at most |
| default tooltips | a tooltip with definition and comparison |
| live connection that asks for a password | extract (`save_as_extract`) |

## 23. Extending this knowledge base

Profile a new batch of external workbooks with one command:

```bash
.venv/bin/python tools/study_workbooks.py <folder> --label "Source" --json /tmp/study.json
```

The script prints a markdown section (forms, dashboard composition, nesting, analytical techniques, formats,
colors, fonts, actions). Paste it under its own heading, "External sources: <source>", and end it with **what
we adopt**; otherwise the base becomes a dump of numbers. `find_idiom` asks the existing corpus how an idiom
is written in XML.

Only applicable knowledge enters this base: an observation without a "do this" conclusion is not knowledge.
House-style measurements go to `STYLE_GUIDE.md`; a defect every check misses becomes a check and a test.

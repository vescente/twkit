# Naming and folders: a build rule

A built workbook is opened by a person. A data pane full of `Calculation_0137905884463108`,
`Sheet 1 (2)` and `Before promo (copy)_1154747769647114` is unusable even when the numbers are
right: a real legacy workbook had 73 fields with no folders and 33 sheets with `(2)` suffixes and
could only be read formula by formula.

The rule is mandatory and checked by the linter (**R35**). Priority: after `house_style_rules`
(what is customary); this file says what to call things and where to put them.

---

## 1. Data pane folders

Folder names are measured across working workbooks, not invented. In a corpus of 12 workbooks:
`Fields` in 12 of 12, `Measures` 8, `System` 7, `Date` 6, `Calcs` 5. Use them as is:

| Folder | Contents |
|---|---|
| `Fields` | source dimensions (strings, codes) |
| `Date` | date columns |
| `Measures` | numeric source columns |
| `Calcs` | **every** calculated field a person looks at |
| `System` | technical: `updated_at`, service flags, `_` helpers |

- Folders are always created, not only past some field count.
- A calculated field outside `Calcs` is a violation. One exception: a `_` helper goes to `System`.
- Parameters are kept separately by Tableau and do not go into folders.
- **Do not invent folder names.** Topic folders (`ROMI`, `Retention`, `Segments`) appear once
  per workbook in the corpus: an exception for one report, not a pattern. Numbered or localized
  names (`2. Metrics`) appear nowhere; a workbook that used them stood out from all others.
- **A source column nobody looks at goes to `System`, not `Measures`.** A `Measures` folder
  holding all 86 columns of a wide mart cannot be worked with.

## 2. Field names

**Forbidden:**
- Tableau defaults: `Calculation_0137905884463108`, `Sheet 1`, localized equivalents
- copy traces: `(copy)`, `(2)`, `_1154747769647114`
- column names as captions: the field is `Deposits`, not `dep_sum`

**Do:**

| Role | Style | Example |
|---|---|---|
| calculated measure | Title Case business name | `Deposits`, `Avg Dep Amount` |
| calculated dimension | Title Case | `Segment Moved`, `Period` |
| per-period variant | base name + suffix | `Deposits P1`, `Deposits P2` |
| difference | base name + `Δ` / `Δ%` | `Deposits Δ`, `Deposits Δ%` |
| helper (not for eyes) | `_` + lower_snake | `_seg_at_period_end` |
| parameter | `p_` + lower_snake | `p_start_dt`, `p_metric` |
| user-facing parameter | as customary in the corpus | `Level 1`, `Metric` |

Captions and values are in **English**.

## 2.1. The name decides column ORDER

Measure order in a table follows the **alphabet**: a manual sort writes `<manual-sort>`, and
Tableau refuses to open such a workbook. Column order is therefore a consequence of the name;
choose the name with that in mind.

| technique | names | effect |
|---|---|---|
| delta next to its measure | `NGR`, `NGR Δ` | the alphabet puts the delta right after the measure |
| period comparison | `P1`, `P2`, `Δ`, `Δ %` | the Greek letter sorts after Latin |
| shares together | `%, Approval rate`, `%, CR FTD` | all ratios gather in one block |
| source mark | `CPA (excel)`, `Fix costs (excel)` | shows where a number comes from when there are two sources |

Both `%, ` and `(excel)` come from working workbooks. They solve one task: the reader understands
the column without opening the formula.

## 3. Sheet and dashboard names

- A sheet is named after what it shows: `Segments by metric`, `Segment moves`. Not after its form
  (`Bar 1`), a number (`Sheet 27`) or with a `(2)` suffix.
- KPI tile: `KPI <Metric>`, e.g. `KPI Deposits`, `KPI Active Users`.
- A dashboard carries the report name.
- One meaning = one sheet. A duplicate for a second period is a **parameter**, not a sheet copy:
  33 legacy sheets were six segments × three activities × 2, all of it one view with the segment
  on rows.

## 4. One meaning, one field

A measure for two periods is NOT two fields but one, switched by a parameter
(`house_style_rules` section 2, switcher). 73 legacy fields shrink to about ten this way: long
format by `metric` + switcher + `P1/P2/Δ/Δ%`.

The reverse also holds: **one caption, one field.** Two fields of a data source with the same
caption make every reference by caption ambiguous, and Tableau binds it to whichever comes first,
often the wrong one. An invisible suffix (`\u200b`) is enough to tell them apart. `Book.add_calculated_field`
refuses such a calculated field when it is created; **R42** (error) catches the rest. The table object
(`[__tableau_internal_object_id__]`) is not a field: a field may share its name. None of the 55 corpus
workbooks has such a pair.

---

## How it is checked

`lint_workbook` → **R35**:

| catches | severity |
|---|---|
| calculated field outside `Calcs` | warn |
| Tableau default name (`Calculation_…`, `Sheet N`) | warn |
| copy trace (`(copy)`, `(2)`) in a field or sheet name | warn |
| no data pane folders at all with 10+ fields | warn |

Severity is `warn`, not `error`: existing workbooks predate the rule and it must not break their
delivery. For workbooks WE build, an R35 warn means go back and fix it.

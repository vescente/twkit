# What an installed Tableau Desktop provides

A walk through `/Applications/Tableau Desktop (Apple silicon) 2026.1.app/Contents` (2.4 GB). The
goal is precision: take what the vendor writes and ships instead of guessing the format.

## 1. Main finding: reference workbooks from the vendor

| file | what it is |
|---|---|
| `help/Workbooks/en_US/Superstore.twbx` | Tableau's sample dashboard, 10 sheets |
| `help/Workbooks/en_US/World Indicators.twbx` | second sample: maps, story points |
| `install/Performance/PerformanceRecording_new.twb` | performance recording template |
| `install/Performance/PerformanceRecordingv101.twbx` | the same with data |

**These outrank any user corpus.** They are written by the product and ship with it. A linter rule
that flags them is a wrong rule. Running against them relaxed three rules:

| rule | why it was wrong |
|---|---|
| `R07` | a `.twb` referencing an extract: that is how the vendor template is built |
| `R15` | fields are also declared in `<shared-views>`; and `root.iter("worksheet")` picks up snapshots inside `story-point/capturedDeltas` |
| `R04` | `ATTR(boolean)` is a legitimate Tableau idiom; only `SUM` is meaningless |

All four files are in the tests (`test_vendor_books_have_no_errors`).

## 2. What Tableau does that a naive builder does not

| technique | XML shape | purpose |
|---|---|---|
| **title zone** | `<zone type-v2="title">`, 16 in the samples | a native dashboard title instead of a hand-made text zone |
| **story points** | `<story-points>/<story-point>` with state snapshots | presentation: steps with saved filters |
| **flipboard** | `flipboard`, `flipboard-nav` zones | card navigation inside a dashboard |
| **geographic roles** | `semantic-role="[Country].[ISO3166_2]"` | maps; without a role Tableau does not know the field is a country |
| **binning** | `<calculation class="bin">`, 2494 in vendor `.tds` | histograms without hand-made calculations |
| **field folders** | `<folder-item>`, 380 in `.tds` | data pane order with 30+ fields |
| **map source** | `install/Mapsources/Tableau.tms` | map styles: `dark`, `light`, `normal`, `streets` |

### Geographic roles (full set from vendor `.tds`)

```
[Country].[ISO3166_2]      country (code)        31×
[City].[Name]              city                  15×
[State].[Name]             state/province        15×
[ZipCode].[Name]           postal code           14×
[Geographical].[Latitude]  latitude              10×
[Geographical].[Longitude] longitude             10×
[Geographical].[Geometry]  geometry (polygons)    6×
```

A country column with the `[Country].[ISO3166_2]` role becomes a map instead of a list of strings.

## 3. Vendor number masks absent from the corpus

What the corpus actually uses, and how often: `STYLE_GUIDE.md` section 4.

Vendor samples (for comparison; the corpus is dominated by `p0.0%` and `n#,##0`):

```
c"$"#,##0;("$"#,##0)          38×  money, negatives in parentheses (financial style)
C1033%                        22×  percent with locale 1033 (en-US)
c"$"#,##0,,,B;("$"#,##0,,,B)  10×  BILLIONS with one letter
c"$"#,##0,K;("$"#,##0,K)       7×  thousands (taken as eur_k)
```

Negatives in parentheses is a financial convention and reads better than a minus.

## 4. Density: the corpus is overloaded

| | zones per dashboard | nesting |
|---|---|---|
| Tableau samples | **25.7** | 9 |
| Tableau Public | 60.9 | 10 |
| house corpus | 50.1 | 11 |

The vendor builds twice as simply. This backs `DESIGN_KB.md` section 7: parameters yes, a pile of
controls no.

## 5. Datasource structure: `.tds` as the reference

`install/defaults/Datasources/Sample - Superstore.tds`: 89 columns, written by Tableau. Column
attributes by frequency: `datatype` 89, `name` 89, `ordinal` 71, `role` 18, `type` 18,
`caption` 5, `hidden` 5, `semantic-role` 4, `aggregation` 2.

Therefore:
- Tableau sets `ordinal` almost always (see `FORMAT_NOTES.md`);
- `role`/`type` only where they differ from what the data type implies;
- `hidden="true"` is the native way to hide a technical field instead of deleting it.

## 6. What the app does NOT contain (verified)

- **No palettes in plain form.** `Preferences.tps` is a user file in `~/Documents/My Tableau
  Repository`, not part of the bundle. Palettes are compiled in.
- **`strings` extracts almost nothing**: 2.5 MB `libtabwbfileformat.dylib` holds only 562 strings;
  all text lives in Qt resources (`tablangres.rcc`, 27 MB). Take allowed values from the XSD
  (`FORMAT_NOTES.md`), not from the binary.
- **No connector plugins as files**: `Plugins/` holds only the JRE; connectors are compiled into
  `libtabconnectorsbase.dylib` (18 MB).
- **No headless render.** No `tabcmd`, no CLI image export: `MacOS/` holds `Tableau`,
  `tabprotosrv`, `crashpad_handler`, `atrdiag`. Visual checks need the app window, the embedded
  thumbnails or the frame model.

## 7. Side benefit: test data without a database

`install/defaults/Datasources/Sample - Superstore.{tds,xls}` and `World Indicators.hyper` are
local. Build tests can run on them without a VPN or a private mart: a universal data set every
Tableau user has.

## 8. What was implemented from this

- [x] vendor workbooks in linter calibration (4 files, tests)
- [x] three rules relaxed after them (R04, R07, R15)
- [x] `_worksheets()` walks only `<worksheets>`, not story-point snapshots
- [x] geographic roles → `schema.apply_geo_roles()` + the `geo_map` block
- [x] title zone → `dash.py` (`type-v2='title'`)
- [x] binning → the `bins` block
- [x] field folders → `blocks.field_folders` / `auto_folders`, corpus folder names
      (`Fields`/`Measures`/`System`, in `<folders-common>`, no `role`; 141 folders in 24 workbooks)
- [x] negatives in parentheses → `style.FMT["eur_fin"/"eur_fin_k"/"eur_fin_b"]`
- [x] story points → `twkit/story.py`, structure taken from `World Indicators.twbx`
      (paired `flipboard-nav` ↔ `flipboard` zones, window `class="dashboard"`)
- [x] tests on vendor data → `tests/test_end_to_end_vendor_data.py`
- [x] flipboard as a dashboard block → `story.flipboard_zone` + `pair_flipboard_zones`

| technique | before | after |
|---|---|---|
| field folders | 24 fields mixed in the pane | 3 folders: Fields / Measures / System |
| story | not supported | `dashboard type="storyboard"`, steps with conclusions |
| financial format | a minus, lost in print | `€ 1 234` / `(€ 1 234)`, the vendor convention |


## Color: what the official docs say

Sources: `help.tableau.com/current/pro/desktop/en-us/`:
`formatting_create_custom_colors.htm`, `viewparts_marks_markproperties_color.htm`,
`formatting_specific_numbers.htm`.

### A named custom palette: `Preferences.tps`

The file lives in `My Tableau Repository` (next to `Workbooks/`).

```xml
<?xml version='1.0'?>
<workbook>
  <preferences>
    <color-palette name="MyColors" type="regular">
      <color>#1e4c56</color>
      <color>#cba94b</color>
    </color-palette>
  </preferences>
</workbook>
```

| `type` | for | colors |
|---|---|---|
| `regular` | categorical | as many distinguishable as needed |
| `ordered-sequential` | sequential | TWO ends suffice; Tableau fills in between |
| `ordered-diverging` | diverging | two halves; the middle is filled in |

- Quotes in `name` and `type` must be STRAIGHT. Curly quotes from a text editor break the file.
- The `Edit Colors` dialog shows at most 20 colors; a palette may hold more.

### Quantitative color

- **Stepped Color**: `num-steps`. Values fall into equal bins, one color per bin. On a diverging
  palette an EVEN step count puts the transition exactly on a bin boundary; an odd count puts it in
  the middle of the central bin. So `num-steps=2` + `center=0` gives a clean split by sign.
- **Use Full Color Range**: diverging palettes only. Without it Tableau treats the range as
  symmetric around zero, and **the side with smaller magnitudes comes out faded**: in the docs
  example `-858` is drawn GREY without the option and dark red with it. In XML this is the
  `symmetric` attribute, inverted (`symmetric='false'` = option on).
- **Reversed**: reverses color order.
- **Include Totals**: whether totals take part in the color scale.
- **Center**: where the neutral tone sits on a diverging palette.

### Number masks

Three sections separated by semicolons: `<positive>;<negative>;<zero>`. A skipped section is an
empty slot between semicolons.

**There are NO color codes in masks.** The docs say so directly: "custom number formats to color
code text aren't applicable because you can apply color to text using the Marks card". Excel
`[Red]`/`[Green]` syntax is not supported.

### What the docs do NOT cover

`separate-domains` ("Use Separate Legends") is not publicly documented. It is known only from a
reference pair (`heat_separate_legends`). This is normal: part of the `.twb` dialect is
undocumented and comes from reference workbooks, not from the web.

---

## Vendor tutorial "Get Started with Tableau Desktop"

Source: `help.tableau.com/current/guides/get-started-tutorial/en-us/`, all 10 pages. Only what the
docs STATE, and whether it is covered here.

### What Tableau does on its own

| situation | Tableau picks | here |
|---|---|---|
| a time field in the view | **line** | `R17` warns on `Automatic` |
| a second discrete dimension added | **bars** | same |
| continuous measure on Color, values ≥ 0 | **blue** | — |
| continuous measure on Color, values < 0 | **orange** | — |
| measure with both signs on Color | **diverging palette** (Orange-Blue Diverging) | sign-based color is native behavior, not a trick |
| geographic field double-clicked | goes to **Detail**, a map is built, `Latitude`/`Longitude` appear on shelves | `geo_map` block |

A green pill = continuous field, blue = discrete. In XML: `type="quantitative"` versus
`nominal`/`ordinal`.

### Geographic roles: the docs' full list (11)

Airport · Area Code (U.S.) · CBSA/MSA (U.S.) · City · Congressional District (U.S.) ·
Country/Region · County · NUTS Europe · State/Province · Zip Code/Postcode.

### Step 5 trap

**An exclusion stays when the field leaves the shelves.** The tutorial shows it: `Postal Code` is
excluded, then removed from the shelf; "even when you remove the Postal Code field from the view,
the filter remains". The filter is invisible on screen but still cuts rows. Covered by
`edit_exclude_members`.

### Keep Only / Exclude is NOT a regular filter

Selecting several marks → **Keep Only** creates an `Inclusions` field with a two-circle icon: a
SET, not an enumeration. Right click → **Exclude** is the other side of the same technique.

In XML: a hidden group in the datasource plus a `function='except'` filter on the sheet (24 of 110
corpus workbooks):

```xml
<group hidden='true' name='[Exclusions (segment)]' name-style='unqualified'
       user:auto-column='exclude'>
  <groupfilter function='crossjoin'>
    <groupfilter function='level-members' level='[none:segment:nk]'/>
  </groupfilter>
</group>
```
```xml
<filter class='categorical' column='[ds].[Exclusions (segment)]'>
  <groupfilter function='except' user:ui-domain='database'
               user:ui-enumeration='exclusive' user:ui-marker='enumerate'>
    <groupfilter function='crossjoin'>
      <groupfilter function='level-members' level='[none:segment:nk]'/>
    </groupfilter>
    <groupfilter function='reorder-dimensionality'>
      <groupfilter function='crossjoin'>
        <groupfilter function='union'>              <!-- only when more than one value -->
          <groupfilter function='member' level='[none:segment:nk]'
                       member='&quot;Churned&quot;'/>
        </groupfilter>
      </groupfilter>
      <order><hierarchy name='[none:segment:nk]'/></order>
    </groupfilter>
  </groupfilter>
</filter>
```

Why it cannot be replaced by enumerating the remaining values: an enumeration FREEZES the domain,
so a new value in the data never reaches the sheet and the report silently loses rows.

Member encoding (569 corpus nodes): a string is quoted (`&quot;Europe&quot;`), a number bare
(`1`), a boolean bare (`true`). An unquoted string matches nothing, and the exclusion cuts
everything.

`dry_run` translates exclusions to `NOT (a IN (…) AND b IN (…))`; before that it returned numbers
that were not on screen.

### Order of operations (query pipeline)

The order list on the docs page is an IMAGE with no text, so only statements made in words are
listed (`help.tableau.com/current/pro/desktop/en-us/order_of_operations.htm`):

1. Filters run in pipeline order, NOT in the order they were added.
2. A top-N filter and a regular dimension filter sit at the SAME pipeline step and apply together.
   Hence the classic miss: "top 10 customers in New York" returns the top 10 across all cities.
3. The cure is to put the regular filter into CONTEXT: a context filter runs before any other sheet
   filter.
4. A dimension filter applies BEFORE a table calculation, so "percent of total" recomputes every
   time a filter box is unchecked. If the percentage must stay fixed, replace the table calculation
   with a `FIXED` expression.
5. Data source filters run before context filters.
6. "Latest date" is global to the workbook, computed after data source filters and before context
   filters, then behaves like a regular dimension filter.

Items 2–3 are a warning in `edit_top_n` → `edit_filter_context`.

### Not in the tutorial

The tutorial does not cover a fixed axis (Edit Axis → Fixed). No `.twb` idiom for it appears in the
110 corpus workbooks or in the XSD.

### Gaps after the walkthrough

| technique | corpus | here |
|---|---|---|
| exclusions / sets | 24 workbooks | `edit_exclude_members` |
| `action-filter` (Use as filter on a dashboard) | 17 workbooks | `add_dashboard_action` |
| `<drill-paths>` (hierarchies) | 14 workbooks | `add_hierarchy` |
| `<annotations>` (Annotate → Mark) | 4 workbooks | **no** |

## Hide/show button: the state and the button are DIFFERENT nodes

The technique has two parts, and half of it does not work alone: with only `hidden-by-user` the
zone disappears with no way back, because there is no button on screen (the XML is valid and every
check is silent).

**Part one: the state.** A `layout-flow` container with `hidden-by-user='true'` on it AND on all
descendants. The value is only ever `true`: an expanded container does not store the attribute
(123 occurrences in six workbooks, zero `false`).

**Part two: the button.** A separate FLOATING `type-v2='dashboard-object'` zone, a direct child of
`<zones>` next to the root container:

```xml
<zone h='2837' id='34' type-v2='dashboard-object' w='1478' x='97624' y='18676'>
  <button action='' active-visual-state-index='1'>
    <toggle-action>tabdoc:toggle-button-click-action window-id="{2FFDF9CF-…}" zone-id="34" zone-ids=[30]</toggle-action>
    <button-visual-state /><button-visual-state />
  </button>
</zone>
```

- `zone-ids=[30]` is the target, the collapsed container;
- `zone-id="34"` is the button's own id;
- `window-id` is the uuid of the page's **window** (`<windows><window class='dashboard'><simple-id
  uuid=…>`), NOT of the same-named `<dashboard>`: their uuids differ, and the wrong one gives a
  button that toggles nothing;
- `active-visual-state-index='1'` is set only while the target is collapsed;
- exactly two `<button-visual-state/>`, one per button look.

**Neighbours must sit in a `layout-flow` with `layout-strategy-id='distribute-evenly'`.** In
`layout-basic` coordinates are absolute, so a collapsed container leaves a hole instead of giving
up its space. In a flow: collapsed, the neighbour takes the full width; expanded, they split evenly.

The `twb_2026.2.0.xsd` schema also knows `paired-zone-id` on `<zone>`, but it never appears in the
corpus: it is a different mechanism.

`edit_zone_hide_button` sets all of this.

## `%` is escaped in a parameter member, not in a formula branch

The same list item is stored in the workbook with TWO spellings:

```xml
<member value="&quot;first day RTP \%&quot;"/>     <!-- parameter domain: with a backslash -->
WHEN 'first day RTP %' THEN [Calculation_…]        <!-- formula branch: without -->
```

So the value list and the formula cannot be walked with one list of strings:
`drop_param_members` expects `first day RTP \%`, `drop_case_branches` expects `first day RTP %`.
A miss gives a menu item that selects nothing, and no automatic check sees it.

The cheapest cure: do not put `%` in NEW dimension labels.

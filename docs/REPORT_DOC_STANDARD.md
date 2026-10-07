# Dashboard description standard

One dashboard, one document. It goes to a wiki and is read by people who did not build the
workbook: analysts, managers, a new developer.

## Law: facts only

The description answers **what it shows and how it is computed**. Nothing else.

**Never in the document:**

| forbidden | why |
|---|---|
| caveats ("⚠️ careful, this metric is wrong when…") | the reader comes for a definition, not a list of fears |
| reasoning ("we chose this approach because…") | the decision is made; its rationale lives in the task |
| excuses ("this is missing because there was no data") | what is absent is not mentioned |
| change history, measurements, variant comparisons | that is a work log; it belongs in the task |
| "why we did not do X" in any form | see above |

A missing metric is simply not mentioned. If a limitation changes how a number READS, state it as
part of the metric definition, in one line and without apology: "Contribution = NGR − Traffic
Spend", not "Contribution is incomplete because provider costs are not subtracted".

**Tone.** Present tense, active voice, short lines. "Horizon changes Deposits, NGR, Contribution",
not "Horizon may affect which metrics get recalculated".

## Required structure

Sections go in this order. An empty section is dropped entirely, not left with a dash.

```
# <Dashboard name>

<One line: what it shows and who needs it.>

| | |
|---|---|
| File | <.twbx name> |
| Source | <schema.table, connection type> |
| Refresh | <schedule, job name> |
| Grain | <what one row is> |
| Currency | <if money> |
| Pages | <list> |

## <Key concept>        ← only if there is one: cohort, segment, period
<Definition in 2-3 lines.>

## Filters and parameters
| control | type | what it does |

## Metrics
| metric | formula |
<A formula, not a description in words. General counting rules go below, if any.>

## Page contents
<A list: what sits where, what color encodes.>
```

## Section rules

**Header table.** File name, source, refresh schedule, grain, currency, pages. It tells the reader
where the numbers come from and when they are fresh.

**Key concept.** Add this section when the report has a term without which the table cannot be
read: cohort, segment, status, comparison period. Definition in 2-3 lines, no hand-waving examples.

**Filters and parameters.** A three-column table. For a switcher that changes several metrics at
once, give an explicit list of what it changes and what it does NOT change: the one place where
enumeration fits, because it is the control's behavior.

**Metrics.** A "metric → formula" table. A formula, not a paraphrase. General counting rules (e.g.
"shares are computed from sums") go in one paragraph under the table.

**Page contents.** What is on the canvas and what color encodes. No pixel-level layout.

## Where to put it

Next to the workbook: `<Dashboard name> - description.md`. The file name matches the workbook name
so it is found without searching.

## Check before delivery

- [ ] no "because", "unfortunately", "could not", "careful", "⚠️" in the text
- [ ] no section about limitations, caveats or what the report lacks
- [ ] every metric has a formula, not a description in words
- [ ] the header is complete: source, schedule, grain
- [ ] every parameter says what it changes
- [ ] the document reads in two minutes

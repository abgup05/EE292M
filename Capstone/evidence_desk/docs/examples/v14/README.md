# Version 14 example payloads

What the API serves for the version 14 additions, made offline by `make examples`
(`tests/examples_v14.py`) from the recorded NVIDIA fixtures with the extractive engine:
no model, no EDGAR request. `tests/test_examples_v14.py` makes them again and fails when
a file here is out of date. Clock times (`started_at`, `finished_at`, each source's
`retrieved_at`) are fixed at 2026-11-18 12:00 UTC so a file changes only when a shape or
a result does.

| File | Route | What it shows |
|---|---|---|
| `run.json` | `GET /api/runs/{id}` | Five claims on NVDA's newest filings: two tests that hold, one that fails, one that cannot be computed, one claim that does not compile |
| `as-of-run.json` | `GET /api/runs/{id}` | The same five claims in a run as of 2026-03-01 (`ThesisRequest.as_of`) |
| `restatements.json` | `GET /api/companies/NVDA/restatements` | NVDA's restatement ledger from the recorded facts: 28 of 922 periods restated |
| `brief.md` | `GET /api/runs/{id}/export.md` | The brief of `run.json`, with its `## Computed tests` section |

Peers (`GET /api/companies/{ticker}/peers`) were not built in this version, so there is no
peers example.

Every other field of a run is unchanged by this work. The extractive engine judges no stance,
so a claim's verdict here is `supported` or `challenged` only through its computed test,
and `unjudged` otherwise.

## The run request

`inputs.as_of` (string `YYYY-MM-DD` or null): the date the run is as of. With a date,
the run reads only the filings, 8-Ks and XBRL facts filed on or before it. Refused
(422) when it is in the future, before 2009, or given with extra pages (`urls`).

## `as_of` on a run (the evidence's age), two new fields

- `requested` (string or null): `inputs.as_of` again; null for a run of the newest filings.
- `requested_note` (string): one sentence saying what a dated run read; empty otherwise.

With `requested`, `days_since_newest` counts to that date, not to the run's start.

## `coverage`, four new counts

- `claims_compiled`: claims that compiled to a computed test.
- `computed_holds`, `computed_fails`, `computed_cannot`: how those tests came out; the three
  add up to `claims_compiled`.

## A claim, two new fields

- `computed` (object or null): the claim's computed test, below. Null when the claim does
  not compile.
- `compile_note` (string): why the claim does not compile ("Not a numeric claim this
  version computes: ..."); empty when it compiles.

`verdict` counts the computed test as verified evidence: a test that holds as support, one
that fails as a challenge, one that cannot be computed as nothing. The summary was written
from the verdicts of the findings alone.

## `computed` (ComputedTest)

- `canonical`: the test as compiled, with unbound periods (`gross_margin[Q] > gross_margin[Q-4]`).
- `form`: which of the eight forms (`direction`, `acceleration`, `streak`, `threshold`,
  `growth_threshold`, `faster_than`, `compound`, `share`).
- `bound`: the test with the periods it was computed for
  (`gross_margin[Q2 FY2027] > gross_margin[Q2 FY2026]`); empty when no period could be placed.
- `outcome`: `holds`, `fails` or `cannot_compute`.
- `outcome_label`: the outcome in words ("Holds", "Fails", "Cannot be computed").
- `reason`: why it could not be computed; empty otherwise.
- `comparison`: the operator (`>`, `<`, `>=`, `<=`).
- `left`, `right`: the two sides compared, each an operand (below) or null; `right` is a
  constant for a threshold.
- `operands`: every measure value read to get the two sides.
- `arithmetic`: the computation written out line by line; the last line ends "holds" or
  "fails".
- `margin`: left minus right, in the sides' unit (points for percents); null when not computed.
- `margin_display`: the margin as text ("+2.6 points").
- `counted_as`: the stance the verdict rule counts: `supports`, `challenges`, or "".
- `note`: anything else the reader should know (a share read from a filing's tags, a
  breakdown that could not be read); often empty.
- `as_of`: the date the facts were read up to; "" when every fact was read.
- `history`: the outcome as of each 10-K and 10-Q filing date in the five years to the
  newest one (at most 24 points), oldest first. Empty for a share of revenue.
- `history_note`: what the history covers and how often it flipped, or why there is none.

### An operand (`left`, `right`, each of `operands`)

- `term`: the bound term (`gross_margin[Q2 FY2027]`).
- `label`: what and which period, in words.
- `value`: unrounded (a percent as 75.0); null when it cannot be computed.
- `unit`: `USD`, `percent`, `USD_per_share` or `count`.
- `display`: the value as text.
- `formula`: the arithmetic with the numbers used; empty for a value read from one fact.
- `inputs`: the facts read, each a fact reference (below).
- `note`: why the value is missing, when it is.

### A fact reference (each of `inputs`)

`concept`, `unit`, `start` (null for an instant), `end`, `value`, and the filing the value
came from: `accession`, `form`, `filed`. `derived` is true for a value computed from
others (the filing named is the latest of its inputs), `restated` true when an earlier
filing gave the same concept and period another value, and `note` says how a derived or
tagged value was got.

### A history point (each of `history`)

- `filed`, `form`, `accession`: the 10-K or 10-Q whose filing date the point is as of.
- `outcome`: as for the test, from the facts filed by that date only.
- `bound`: the test with that day's periods.
- `left`, `left_display`, `right`, `right_display`: the two sides as values and as text
  ("n/a" when a side could not be computed).
- `flipped`: true when the outcome differs from the last point before it that could be
  computed.
- `reason`: why the point could not be computed; empty otherwise.

## `restatements.json` (RestatementLedger)

- `company`, `cik`, `ticker`: whose ledger it is.
- `as_of`: the date the ledger is as of (`?as_of=YYYY-MM-DD`); "" for every fact.
- `tolerance_note`: when two values count as the same.
- `metrics_checked`: the metrics compared.
- `periods_checked`: the denominator: every period of every metric reported by at least
  two filings.
- `periods_restated`: how many of those changed value in a later filing.
- `entries`: one per restated period, newest period first within each metric:
  - `key` (`metric:period:end`), `label`, `unit`, `period` (`annual`, `quarter`,
    `half_year`, `nine_months`, `instant` or `other`), `start`, `end`, `period_label`;
  - `reports`: every report of the period, the unchanged ones included;
  - `concept_changed`: true when a later filing tagged the period with another concept;
  - `values`: the first value, then each that differed from the one before it. Each has
    `value`, `display`, `accession`, `form`, `filed`, `concept`, `change` and
    `change_display`, `change_percent` and `change_percent_display` (null and "" for the
    first value, and the percent null when the value before was zero), and
    `returns_to_earlier` (true when the value goes back to one the period had before:
    more often a mistagged period in the filing between than two restatements).
- `notes`: how to read the ledger (a stock split, for one).

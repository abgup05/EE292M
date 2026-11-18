# Facts with dates

Version 14 gives every XBRL fact the date it became known: the filing date of the filing that reported
it. From that come four things: a fact book as of a date, a store of every fact, a ledger of restated
values, and runs as of a past date. None of them involves a model.

## A fact is known from the day its filing was filed

XBRL's `fy` and `fp` describe the filing, not the fact (a 10-K for fiscal 2026 reports fiscal 2024 and 2025
too), so a fact's period is placed by its own `start` and `end`, and when it became known by the `filed`
date of the filing that reported it. `FactBook(payload, as_of=day)` (`core/facts.py`) reads only the facts
whose filing was filed on or before `day`: a fact filed on the day is seen, one filed the day after is not.
Every metric, figure, fiscal calendar (`periods.fiscal_calendar(payload, as_of=)`), ledger and computed test
built from such a book sees the company as it stood that day. Without `as_of` every fact is read, exactly
as before.

## The fact store

`data/facts/facts.sqlite` (class `FactStore` in `store.py`, disposable). One row per company: CIK,
ticker, name, the SIC code and its description from EDGAR's submissions index, how many facts were kept
and how many skipped (an entry without a usable end, value, accession, form or filing date), the SHA-256
of the body, when it was loaded. One row per us-gaap fact: concept, unit, start, end, value, accession,
form, filing date, and XBRL's `fy`, `fp` and `frame` kept as given. A run keeps the facts it reads there;
so do `GET /api/companies/{ticker}/metrics` and `/restatements`. `make facts-load TICKERS="NVDA AAPL"`
loads companies outside a run (two requests each). A body already stored unchanged is left alone; a
changed one replaces the company whole. Deleting the file loses nothing that EDGAR cannot give again.

## The restatement ledger

`GET /api/companies/{ticker}/restatements[?as_of=YYYY-MM-DD]` and `make restatements T=NVDA [ARGS='--as-of
2020-01-01']` list every metric and period whose value differs between the company's filings: the first
value and its filing, each later value that differs by more than the tolerance (USD 1,000,000, or USD 0.01
per share: these filings round to the million), its filing, and the change in units and percent. The
denominator is every period of every metric reported by at least two filings. A value that goes back to one
the period had before is marked `returns_to_earlier`: more often a filing in between that tagged the wrong
period than two restatements. A change of a per-share value by a whole-number factor is most likely a stock
split, and the ledger says so. Fields: `docs/examples/v14/README.md`.

Live on 18 November 2026 (`make restatements T=NVDA`, live EDGAR, no model; written to
`results/restatements-NVDA-20261118T102615Z.txt`, not committed): **28 of 922** NVIDIA periods reported by at
least two filings changed value in a later filing. By metric: revenue 1, cost of revenue 2, gross profit 1,
net income 4, diluted EPS 17 (the stock splits), operating cash flow 2, inventory 1. In 5 of the 28 a later
value goes back to an earlier one. On the recorded fixture (`tests/fixtures/edgar`, facts to 2026-08-26) the
count is the same, 28 of 922 (`docs/examples/v14/restatements.json`). Nobody has read the 28 against the
filings to say which are restatements and which are tagging errors.

## Runs as of a past date

`ThesisRequest.as_of` (`--as-of` on the command line, `as_of` in `POST /api/runs`). The run reads the newest
10-K filed on or before the date, the 10-Qs filed after it up to the date, the 8-Ks filed after the 10-K up
to the date, and the facts filed by the date. EDGAR's recent index holds about a thousand filings; when it does
not reach back to the 10-K, older index pages are read, at most `MAX_OLDER_INDEX_PAGES`. If no 10-K was filed
by the date in what can be read, the run fails and says so. The date is refused (422) when it is in the
future, before 2009 (no XBRL), or given with extra pages, which cannot be read as they stood. The as-of block
counts the days from the newest filing read to the requested date, and `requested_note` says what the run
read. A run without a date is unchanged: the tripwire's `prompts` stage and the recorded replay
(`tests/golden/replay.json`) did not move.

Live on 18 November 2026 (`make run ARGS='run --ticker NVDA --decision "Whether to keep an overweight
position in NVIDIA" --claim "Gross margin is expanding" --as-of 2026-03-01'`, live EDGAR, extractive engine,
no model; `results/run-38147b6d860c.json`, not committed): the run read one filing, the 10-K filed 25 February
2026, and the facts; "EDGAR lists 1" of 3 filings asked, since no 10-Q had been filed between the 10-K and the
date. The claim compiled to `gross_margin[Q] > gross_margin[Q-4]`, computed as
`gross_margin[Q4 FY2026] > gross_margin[Q4 FY2025]`: 75.0% against 73.0%, holds by 2.0 points, so the claim is
supported (the extractive engine's three findings are context). Its history over the 20 periodic filing
dates of the five years to 1 March 2026 flips 5 times, the last on 25 February 2026, from fails to holds. No
fact reference anywhere in the record was filed after 1 March 2026.

## No lookahead: the proofs

`tests/lookahead.py` has two checks that do not use the code under test: `late_refs` finds every fact
reference (a `filed` beside an `accession`) in an output filed after the date, and `pruned` deletes every fact
filed after the date from the raw payload, so the output as of the date can be compared with the output of a
payload that never held the later facts.

| What | Test | Dates |
|---|---|---|
| The metrics report | `tests/test_facts_as_of.py` | Every periodic filing date and the day before it: 138 (NVDA), 140 (AAPL), 136 (MSFT) |
| The restatement ledger | `tests/test_restatements.py` | 2015-06-30, 2019-03-01, 2023-11-01 on each of the three |
| Claim evaluation and history | `tests/test_claim_eval.py` | Seven claims of five forms on the last six filing dates, every twelfth, and the day before each of the last three, on each of the three |
| A run | `tests/test_as_of_run.py`, `tests/test_computed_run.py` | The recorded NVDA run as of 2026-06-01 and the day after the annual report |
| The golden computed claims | `tests/test_claim_results.py` | Each of the 69 cases as of its date |

Both checks were shown to catch a leak: `test_the_checks_catch_a_filter_that_reads_the_period_end_instead_of_the_filing_date`
swaps the filter for one that treats a fact as known once its period has ended, and both fire.

## What is not shown

- Only us-gaap facts are read and stored; a company that reports under IFRS has none.
- The SIC code is stored for each company but nothing uses it yet; peers were not built (see the capstone README).
- A run as of a date reads each filing's document as EDGAR serves it today; it cannot tell whether a document
  was changed in place after the date. The company-facts body is today's too, filtered by filing date.

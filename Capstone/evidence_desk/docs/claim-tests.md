# Claims as computed tests

Version 14 compiles each thesis claim to a typed test where it can ("Gross margin is expanding" becomes
`gross_margin[Q] > gross_margin[Q-4]`), computes the test from the company's dated XBRL facts with its
arithmetic written out, and counts the outcome in the claim's verdict. A claim it cannot compile says why
and is judged as before. No model compiles, computes or counts anything here.

## The compiler (`core/claimtest.py`)

A small grammar of regular expressions, checked in a fixed order: first the reasons a claim is *not* a
numeric claim this version computes (a forecast or a conditional, a cause, peers or expectations, a top-N
share, a valuation, a calendar year, a measure outside the set, a margin it does not name, a judgement, a
segment's or a geography's growth), then the eight forms. A claim that compiles prints a canonical test with
unbound periods; one that does not gets a reason, shown on the claim as `compile_note`.

| Form | Example claim | Canonical test |
|---|---|---|
| direction | Gross margin is expanding. | `gross_margin[Q] > gross_margin[Q-4]` |
| acceleration | Revenue growth is accelerating. | `yoy(revenue)[Q] > yoy(revenue)[Q-1]` |
| streak | Revenue has grown for four consecutive quarters. | `streak(revenue)[Q] >= 4` |
| threshold | Diluted EPS is above $4. | `eps_diluted[FY] > $4` |
| growth_threshold | Revenue grew more than 200% year over year. | `yoy(revenue)[Q] > 200%` |
| faster_than | Operating income is growing faster than revenue. | `yoy(operating_income)[Q] > yoy(revenue)[Q]` |
| compound | Revenue has compounded at over 10% for five years. | `cagr(revenue, 5y)[FY] > 10%` |
| share | Data center is more than 80% of revenue. | `share(segment "Data Center")[filing] > 80%` |

Periods: `Q` (the newest quarter), `Q-k`, `FY`, `FY-k`, `FY2026`, `Q2 FY2027`, `TTM`, `TTM-4`, `filing`. Measures:
revenue, gross profit, operating income, net income, R&D, operating expenses, operating cash flow, capital
expenditure, free cash flow, the four margins and R&D's share of revenue, free cash flow margin, diluted EPS,
cash, inventory, receivables. The exact canonical forms are in `eval/claim-tests.json` (`canonical_form`).

**Labels, written before the grammar.** `eval/claim-tests.json` holds 150 development and 60 held-out claims,
each with the canonical test it should compile to or "none" with the reason, written by hand on 18 November
2026 by the same Claude session that then wrote the grammar (commit f26f982, before the compiler existed). The
development set was read while writing the grammar; the held-out set is scored at most twice
(`HELD_OUT_SCORINGS`) and was never tuned on. A claim scores when the printed test equals the label exactly.

| Scoring (`make claim-labels [ARGS='--set held_out']`) | Exact | Expected to compile | Expected none |
|---|---|---|---|
| Development, first scoring (commit e9f4524) | 150 of 150 | 81 of 81 | 69 of 69 |
| Development, final | 150 of 150 | 81 of 81 | 69 of 69 |
| Held out, first scoring (`eval/results/claim-tests-held_out-20261118T095843Z.txt`) | 60 of 60 | 30 of 30 | 30 of 30 |
| Held out, second and last (`eval/results/claim-tests-held_out-20261118T102602Z.txt`) | 60 of 60 | 30 of 30 | 30 of 30 |

Read these numbers for what they are. The labels and the grammar have one author, and the grammar was
written with the development labels open: 150 of 150 says the grammar covers those phrasings, not that it
reads an analyst's. The held-out claims were written in the same sitting, in the same voice; 60 of 60 says
the grammar was not overfitted to individual development sentences, and nothing about claims written by
someone else. The compiler did not change between the two held-out scorings except to read its length cap
from `limits.py`.

## Evaluation (`core/claim_eval.py`)

`evaluate(test, book, calendar=, reports=)` binds the unbound periods to dates through the company's fiscal
calendar as of the book's date (`Q` is the newest quarter whose facts the book holds, `FY2026` the fiscal year
the company labels so), reads the measures from the facts, and compares. A quarter missing from the facts is
derived when it can be (the fourth quarter as the year less nine months), and the formula says so. House
definitions: operating expenses are gross profit less operating income; a streak counts sequential rises; a
CAGR runs over fiscal years. A share of revenue comes from the newest filing's tagged breakdowns (a segment or
product, a geography, or the largest single customer, leaving out rows marked as not a customer). The result
carries both sides, every operand with the facts it read (accession, form, filing date), the arithmetic line
by line, the margin, and `cannot_compute` with the reason when a side is missing.

**History.** For each compiled claim, the outcome as of every 10-K and 10-Q filing date in the five years to
the newest one (`HISTORY_YEARS`, at most `MAX_HISTORY_POINTS` = 24 points), each from the facts filed by that
date, from the facts the run already has: no extra request. A point is `flipped` when its outcome differs from
the last point before it that could be computed. A share has no history: the breakdowns come from one filing.

**The golden computed claims.** `eval/claim-results.json`: 52 cases (r01 to r52) over NVIDIA, Apple and
Microsoft at several dates, all three outcomes present. The expected values are written by
`evaluation/claim_oracle.py` (`make claim-results-key ARGS='--write'`), a separate route that reads the raw
company-facts JSON, places periods and labels fiscal years on its own, and never calls the evaluator.
`tests/test_claim_results.py` checks that the key is exactly what the oracle gives (so no expected value was
edited), and that the evaluator, run as of each case's date, agrees on the outcome, the bound test and both
sides to a relative 1e-9, with no fact filed after the date: **52 of 52**. While building it the two routes
disagreed once, on r14 (NVIDIA fiscal 2008): the oracle labelled the comparative years of the first filings
wrongly. The oracle's rule was fixed and only r14 changed; no expected value was edited by hand.

## In a run (`services/computed.py`)

After the facts are read, every claim is compiled and each compiled claim is computed from the run's fact book
(as of the run's date when it has one), with its history. The engine is asked exactly what it was asked before:
the prompts stage of the tripwire did not move and the recorded replay's requests (`tests/golden/replay.json`)
are unchanged. The summariser is shown the verdicts of the findings alone, as before; only then does each
computed test enter its claim's verdict (`policy.claim_verdict(findings, computed)`): a test that holds counts
as a supporting piece of verified evidence, one that fails as a challenging one, one that cannot be computed as
nothing, with the reason on the claim. A claim the run ran out of time for keeps no verdict. A reviewer's
reviewed verdict counts the computed test too; it is not something a reviewer accepts or rejects.

The brief has a section of its own, **Computed tests**, before the claims: each claim's test, the bound test,
the outcome and how it counts, the arithmetic, and the history as a table (filed, form, outcome, both sides,
flipped). `docs/examples/v14/brief.md` shows it.

**Verdicts before and after**, the example thesis (five claims; only "Gross margin is expanding." compiles, and
each of the other four carries its reason in `compile_note`):

| Run | c1 | c2 | c3 | c4 Gross margin is expanding. | c5 |
|---|---|---|---|---|---|
| Tripwire, extractive engine (`make golden-check`), before | unjudged | unjudged | unjudged | unjudged | unjudged |
| Tripwire, after (re-baselined on purpose, commit 62846b1) | unjudged | unjudged | unjudged | **supported** | unjudged |
| Replay of recorded answers (`make replay`), before | supported | supported | mixed | mixed | mixed |
| Replay, after | supported | supported | mixed | mixed | mixed |

The replay's answers come from the cassette `demo/cassettes/nvda-example`, recorded on 17 November 2026 by a
Claude Code subagent standing in for the Anthropic API; no model was called for this version. In the replay
c4 stays mixed: its findings already support and challenge, and a test that holds adds support. The tripwire's
coverage stage also gained the four new counts (1 compiled, 1 holds).

## Compiler against a model (evaluation only)

`make eval ARGS='compiler-vs-model --record --max-calls 60'` gives a model, for each of the 52 golden cases, the
reported-figure lines an assessment prompt would show for that company as of the case's date (plus the tagged
figures for a share) and the claim, and asks for holds, fails or cannot_tell with a JSON schema, through the
cassette `eval/cassettes/compiler-vs-model`. It prints how many requests the cassette already answers and how
many it would make before making any, refuses `--record` without `--max-calls` or above it, and scores the
model and the compiler against the key, saying where the answers came from. It was built and tested with a
fake transport only. **No model answer has been recorded, so there is no model score.** Without a recording
the command says: 52 cases, 0 answered, 52 requests to make.

## What is not shown

- That the grammar reads claims written by anyone but its author (see the label scores above).
- Whether a computed test agrees with what an analyst means: "expanding" is read as against the same quarter a
  year earlier, not the previous quarter. The canonical test is printed beside every outcome so a reader can
  see which comparison was made.
- How a model would do on the same figures: the harness exists and has not been run against a model.

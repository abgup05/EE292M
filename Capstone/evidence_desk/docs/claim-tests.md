# Claims as computed tests

Version 14 compiles each thesis claim to a typed test where it can ("Gross margin is expanding" becomes
`gross_margin[Q] > gross_margin[Q-4]`), computes the test from the company's dated XBRL facts with its
arithmetic written out, and counts the outcome in the claim's verdict. A claim it cannot compile says why
and is judged as before. No model compiles, computes or counts anything here.

## The compiler (`core/claimtest.py`)

A small grammar of regular expressions, checked in a fixed order: first the reasons a claim is *not* a
numeric claim this version computes (a forecast or a conditional, a cause, peers or expectations, a top-N
share, a valuation, a calendar year, a measure outside the set, a margin it does not name, a judgement, a
segment's or a geography's growth), then the forms. A claim that compiles prints a canonical test with
unbound periods; one that does not gets a reason, shown on the claim as `compile_note`. A claim refused
whole may be two tests joined by "and" (below).

**The whole sentence.** A claim compiles only when its test explains every content word of the sentence. After
the grammar reads a test, every phrase that test accounts for is struck out of the claim: its measures, its
comparison and its threshold, the periods it is bound to (and no other period named), its span, and the words of
its form ("expanding", "more than doubled", "consecutive", "compounded"). What is left must be on a short written
list of words that carry no meaning for a test (`NO_MEANING`: articles, forms of "be" and "have", "of", "in",
"than", "the company's", "still", "now", "currently", "total", "reported", "also" and a few more). Any other word
left refuses the claim, and the refusal names the words: "not compiled: 'plus vendor non-trade' is not
understood". A measure qualified by a segment, a product or a geography ("Gaming operating income", "Azure
revenue") is not the company's measure: it is refused, unless the sentence is that part's share of revenue,
which is read from the newest filing's tags. A test that compares a measure with itself is refused. One form is
exempt from the word count: a share of revenue is read by one pattern anchored at both ends of the sentence, so
it has no words left over; its subject is free text, matched later against the filing's tagged members (one
that matches none cannot be computed, and says so). The pattern may end with a period from a fixed list ("last
fiscal year", "in fiscal 2026", "in the latest quarter"), and a subject that says "together", "combined" or
"collectively", or joins names with "and" before "are", is refused as a sum of several parts. The rule lives in `unexplained()` and
`compile_claim()`. `tests/test_whole_sentence.py` started with 16 new sentences, four for each way a claim was
read wrongly (a part read as the whole, an unknown measure read as a known one, a named period ignored, half a
claim dropped), and two tests of the refusal's wording: all 18 failed on the grammar before the rule. Two of
the period sentences ("on a trailing basis", "between fiscal 2023 and fiscal 2024") then became readable and
moved to the list of sentences that must compile; the three period sentences that replaced them were not run
against the old grammar.

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
| share, a named year | Data Center revenue made up over 80% of total revenue last fiscal year. | `share(segment "Data Center")[FY] > 80%` |
| compare | Operating cash flow was above net income in the latest fiscal year. | `operating_cash_flow[FY] > net_income[FY]` |
| change over a span | Revenue more than tripled between fiscal 2023 and fiscal 2025. | `change(revenue, FY2023)[FY2025] > 200%` |
| each of N periods | Gross margin has stayed above 70% for the last four quarters. | `each(4): gross_margin[Q] > 70%` |
| every year since | Free cash flow has risen every year since fiscal 2023. | `each(since FY2023): free_cash_flow[FY] > free_cash_flow[FY-1]` |
| two tests, "and" | Revenue grew more than 50% year over year and gross margin is above 70%. | `(yoy(revenue)[Q] > 50%) and (gross_margin[Q] > 70%)` |

Periods: `Q` (the newest quarter), `Q-k`, `FY`, `FY-k`, `FY2026`, `Q2 FY2027`, `TTM`, `TTM-4`, `filing`
(a share's or a part's: the newest filing's newest period). Measures:
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
product, a geography, or the largest single customer, leaving out rows marked as not a customer), or, for a
fiscal year or quarter the claim names, from the column of the newest 10-K or 10-Q of that length (350 to 380
days, or 80 to 100) ending within 10 days of that period's end in the facts; when no filing read has one,
it cannot be computed and the reason lists the periods each filing reports. A part's revenue or operating
income is read the same way. A change, `change(m, BASE)[P]`, is growth from BASE to P on a positive base. A test
held in each of N periods is computed once per period, each a quarter (or a fiscal year) earlier, and two
tests joined by "and" once each; the result holds when every part holds, fails when any part fails, and
otherwise cannot be computed, naming the part. It carries `combines` ("each" or "and") and `parts` (each part
computed alone, newest first); its `left` and `right` are the first part's, and it has no `margin`. The
result
carries both sides, every operand with the facts it read (accession, form, filing date), the arithmetic line
by line, the margin, and `cannot_compute` with the reason when a side is missing.

**History.** For each compiled claim, the outcome as of every 10-K and 10-Q filing date in the five years to
the newest one (`HISTORY_YEARS`, at most `MAX_HISTORY_POINTS` = 24 points), each from the facts filed by that
date, from the facts the run already has: no extra request. A point is `flipped` when its outcome differs from
the last point before it that could be computed. A share or a part has no history, in any part of a test: the
breakdowns come from one filing. A test held in each of several periods, or two tests joined by "and", has one
point per filing date like any other, its `bound` naming every part.

**The golden computed claims.** `eval/claim-results.json`: 69 cases (r01 to r69) over NVIDIA, Apple and
Microsoft at several dates, all three outcomes present. The expected values are written by
`evaluation/claim_oracle.py` (`make claim-results-key ARGS='--write'`), a separate route that reads the raw
company-facts JSON, places periods and labels fiscal years on its own, and never calls the evaluator.
`tests/test_claim_results.py` checks that the key is exactly what the oracle gives (so no expected value was
edited), and that the evaluator, run as of each case's date, agrees on the outcome, the bound test and both
sides to a relative 1e-9, with no fact filed after the date: **69 of 69**. While building it the two routes
disagreed once, on r14 (NVIDIA fiscal 2008): the oracle labelled the comparative years of the first filings
wrongly. The oracle's rule was fixed and only r14 changed; no expected value was edited by hand. Cases r53 to r69
were added with the forms below (each of N periods, every year since, a change over a span, two measures
compared, two tests joined by "and", a share for the latest and a named fiscal year); the oracle reads them by
its own rules (it moves period tokens back step by step, splits "and" in the text, and takes a year's share from
the recorded 10-K's column that ends exactly on that year's end) and agreed with the evaluator on all 17 the
first time it was run.

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

Each claim also records who read it (`Claim.readings`, `ComputedTest.read_by`, `Run.claim_readers`), and the
brief prints "Read by" under each test. With the model parser off (the default) that is the grammar alone.

## The measure catalogue (`core/measures.py`)

Every measure a claim test can name, in one place: the metrics panel's 18, as before, and 39
more taken from the "metric" refusals of sets A and B (below). Each entry has its key, its
label, its kind (an amount over a period, a balance, a percent, per share, or a share count),
the words a claim names it by, and how it is computed: a concept group with alternatives
(`facts.CLAIM_GROUPS`), or a written formula over other measures. Added:

- **Shareholder returns:** `share_repurchases`, `dividends_paid`, and `shareholder_returns` =
  repurchases + dividends (a company that pays no dividend counts zero for it, and says so).
- **Debt and cash:** `long_term_debt` (non-current), `current_debt`, `commercial_paper`,
  `total_debt` = the three (a part the balance sheet does not report counts zero; leases are left
  out), `marketable_securities`, `cash_and_securities` = cash + marketable securities, `net_cash`
  = cash and securities − total debt, `net_debt` the reverse.
- **Expenses:** `total_operating_expenses` (as reported; else gross profit less operating
  income), `sga` (as reported; else sales and marketing + G&A), `sales_marketing`,
  `general_admin`, `sbc`, `d_and_a`, `cost_of_revenue`, `interest_expense`, `interest_income`,
  `other_income`.
- **Tax:** `income_tax`, `pretax_income`, `effective_tax_rate` = income tax ÷ pre-tax income.
- **Ratios to revenue:** `sga_ratio`, `sales_marketing_ratio`, `opex_ratio`, `capex_ratio`,
  `sbc_ratio`; a four-quarter ratio sums both parts over the four quarters.
- **Balance sheet:** `total_assets`, `total_liabilities`, `equity`, `goodwill`, `ppe`,
  `accounts_payable`, `deferred_revenue` (current + non-current, and each part).
- **The diluted share count:** `diluted_shares` (weighted average; never differenced, so a
  fourth quarter needs its own fact; no four-quarter total).

None of these is on the metrics panel, in the restatement ledger or kept by `record_facts`: the
reported-figures report and the tripwire's figures stage are unchanged, and `make figures` on
the eight probe companies printed the same output before and after (`docs/evidence/measures-eight-companies.md`).

**A part of the company** (from a filing's tagged breakdowns, so with no history): a segment's
or a geography's revenue, `revenue(segment "X")[filing]`; its change on a year earlier when the
filing tags both years, `yoy(revenue(segment "X"))[filing]`; and a segment's operating income,
`operating_income(segment "X")[filing]`, read from a breakdown built only for claim tests
(`breakdowns.CLAIM_SPECS`, kept apart in the cache). A model reader may name a part; **the grammar
does not**, because its labels say a part's figure is not the company's (d089, d129, h040, h041
expect none). Those four labels may be outdated now that a part's figure can be computed; they
were left as they are, for a deliberate relabelling.

**Which of the eight have each measure** for the newest fiscal year: `make measures-probe` (live;
the eight by default) computes each measure as a claim test does and names each miss with its
reason. Eight of the 39 added measures have a value for all eight companies; five are reported by
four or fewer: sales and marketing and its ratio (2 of 8), commercial paper (2), G&A (3), non-current
deferred revenue (4). A claim about one of them on a company that does not tag it cannot be
computed, and says which concept was missing. Every one of the eight newest 10-Ks tags a segment's
revenue for both years; six tag a segment's operating income (not JPM, TSLA). The table and every
miss: `docs/evidence/measures-eight-companies.md`.

## Readers and the counting rule

The grammar reads every claim. Up to two model readers can read it too:
`EVIDENCE_DESK_CLAIM_READER=model` (one) or `models` (two), off when empty or `grammar`, with
`ANTHROPIC_READER_MODEL` (default `claude-haiku-5-5`) and `ANTHROPIC_READER_MODEL_2` (default
`claude-sonnet-5-5`), all in `.env.example`. A model reader (`engines/claim_reader.py`) is given the
claim, escaped inside a `<claim>` element, and what this version computes, built from the catalogue
(each measure, its kind and, where derived, its formula; the forms; the periods; how a part's
measure is written), and answers the typed test as JSON under a schema, one request per claim,
through the same transport and cassettes as every model step (step `read`; the second reader
`read_2`, because a cassette's key holds the step and not the model). Its answer is validated into
the grammar's own `ClaimTest` (`core/claim_reading.py`) and refused when it does not validate or
names anything unsupported. "Not a claim this tool can compute" is a valid answer.

**One normal form** (`core/claim_normal.py`, pure). Readers write one test in several ways; each
reading is put in one form before readings are compared: `a > b` and `b < a` are one (the more
recent term first); a named fiscal year or quarter is counted back from the newest one the facts
hold (in a run; the harness, which reads no facts, leaves it named), a share's or a part's
too (its `filing` period stays apart: whether the newest filing is the 10-K is not known there);
growth above or below zero is a rise or fall on the same span (`yoy`, `qoq`, `cagr` over N years,
`change` from its base); a compound rate over one year, and a change over one year (or quarter), is
the growth; a count of rises is a whole number (`> 3` is `>= 4`); a test held in each of one period
is the test, every year since a named one is that many years, and a rise on the period before held
in each of N periods is a streak of at least N; two tests joined by "and" and a comparison of two
measures are put in one order; numbers to six significant digits; a member's name without case,
spacing or "&". `>` and `>=` stay different for an amount or a percent. Each equivalence has a test that
failed first against a stub returning the canonical text (`tests/test_claim_normal.py`).

**What counts** (`policy.reading_agreement`):

- **The grammar alone** (the default): a compiled test counts, as before. This is **one reader**,
  and the run says so in `Run.claim_reading_rule`: "One reader: the grammar. A computed test
  counts when the grammar compiles the whole sentence; no second reading checks it."
- **With model readers:** a test counts when at least two readers reach the same normal form. The
  test computed is the grammar's writing of it when the grammar is one of them, else the first
  agreeing model's: so a test can count when the grammar refused it and both models agree.
- **Three readers, one dissent:** when two agree and the third writes a different test (not a
  refusal), it counts, the computed test is marked "counted, with one dissenting reading"
  (`ComputedTest.agreement` `agreed_with_dissent`), and the dissent is shown
  (`ComputedTest.dissent`, and in its note). A refusal is not a dissent.
- **No two agree:** every reading is shown ("Readings differ: not counted"), the grammar's test (if
  it read one) is computed and shown but counts as nothing, and the verdict rests on the findings
  alone. A reader that could not be asked reads nothing, and the run's errors say so.

Whether a counted reading moves a verdict still depends on its outcome: a test that cannot be
computed counts as nothing, whoever read it.

The payload fields added for this, all additive: `Run.claim_reading_rule`;
`ClaimReading.normal_form` and the reader value `model_2`; `ComputedTest.agreement` (`one_reader`,
`agreed`, `agreed_with_dissent`, `not_agreed`), `agreement_label` and `dissent`. `readings`,
`read_by` and `claim_readers` keep their shapes (`claim_readers` is "grammar, model and model_2"
with two models). With no model reader nothing is asked: every recorded request is unchanged and
the replay and the tripwire match (`make golden-check`).

## The claim-readers harness and the judge's file

`make eval ARGS='claim-readers --set FILE --record --max-calls N'` reads every claim of a set with
the grammar and the model readers (`--readers models`, the default; `model`; or `grammar`, which asks
nothing), through the cassette `eval/cassettes/claim-readers`, and writes
`eval/results/claim-readers-<set>.csv`: one row per claim with each reader's normal form (or `none`
and why), who answered for each model (from the cassette), which pairs of readers agree, the rule's
conclusion, the test it would count, the dissent, and three empty judge columns. Before any call it
prints, for each model, how many requests the cassette already answers and how many it would make;
it refuses `--record` without `--max-calls` or above it; answers are kept as they arrive, so a run
stopped part way resumes without asking again. The summary counts each conclusion and names its
claims, so "counted, with one dissenting reading" is countable on its own.

`--judge` also writes `claim-readers-<set>-for-judge.md`, for a judge who has not seen the grammar:
the notation in plain words (generated from the catalogue), then every reading the rule would
count, with its sentence and normal form and an empty verdict column. It does not say which
readings had a dissent. Built and tested with fake transports only. **No model reading has been
recorded, so there is no agreement rate and no model reader's accuracy.** Grammar alone (no key),
the judge's files for sets A and B are `eval/results/claim-readers-claim-tests-foreign-for-judge.md`
(31 counted readings) and `eval/results/claim-readers-claim-tests-foreign-b-for-judge.md` (20).

## Compiler against a model (evaluation only)

`make eval ARGS='compiler-vs-model --record --max-calls 70'` gives a model, for each of the 69 golden cases, the
reported-figure lines an assessment prompt would show for that company as of the case's date (plus the tagged
figures for a share) and the claim, and asks for holds, fails or cannot_tell with a JSON schema, through the
cassette `eval/cassettes/compiler-vs-model`. It prints how many requests the cassette already answers and how
many it would make before making any, refuses `--record` without `--max-calls` or above it, and scores the
model and the compiler against the key, saying where the answers came from. It was built and tested with a
fake transport only. **No model answer has been recorded, so there is no model score.** Without a recording
the command says: 69 cases, 0 answered, 69 requests to make (run on 18 November 2026, after the forms round).

## Claims the grammar's author did not write

`eval/claim-tests-foreign.json` holds 120 analyst claims written by another model (Claude Sonnet 5.5), told not
to look at the repository: 40 each for NVIDIA, Apple and Microsoft, each marked by its author `numeric` or
`not_numeric`. The brief expected 80 and 40; the file has 83 and 37. It was committed unchanged (cb0265c,
SHA-256 `e73090c2…87983`) before anything was scored. Odd ids are the development half, even ids the held-out
half (60 each; 43 and 40 numeric).

**The judge is the grammar's author.** For each claim, `eval/claim-tests-foreign-judgements.json` records the
test the compiler printed (or none) and a judgement with a one-line reason: `right`; `wrong` (it compiled to a
test that does not mean what the sentence says); or not compiled, with the cause for a claim marked numeric
(`metric` the tool does not have, `form` the grammar does not have, `period` it cannot place, `phrasing` of
something it supports). Each entry says whether it was judged before or after the grammar changed. No second
person or model has checked a judgement; read them line by line before trusting a number below. A wrong
compile counts worse than no compile: it turns a misreading into a computed verdict.

`make claim-foreign` scores it offline (`ARGS='--write eval/results/FILE.txt'` keeps the text); it exits 1 while
any reading it prints is unjudged. `tests/test_foreign_claims.py` pins the final numbers.

| Numeric claims (author's label) | Before (09ce28a) | After (c8aca10) |
|---|---|---|
| **Held-out half** (40): compiled and right | 7 | 8 |
| Held-out: compiled and **wrong** | 15 | 11 |
| Held-out: not compiled (metric, form, period, phrasing) | 18 (8, 5, 1, 4) | 21 (9, 8, 1, 3) |
| Development half (43): compiled and right | 8 | 14 |
| Development: compiled and **wrong** | 6 | 0 |
| Development: not compiled (metric, form, period, phrasing) | 29 (18, 7, 0, 4) | 29 (19, 10, 0, 0) |
| All 83: right, wrong, not compiled | 15, 21, 47 | 22, 11, 50 |

Of the 37 claims marked `not_numeric` (17 development, 20 held out), none compiled, before or after. Records:
`eval/results/claim-tests-foreign-before.txt` and `claim-tests-foreign-after.txt`.

The headline is the held-out half: on claims written by someone else, the grammar reads 8 of 40 numeric claims
rightly and 11 wrongly, and leaves 21 alone. Most of what it leaves are measures it does not have (debt,
buybacks, dividends, share count, a segment's history) or forms it does not have (a condition held in each of
several periods, a rank, an approximate value, two statements in one).

**What changed, from the development half only.** A condition held in each of several periods ("above 70% for
the last four quarters", "in each of the last three quarters", "every year") is refused, except a rise in each
of the last N years or N sequential quarters, which is the streak form. Two statements joined by "but",
"though", "although", "despite" or "whereas" are refused. Marketable securities and short-term investments are
measures outside the set, no longer read as cash. "At or above", "at or below", "hit", "reached" and "better
than" are comparators. A share may be "of the total", and its subject may carry its revenue words ("iPad sales",
"revenue from the United States"). Spans may be in fiscal years. No metric was added: the commonest missing
measures (share repurchases, debt, the diluted share count, dividends) each appear in one or two development
claims, and a new measure is a new concept group in `core/facts.py`, which changes the metrics report, the
restatement ledger and the tripwire, and would need `make figures` on the eight probe companies before and after.

**The discipline, which cannot be proven.** The held-out results of the first scoring were seen before the
grammar changed. No rule was added or changed because of an even-id claim; each rule's test sentences in
`tests/test_claimtest.py` are new sentences, not foreign ones. Some even-id claims moved as a side effect
(f006, f052, f084 and f096 are now refused by the each-period rule; f088 now compiles as a share). Nothing but
this statement shows that the even ids were not used.

**The wrong compiles that remained after c8aca10** were all in the held-out half, and each was a pattern no
development claim showed:

- a part of the company read as the whole: f050 (a product line's revenue as total revenue), f104 (a segment's
  operating income and revenue as the company's);
- a measure the grammar does not know read as one it does: f064 (SG&A, compared as gross profit with itself),
  f106 (sales and marketing as a percent of revenue, read as revenue shrinking), f068 (receivables plus vendor
  non-trade receivables as receivables);
- a period read wrongly: f016 ("between fiscal 2024 and fiscal 2025" bound to FY2024), f058 (the named
  "September quarter" ignored), f098 ("on a trailing basis" read as the fiscal year);
- half a claim: f020 (the "more than ten points" of an expansion dropped), f060 ("and has barely moved in three
  years" dropped), f102 ("roughly in line with revenue" read as receivables grew).

They were left then because fixing them would have been fitting to the held-out half.

**Set A after the whole-sentence rule (10425c0).** After that scoring, all 120 claims of this file became
development material ("set A"); a fresh set B, written later by another model, is to be scored once at the end.
The four patterns above were not patched one by one: the whole-sentence rule refuses them all. Three readings
were fixed on purpose with set A open, since it is now development material: "on a trailing basis" is the
trailing twelve months, growth "between fiscal 2024 and fiscal 2025" is fiscal 2025's, and a share may say "is
now less than". `make claim-foreign` (record: `eval/results/claim-tests-foreign-whole-sentence.txt`; the 14 new
readings are judged with stage `whole-sentence`):

| Set A, all 120 (`make claim-foreign`) | Before the rule (c8aca10) | After the rule (10425c0) |
|---|---|---|
| Numeric (author's label), 83: compiled and right | 22 | 23 |
| Numeric: compiled and **wrong** | 11 | **0** |
| Numeric: refused (metric, form, period, phrasing) | 50 (28, 18, 1, 3) | 60 (33, 21, 2, 4) |
| Not numeric (author's label), 37: refused | 37 | 37 |

Coverage is 23 of 83 numeric claims (28%), down from 33 compiled, of which 11 were wrong. Two right readings
were lost to the rule, both claims with a trailing comment the parse does not explain: f012 ("…, which is
worth watching") and f092 ("…, producing operating leverage"). Gained: f016, f098 (wrong before, right now),
f018 (refused before). Of the 11 wrong compiles, 9 are now refused, each naming the words it could not explain
(f050 "wearables home and accessories", "several periods"; f058 "september quarter", "june quarter"; f060
"barely moved in three years"; f064 "sg&a"; f068 "plus vendor non-trade"; f102 "roughly in line with revenue";
f106 "marketing expense as a percent"; f020 "more than ten points"; f104 by the part rule, "intelligent cloud").
**The judge of every reading of set A is still the grammar's author**, and every rule above was written with set
A open: these numbers say the rule removes the wrong compiles it was designed against, not that it will on
claims nobody here has read. Set B is that test.

**Set B, scored once.** `eval/claim-tests-foreign-b.json` (commit 446695a): 120 more claims by Claude Sonnet
5.5, 80 marked numeric and 40 not, 40 per company, none shared with set A, written without sight of the grammar
and committed before the grammar's author read it. The grammar of 10425c0 was run on all 120 and its raw output
committed (`eval/results/claim-tests-foreign-b-raw.txt`, de0762c) before anyone read the set; the judgements
followed (`eval/claim-tests-foreign-b-judgements.json`); the grammar was not changed for anything set B
shows until both sets became development material on 18 November 2026 (below): this result was scored once. `make claim-foreign ARGS='--claims eval/claim-tests-foreign-b.json
--judgements eval/claim-tests-foreign-b-judgements.json'` (record: `eval/results/claim-tests-foreign-b.txt`):

| Set B, all 120, judged by the grammar's author | Count |
|---|---|
| Numeric (80): compiled and right | 5 |
| Numeric: compiled and **wrong** | 1 |
| Numeric: refused (metric, form, period, phrasing) | 74 (47, 8, 3, 16) |
| Not numeric (40): refused | 40 |

Coverage on claims nobody here had read is 6 of 80 numeric claims compiled (8%), 5 of 80 rightly (6%). The one
wrong compile, g046 ("Japan and Rest of Asia Pacific together are less than 15% of net sales"), went through the
exemption described above: the anchored share sentence is not word-counted, and its free-text subject read two
segments summed as one segment called "Japan And Rest Of Asia Pacific Together" (no filing tags such a member, so
it would be computed as "cannot be computed", not counted; it is still a wrong reading). Of the 74 refusals, 47
name a measure the tool does not have (debt, buybacks, dividends, equity, tax, a segment's or a product's own
figures), and 16 are phrasings of something it supports (statement names such as "cash generated by operating
activities", "FY25", "outpaced", "higher than", a list of expense lines meaning operating expenses). The judge
is still the grammar's author. `eval/results/claim-foreign-b-for-judge.md` explains the notation in plain words
and lists the six compiled claims with an empty verdict column, for a judge who has not seen the grammar.

**Sets A and B after the measure catalogue (both development material).** On 18 November 2026
both sets became development material: the catalogue's measures and the grammar rules they needed
were taken from their refusals, so the numbers below are on claims the grammar was changed for,
not a held-out score. Set B's scored-once result above stands as recorded. New readings were
judged by the same session that wrote the catalogue, marked "catalogue, 18 November 2026" in the
judgement files; no earlier judgement was changed. `make claim-foreign` (records:
`eval/results/claim-tests-foreign-catalogue.txt`, `eval/results/claim-tests-foreign-b-catalogue.txt`):

| Grammar alone, judged by the grammar's author | Set A (83 numeric) | Set B (80 numeric) |
|---|---|---|
| Compiled and right, before the catalogue | 23 | 5 |
| Compiled and right, after | 31 | 19 |
| Compiled and **wrong**, after | 0 | 1 (g046, as before) |
| Refused, after (metric, form, period, phrasing) | 52 (26, 21, 2, 3) | 60 (33, 8, 3, 16) |
| Not numeric, refused | 37 of 37 | 40 of 40 |

**The forms round (18 November 2026, both sets as development material).** The model readers were
limited by the forms, not by reading, so the forms that recur in the "form" and "period" refusals of
sets A and B were added, each to the catalogue the readers' prompt and schema are built from
(`core/claim_reading.py`, `engines/claim_reader.py`), the normal form, the evaluator (as of a date,
with history except for a share or a part) and, where the whole-sentence rule still holds, the grammar:

- **each of the last N periods** (`each(N): T`, N from 2 to `MAX_EACH_PERIODS` = 12): T held in
  each of the latest N quarters or fiscal years, or in each quarter of a named fiscal year (f003,
  f047, f052, f084, g015, g041). "Grew in each of the last four quarters" stays refused unless the
  claim says sequentially or year over year;
- **every year since a named one** (`each(since FY2023): T`), only for a change on the year
  before (f006, f066); said of a level it is refused, since whether the named year counts is unclear;
- **a change over a span** (`change(m, BASE)[P]`): between two named fiscal years, since one, over
  the past N years, and multiples (doubled, tripled, quadrupled, "three times its fiscal 2023
  level"; f009, f027); a compound rate from one named year to another (g067);
- **two measures compared** (`compare`): the levels of two measures of the same kind in one
  period (f021, f093);
- **a share, or a part's figure, for a fiscal year or quarter** a filing read reports, latest or
  named (f002, g044), refused with the periods the filings do report when none has it;
- **two tests joined by "and"**, a conjunction that holds only when both do, with the operands,
  arithmetic and history of both; tried only when the claim is refused whole, each part must
  compile alone, and a period named in one part only refuses it. Contrast words are still refused.
- **g046** (set B's one wrong compile, two segments summed read as one): fixed by a rule, a share
  whose subject says "together", "combined" or "collectively", or joins names with "and" before
  "are", is a sum of parts, which no filing tags.

| Grammar alone, judged by the grammar's author | Set A (83 numeric) | Set B (80 numeric) |
|---|---|---|
| Compiled and right, after the catalogue | 31 | 19 |
| Compiled and right, after the forms | 42 | 23 |
| Compiled and **wrong**, after the forms | 0 | 0 (g046 now refused) |
| Refused, after the forms (metric, form, period, phrasing) | 41 (22, 15, 1, 3) | 57 (33, 8, 2, 14) |
| Not numeric, refused | 37 of 37 | 40 of 40 |

Commands and records: `make claim-foreign` (`eval/results/claim-tests-foreign-forms.txt`) and
`make claim-foreign ARGS="--claims eval/claim-tests-foreign-b.json --judgements
eval/claim-tests-foreign-b-judgements.json"` (`eval/results/claim-tests-foreign-b-forms.txt`). The
15 new readings and g046's refusal were judged by the session that wrote the forms ("forms, 18 November 2026"); no
earlier judgement changed. `tests/test_forms.py` holds each form's evaluator, schema, normal-form and
grammar tests (written first and seen failing) and the sentences that must still be refused.

**Left out, and why** (by what the refusals show):

- *Approximate or ranged figures* ("about", "roughly", "mid-30s", "barely", "well over", "double
  digits", "tiny", "the vast majority", "flat"; f010, f026, f043, f051, f055, f060, f069, f094, f100,
  f102, g016, g052, g061, g086, g091, g093, g105): no bound to test without inventing one.
- *Ranks and records* (the largest segment, a record, the biggest quarter; f061, f082, g058, g103):
  each would need every member or every period ranked; four claims, no common shape.
- *A part's revenue or its change in the grammar* (g042, f049, g084, g097): the readers' schema and the
  evaluator take a part for a named year or quarter, but the grammar still refuses a part's figure:
  its name is free text before "revenue" inside a sentence the whole-sentence rule must check, and the
  rule cannot tell a member's name from an unexplained word. A share is read by a sentence anchored at
  both ends; a part's value is not.
- *A part held in each of several periods* (g003, g043, g096, f089): a part comes from one filing, which
  holds two or three of its periods at most.
- *A change in a margin in points* ("expanded by more than ten points", f020; "expanded to over 46%",
  f044): one claim each; a change in a percentage stays refused as ambiguous.
- *A multiple of, or a difference from, another measure* ("more than three times total debt", g017;
  "exceeded interest expense by more than $1 billion", g023): one claim each.
- *Sums of measures or members* (f063, g061, g104, g046): no tag gives the sum.
- *Half years, calendar quarter names, a month's year end* (g019, f058, g056, g099): the fiscal
  calendar does not place them.
- *Phrasing of forms that now exist* ("beat ... in all four quarters" f107, "keeps climbing" f096, "the
  rate fell in each" f019, "repurchased more ... than" g064, "grew faster ... over fiscal 2023 to 2025"
  g060, "ended the year at over twice" g010, "north of" f022): readable by a model reader under the new
  schema, not added to the grammar one phrasing at a time.

**Own labels.** The 150 development and 60 held-out labels and the 69 golden results still pass unchanged
(`tests/test_foreign_claims.py::test_the_own_labels_still_compile_exactly`, `tests/test_claim_results.py`), after
the whole-sentence rule too: no own label that expected a compile now refuses (`make claim-labels`: 150 of 150;
the pin: 210 of 210). While the rule was being written, five development labels did refuse (d016, d025, d044,
d045, d053) until the struck-out phrases were found in the whole claim rather than one after another and the
anchored share sentence was exempted; no label was changed. That
pin compiles the 60 own held-out claims a third time, as pass or fail only; the brief required it. No foreign
claim showed an own label to be wrong.

## Labels changed when the measure set grew

On 18 November 2026, before the measure catalogue (`core/measures.py`) was written, ten
labels of `eval/claim-tests.json` were changed. Each one expected "none" only because the
claim names a measure outside the set this version computed, and the catalogue now adds
that measure. They were changed because the tool's measure set grew, not to make a result
pass: they were changed in a commit of their own, before any code that reads the new
measures existed. No other label was touched.

| id | claim | was | now |
| --- | --- | --- | --- |
| d104 | Share buybacks are increasing. | none (buybacks are not in the metric set) | `share_repurchases[Q] > share_repurchases[Q-4]` |
| d105 | Dividends are growing. | none (dividends are not in the metric set) | `dividends_paid[Q] > dividends_paid[Q-4]` |
| d121 | The company returned more than $20 billion to shareholders. | none (not in the metric set) | `shareholder_returns[FY] > $20B` |
| d122 | Accounts payable are rising. | none (not in the metric set) | `accounts_payable[Q] > accounts_payable[Q-4]` |
| d124 | Total assets exceed $100 billion. | none (not in the metric set) | `total_assets[Q] > $100B` |
| d130 | The company has no debt. | none (debt is not in the metric set) | `total_debt[Q] <= $0` |
| d140 | Taxes are lower than last year. | none (taxes are not in the metric set) | `income_tax[FY] < income_tax[FY-1]` |
| d142 | Deferred revenue is rising. | none (deferred revenue is not in the metric set) | `deferred_revenue[Q] > deferred_revenue[Q-4]` |
| h049 | Total debt fell below $10 billion. | none (not in the metric set) | `total_debt[Q] < $10B` |
| h050 | The company spent more than $10 billion on buybacks. | none (not in the metric set) | `share_repurchases[FY] > $10B` |

Two of them are in the held-out set (h049, h050); changing a label does not score it. Labels
that stay "none" although they name a measure now in the catalogue, because the claim is
still not one test: d103 (a judgement), d107 (a judgement), d123 (goodwill as a share of
assets, a ratio the catalogue does not hold), d139 ("comfortably covers"), h048 (shares
outstanding, which the catalogue does not hold; it has the diluted weighted-average count).

## What is not shown

- That the grammar reads analysts' claims well: on 40 held-out numeric claims another model wrote it read 8
  rightly and 11 wrongly, by its own author's judgement (above); after the whole-sentence rule, with all 120
  as development material, 23 of 83 rightly and none wrongly, by the same judge. On set B, read once, 5 of 80
  rightly and 1 wrongly, by the same judge; no independent judge has marked it yet. After the measure
  catalogue, with both sets as development material, 31 of 83 and 19 of 80 rightly, 0 and 1 wrongly: not a
  held-out score.
- How often a model parser agrees with the grammar, or which of the two is right when they differ: nothing
  has been recorded. After the forms round, with both sets as development material, the grammar reads 42 of
  83 (set A) and 23 of 80 (set B) rightly and none wrongly, by its author's judgement: not a held-out score,
  and the new forms have not been read by a model through the API here.
- Whether a computed test agrees with what an analyst means: "expanding" is read as against the same quarter a
  year earlier, not the previous quarter. The canonical test is printed beside every outcome so a reader can
  see which comparison was made.
- How a model would do on the same figures: the harness exists and has not been run against a model.

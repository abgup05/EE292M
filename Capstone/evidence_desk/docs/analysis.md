# The analysis (version 0.14.2)

A run used to end with verdicts, quotations and a table of reported figures. That is a record of
what the filings say, not an analysis of the thesis. The analysis step adds, after the verdicts
are final, what an analyst would work out about each claim, how the claim looks from outside the
company and at its price, and an argument about what it all means for the decision. It changes
no verdict and no status.

Code: `services/analysis.py` (the step), `core/relevance.py`, `core/analytics.py`,
`services/view_providers.py`, `core/persistence.py`, `core/corollaries.py`,
`core/analysis_audit.py`, `engines/analyser.py`; record types in `core/analysis_models.py`;
numbers and wording in `core/analysis_policy.py`.

## Who writes what

| Part | Written by | Checked by |
| --- | --- | --- |
| Which measures bear on a claim; the headline figures | code (`core/relevance`) | tests |
| Analytics and their readings, from every provider | code; `reading_origin` is always `code` | tests against the definitions and against two companies' raw facts; the views' own tests |
| Odds a test holds in each of the next four quarters | code (`core/persistence`) | tests against an exact enumeration |
| Corollaries: the sentence, the expected outcome, the reason | a model (step `propose`) | read by the grammar and by the model's typed form; computed by code |
| The argument: every sentence | a model (step `analyse`, one request per claim; then step `conclude` for the thesis) | every sentence audited by code; a failing sentence is kept and marked |

The record says which of these it holds. `Run.analysis.corollaries_step` and `argument_step` are
each `not_asked` (no model, or the run's time was up), `failed` (asked, no usable answer: an API
failure, a malformed answer, a cassette that holds none), `partial` (the argument only: some of
its requests were answered) or `answered`. `corollaries_by` and
`argument_detail` name the model and whether the answers came from the API or a cassette.
`providers` lists the analytics providers asked, `providers_failed` those that gave nothing and
`provider_reasons` why.

## Relevance: which figures belong to a claim

A measure bears on a claim for one or more stated reasons (`RelevantMeasure.reasons`):

- `test operand`: the claim's computed test reads it;
- `cited by a finding`: a verified finding of the claim cites a reported figure of it;
- `named in the claim`: the claim's words name a measure of the catalogue;
- `part named in the claim`: the claim's test names a segment, product line or geography, or the
  claim's words contain the name of one as the newest filings tag it ("Data Center"). A label of
  three letters or fewer ("US") must be written as tagged, so the word "us" is not a country.

A claim with no measure gets none, and `Claim.analysis.relevance_note` says so. The run's other
reported figures stay in `Run.metrics`; `Run.analysis.untied_metric_ids` lists them, and they are
not part of the analysis.

The parts come from the tags of the newest 10-K and 10-Q the run read. They are read once per run
from the tags the cache keeps, or from the HTML the run fetched (and are then kept for the next
run). Nothing is fetched for them: a filing read from a cache that kept no tags gives
`Run.analysis.breakdowns_note` saying so, and the claims then have no part. This departs from the
first design, which read parts only when a computed test had already read them; with that rule a
claim such as "Data center demand is still accelerating" got no figure at all.

**The headline** (`Run.analysis.headline`) replaces the fixed six figures. In claim order: the
sides of a claim's computed test (the figures the claim is about, for the period it is about;
a constant is not a figure); for a claim with no test, the newest reported figure of each measure
with its change on a year earlier, and the growth of a part it names. At most 12.

## Analytics

Every analytic answers a question and says which (`Analytic.question`). Each has an id that is
stable across runs, its formula with the numbers used, its inputs with where each came from, and
one reading written from a template. One that cannot be computed is still on the record for the
claim that asked, with `available` false and why. `scope` is `claim` for an analytic about a
claim (`claim_ids` says which) and `company` for one about the company and the decision as a
whole, which is shown for the thesis and also under any claim in its `claim_ids`.

Three providers, in order (`Run.analysis.providers`):

### From the run's own facts (`facts`, `core/analytics.py`)

None is computed for the thesis at large. An analytic is on the claim's own basis: a claim whose
test names only fiscal years gets fiscal-year analytics for that year, and what has happened
since; any other claim the newest quarters.

| Id | Question | What is computed |
| --- | --- | --- |
| `an:<measure>:yoy` | Which way is it moving on a year earlier? | newest quarter against the same quarter a year before: percent for an amount, points for a ratio |
| `an:<measure>:acceleration` | Is growth speeding up or slowing? | growth on a year earlier in the newest quarter less the same in the quarter before, in points; the reading adds four quarters before. Amounts only |
| `an:<measure>:trend8` | Where does it stand against the last two years? | change over 8 quarters (points), or the compound quarterly rate `(last ÷ first)^(1/8) − 1`; the reading names the high and the low |
| `an:<measure>:<fy>:path` | What has it done over the last fiscal years? | the value in up to 4 fiscal years ending with the claim's, and the growth each year; says whether growth slowed |
| `an:<measure>:<fy>:since` | What has happened since that fiscal year ended? | the newest quarter after the fiscal year, on a year earlier, beside the fiscal year's own change |
| `an:<claim>:headroom` | How much room does the test have, against how far the figure usually moves? | left less right (the tightest period of a test held in several), and that room over the median move of the left side between the test's distinct readings. Not computed when it would only repeat the test's margin |
| `an:<claim>:needed`, `:cushion` | How far short did it fall? How much could it have given up? | for growth against a constant: the level needed, `base × (1 + threshold)`, against the level reached |
| `an:<claim>:sides` | Is the gap between the two sides closing or widening? | for one amount against another: left ÷ right at each of the last 4 distinct readings of the test's history |
| `an:<claim>:history` | How often has this been true before? | over the test's history, counting a run of filing dates with the same two sides once: readings held, the longest run, the last change. Not for a test of a named period |
| `an:bridge:cash:<fy>`, `:ttm` | Where did the cash go between net income and free cash flow? | net income, operating cash flow, capital expenditure and free cash flow over the claim's fiscal year and over the newest four quarters; the non-cash charges the facts tag; the change in receivables and inventory over the same period |
| `an:bridge:op_margin` | What moved the operating margin? | the change on a year earlier split into gross margin, R&D and other operating expenses, each as a share of revenue |
| `an:bridge:growth:<breakdown>:<q or fy>` | Which parts of the business drove the growth? | each part's change over the total a year before, from the filing's tags; only parts that split the total without overlap (a part's own sub-parts are left out) |
| `an:part:<name>:<q or fy>:growth` | Is the part growing faster or slower than the company? | the part's growth on a year earlier beside the total's, and its share of revenue in both years |
| `an:part:<name>:<q or fy>:pace` | Is its growth speeding up or slowing? | the part's growth in the newest period less its growth in the period before (the year before when the filing tags three years; else the earlier part of the year to date) |
| `an:eq:cash_conversion` | Is net income turning into cash? | operating cash flow ÷ net income over four quarters; the reading adds the newest quarter alone and the four quarters a year before |
| `an:eq:dso`, `an:eq:dio` | Is revenue being collected? Is inventory building ahead of sales? | balance ÷ the quarter's revenue (cost of revenue) × the quarter's days, and a year before |
| `an:eq:sbc_ratio`, `an:eq:capex_ratio` | How much is paid in stock? How much goes back into capital expenditure? | the cost over four quarters ÷ revenue, and a year before |
| `an:eq:deferred_revenue` | Is revenue billed ahead of delivery growing or shrinking? | the balance's change on a year earlier, beside revenue's |
| `an:eq:roe` | What is the return on equity made of? | net income ÷ average equity over four quarters, as net margin × asset turnover × equity multiplier |

Which claims each bridge and signal is tied to is `BEARS_ON` in `core/analytics.py`: for example
receivable days bear on a claim about revenue or receivables, inventory days on one about
inventory, gross margin or cost of revenue, and a claim about cash flow gets the walk, which
already carries its stock compensation, capital expenditure and working capital.

### The outside view (`outside_view`, `docs/outside-view.md`)

From SEC's XBRL frames, which hold one value per filer per calendar year.

| Id | Question | What is computed |
| --- | --- | --- |
| `an:base_rate:<ticker>:<class>:<test>:<date>` | How often has this been true of comparable companies, and did it last? | for a claim whose computed test frames can hold, in each of two reference classes (filers of the company's size; filers of its SEC industry code): the company-years in which the test held, of those that could be computed, and of the ones that held and could be read a year later, how many held again. The company itself is left out |
| `an:peer:<ticker>:<measure>:<year>:<date>` | Where does the company stand among its industry on this? | the company's rank, percentile and the class median in the newest year and the year before, for the rates a claim bears on (growth, a margin, cash conversion); at most 2 a claim |

A test frames cannot hold (one held in each of several quarters, a part of the business) gives
one line saying so. A base rate's `note` names the class exactly and says what the number is
not: a count of what happened to other companies, not a probability for this one.

### The market view (`market_view`, `docs/market-view.md`)

At the newest quarter-end price SEC's Form 13F filings give as of the run's date (the price's
date and the filing it came from are in each `note`). All three are `scope: company`.

| Id | Question | What is computed |
| --- | --- | --- |
| `an:pe:<ticker>:<price date>` | What is being paid for a dollar of earnings? | market value ÷ net income over four quarters |
| `an:fcf_yield:<ticker>:<price date>` | What does its free cash flow yield at this price? | free cash flow over four quarters ÷ market value |
| `an:reverse_dcf:<ticker>:<price date>` | What growth does the price already assume? | the constant revenue growth over 10 years at which a discounted cash flow under the stated assumptions equals the enterprise value; the reading sets it beside the company's own growth, what filers of its size have done, and the same at the industry's median and 90th-percentile margin. Also listed under each claim about revenue |

An implied growth is arithmetic under the assumptions in its `note` (a discount rate, a terminal
growth, a margin held for ten years). It is what the price needs, not a forecast and not a price
target. With no price (no manager's 13F holds the company) there is one line saying why.

**What the run leaves out of the two views**, as inputs of the others, repeats or tables: the
market value, enterprise value, EV to sales and price to free cash flow; the persistence count
and the two margin scenarios as lines of their own (the readings carry them); a peer standing by
dollars, which says only that the company is large, or of a measure no claim bears on; the
valuation lines under a claim. `GET /api/companies/{ticker}/analytics` serves all of them. Not in
a run at all: the reaction to an 8-K, which needs daily closes the 13F source does not have; a
price supplied by the user, which the market route accepts and `ThesisRequest` does not; and
base rates of corollaries, which would cost one reading of the frames for each.

### Time, failure and the date

The two views read EDGAR during a run (frames, the industry's member list, 13F tables), each
kept on disk once read. Each has a time budget: `OUTSIDE_BUDGET_SECONDS` (20) and
`MARKET_BUDGET_SECONDS` (15) in `core/analysis_policy.py`. A provider runs in a thread of its
own and the run waits that long; past it, or when EDGAR does not answer, the provider is named
in `providers_failed` with its reason in `provider_reasons`, `Run.errors` gets one line, and the
run carries on with what the others gave. The thread is left to finish what it was reading, so
what it keeps is there for the next run. A provider with a budget is not started once the run's
own time limit is reached. With a cold cache the outside view will usually run out of time on
the first run of a company and answer on a later one.

Both honour `as_of`: no frame of a year not yet reportable by the date, no 13F filed after it,
and the company's facts (the payload the run already read, not fetched again) cut at the
price's date. `tests/test_view_providers.py` runs a thesis as of a date and looks for any later
date in what the two views returned.

A run gets the two views when its filing source reaches EDGAR (the API and the CLI). A run
given no providers (the watcher's, the offline tests) computes from its own facts only.

### What was deleted from the first build, and why

The first build computed a fixed set of numbers per measure and more for the thesis at large.
Deleted as restatement of a figure the reader already has: the latest level, the flip value of a
test against a constant (it is the constant), and a test's margin stated again. Deleted as noise
for most claims: the change on the quarter before, the 4-quarter trend beside the 8-quarter one,
the position in the 8-quarter range (kept as words in the trend's reading), the standalone
typical move (kept where it gives the room a scale). Deleted as duplicates: the accrual share of
net income, which is one minus cash conversion, and the three DuPont lines, now the reading of
return on equity. Both sides' own paths are not computed for a test of one measure against
another: the gap is the subject.

## Odds that a test holds (`core/persistence`)

For a test of a quarterly measure of the whole company against a constant (its value, also held
in each of several quarters, or its growth on a year earlier). 10,000 paths of 4 quarters; each
step is drawn with replacement from the measure's own quarterly changes of the last 20 quarters
(differences in points for a ratio, growth rates for an amount), from the current value; for
growth on a year earlier each future quarter is compared with the known quarter four before it.
The estimate is the share of paths in which the test holds in all 4 quarters. Seed 20261118.
With fewer than 8 changes there is no number, only a warning. `Persistence` records the method,
the sample size (`changes`), the paths, the seed, the horizon and a `caveat` that belongs
wherever the number is shown: it resamples the past, knows nothing of trend, seasonality or
events, and is not a forecast.

## Corollaries (`core/corollaries`, step `propose`)

One request proposes, for every claim, including one no test compiles for, two or three
implications: "if this claim were true, what else would be true in the figures?" Each is a
sentence in the claim-test language, the outcome expected (`holds` or `fails`), a reason, and the
typed test the proposer means (the reading schema of `core/claim_reading`, which has no nullable
field and no union; `PROPOSE_TYPED_FORM` in `core/analysis_policy.py` turns the typed form off if
the API ever refuses the schema). The proposer is given the names of the parts the filings tag.

Two readers read each: the grammar reads the sentence, and the typed form is validated.

| `status` | Meaning | Computed | Counts toward the flag |
| --- | --- | --- | --- |
| `agreed` | both read the same test (normal form) | yes | yes |
| `grammar_only` | the typed form did not validate | yes | yes |
| `proposer_only` | the grammar read no test; labelled "the proposing model only" | yes | yes |
| `not_agreed` | the two read different tests; both are shown | the proposer's | no |
| `not_computable` | neither read a test | no | no |

Two readers is weaker than the rule the thesis's own claims are read under, and the record says
so (`Run.analysis.corollary_rule`). A corollary never moves a verdict. A claim with at least 2
counted corollaries of known outcome, more than half of them against what it implies, gets
`Claim.analysis.corollary_flag`.

## The argument (`engines/analyser`, steps `analyse` and `conclude`)

After the corollaries are computed: **one request per claim**, up to 3 at once (the limit the
engine assesses claims under, `limits.MAX_CONCURRENT_ASSESSMENTS`), **then one for the thesis**.
One request for everything was tried first: its answer ran past a 10,000-token cap and, at the
speed observed, a longer one would have taken about three minutes of a run that has four. Each
request now has a cap of 4,000 output tokens and one attempt of at most 60 seconds, so five
claims are two rounds and the thesis a third.

A claim's request shows the decision, every claim's text, verdict and computed test (so the
model knows the thesis the claim belongs to), and the whole material of the one claim it argues:
the run's own notes on it, its verified findings with a quotation, its analytics (each opening
with its question; one from the outside or market view followed by its note, which carries the
class or the assumptions), its corollaries, its odds and what could not be computed; then the
analytics about the company as a whole, the reported figures the claims are tied to, the 8-Ks
with each item's opening sentences, and the date the run is as of. A withheld finding is never
shown.

The claims' arguments are audited as they come back. The thesis's request shows the whole
record and, per claim, the audited argument: its lean, its assessment, what decides it and what
would change the verdict, with each sentence that failed the audit marked and why, or the note
that the claim has no argument. It is told to build on them and not to rest a point on a
sentence marked unverified.

It writes, per claim: `lean` (supports, challenges, mixed, unclear), `assessment` (up to 6
sentences: is the premise true, and is the step from the claim to the decision backed by the
record or assumed), `case_for`, `case_against`, `decides` (up to 3 each) and `would_change` (up
to 3 conditions, each a measure with a comparison and a threshold, or an 8-K category). For the
thesis: `leans_on`, `weakest_link` with `weakest_why`, `strongest_for`, `strongest_against`,
`bottom_line` (up to 6) and 2 or 3 `scenarios` of observable conditions. Every sentence is
`{text, cites}`. No price target and no buy, sell or hold advice; valuation only where an
analytic in the record gives it. The prompt says what a base rate is (a count in a named class,
not a probability for this company) and what an implied growth is (arithmetic under stated
assumptions at a dated price, not a forecast).

The model is the engine's by default (`ANTHROPIC_ANALYSIS_MODEL`, then `ANTHROPIC_MODEL`, then
`claude-opus-5-5`). Record text goes in escaped and every string the model returns is
unescaped. A cassette keys each request by its content, so each claim's answer and the thesis's
are recorded and replayed apart, and a replay that lacks some degrades claim by claim.

**When a request fails.** A claim whose request fails, or is not sent because the run's time is
up, has no argument and `Claim.analysis.argument_note` says why; the others stand, and the
thesis's request runs on what there is. `Run.analysis.argument_claims_answered` of
`argument_claims_asked` and `thesis_step` say what happened; `argument_step` is `answered` only
when every claim and the thesis were, `partial` when some were, `failed` when requests were sent
and none was answered, `not_asked` when none was sent. `Run.errors` gets one line naming each
request that failed.

**Each answer is asked for flat, and code regroups it.** The API compiles a schema into a
grammar and refused the first schema, which spelled the sentence object out under each of nine
sections, a condition and a scenario (HTTP 400, "The compiled grammar is too large"); it
accepted `propose`. Each schema now states the sentence once:

    a claim     lean, sentences[] {section, text, cites[]},
                conditions[] {text, cites[], measure, comparison, threshold, unit, event_category}
    the thesis  leans_on[], weakest_link, sentences[] {section, scenario, text, cites[]}

`section` is each schema's only enum (assessment, case_for, case_against, decides for a claim;
bottom_line, weakest_why, strongest_for, strongest_against, scenario for the thesis);
`scenario` is the scenario's name when the section is scenario. `parse_claim_argument` and
`parse_thesis_argument` put each sentence under its section in the order written, which gives
the record the same shape as before (`ClaimArgument`, `ThesisArgument`), and check in code what
the schema does not: a lean, comparison, unit or category it does not know becomes `unclear`,
`none` or empty; a sentence in a section that is not its subject's, over a section's cap or in a
fourth scenario is cut, counted in `analysis_sentences_cut`, and `argument_note` says why once
per reason. No schema has a union or a nullable field, and `tests/test_analysis_schema.py` keeps
each at no more than half the size of the accepted `propose` schema (schema nodes plus enum
members), with one enum.

### The audit (`core/analysis_audit`)

A sentence is `verified` when all three hold; otherwise it is kept, marked, and `problems` says
why:

1. every id it cites is in the run and may be cited: a verified finding, an analytic of any
   provider, a reported figure, a computed test (`test:c2`), a corollary, odds, an 8-K event. A
   finding the run withheld may not;
2. at least one cited id is evidence (a claim id names what the sentence is about, and is not);
3. every number it writes is a value of something it cites, by `core/numcheck.check_numbers`,
   the check the findings pass.

One exception to 3, on purpose: a `would_change` condition may write its own threshold
(`Condition.threshold`), which is a line the model proposes to watch, not a statement about the
record. A scenario's conditions get no such exception.

A `lean` that contradicts the claim's verdict (supports against Challenged, challenges against
Supported) is `ClaimArgument.lean_flag` and a line in `Run.analysis.flags`. The verdict stands.

**What the audit does not decide.** Whether a sentence follows from what it cites. A sentence
with no number that cites a real id passes. The audit makes every figure traceable and every
source real; the reader, shown each citation, judges the inference.

## When there is no model's analysis

| Case | `corollaries_step` / `argument_step` | The record holds |
| --- | --- | --- |
| The extractive engine, no key, or a run the watcher started | `not_asked` / `not_asked` | relevance, headline, analytics, odds |
| The run's time limit was reached before a request | `not_asked` for that request | the same, and whatever was answered before |
| A request failed, or its answer was malformed | `failed` for the corollaries; `partial` or `failed` for the argument | the same, with the arguments that were answered; a failed `propose` does not stop the argument |
| A cassette that lacks an answer | `failed`, or `partial` when it holds some of the argument's | the same; a read-only cassette saves no pending request |

In each case `corollaries_note` and `argument_note` give the reason and `Run.errors` gets exactly
one line. The run's status is unchanged.

## Counts (`Run.coverage`)

- `analytics_computed` + `analytics_unavailable` = the analytics on the record;
  `analytics_providers_failed` counts providers that gave nothing (their analytics are in
  neither).
- Corollaries, meaningful only when `corollaries_step` is `answered`: `corollaries_proposed` =
  `corollaries_as_expected` + `corollaries_against` + `corollaries_cannot_tell` +
  `corollaries_no_test` + `corollaries_not_agreed`. A corollary not agreed is computed and shown
  but is in neither outcome count. `corollaries_computed` = as expected + against.
  `corollary_flags` counts flagged claims.
- The argument's requests: `analysis_claims_answered` of `analysis_claims_asked` claim requests
  and `analysis_thesis_answered` (0 or 1). Its sentences, meaningful when `argument_step` is
  `answered` or `partial` and then covering the requests that were answered:
  `analysis_sentences_written` = `_verified` + `_unverified`; `_cut` counts sentences over a
  section's cap, removed before the audit; `analysis_unverified_no_evidence`, `_unknown_id`,
  `_disallowed_id` and `_number` count each reason once per sentence, so they can add up to more
  than `_unverified`. `analysis_claims_argued` of `claims_total`; `analysis_lean_flags`.

## Adding a provider

`services/analysis.analyse_run(..., providers=...)` runs a list of `AnalyticsProvider`
(`core/analytics.py`): an object with a `name` and `provide(request) -> list[Analytic]`. The
request carries the run's fact book and calendar, the measures each claim bears on, the computed
tests, the tagged breakdowns, and for a provider that reads outside the run's facts the company,
each claim's text, the date the run is as of, today by the run's clock and the facts payload.
One that reads a network sets `budget_seconds`. `DEFAULT_PROVIDERS` in `services/analysis.py`
is the run's own facts; `services/view_providers.run_providers` adds the two views for a run
that can reach EDGAR.

## Examples and recording

`make examples-analysis` (offline: no model, no EDGAR; the frames, 13F tables and facts are the
recorded fixtures of `make fixtures-market`) writes `docs/examples/analysis/`:

- `run.json`, `brief.md`: the five claims of the live NVIDIA sample with the extractive engine:
  the computed analysis from all three providers, and the notes saying no model wrote an
  argument.
- `run-hand-built-argument.json`, `brief-hand-built-argument.md`: the same run with scripted
  answers standing in for a model, to show every shape (each corollary status, a verified and an
  unverified sentence of each kind, a condition, a scenario, both flags). No model wrote them, the
  record says so, and its argument is not an argument.
- `run-model-argument.json`, `brief-model-argument.md`: the same run with a model's answers,
  replayed from `demo/cassettes/analysis-example`. Written only once they are recorded.
- `replayed-run.json`: the example thesis replayed from `demo/cassettes/nvda-example`, once that
  cassette holds the two answers.

`make record-analysis` records the model's answers through the API. Each of the two examples
has five claims and so makes 7 requests (1 for the corollaries, 5 for the claims, 1 for the
thesis), 14 in all. It prints that number first, sends only a request a cassette lacks and never
more than `MAX_CALLS` (default: all). Then `make examples-analysis` and
`make golden-baseline`, and read both diffs: the replayed example now carries an argument.

## Not verified

- The corollaries have been answered by a model and recorded (claude-opus-5-5, through the API).
  The argument has not: its per-claim and thesis requests have been exercised only with a fake
  transport. Whether the API accepts the two schemas, whether an answer fits in 4,000 tokens and
  60 seconds, how many sentences pass the audit and whether the argument is one an analyst would
  respect are unknown until `make record-analysis` is run and its output read.
- The two views have run inside a run only on NVIDIA's recorded frames, 13F tables and facts,
  from disk. How long they take against EDGAR with nothing kept, and how often the budgets cut
  them off, was not measured.
- The facts provider's analytics were checked by hand on NVIDIA and Apple from the recorded
  facts (`tests/test_analytics_recorded.py`), not on the other six probe companies, and the
  parts on NVIDIA's tags only.
- The time the step adds to a run was not measured outside a profiler.

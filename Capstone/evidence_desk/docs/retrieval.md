# Retrieval: what it does, how it was measured, what changed

## What it does today

Each filing is cut into passages of about 1,100 characters, exact slices of its text
(`retrieval/chunk.py`). All passages of a run go into one Okapi BM25 index (`bm25.py`, k1 1.5,
b 0.75; tokens from `core/text.py`). A claim is searched with its own text plus up to four planner
queries; a passage scores its best BM25 score over them, and the engine is offered the top 8
(`search.py`), at most 5 per filing when there are several; one filing now gets all 8 (was 5).

## Measurements (24 answerable cases; `eval/results/v5/`, cap fix applied unless noted)

| Variant | recall@3 | recall@8 | recall@20 | MRR |
|---|---|---|---|---|
| claim, before the cap fix (`eval/results/`) | 5 | 7 | 13 | 0.258 |
| claim | 5 | 9 | 13 | 0.258 |
| claim+queries, before the cap fix (`eval/results/`) | 12 | 18 | 21 | 0.458 |
| claim+queries (the pipeline) | 12 | 18 | 21 | 0.458 |
| queries-rrf | 10 | 16 | 22 | 0.430 |
| queries-heading | 12 | 18 | 20 | 0.472 |
| queries-rrf-heading | 13 | 16 | 21 | 0.491 |

The cap fix moves two "claim" cases into the top 8 (cost-tariffs-unrecovered and
aapl-asian-assembly, rank 7 on one filing) and no "claim+queries" case. recall@8 by company:

| Variant | NVDA (9) | COST (4) | AAPL (4) | MSFT (4) | KO (3) |
|---|---|---|---|---|---|
| claim+queries, and queries-heading | 5 | 3 | 4 | 4 | 2 |
| queries-rrf, and queries-rrf-heading | 5 | 3 | 4 | 3 | 1 |

RRF's gains are two cases, both NVIDIA (data-center-drives-growth 20 to 4, custom-silicon-threat
23 to 1). It loses four that claim+queries had: nvda-few-buyers-dominate (7 to 12),
nvda-crypto-lawsuit-over (2 to 15), msft-azure-growth (7 to 9), ko-north-america-volume (6 to 10).
Outside NVIDIA it gains nothing at recall@8 and loses two. Headings change no recall@8 case and
do not rescue ko-irs. **Decision: keep claim+queries**: no candidate beat it by more than two
cases without losing one. The candidates stay registered for evaluation; none is wired in.

## Diagnosis of the misses (claim+queries)
`make test T="eval/explain.py -s -k <case>"` prints per-term BM25 shares of the must-retrieve
and the first-ranked passage. In four of six misses the first-ranked passage wins on the
claim's own words: a claim has 8 to 12 content terms and a planner query 2 to 4, so under "best
score over queries" the claim's scale beats a short query that names the passage exactly.

- nvda-data-center-drives-growth, rank 20: "Business › Competition" (11.8 via the claim: "hardware"
  tf 4, "server", "AI") beats the MD&A revenue table (7.9 via "Data Center revenue").
- nvda-china-reopened, rank 15: the neighbouring risk factor (20.1 via the claim: "chip" tf 4,
  "approval", "china") beats s1-p134 (13.0 via "China export license H20"). The claim's British
  "licence", "data-centre" stem to `licenc`, `centr` and never meet `licens`, `center`.
- nvda-commitments-small, rank 20: a channel-credit risk factor
  (20.9 via the claim; "counterparty" tf 3 alone gives 7.6) beats the MD&A passage on supply and
  capacity commitments (10.3 via "supply and capacity purchase commitments").
- nvda-custom-silicon-threat, rank 23 (top-20 miss): a GPU-demand risk factor (11.6 via "reduced
  demand for our GPUs") beats a 56-token fragment (8.8) that says "in-house expertise".
- cost-north-america-dependence, rank 88 (top-20 miss): a supplier risk factor (11.7: "profit",
  and the pronoun "us" tf 4 matching the claim's "US") beats s1-p26 (2.4, "sales" only). "U.S."
  tokenizes to nothing (single letters are dropped); "Canadian" never meets "Canada".
- ko-irs-dispute-settled, rank 106 (top-20 miss): MD&A "Contractual Obligations" (20.1 via "tax
  litigation unrecognized tax benefits cash payment") beats the "Tax Audits" note (7.8 via "IRS
  notice of deficiency appeal"); the claim says "US tax authority", not IRS.

## Candidates, written down before any was measured
1. `queries-rrf`: reciprocal-rank fusion, sum of 1/(60 + rank) over matching queries (k = 60,
   Cormack et al. 2009; not tuned). Expected to remove the claim's scale advantage and reward
   consensus. Risk: a passage only the claim finds becomes one vote in five.
2. `queries-heading`: each passage scored with its section locator before its text (quotes
   unchanged); expected to help where a subheading names the topic ("Tax Audits").
3. `queries-rrf-heading`: both.

Not tried: down-weighting tables (data-center's passage is a table), a larger cut (a budget,
not a ranking), tokenizer fixes for "U.S." and British spelling (one case each; `tokenize` is
shared with the extractive engine, so the tripwire's evidence stage would move).

## What changed, and which recordings it invalidates

Wired: only the cap fix (`PassageIndex.search`, now `cut(ranked(...))`). It changes what a
single-filing run offers, so 10 of the 30 assess requests in `eval/cassettes/golden` (the 5
COST and 5 AAPL cases) no longer match (checked by replaying a copy: 10 pending), and
`eval/results/generation-2026-11-17` is stale for them. The NVIDIA example (three filings),
`demo/cassettes/nvda-example` and the tripwire's retrieval stage did not move. Wiring RRF would
change the passages of nearly every run: all 30 golden assess requests, the example cassette and
the tripwire from `retrieval` on.

## What the golden set cannot tell you

24 answerable cases, 9 of them NVIDIA: one case is 4 points of recall, so a two-case difference
is within what a different drafter would move. The cases and their must-retrieve passages were
drafted by a Claude Opus session on 2026-11-17 and checked mechanically; no person has read each
case. The planner queries were recorded once, from one stand-in model, so query variance is
unmeasured. A miss means the named excerpt was not offered, not that no useful evidence was.

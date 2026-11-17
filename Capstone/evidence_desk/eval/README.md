# Golden set: retrieval and generation, scored apart

Known thesis claims, each with the filing passage a correct answer must cite and the stance a
careful reader would take. Retrieval is scored on whether that passage reaches the engine;
generation on what the model and the citation gate make of the passages it was given.

**Status.** The 30 cases (24 answerable, 6 unanswerable, five companies) were drafted by a
Claude Opus session from the filing text on 2026-11-17 and validated mechanically. The author
has not yet read them case by case: each `expected` stance is a model's reading, not ground
truth. The cases are an answer key; never edit one to improve a score.

## Files

- `golden.json`: cases with `id`, `ticker`, `filings` (newest first), `claim`, `kind`
  (`answerable`/`unanswerable`), `expected` (`supports`/`challenges`/`mixed`, or `none`),
  `must_retrieve` (1 to 3 exact 60 to 400 character excerpts with a section prefix) and `why`.
- `filings.json`: every filing pinned by URL and SHA-256 of its HTML, with the company's `cik`
  and `name` (the prompts carry them); `facts`: each company's XBRL facts pinned by SHA-256.
- `cache/` (gitignored): fetched filings and facts. `results/`: one JSON and one Markdown record
  per scoring run. `queries.json`: the planner's queries, with provenance. `cassettes/golden/`:
  the model answers (`docs/cassettes.md`).

## Commands

    make eval ARGS="fetch"            # cache every pinned filing and company's facts (once)
    make eval-validate                # check every case; exit 1 on any failure
    make eval ARGS="run --variant claim"                                  # retrieval, claim only
    make eval ARGS="plan --cassette eval/cassettes/golden --out eval/queries.json"
    make eval ARGS="run --variant claim+queries --queries eval/queries.json"  # retrieval
    make eval ARGS="generate --cassette eval/cassettes/golden --queries eval/queries.json"

Add `--offline` after `ARGS="` to forbid EDGAR. Adding a case: `ARGS="pin TICKER"`, find the
passage with `ARGS='show TICKER ACCESSION "Item 1A" --grep margin'`, copy it exactly, validate.

## The answer loop (the API cannot be called)

`plan` groups the cases by ticker in file order into requests of at most six claims (the
unanswerable ones too, so the planner is not told which they are) and asks
`ClaudeAnalyst.plan` through the cassette, as a run would with the decision "Whether the thesis
still holds after the latest filings". `generate` runs every case as a one-claim run: retrieval
with the claim and its queries (top 8, at most 5 per filing), the company's reported figures,
`assess` through the cassette, the citation gate, and the verdict rule. A request with no
answer is saved under `cassettes/golden/pending/`; the command prints how many, writes nothing
and exits 3. Answer them (`docs/cassettes.md`), run again; exit 0 means the file was written.
Expect 6 plan requests, then one assess request per case offered a passage (30).

## Reading the numbers

Retrieval (`results/retrieval-*`): a passage is relevant when it is in the excerpt's filing and
holds at least half the excerpt's characters. recall@3 and @20 and MRR use the uncapped ranking
(beyond 50 is a miss); recall@8 is what a run offers, with 5 passages per filing at most.
Every rate is over the 24 answerable cases.

Generation (`results/generation-*`), every rate with its denominator:

- *Verdict agreement* (24 answerable): `supports` gives supported, `challenges` challenged,
  `mixed` mixed; with the table of expected against obtained (incl. unjudged, not_addressed).
- *Cites a must-retrieve passage*: a verified excerpt holds half of an excerpt (same rule).
- Both split by whether a must-retrieve passage was offered: a miss is a retrieval failure.
- *Refusal* (6 unanswerable): no verified finding and the verdict not_addressed.
- *Counts* (all 30): quotes offered, verified, rejected; numbers checked and unmatched;
  findings proposed, verified and withheld, with the reasons. A withheld finding never counts.

## What it does not show

- Answers written by a stand-in rather than the model a run calls are an upper bound for quote
  validity; the report names who answered (`via`, `model`) at the top.
- Agreement is with a model-drafted key, unread by the author. Citation is strict: a right
  answer may rest on other evidence than the excerpt named.
- One recording per prompt: no variance across samples, and no test of the live API call.
- Facts change when a company files: on a fresh clone without `cache/`, refetched facts may no
  longer match their pin, and `generate` stops rather than score with different figures.

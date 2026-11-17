# Retrieval golden set

Known thesis claims, each with the filing passage a correct answer must cite. It measures only
whether BM25 retrieval puts that passage in front of the engine, not the stance or verdict.

**Status.** The 30 cases in `golden.json` were drafted by a Claude Opus session from the filing
text on 2026-11-17 and validated mechanically (below). The author has not yet read them case by
case. Until then each `expected` stance is a model's reading of the filing, not a ground truth;
the `must_retrieve` excerpts are checked to exist, not checked to be the best evidence.

## Files

- `golden.json`: `{"version": 1, "status", "cases": [...]}`. A case has `id` (kebab-case),
  `ticker`, `filings` (accession numbers, newest first, as a run orders them), `claim` (an
  analyst's paraphrase), `kind` (`answerable`/`unanswerable`), `expected` (`supports`,
  `challenges`, `mixed`; `none` if unanswerable), `must_retrieve` (answerable only: 1 to 3
  `{accession, section, text}`: an exact 60 to 400 character excerpt and a prefix of its
  section heading such as `Item 1A` or `Part I, Item 2`) and `why`.
- `filings.json`: every filing a case uses, pinned by ticker, accession, form, period end, URL
  and the SHA-256 of the original HTML. A filing whose hash differs from its pin is an error.
- `cache/` (gitignored): filings not in `tests/fixtures/edgar`, as fetched. `results/`: one JSON
  and one Markdown record per scoring run (inputs pinned by hash, limits, every case).

## Running

`make -B eval ARGS="..."` runs `python -m app.evaluation run ...` (a leading `run` before another
command is dropped). `-B` is needed until `eval` is in the Makefile's `.PHONY`; otherwise this
directory, also named `eval`, makes `make eval` report "up to date" and do nothing.

    make -B eval ARGS="fetch"     # cache every pinned filing (EDGAR, once)
    make eval-validate            # check every case; exit 1 on any failure
    make -B eval                  # score the "claim" variant, write results/
    make -B eval ARGS="--variant claim+queries --queries eval/queries.json"  # {case_id: [...]}

Validation checks fields and enums, unique ids, pinned filings, and that every excerpt is found
by the citation gate's `TextIndex.locate` in the stored text, inside a section whose heading
starts with the stated prefix at a word boundary (`Item 1` does not match `Item 1A`). The NVIDIA
and Costco cases run offline from the recorded fixtures (a test checks it).
## Adding a case

1. Pick the filing. If it is not in `filings.json`: `make -B eval ARGS="pin TICKER"` (latest
   10-K and newest 10-Q) or `ARGS="pin TICKER ACCESSION"`.
2. Find the passage: `make -B eval ARGS='show TICKER ACCESSION'` lists the sections;
   `ARGS='show TICKER ACCESSION "Part I, Item 2" --grep margin'` prints matching lines.
3. Copy 60 to 400 characters exactly, and the section prefix. Write the claim in your own
   words, avoiding the excerpt's distinctive terms.
4. For an unanswerable case, search the filings for the key terms and record that in `why`.
5. Run `make eval-validate` until it passes.

## Reading the numbers

Each answerable case's filings are parsed and chunked exactly as a run does (sources `s1`, `s2`,
... in `filings` order) and ranked by `PassageIndex`. A passage is relevant when it is in the
excerpt's filing and holds at least half of the excerpt's characters. The rank is that of the
first relevant passage; beyond 50 it is "not in top 50", a miss. Every rate's denominator is the
number of answerable cases (24); unanswerable cases are not scored for retrieval.
recall@3 and recall@20 are the share of cases with a relevant passage at that rank or better;
MRR is the mean of 1/rank, a miss counting 0. recall@8 is what a run offers the engine, with the
pipeline's cap of 5 passages per filing: a one-filing case is offered only 5 passages.

# Architecture

Evidence Desk (version 0.9.0) tests an equity analyst's thesis claims against the company's own SEC filings and shows,
per claim, the verbatim passages and figures that support or challenge it. A reviewer can accept or reject each
finding, save a thesis, run it again and see what moved. `../PROMPT.md` is the brief; `docs/reviews/` the review.

## Stack

- Python 3.14, FastAPI, Pydantic, httpx, BeautifulSoup, SQLite; `anthropic` for the optional model engine. No front-end build.
- Docker Compose, on `127.0.0.1:8766` only; dependencies install at image build. All through the `Makefile`.

## Layout (one job per module)

    src/app/core/models.py      the record types (request, run, finding, decision, thesis, comparison); pure data
    src/app/core/limits.py      every number of the data contract
    src/app/core/policy.py      the verdict rule, the complete/partial rule and their wording
    src/app/core/ports.py       the interfaces the pipeline depends on, and the drafts crossing them
    src/app/core/documents.py   Document, Section, Passage, FilingRef: what adapters hand over
    src/app/core/gate.py        the citation gate: drafts in, byte-exact verified evidence out
    src/app/core/review.py      a reviewer's decisions on one run, and the reviewed verdict per claim
    src/app/core/compare.py     what moved between two runs of one thesis
    src/app/core/links.py, text.py   text-fragment links to an excerpt; word tokens and sentence spans
    src/app/core/filing_diff.py what was added, removed, reworded or renumbered between two filings, Item by Item; change_models.py is its pure data
    src/app/core/claim_changes.py   which changed paragraphs of a run's filings share words with each claim (BM25 and a rule of two shared terms; no model); claim_change_models.py is its pure data
    src/app/core/breakdowns.py  builds revenue by segment, product and geography and customers' shares from one filing's tagged facts; checks members against the tagged total; breakdown_models.py is its pure data
    src/app/core/facts.py       FactBook: values from XBRL company facts, placed by their dates
    src/app/core/metrics.py     computes the metrics report from facts; metric_models.py is its pure data
    src/app/core/numcheck.py    the numeric check: each number a statement writes is in what it cites
    src/app/core/meaning.py     the meaning check's pure half: what the checker is shown, and applying its judgements
    src/app/sources/edgar.py    SEC EDGAR adapter: ticker, filing selection, rate-limited fetch
    src/app/sources/filing.py   splits a 10-K/10-Q into Part and Item sections
    src/app/sources/http.py     bounded fetch of a public page, every redirect hop revalidated
    src/app/sources/urls.py, web.py, xbrl.py   public-URL validation; page text; the company-facts URL and body
    src/app/sources/ixbrl.py    reads a filing's own tagged numbers (inline XBRL: contexts, units, ix:nonFraction) with a targeted scan; what it cannot read is counted with its reason
    src/app/retrieval/chunk.py, bm25.py   sections into passages (exact substrings); Okapi BM25 scoring
    src/app/retrieval/search.py ranks a run's passages for one claim (top 8; at most 5 per source when there are several)
    src/app/engines/claude.py   Claude engine: builds each request and parses each answer
    src/app/engines/checker.py  the meaning checker: a second model judges each verified finding (NoChecker: none)
    src/app/engines/transport.py, cassette.py   the Transport port and its API adapter; answers recorded once, replayed by key
    src/app/engines/extractive.py, fallback.py   deterministic engine, no stance; a primary engine falling back to it
    src/app/services/ingest.py  select, read (cache or EDGAR), parse, deduplicate, record the sources
    src/app/services/numbers.py, examples.py   XBRL facts in, metrics and offered figures out; the NVIDIA example thesis
    src/app/services/thesis_run.py  one run, stage by stage; the only place a run advances
    src/app/services/theses.py  saved theses: create, start a run of one, the latest comparison
    src/app/services/export.py  the Markdown brief, plain or with the reviewer's decisions
    src/app/services/filing_changes.py  selects a company's two latest filings of one form, reads them through the cache, compares them
    src/app/services/claim_changes.py   for a run: the filing before each filing it read, the two comparisons, the ranking per claim; a comparison that cannot be made is a note, never an error
    src/app/services/breakdowns.py   the latest filing of a form, fetched and read into breakdowns
    src/app/store.py            SQLite: Store (the record) and FilingCache (disposable)
    src/app/backup.py           backs up the record; checks that the newest backup restores
    src/app/wiring.py           composition root: reads the environment, builds collaborators
    src/app/api.py              HTTP routes and static files
    src/app/cli.py              command line onto the same use case
    src/app/demo.py, probe.py, changes.py, breakdowns.py, record_fixtures.py, record_facts.py   live demo; live parser check; the filing comparison and the tagged breakdowns from the command line; fixture recorders
    src/app/evaluation/golden.py, corpus.py   load and validate the golden set; the filings it is measured on, pinned by hash
    src/app/evaluation/retrieval_eval.py  scores where the right passage ranks; the variant registry
    src/app/evaluation/cli.py   `python -m app.evaluation`: validate, run, fetch, pin, show, plan, generate, mismatch
    src/app/evaluation/companies.py, planning.py, generation_eval.py   pinned figures, planned queries, answer scoring
    src/app/evaluation/mismatch_eval.py   plants real quotes under statements they do not belong to and scores what the meaning check says
    src/app/evaluation/reading_sheet.py   lays the golden cases out for a person to read (`make golden-sheet`)
    src/web/                    index.html, app.js, styles.css, sample-run.json, sample-synthetic.json, sample-changes.json, sample-run-changes.json, sample-breakdowns.json, sample-breakdowns-gap.json (synthetic)
    eval/                       the golden set, its pinned filings, cache/ and results/; README.md
    tests/                      offline tests, fakes.py (EDGAR, pages, engine, clock), smoke.py; replay_run.py, golden_run.py, speed_run.py
    tests/live_walk.py          the live end-to-end walk over HTTP; tests/golden/ the tripwire and replayed verdicts
    uitests/                    browser tests: the rendered DOM of the two sample runs and the sample filing comparison against their JSON

## Storage: the record and the cache

Two SQLite files under the data directory (`EVIDENCE_DESK_DATA_DIR`; `data/`, gitignored), both in `store.py`.

- **The record**, `data/record/record.sqlite`, class `Store`: `runs` (each run as JSON), `decisions` (one per run and
  finding) and `theses` (saved requests and their run ids). Nothing can rebuild it: a later run meets a different
  EDGAR, perhaps a different parser and model, and a decision exists nowhere else. It is the only file backed up.
- **The cache**, `data/cache/filings.sqlite`, class `FilingCache`: `texts`, each document's text once, keyed by its
  SHA-256; `filings`, an index from (accession, parser version) to that hash, the publisher, section spans and fetch
  time. The record holds only the hash, never the text.
- **Backup.** `make backup` copies the record with SQLite's online backup (safe while the app runs) to
  `backups/record-<UTC>.sqlite` with a `.sha256`, and writes `backups/decisions-<UTC>.jsonl`, one line per decision.
  `make restore-check` verifies the newest backup's hash, restores it to a temporary directory and compares run ids,
  decisions and theses with the live record: PASS, or FAIL with the first difference.
- **Deleting the cache loses no record, and one thing a record points at.** The next run fetches the filings from EDGAR, parses them again and refills it. But the stored text that an old run's excerpts are offsets into lives only in the cache. With it gone, the excerpts are still in the record as text; checking that they are spans of the stored text again needs the same filing fetched and parsed by the parser that produced it.
  Runs in the record are unchanged. A version 3 database at `data/runs/runs.sqlite` is not read.

## The pipeline (`services/thesis_run.execute_run`)

1. **Resolve.** `FilingSource.company` maps the ticker to CIK and name; the API and the CLI do it before a run starts,
   so an unknown ticker is refused, not a failed run.
2. **Ingest** (`services/ingest`). The newest 10-K and the 10-Qs filed after it, newest first, then any extra pages. A
   filing is looked up in the cache by accession and `PARSER_VERSION` (the SHA-256 of `sources/filing.py` plus the
   BeautifulSoup version, so editing the parser invalidates every cached filing); a hit is rebuilt from the cached
   text and not fetched. A miss is fetched within EDGAR's limits, parsed into Items and indexed. Extra pages are
   always fetched: a page can change. A failure is recorded on its `Source` and the others continue. Identical content
   is read once. With no readable source the run ends `failed` with no brief.
3. **Numbers** (`services/numbers`). The company's XBRL facts become a metrics report on the run; the newest quarters
   and years of a few key metrics are the figures offered to the engine. A failure is a coverage limit, never the end
   of the run, but the run is then partial. The facts are never chunked or quoted.
4. **Plan.** The engine writes up to four queries per claim.
5. **Retrieve.** All passages of the run go into one BM25 index; each claim is searched with its own text and queries.
6. **Assess.** One engine call per claim returns findings with stances, quotes and cited figure ids. Up to
   `MAX_CONCURRENT_ASSESSMENTS` (3) calls run at once; claims start and pass the gate in claim order, so the record
   (ids included) is the one a sequential run gives. A failed call falls back for that claim only.
7. **Verify.** `gate.gate_claim` locates each quote inside a passage offered for its claim (the one it names, else
   another offered passage of the same source, whose locator the excerpt then carries) in the stored text
   (`FilingCache.source_texts`) and keeps the stored span; a quote found only elsewhere in the source, or one that
   includes a heading line the parser wrote, is rejected. A cited figure must have been offered; `core/numcheck`
   requires every number a statement writes to appear in its excerpts or figures. A finding with no surviving quote
   or figure, or an unmatched number, is withheld and counted. A verified finding's reason, a claim's commentary,
   the unknowns and the next steps are checked the same way: a reason or commentary with an unmatched number is
   replaced by a note, an unknown or next step is dropped; a model summary with an unmatched number is replaced by
   the template. Every quote is counted as found or rejected (`quotes_found + quotes_rejected == quotes_offered`).
8. **Check meaning** (when a `Checker` is configured). In the worker that assessed the claim, right after its gate,
   one request per claim shows a second model (`ANTHROPIC_CHECK_MODEL`, default `claude-haiku-5-5`) each verified
   finding's statement, stance, excerpts and cited figures, never the engine's rationale or confidence
   (`core/meaning.check_items`). "supported" marks the finding passed, "partly" keeps it marked partly, and
   "not_supported" withholds it with the checker's reason and drops its evidence. A checker failure leaves that
   claim's findings unchecked, adds one error line and a coverage limit, and never fails the run; neither "partly"
   nor a failed check makes a run partial. A checker on the engine's own model is recorded as a coverage limit.
9. **Decide.** `policy.claim_verdict` sets each verdict from verified findings only; a finding that rests on
   reported figures alone counts as its stance only when the meaning check passed it, and as context otherwise
   (`Finding.counted_as`, `count_note`). `policy.run_status` sets complete, partial (with each reason and its
   denominator) or failed; a filing mostly outside numbered Items (`Source.item_coverage` below
   `MIN_ITEM_COVERAGE`) or unreadable XBRL facts make a run partial. `policy.provenance_note` writes the run's
   provenance from the sources it read (`Brief.provenance_note`). The 300-second limit is checked before every
   source and each round of claims; a claim not started in time is reported as not assessed.

Saves: the run is saved at each stage, after each source and after each claim. A save while the status is `running`
is a progress save, not synced to disk on its own; the final save is synced and carries those before it. A power cut
can lose an unfinished run, never corrupt the file. `new_run(request, thesis_id)` makes the running record; `thesis_id`
ties it to a saved thesis.

After a run, outside `execute_run`: **review** (`core/review.build_review`): a reviewer accepts or rejects a verified
finding; a claim's reviewed verdict is `policy.claim_verdict` over its accepted findings, so reviewer and engine follow
one rule; other decisions are ignored; the review is computed per request, not stored. **Compare**
(`core/compare.compare_runs`): two runs of one thesis, claims matched by text: verdict moved or not, excerpts added and
dropped, filings new or gone.

## Patterns and interfaces

- **Ports and adapters.** `core/ports.py` declares `FilingSource`, `PageFetcher`, `Analyst` and `Checker`. `sources/edgar.py`
  adapts SEC EDGAR to `FilingSource`; `sources/http.py` is the `PageFetcher`. The pipeline imports only the ports.
- **Transport as a port, two adapters.** `engines/transport.py` declares `Transport` (a `ModelRequest` in, the answer
  out). `AnthropicTransport` calls the API; `engines/cassette.CassetteTransport` answers from recorded responses keyed
  by the SHA-256 of the request; a changed prompt finds no answer and is saved to `pending/` (`docs/cassettes.md`).
  `ClaudeAnalyst` builds the same prompts either way. The meaning checker shares the engine's cassette and run through
  `CassetteTransport.sibling`, so a pending check blocks the summary; the cassette starts a new run only at a plan.
- **Strategy.** The engines (`engines/claude.py`, `engines/extractive.py`) are interchangeable behind `Analyst`.
  Retrieval variants are a separate registry, `VARIANTS` in `evaluation/retrieval_eval.py`.
- **Decorator.** `engines/fallback.py` wraps an engine in the same `Analyst` interface and uses the extractive engine
  for any step that raises, reporting it.
- **Repository, split by what can be rebuilt.** `Store` (runs, decisions, theses) and `FilingCache` (texts, parsed
  filings) in `store.py`; nothing else touches SQLite. Both use one private `_Database` (one connection under a lock,
  WAL).
- **Gate and pure rules.** `core/gate.py` (`gate_claim`) is the only path from an engine's draft to evidence a reader
  sees; `core/review.py` and `core/compare.py` also take records and return records. None touches the network, a store
  or a clock; `services/theses.py` reads the store and calls them.
- **Composition root.** `wiring.py` (`analyst_from_env`, `checker_from_env`, `filings_from_env`, `store_from_env`,
  `cache_from_env`) is
  the only module that reads the environment; nothing opens a database at import time. `create_app` builds one
  `FilingCache` shared by all runs.
- **Two entry points, one use case.** `api.py` (`create_app`, run by uvicorn `--factory`) and `cli.py` (`main`) both
  call `thesis_run.execute_run`; `api.py` holds routes only.
- **One wording source.** `policy.py` and `limits.py` hold every label, note and number. The page reads them from `GET
  /api/meta`; the export and the CLI import them (review findings F1, F8).

New routes in `api.py`: `GET /api/runs/{id}/review`; `PUT /api/runs/{id}/findings/{fid}/decision` (404 unknown run or
finding, 409 while running, 422 withheld finding); `GET .../export.md?reviewed=true`; `/api/theses`, `/api/theses/{id}`,
`POST /api/theses/{id}/runs`, `GET /api/theses/{id}/changes`.

## Where a change goes

- **A new source format** (XBRL facts, a PDF exhibit): an adapter in `sources/` returning `core.documents.Document`
  (text plus sections that are exact substrings), called from `services/ingest.py`. Nothing downstream changes.
- **A change to the verdict or status rule**: `core/policy.py` and its tests only.
- **A new output view**: a module that reads a `Run` (and a `Review` if it shows decisions) and the wording in
  `core/policy.py`, as `services/export.py` does; serve it from `api.py`.
- **A new metric**: its computation in `core/metrics.py` (writing the formula out); if the engine should see it, its
  key in `services/numbers.FIGURE_KEYS`. The gate and numeric check apply unchanged; re-baseline the tripwire.
- **A prompt or schema change** (`engines/claude.py`): the tripwire's `prompts` stage moves and the replay finds no
  answers. The checker's prompt (`engines/checker.py`) is not in the `prompts` stage: a change to it shows only as
  pending `check` requests in the replay. Re-record the cassette (`docs/cassettes.md`), review the answers, `make golden-baseline`, read the diff of
  `tests/golden/`, commit together.
- **A new engine**: a class with `name`, `plan`, `assess`, `summarize` in `engines/`, chosen in `wiring.py`. The gate
  and the policy apply to it unchanged.
- **A schema change to the record** (`RECORD_SCHEMA` in `store.py`): it only creates missing tables and there is no
  migration code, so write the migration with the change. `make backup` first, `make restore-check` after; records
  that no longer validate are skipped with a warning, so compare counts too. The cache needs no care: delete it.
- **A new kind of reviewer decision**: a value in `DecisionValue` (`core/models.py`), its label in
  `policy.DECISION_LABELS`, its effect in `core/review.build_review`, then the page and export. Decisions are stored
  as JSON, so no new column. Back up first.
- **A new retrieval variant**: a `Variant` in `VARIANTS` in `evaluation/retrieval_eval.py`. Measure it on the golden
  set (`make eval ARGS='run --variant NAME'`) before it is wired into `retrieval/search.py` or the pipeline.
- **A change to how two filings are compared** (the threshold for "reworded", what counts as a table row): `core/filing_diff.py`, whose constants sit at its top, with `tests/test_filing_diff.py`. The comparison is separate from a thesis run: `GET /api/companies/{ticker}/changes` and `make changes` both call `services/filing_changes.filing_changes`. Read the pairs a new threshold adds before keeping it (`docs/filing-changes.md`).
- **A change to which changed paragraphs are listed under a claim** (how many words must be shared, how many are listed, how repeats are folded): `core/claim_changes.py`, whose two constants sit at its top, with `tests/test_claim_changes.py`. It is computed on demand by `GET /api/runs/{id}/changes` from the filings the run read and is not part of the run record, so the tripwire does not move. After a change, run `make sample-run-changes` and read what each claim now lists (`docs/claim-changes.md`).
- **A change to the breakdowns** (another axis, another revenue concept, a new shape of nested members): `core/breakdowns.py`, whose specifications and constants sit at its top, with `tests/test_breakdowns.py`; a number format the reader does not know: `sources/ixbrl.py` with `tests/test_ixbrl.py`. Start from a failing test built on a small excerpt of the real filing, then run `make breakdowns` on the eight probe companies, annual and quarterly, and check that every breakdown still adds up to its tagged total (`docs/breakdowns.md`).

## The boundary

The backend computes every result: verified excerpts, verdicts, status, every count in `Run.coverage`, the reviewed
verdicts and the comparison. The frontend collects input and decisions, polls, and draws the record with the wording
from `/api/meta`; it computes no verdict and no excerpt context. The same holds for the three records that are not
part of a run (the comparison of two filings, the changed paragraphs listed under each claim, the tagged breakdowns):
each arrives with its counts, its links and what they open, its column headings, its cells and its changes already
computed and formatted, and the page only places them. Requests are validated at the API: the schema in
`core/models`, extra URLs (public, distinct) in `api.py`, the ticker against EDGAR. Refusals are 422 `{"error",
"details": [{"field", "message"}]}`; EDGAR unreachable is 503; a valid request the state forbids is 409. Filing and
page text reaches the model only as escaped data inside `<passage>` elements, and the gate, not the model, decides
what counts. Filings come only from `www.sec.gov` and `data.sec.gov` (7 requests per second, 30 s, 40 MB, retries on
429/503); extra pages go through the private-address-safe fetcher. The key stays in `.env`.

## Verification and operation

- `make verify`: image build, ruff, `node --check`, the offline tests, `tests/smoke.py` against the live container
  (no internet), and `make uitest` (headless Chromium renders the two sample runs and the sample filing comparison; `uitests/`
  checks the DOM against their JSON). Offline tests use `tests/fakes.py`; `make fixtures` re-records EDGAR responses.
- `make golden-check` compares the offline example run with `tests/golden/golden.json` and names the first stage that
  moved; `make golden-baseline` rewrites it. `make profile` and `make bench` time the offline run (`docs/testing.md`,
  `docs/speed.md`).
- `make eval-validate` checks each golden case against its pinned filing; `make eval ARGS='run --variant claim'`
  scores retrieval into `eval/results/`; `ARGS='fetch'` fills `eval/cache`. `make probe TICKERS="AAPL"` checks how a
  filer's filings split.
- `make up` serves `http://127.0.0.1:8766`; `make up-recorded` replays model answers from
  `demo/cassettes/nvda-example` (EDGAR, no key; compose passes `EVIDENCE_DESK_CASSETTE` through). `make run
  ARGS='example'` runs the CLI; `make demo` runs the example live.
- `make live-walk`: the app recorded, then `tests/live_walk.py` over HTTP with live EDGAR: a run, decisions, the
  reviewed brief, a thesis run twice (the second from the cache) and the comparison.

# Architecture

Evidence Desk (version 0.2.0) tests an equity analyst's thesis claims against the company's
own SEC filings and shows, per claim, the verbatim passages that support or challenge it.
`../PROMPT.md` is the brief; `docs/reviews/` holds the structure review this design answers.

## Stack

- Python 3.14, FastAPI, Pydantic, httpx, BeautifulSoup, SQLite (stdlib); the `anthropic` SDK
  for the optional model engine. Static HTML, CSS and browser JavaScript, no build step.
- Docker Compose, published on `127.0.0.1:8766` only; dependencies install at image build from
  `docker/pyproject.toml` and `docker/uv.lock`. Everything runs through the `Makefile`.

## Layout (one job per module)

    src/app/core/models.py      the record types (request, run, source, evidence, finding); pure data
    src/app/core/limits.py      every number of the data contract
    src/app/core/policy.py      the verdict rule, the complete/partial rule and their wording
    src/app/core/ports.py       the interfaces the pipeline depends on, and the drafts crossing them
    src/app/core/documents.py   Document, Section, Passage, FilingRef: what adapters hand over
    src/app/core/gate.py        the citation gate: drafts in, byte-exact verified evidence out
    src/app/core/links.py       text-fragment links that open a filing at an excerpt
    src/app/core/text.py        word tokens and sentence spans (exact slices)
    src/app/sources/edgar.py    SEC EDGAR adapter: ticker, filing selection, rate-limited fetch
    src/app/sources/filing.py   splits a 10-K/10-Q into Part and Item sections
    src/app/sources/http.py     bounded fetch of a public page, every redirect hop revalidated
    src/app/sources/urls.py     public-URL validation and canonicalization
    src/app/sources/web.py      extracts text and headings from a public page
    src/app/retrieval/chunk.py  packs a document's sections into passages (exact substrings)
    src/app/retrieval/bm25.py   Okapi BM25 scoring
    src/app/retrieval/search.py ranks a run's passages for one claim (top 8, at most 5 per source)
    src/app/engines/claude.py   Claude engine: plan, assess, summarize; filing text as escaped data
    src/app/engines/extractive.py  deterministic engine: quotes best-matching sentences, no stance
    src/app/engines/fallback.py the primary engine, falling back step by step and reporting it
    src/app/services/ingest.py  select, retrieve, parse, deduplicate and record the sources
    src/app/services/thesis_run.py  one run, stage by stage; the only place a run advances
    src/app/services/export.py  the Markdown brief
    src/app/services/examples.py   the NVIDIA example thesis
    src/app/store.py            SQLite repository: run records and stored source text
    src/app/wiring.py           composition root: reads the environment, builds collaborators
    src/app/api.py              HTTP routes and static files
    src/app/cli.py              command line onto the same use case
    src/app/demo.py             live demonstration through the HTTP API, writes results/
    src/app/record_fixtures.py  records the NVIDIA EDGAR fixtures under tests/fixtures/edgar
    src/web/                    index.html, app.js, styles.css, sample-run.json
    tests/                      offline tests, fakes.py (EDGAR, pages, engine, clock), smoke.py

## The pipeline (`services/thesis_run.execute_run`)

1. **Resolve.** `FilingSource.company` maps the ticker to CIK and name. The API and the CLI
   resolve it before a run starts, so an unknown ticker is refused, not a failed run.
2. **Ingest** (`services/ingest`). The newest 10-K and the 10-Qs filed after it, newest first,
   then any extra pages. Each filing is fetched within EDGAR's limits and parsed into Items; a
   failure is recorded on its `Source` and the others continue. Identical content is read once.
   With no readable source the run ends `failed` with no brief.
3. **Plan.** The engine writes up to four queries per claim.
4. **Retrieve.** All passages of the run go into one BM25 index; each claim is searched with its
   own text and its queries, so no claim's passages depend on another claim.
5. **Assess.** One engine call per claim returns findings with stances and quotes.
6. **Verify.** `gate.gate_claim` locates each quote in the stored text of its source and keeps the
   stored span; a finding with no surviving quote is withheld and counted.
7. **Decide.** `policy.claim_verdict` sets each verdict from verified findings only;
   `policy.run_status` sets complete, partial (with each reason and its denominator) or failed.
   The 300-second limit is checked before every source and every claim.

## Patterns and interfaces

- **Ports and adapters.** `core/ports.py` declares `FilingSource` (company, periodic_filings,
  fetch), `PageFetcher` and `Analyst`. `sources/edgar.py` adapts SEC EDGAR to `FilingSource`;
  `sources/http.py` is the `PageFetcher`. The pipeline imports only the ports.
- **Strategy.** The engines (`engines/claude.py`, `engines/extractive.py`) are interchangeable
  behind `Analyst` (`plan`, `assess`, `summarize`).
- **Decorator.** `engines/fallback.py` wraps a primary engine in the same `Analyst` interface and
  answers with the extractive engine for any step that raises, reporting each fallback.
- **Repository.** `store.py` (`save_run`, `get_run`, `list_runs`, `save_source_text`,
  `get_source_texts`); nothing else touches SQLite.
- **Gate.** `core/gate.py` (`gate_claim`) is the only path from an engine's draft to evidence a
  reader sees. It is pure: no network, no clock.
- **Composition root.** `wiring.py` (`analyst_from_env`, `filings_from_env`, `store_from_env`) is
  the only module that reads the environment. Nothing opens a database at import time.
- **Pipeline.** `services/thesis_run.py` runs the stages in order over the ports.
- **Two entry points, one use case.** `api.py` (`create_app`, run by uvicorn with `--factory`)
  and `cli.py` (`main`) both call `thesis_run.execute_run`; `api.py` holds routes only.
- **One wording source.** `policy.py` and `limits.py` hold every label, note and number. The page
  reads them from `GET /api/meta`; the export and the CLI import them (review findings F1, F8).

## Where a change goes

- **A new source format** (say XBRL facts or a PDF exhibit): an adapter in `sources/` that returns
  `core.documents.Document` (text plus sections that are exact substrings), called from
  `services/ingest.py`. Nothing downstream changes.
- **A change to the verdict or status rule**: `core/policy.py` and its tests only.
- **A new output view**: a module that reads a `Run` and the wording in `core/policy.py`, as
  `services/export.py` does; serve it from `api.py`.
- **A new engine**: a class with `name`, `plan`, `assess`, `summarize` in `engines/`, chosen in
  `wiring.py`. The gate and the policy apply to it unchanged.

## The boundary

The backend computes every result: verified excerpts, verdicts, status and every count in
`Run.coverage`. The frontend collects input, polls, and draws the record with the wording from
`/api/meta`; it computes no verdict and no excerpt context. Requests are validated at the API:
the schema in `core/models.ThesisRequest`, extra URLs (public, distinct) in `api.py`, the ticker
against EDGAR. Refusals are 422 `{"error", "details": [{"field", "message"}]}`; EDGAR
unreachable is 503. Filing and page text reaches the model only as escaped data inside
`<passage>` elements, and the gate, not the model, decides what counts. Filings come only from
`www.sec.gov` and `data.sec.gov` (7 requests per second, 30 s, 40 MB, retries on 429/503);
extra pages go through the private-address-safe fetcher. The key stays in `.env`.

## Verification and operation

- `make verify`: image build, ruff, `node --check`, the offline tests, and `tests/smoke.py`
  against the live container (health, meta, static files, refusals, 404s; no internet).
- Offline tests use `tests/fakes.py`: the recorded NVIDIA 10-Q and 10-K, small synthetic
  filings, a scripted engine and a manual clock. `make fixtures` re-records EDGAR responses.
- `make up` serves `http://127.0.0.1:8766`; `make run ARGS='example'` runs the CLI;
  `make demo` runs the NVIDIA example live through the API and writes `results/demo-<UTC>.*`.
- Runs are stored in `data/runs/runs.sqlite` (`EVIDENCE_DESK_DATA_DIR`), gitignored.

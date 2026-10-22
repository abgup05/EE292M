# Architecture

Evidence Desk turns one research question into a decision brief whose every
factual finding links to an exact excerpt from a page the backend retrieved.
This file describes how the first slice is built; `../PROMPT.md` is the brief
it implements and `../README.md` is the plan.

## Stack

- Backend: Python 3.14, FastAPI, Pydantic, httpx, BeautifulSoup, SQLite (stdlib).
- Model backend: the `anthropic` SDK, optional; used only when `ANTHROPIC_API_KEY`
  is set. Otherwise a deterministic extractive synthesizer runs.
- Search backend: Brave Search API over httpx, optional (`BRAVE_SEARCH_API_KEY`).
- Frontend: static HTML, CSS and browser-native JavaScript; no build step.
- Container: Docker Compose, published on `127.0.0.1:8766` only. Dependencies
  install at image build from `docker/pyproject.toml` and `docker/uv.lock`.
- Everything runs through the `Makefile`; `make verify` is the gate.

## Layout

    Makefile                    build, test, lint, smoke, verify, demo, fixtures, lock
    docker/                     Dockerfile, compose.yaml, pyproject.toml, uv.lock
    .env.example                optional credentials (copy to .env, gitignored)
    src/app/urls.py             URL validation, private-address rejection, canonicalization
    src/app/fetch.py            bounded HTML retrieval with per-hop redirect validation
    src/app/extract.py          boilerplate removal, section locators, metadata, content hash
    src/app/models.py           request validation and the persisted run record types
    src/app/synthesize.py       Synthesizer interface, Draft, extractive backend
    src/app/claude.py           Claude backend (page text as data, JSON-schema output)
    src/app/search.py           Brave web discovery
    src/app/verify.py           citation verification gate
    src/app/pipeline.py         one run: plan, discover, retrieve, extract, synthesize, verify
    src/app/store.py            SQLite persistence for runs and stored source text
    src/app/export.py           Markdown brief
    src/app/api.py              HTTP API and static assets
    src/app/demo.py             live two-seed demonstration, writes results/
    src/app/record_fixtures.py  records the real seed pages under tests/fixtures
    src/web/                    index.html, app.js, styles.css
    tests/                      unit tests (offline), smoke.py (live container), fixtures/
    data/runs/                  SQLite database (gitignored)
    results/                    demo records (gitignored)

## Pipeline

`pipeline.execute_run` is the only place a run is advanced. Each stage is
injectable, so the tests run the real pipeline with a fake fetcher.

1. **Plan.** The synthesizer derives 3–6 subquestions with search queries. The
   original question, decision and scope are stored unchanged on the run. If
   the model backend fails, the template plan is used and the failure recorded.
2. **Discover.** Seed URLs first, then at most 30 search results if a provider
   is configured; otherwise a coverage limit says so. Candidates are
   canonicalized (`urls.canonicalize`) and deduplicated before any fetch.
3. **Retrieve.** `fetch.fetch_page` validates every hop: scheme, literal
   private addresses, DNS resolution to a private address, embedded
   credentials. 12 s timeout, 2 MB streamed cap, HTML content types only, at
   most 5 redirects. Retrieval stops at `source_budget` successes or the 180 s
   run limit, and both are recorded as coverage limits. Each failure becomes a
   `Source` with `extraction_status: failed` and an error; a duplicate canonical
   URL or identical content hash is recorded as a duplicate, not a new source.
4. **Extract.** `extract.extract_document` removes scripts, styles, navigation,
   headers, footers, asides and forms, keeps headings as section locators, and
   hashes the resulting text. The publication date comes from metadata
   (`article:published_time`, `citation_date`, `<time datetime>` and the like)
   or is absent; visible text is never parsed for a date. The exact text is
   stored per source in SQLite.
5. **Synthesize.** A `Synthesizer` returns a `Draft`: findings, evidence
   (source ID, excerpt, locator, stance), direct answer, disagreements,
   unknowns, next steps. The Claude backend sends page text inside `<source>`
   elements with a system prompt that names it as data, requests JSON against
   a schema and parses strictly; refusal, truncation or bad JSON raises and the
   pipeline falls back to the extractive backend, recording the error. The
   extractive backend scores exact sentences by keyword overlap and quotes
   them with `low` confidence and an explicit rationale.
6. **Verify.** `verify.verify_findings` keeps a finding only if at least one
   evidence record exists, names a stored source and is an exact substring of
   that source's stored text. Bad evidence is dropped, findings without any
   surviving evidence are moved to `unsupported_findings`, and single-source
   findings are flagged. The brief is built from verified findings only.

Status is `complete` only when at least six sources were extracted, 3–8
findings were verified, no finding was withheld and every subquestion was
answered; otherwise `partial` with the reasons appended to `coverage_limits`.
A run with no extractable source is `failed` with an error and no brief. A
run with no seed URLs and no search provider fails before planning, so no
model call is spent on a run that cannot fetch anything.

## Boundary

The backend owns fetching, credentials, extraction, provenance, synthesis and
verification. `POST /api/research` validates the request (lengths, 6–15
budget, distinct public URLs) and starts the run in a worker thread;
`GET /api/research/{id}` returns the persisted record, which contains only the
cited excerpts, not full page text; `GET /api/research/{id}/export.md` renders
the same record. The frontend validates for immediate feedback, polls, and
renders; it computes nothing. The boundary sits after verification so the
API, the export and the page all show the same checked findings.

## Verification and operation

- `make test`: offline unit tests, including the real pipeline with a fake
  fetcher, the Claude backend with a stub client, and the recorded fixture.
- `make smoke`: the live container over HTTP, without internet.
- `make lint`: ruff check and format, `node --check` for the script.
- `make verify`: build, lint, test, smoke.
- `make demo`: the real two-seed run; writes `results/demo-<UTC>.md`.
- `make fixtures`: records the real seed pages under `tests/fixtures/`.

Secrets live in `.env`; the compose file passes them to the container and
nothing logs them. Retrieved text is treated as data throughout: it is never
executed, never used as a prompt instruction, and only ever quoted.

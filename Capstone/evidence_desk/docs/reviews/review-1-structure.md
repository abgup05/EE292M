# Review 1: structure of the first version

- **Session:** Week 5A, "Order Enables Creativity" (review of the capstone's code)
- **Reviewed:** tag `capstone-v1` (commit `45ff843`), the generic research-brief version
- **Reviewer:** Claude Sonnet 5.5, in a fresh context with read-only tools. It did not write the code and was not shown the work logs, the homework files or any earlier conversation. There was no colleague review for this session.
- **Run on:** 17 November 2026
- **Checklist given to the reviewer:** the session's four items: the messaging, the organization, the design patterns and interfaces, one suggestion.

The reviewer's text follows unedited. My decision on each finding is in `Homework/Week 5/W5L1.md` and, for anything not built in, in one line of the README.

---

**Message as I understood it:** For a researcher or project lead deciding whether to proceed, revise or investigate further, Evidence Desk turns a question into a decision brief whose findings each cite a server-verified exact excerpt, and marks the brief PARTIAL when evidence is thin.

Template slots: the "who decides" slot is filled but generic (researcher or project lead, no concrete case). The "has this problem" slot is only implied. "We will know because" is missing from the README openings. Both openings state mechanisms (substring check, PARTIAL status) but no success evidence, such as a reviewer finding a bad citation or time saved. Capstone/README.md:46-48 gives success criteria, but they sit at the bottom.

**F1. [organization]** The complete/partial rule is spread over several files. The thresholds `MIN_FINDINGS`/`MAX_FINDINGS` are defined twice, in `pipeline.py` and `synthesize.py`. The "six sources" threshold is `MIN_COMPLETE_SOURCES` plus the literal word "six" in a message. The prompt at `claude.py:45` says "3 to 8", `pipeline.py:262` says "3 to 8", and `export.py:10-13` and `web/app.js:29-30` each carry their own status wording. Evidence: pipeline.py:35-37,252-262; synthesize.py:90-91; claude.py:45; app.js:29. Fix: put the rule and its constants in one `policy.py` (or on `RunStatus`) and import them everywhere.

**F2. [patterns]** `api.py` is the composition root but also contains policy. It imports concrete `ClaudeSynthesizer`, `fetch_page` and `searcher_from_env`, and chooses a backend from env vars. It also holds a `_FROM_ENV` sentinel and runs `app = create_app()` at import time, which opens a SQLite store as a side effect. Evidence: api.py:20-27,35-39,46,54,136. Fix: move env wiring into a `wiring.py` or `config.py`, and keep `api.py` as routes only.

**F3. [patterns]** Core record types import URL policy. `ResearchRequest` validators call `validate_public_url` and `canonicalize`, so `models` depends on `urls`, and `urls` is also used by `fetch`. Evidence: models.py:14,72-85. Fix: put the seed-URL validator in the API layer or a request-schema module, and keep `models.py` pure data.

**F4. [patterns]** The pipeline knows too much and mixes jobs. `_retrieve` handles budget, time limit, fetch, canonical dedup, extraction, content-hash dedup, persistence and building the `Source` record. `execute_run` also hard-codes the extractive fallback in two places. Evidence: pipeline.py:146-217,71,119,246. Fix: split retrieval/dedup into `retrieve.py`, and make fallback a `FallbackSynthesizer` decorator.

**F5. [organization]** Adding PDF has no single place to go. `fetch.py` accepts only `HTML_TYPES` and returns `html: str`. `pipeline.py:184` calls `extract_document(canonical, page.html)` directly. `Source.source_type` is a free string defaulting to "public_html" and is never branched on. Evidence: fetch.py:23,101-103; pipeline.py:184; models.py:107. Fix: add an `Extractor` registry keyed by content type, with `FetchedPage` carrying bytes plus content-type.

**F6. [patterns]** The `Fetcher`/`Searcher` type aliases and `Draft` live in `pipeline.py` and `synthesize.py`, so `api` and `claude` import pipeline and synthesize internals. `claude.py` depends on `synthesize.Draft`. `Synthesizer` mixes two roles (`plan` and `synthesize`) in one Protocol. Evidence: claude.py:26; pipeline.py:39-40; synthesize.py:107-119. Fix: create a `ports.py` holding `Fetcher`, `Searcher`, `Synthesizer` and `Draft`, and split `Planner` from `Synthesizer`.

**F7. [patterns]** `api.py` sets `run.status = "failed"` with a raw string instead of `RunStatus.failed`, and it does not set `finished_at`. Evidence: api.py:82. Fix: reuse `_finish` from the pipeline or a public `fail_run()`.

**F8. [organization]** There is no single "new output view" seam. `export.py` renders Markdown by hand with its own status notes, and `app.js` re-renders the same record separately. Evidence: export.py:9-14,25-107; app.js:29. Fix: have the API expose status labels and notes as data, and let both views read them.

**F9. [messaging]** The README opening states mechanisms, not a user-visible success measure. The reader cannot tell what "worth it" means. Evidence: evidence_desk/README.md:3-8; Capstone/README.md:3. Fix: add one sentence of the form "we will know it works because a reviewer can trace N of N findings to a passage and PARTIAL is shown when ...".

**F10. [patterns]** The extractive synthesizer has several jobs: keyword scoring, stance heuristics based on substring checks of subquestion text ("against", "unknown"), and building Drafts. Stance logic is coupled to the template wording of `plan()`, so editing a template string silently changes stance behaviour. Evidence: synthesize.py:187,233-241,155-158. Fix: give `Subquestion` a `kind` field and branch on that.

**Patterns in use:** Strategy/Protocol (`Synthesizer`, with the extractive and Claude implementations); dependency injection (`Fetcher`, `Searcher` and `clock` passed as callables); pipeline (`execute_run` as a sequence of stages); repository (`Store`); gatekeeper (`verify_findings`); fallback by exception handling, written inline; factory (`searcher_from_env` and `synthesizer_from_env`).

**One suggestion:** Extract a single `policy` module that owns the status rule, the finding and source limits and the status notes, and have the pipeline, the Claude prompt, the export and the frontend all read from it. The complete/partial rule is the product's central claim and is currently scattered across five files, so it can drift.

**What I could not judge from the repository alone:**

- Whether the measured demo numbers are real, since I did not read the demo record or run the app.
- Whether `make verify` is green, or whether the tests fail when results are wrong.
- Whether the intended reader's real decision is served, since there is no user evidence in the repository.

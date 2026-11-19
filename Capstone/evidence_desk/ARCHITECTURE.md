# Architecture

Evidence Desk (version 0.14.1) tests an equity analyst's thesis claims against the company's own SEC filings and shows,
per claim, the verbatim passages and figures that support or challenge it. A reviewer can accept or reject each
finding, save a thesis, run it again and see what moved. `../PROMPT.md` is the brief; `docs/reviews/` the review.

## Stack

- Python 3.14, FastAPI, Pydantic, httpx, BeautifulSoup, SQLite; `anthropic` for the optional model engine. No front-end build.
- Docker Compose, on `127.0.0.1:8766` only; dependencies install at image build. All through the `Makefile`.
- Two long-lived processes from one image: the app (`app`) and, since version 13, the watcher (`watch`, no port).

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
    src/app/core/facts.py       FactBook: values from XBRL company facts, placed by their dates; a quarter is 12 to 17 weeks, and a fiscal year is a year-long period an annual report reported; as of a date it reads only facts filed by then
    src/app/core/restatements.py   the restatement ledger: each metric and period whose value differs between filings, with both filings and the change; fact_models.py is its pure data (and the fact store's)
    src/app/core/claimtest.py   the claim compiler: claim text to a typed test of nine forms (held in one period or in each of several, alone or two joined by "and") with a canonical printed form, or the reason it is not numeric; compiles only when the test explains every word, and refuses a flow against an amount in a sentence that names no period (rule 3, applied to every reader's test); pure, no model
    src/app/core/claim_reading.py  a typed test as JSON, and the strict validation of a model reader's answer into it; pure
    src/app/core/measures.py    the measure catalogue: every measure a claim test can name, how a claim names it and how it is computed (a concept group of facts.CLAIM_GROUPS, or a formula), and a part's measures; pure
    src/app/core/claim_normal.py  one normal form for a claim test, so that two readers' writings of one test compare equal; pure
    src/app/core/claim_eval.py  evaluates a compiled claim against a FactBook (as of a date) with its arithmetic, and its history over the 10-K and 10-Q filing dates of five years; claim_test_models.py is its pure data
    src/app/core/tagged_figures.py  turns a filing's tagged breakdowns into figures a finding can cite (ids starting "tagged:") and chooses the ones offered; pure
    src/app/core/metrics.py     computes the metrics report from facts; metric_models.py is its pure data
    src/app/core/analysis_models.py, analysis_policy.py   the analysis's pure data (analytic, relevance, headline, corollary, odds, argument, sentence) and every number and sentence it uses
    src/app/core/relevance.py   which measures bear on each claim and why (test operand, cited, named, a part the filings tag), the headline figures (the sides of each claim's test), the reported figures tied to no claim; pure
    src/app/core/analytics.py   the analytics, each answering a stated question about a claim on the claim's own basis (quarters, or a fiscal year and what came since): a measure's path, a computed test's room and record, the walk from net income to free cash flow, a named part against the company, earnings quality; the AnalyticsProvider port and FactsProvider; pure
    src/app/core/persistence.py the odds a quarterly test keeps holding, by resampling its own past changes (seeded); pure
    src/app/core/corollaries.py a model's proposed implications read by the grammar and the typed form, computed and compared; the flag; pure
    src/app/core/analysis_audit.py   what a sentence of the argument may cite, and the audit of each (ids, evidence, numbers; a condition may state its own threshold); the lean flag; pure
    src/app/core/numcheck.py    the numeric check: each number a statement writes is in what it cites
    src/app/core/periods.py     the period check: each year or fiscal label a statement names is in its evidence (reported, never withheld); a company's fiscal calendar from its newest annual report; a planted wrong year, for measuring the check
    src/app/core/meaning.py     the meaning check's pure half: what the checker is shown, and applying its judgements
    src/app/core/events.py      the rules about 8-Ks: SEC's table of items with a category each, an item's opening sentences and the officer roles a 5.02 names, a claim's categories (lexicon and a name-and-leaving pattern), which 8-Ks a run reads, which postdate a finding, a claim's caution and note, the as-of block; event_models.py is its pure data
    src/app/core/watch_models.py, watch_policy.py   the standing watch's pure data (watch, job, triage, inbox item, what moved) and every number and sentence it uses
    src/app/core/triage.py      whether a new filing bears on each claim, by rule (8-K item categories, results, periodic reports and their changed paragraphs); an extension point, unwired; pure
    src/app/core/watch_report.py   what moved between a thesis's previous run and the one a filing caused, from core/compare; pure
    src/app/core/view_models.py the record types of the outside view and the market view: one result shape (id, value, unit, display, formula, inputs with source and dates, assumptions, one templated reading, data origin); pure data
    src/app/core/frames.py      SEC XBRL frames into a panel of measures by filer and year: rows placed by their dates, a concept group resolved filer by filer in the order of facts.GROUPS, which years a date admits; pure
    src/app/core/base_rates.py  a compiled claim test read on fiscal years; how often it held among a reference class decided in the base year (the company left out), how often it held again, the nearest cases; the spread of ten-year revenue growth of filers of a size; pure
    src/app/core/peers.py       the company's rank and percentile on a measure among its industry class, now and a year before, with its neighbours; pure
    src/app/core/thirteenf.py   a Form 13F information table into share positions; a company matched to an issuer by name; value ÷ shares as a quarter-end price, the unit read from the table; pure
    src/app/core/valuation.py   market value, enterprise value and multiples from a dated price and the facts filed by its date; balances of the newest balance sheet only; pure
    src/app/core/reverse_dcf.py the constant revenue growth at which a stated cash-flow model equals a target, and its sensitivity grid; pure
    src/app/core/price_series.py, reaction.py   daily closes read and cut at a date; a stock's move after a filing against an index and its own normal move; pure
    src/app/sources/frames.py   SEC frames and the company list by SIC code through the EDGAR client, kept under the disposable cache
    src/app/sources/thirteenf.py   a manager's 13F filings and tables through the EDGAR client, kept under the disposable cache; QuarterEndPrices, the price provider that reads SEC
    src/app/sources/prices.py   PriceProvider and the user's own price; daily closes from a file, a request or FRED's S&P 500 (only when asked), with a bounded, allow-listed fetch
    src/app/sources/edgar.py    SEC EDGAR adapter: ticker, filing selection, rate-limited fetch; recent_filings lists the watched forms in one request
    src/app/sources/filing.py   splits a 10-K/10-Q into Part and Item sections
    src/app/sources/current_report.py   splits an 8-K into one section per "Item N.NN" heading, the signature block and an exhibit index after the last item apart; its own parser version
    src/app/sources/http.py     bounded fetch of a public page, every redirect hop revalidated
    src/app/sources/urls.py, web.py, xbrl.py   public-URL validation; page text; the company-facts URL and body
    src/app/sources/ixbrl.py    reads a filing's own tagged numbers (inline XBRL: contexts, units, ix:nonFraction) with a targeted scan; what it cannot read is counted with its reason
    src/app/retrieval/chunk.py, bm25.py   sections into passages (exact substrings); Okapi BM25 scoring
    src/app/retrieval/search.py ranks a run's passages for one claim (top 8; at most 5 per source when there are several)
    src/app/engines/claude.py   Claude engine: builds each request and parses each answer
    src/app/engines/checker.py  the meaning checker: a second model judges each verified finding (NoChecker: none)
    src/app/engines/claim_reader.py  the model readers of each claim's test, one or two of different models, off by default (steps "read" and "read_2"); the prompt is built from the catalogue; a reading that breaks rule 3 is refused whatever period the model wrote
    src/app/engines/analyser.py the analysing model: the "propose" and "analyse" requests, their schemas (no unions) and the bounded parse of each answer (NoAnalyser: none)
    src/app/engines/transport.py, cassette.py   the Transport port and its API adapter; answers recorded once, replayed by key
    src/app/engines/extractive.py, fallback.py   deterministic engine, no stance; a primary engine falling back to it
    src/app/services/ingest.py  select, read (cache or EDGAR), parse, deduplicate, record the sources
    src/app/services/numbers.py, examples.py   XBRL facts in, metrics and offered figures out; the NVIDIA example thesis
    src/app/services/thesis_run.py  one run, stage by stage; the only place a run advances
    src/app/services/theses.py  saved theses: create, start a run of one, the latest comparison
    src/app/services/export.py  the Markdown brief, plain or with the reviewer's decisions
    src/app/services/filing_changes.py  selects a company's two latest filings of one form, reads them through the cache, compares them
    src/app/services/claim_changes.py   for a run: the filing before the newest annual and the newest quarterly report it read, the two comparisons, the ranking per claim; a comparison that cannot be made is a note, never an error
    src/app/services/breakdowns.py   the latest filing of a form, fetched and read into breakdowns
    src/app/services/events.py  a company's 8-Ks after its newest annual report: listed from the index, the ones the rule picks read through the cache and split; a document that cannot be read is a reason on its event, never an error; the item sections offered to a claim
    src/app/services/computed.py   for a run: compiles every claim, computes the compiled ones and their histories from the facts the run read, and counts the outcomes in the verdicts after the summary; returns the compiled tests and breakdowns for the analysis
    src/app/sources/reference.py   the reference pack shipped in src/app/reference (SEC frames for filers that ever reported $100 million of revenue, with their industry codes; three managers' 13F positions): read first, EDGAR only for what it lacks; build_reference.py builds it (`make reference-pack`, `docs/reference-pack.md`)
    src/app/services/view_providers.py   the outside view and the market view as analytics providers of a run: which of their results a run keeps, the question each answers, the claims each is tied to, each provider's time budget; run_providers
    src/app/services/analysis.py   for a run: relevance, analytics from every provider, odds, headline; the two model steps with the corollaries and the audit, and what became of each; what the analysing model is shown
    src/app/services/restatements.py   a company's restatement ledger outside a run, as of a date when given
    src/app/services/outside_view.py   one company and one claim: the frames read, the two reference classes, the base rates and the standings
    src/app/services/market_view.py    one company: the price from a provider, the valuation, the reverse DCF beside what the frames say of filers its size and its industry's margin, the reactions to 8-Ks
    src/app/services/view_analytics.py   outside_analytics and market_analytics: both views as a flat list in the one analytic shape a provider list expects; nothing computed
    src/app/services/tagged_figures.py   for a run that asks: the tags of the newest annual and quarterly report it read, as figures; a filing that cannot be read is a reason, never an error
    src/app/watch/store.py      the watch's tables: WatchStore (watches, seen filings, jobs, inbox, in the record) and WatchStatus (heartbeat and checks, in the cache)
    src/app/watch/service.py    start and stop watching; the Watcher: a cycle polls each watched company once, queues a job per new (thesis, filing), and works each job (triage, then a run or a waiting run, then the inbox item); EXTRA_TRIAGE_RULES
    src/app/watch/views.py, routes.py   the watch list and the watcher's health, shared by the API and `make watch-status`; the watch's HTTP routes, added by create_app
    src/app/watch/__main__.py   the watcher process: `python -m app.watch [run | once | status]`
    src/app/store.py            SQLite: Store (the record), FilingCache and FactStore (both disposable)
    src/app/backup.py           backs up the record; checks that the newest backup restores
    src/app/wiring.py           composition root: reads the environment, builds collaborators
    src/app/api.py              HTTP routes and static files
    src/app/analysis_routes.py  the outside view's and the market view's routes, added by create_app
    src/app/cli.py              command line onto the same use case
    src/app/demo.py, probe.py, figures.py, changes.py, breakdowns.py, record_fixtures.py, record_facts.py   live demo; live parser check; live check of the reported figures, company by company; the filing comparison and the tagged breakdowns from the command line; fixture recorders
    src/app/restatements.py, facts_load.py   a company's restatement ledger as text (`make restatements`); load companies' facts into the fact store (`make facts-load`)
    src/app/measures_probe.py   live check of the catalogue on the eight probe companies: each measure's newest fiscal year as a claim test computes it, and the parts each newest 10-K tags (`make measures-probe`)
    src/app/outside.py, market.py, market_probe.py, market_check.py, record_market.py   the outside view and the market view as text (`make outside-view`, `make market-view`); the live probe of every outside source (`make market-probe`); both views on the eight probe companies (`make market-check`); the recorder of their fixtures (`make fixtures-market`)
    src/app/events.py, events_probe.py   a company's 8-Ks since its annual report as text (`make events`); live check of the 8-K splitter on the eight probe companies (`make events-probe`)
    src/app/evaluation/golden.py, corpus.py   load and validate the golden set; the filings it is measured on, pinned by hash
    src/app/evaluation/retrieval_eval.py  scores where the right passage ranks; the variant registry
    src/app/evaluation/cli.py   `python -m app.evaluation`: validate, run, fetch, pin, show, plan, generate, mismatch
    src/app/evaluation/companies.py, planning.py, generation_eval.py   pinned figures, planned queries, answer scoring
    src/app/evaluation/mismatch_eval.py   plants real quotes under statements they do not belong to and scores what the meaning check says
    src/app/evaluation/reading_sheet.py   lays the golden cases out for a person to read (`make golden-sheet`)
    src/app/evaluation/claim_categories.py   scores the claim-category rule on eval/claim-categories.json (`make event-categories`)
    src/app/evaluation/claim_tests.py   scores the claim compiler on eval/claim-tests.json (`make claim-labels`; the held-out set at most twice)
    src/app/evaluation/claim_oracle.py   the expected results of eval/claim-results.json from the raw facts, by a route that never calls the evaluator (`make claim-results-key`)
    src/app/evaluation/compiler_vs_model.py   the compiler and a model given the same figure lines, scored on eval/claim-results.json (`make eval ARGS='compiler-vs-model'`)
    src/app/evaluation/claim_readers.py   each reader's normal form of each claim of a set, the agreeing pairs and the counting rule's conclusion, one row per claim for a judge; and the judge's file of the readings that would count (`make eval ARGS='claim-readers --set FILE [--judge]'`)
    src/web/                    index.html, app.js, styles.css (one layout, two themes: docs/design.md), specimen.html (every component on made-up data, served at /specimen.html), sample-run.json, sample-run-events.json (a live run, copied unedited), sample-synthetic.json, sample-changes.json, sample-run-changes.json, sample-run-tagged.json, sample-breakdowns.json, sample-breakdowns-gap.json (synthetic), sample-inbox.json, sample-inbox-page-2.json, sample-inbox-watches.json, sample-inbox-health.json, sample-inbox-meta.json (the watch's example payloads of docs/examples/v13, copied unedited by `make sample-inbox`), sample-computed.json, sample-as-of.json, sample-restatements.json, sample-readers.json (version 14's example run, as-of run, restatement ledger and run with two model readers of docs/examples/v14, copied unedited by `make sample-v14`), sample-run-live.json (a live run with three claim readers, copied unedited)
    eval/                       the golden set, its pinned filings, cache/ and results/; README.md
    tests/                      offline tests, fakes.py (EDGAR, pages, engine, clock), smoke.py; replay_run.py, golden_run.py, speed_run.py; lookahead.py (the no-lookahead checks); examples_v14.py (`make examples`, docs/examples/v14; the example with two model readers only once its reads are recorded in eval/cassettes/claim-readers); examples_analysis.py (`make examples-analysis`, docs/examples/analysis) and record_analysis.py (`make record-analysis`, the only analysis code that reaches the API, capped)
    tests/live_walk.py          the live end-to-end walk over HTTP; tests/golden/ the tripwire and replayed verdicts
    tests/market_examples.py    `make market-examples`: docs/examples/market from the recorded frames, facts and 13F tables, offline; tests/outside_fakes.py a hand-made panel of frames
    tests/watch_examples.py, watch_replay.py, watch_contention.py   the watch's example payloads (docs/examples/v13); the live replay of a year of filings against eval/watch-replay-nvda.json; a run timed alone and beside a watcher
    uitests/                    browser tests: the rendered DOM of the sample runs, the sample filing comparison and breakdowns against their JSON; test_events_dom.py the 8-Ks and the as-of line; test_run_events_dom.py the live-run sample and the time line; keys.html + test_keys_dom.py the keys and the themes; test_inbox_dom.py the recorded inbox, and watch.html (the page's code for every answer of the watch routes, with `fetch` stood in for)

## Storage: the record, the cache and the fact store

Three SQLite files under the data directory (`EVIDENCE_DESK_DATA_DIR`; `data/`, gitignored), all in `store.py`.

- **The record**, `data/record/record.sqlite`, class `Store`: `runs` (each run as JSON), `decisions` (one per run and
  finding) and `theses` (saved requests and their run ids). Nothing can rebuild it: a later run meets a different
  EDGAR, perhaps a different parser and model, and a decision exists nowhere else. It is the only file backed up.
  Every field a version adds to the run has a default, so a run recorded before it loads: version 12 added
  `Run.timeline` and `Run.as_of`, `Claim.categories`, `caution` and `event_note`, and `Finding.predated_by`
  (`core/event_models.py`); `tests/test_events_run.py` loads a run recorded by 0.11.1.
- **The cache**, `data/cache/filings.sqlite`, class `FilingCache`: `texts`, each document's text once, keyed by its
  SHA-256; `filings`, an index from (accession, parser version) to that hash, the publisher, section spans and fetch
  time. An 8-K is indexed under the 8-K splitter's own version (`sources/current_report.parser_version`), so a change
  to it invalidates cached 8-Ks and no periodic report. The record holds only the hash, never the text.
- **Backup.** `make backup` copies the record with SQLite's online backup (safe while the app runs) to
  `backups/record-<UTC>.sqlite` with a `.sha256`, and writes `backups/decisions-<UTC>.jsonl`, one line per decision.
  `make restore-check` verifies the newest backup's hash, restores it to a temporary directory and compares it with
  the live record: every column of every stored run, decision and thesis, so a record that no longer parses is
  compared too, and so is the link from a run to its thesis. It then fails if any record in the backup cannot be read by this version. PASS with the backup's age,
  FAIL with the first difference, or (from 0.14.1) BEHIND, exit code 2, when every difference is a row written after
  the second the backup was taken: a row the backup lacks whose creation time is later, or a row both hold that differs
  and whose time of last change is later (decisions, watches, watch jobs, inbox items; runs and theses keep no such
  time, so one that changed still fails). `make backup-status` says in one line what was made or changed since the newest
  backup; `make up` prints it. `make two-writers` has the app and a one-off container write one scratch record at
  once (`EVIDENCE_DESK_DATA_DIR`, overridden for that target only) and checks its integrity and every row.
- **Deleting the cache loses no record, and one thing a record points at.** The next run fetches the filings from EDGAR, parses them again and refills it. But the stored text that an old run's excerpts are offsets into lives only in the cache. With it gone, the excerpts are still in the record as text; checking that they are spans of the stored text again needs the same filing fetched and parsed by the parser that produced it.
  Runs in the record are unchanged. A version 3 database at `data/runs/runs.sqlite` is not read.
- **The standing watch's tables** (version 13, `watch/store.py`, created by `Store.extend` when the app or the watcher
  first opens the record, so a record from before has none and loads unchanged). In the record: `watches` (one per
  watched thesis), `watch_seen` (each filing a watch has seen), `watch_jobs` (unique per thesis and accession; queued,
  running, done or failed, with attempts, a lease and the error) and `inbox`. They are backed up and compared by
  `restore-check` like the other tables. In the cache, because they change every cycle and are worth nothing
  tomorrow: `watcher_beats` (the heartbeat) and `watch_checks` (each company's last and next check and error).
- **The fact store**, `data/facts/facts.sqlite`, class `FactStore`: `companies` (CIK, ticker, name, SIC code and its
  description from the submissions index, how many facts were kept and skipped, the SHA-256 of the body) and `facts`
  (every us-gaap fact: concept, unit, start, end, value, and the accession, form and filing date of the filing that
  reported it, with XBRL's `fy`, `fp` and `frame` kept as given). A run keeps the facts it reads there, and so does
  the ledger route; `make facts-load TICKERS="..."` loads companies outside a run. A company is replaced whole when
  its body changes. Disposable: every row comes again from EDGAR (`docs/facts.md`). Nothing reads it to answer a run
  yet; it is where peer comparisons would start.
- Version 14 added `ThesisRequest.as_of`, `AsOf.requested` and `requested_note`, `Claim.computed` and
  `compile_note`, and four `Coverage` counts, each with a default, so runs recorded before load.

## The pipeline (`services/thesis_run.execute_run`)

A run may be **as of a date** (`ThesisRequest.as_of`): it then reads the newest 10-K filed on or before the date,
the 10-Qs and 8-Ks filed after it up to the date, and only the XBRL facts filed by the date (`FactBook(as_of=)`);
nothing filed later reaches any stage, which `tests/lookahead.py` checks (`docs/facts.md`).

1. **Resolve.** `FilingSource.company` maps the ticker to CIK and name; the API and the CLI do it before a run starts,
   so an unknown ticker is refused, not a failed run.
2. **Ingest** (`services/ingest`). The newest 10-K and the 10-Qs filed after it, newest first, then any extra pages. A
   filing is looked up in the cache by accession and `PARSER_VERSION` (the SHA-256 of `sources/filing.py` plus the
   BeautifulSoup version, so editing the parser invalidates every cached filing); a hit is rebuilt from the cached
   text and not fetched. A miss is fetched within EDGAR's limits, parsed into Items and indexed. Extra pages are
   always fetched: a page can change. A failure is recorded on its `Source` and the others continue. Identical content
   is read once. With no readable source the run ends `failed` with no brief.
3. **Events** (`services/events`, rules in `core/events`). Every 8-K and 8-K/A filed after the newest annual report
   the run read is listed from EDGAR's submissions index (the one `periodic_filings` fetched, reused for 60 seconds,
   so no extra request). Read through the cache (by accession and the 8-K splitter's own version) and split into
   items: every 8-K filed after the newest periodic report, and those with an item of a substantive category since
   the annual report, newest first, at most `MAX_EVENTS_READ` (8). Each one listed is counted as read, failed, capped,
   out of time or listed from the index only, and a failure is a reason on the event, never an error of the run. The
   run records the timeline and an as-of block (the newest filing read and its date, the newest periodic report, the
   days to the run's start, the counts). A claim's categories are set by rule when the claim is made (`docs/events.md`).
4. **Numbers** (`services/numbers`). The company's XBRL facts become a metrics report on the run; the newest quarters
   and years of a few key metrics are the figures offered to the engine. A failure is a coverage limit, never the end
   of the run, but the run is then partial. The facts are never chunked or quoted. When the request has
   `tagged_figures` (off by default), `services/tagged_figures` also reads the inline XBRL of the newest annual and
   quarterly report the run read and adds up to `MAX_TAGGED_FIGURES_OFFERED` (40) figures after these, with ids
   starting `tagged:`; they are recorded with the run's other metrics, so every later stage treats a citation of one
   like any other. They change the assessment prompts, which is why a run must ask for them (`docs/tagged-figures.md`).
   Then **compute** (`services/computed`): every claim is compiled (`core/claimtest`); a compiled claim is evaluated
   from the run's FactBook with its arithmetic, and given its history as of each 10-K and 10-Q filing date of the
   last five years from the same facts, with no extra request; a share of revenue reads the newest filings' tagged
   breakdowns from the cache, for the newest period or the fiscal year or quarter the claim names. A test held in
   each of several periods, or two joined by "and", is computed part by part and holds only when every part does. A claim that does not compile gets `compile_note`. A claim compiles only when its
   test explains every content word of the sentence. No engine is asked anything. A claim test may name any
   measure of the catalogue (`core/measures`), not only the panel's; a part's figure (a segment's revenue or
   operating income) reads the newest filings with the claim-only breakdowns, cached apart. With model readers
   on (`EVIDENCE_DESK_CLAIM_READER=model` or `models`, off by default) each claim is also read by one or two
   models (`engines/claim_reader`, steps `read` and `read_2`, through the engine's transport or cassette), each
   answer validated into the same type (`core/claim_reading`); every reading is put in one normal form
   (`core/claim_normal`) and a test counts when at least two readers reach the same one, with a third reader's
   different test shown as a dissent (`policy.reading_agreement`). With the grammar alone a compiled test counts
   and the run says that is one reader (`Run.claim_reading_rule`; `docs/claim-tests.md`).
5. **Plan.** The engine writes up to four queries per claim.
6. **Retrieve.** All passages of the run go into one BM25 index; each claim is searched with its own text and queries.
   8-K sections never enter the index: a claim with a substantive category is also offered up to
   `EVENT_PASSAGES_PER_CLAIM` (2) item sections of its categories from 8-Ks read, newest first, as passages marked
   with their form and filing date; an 8-K becomes a source of the run only when one of its sections is offered. The
   Claude engine is told about newer filings only in a prompt that carries such a passage.
7. **Assess.** One engine call per claim returns findings with stances, quotes and cited figure ids. Up to
   `MAX_CONCURRENT_ASSESSMENTS` (3) calls run at once; claims start and pass the gate in claim order, so the record
   (ids included) is the one a sequential run gives. A failed call falls back for that claim only.
8. **Verify.** `gate.gate_claim` locates each quote inside a passage offered for its claim (the one it names, else
   another offered passage of the same source, whose locator the excerpt then carries) in the stored text
   (`FilingCache.source_texts`) and keeps the stored span; a quote found only elsewhere in the source, or one that
   includes a heading line the parser wrote, is rejected. A quote must also be whole (`gate.is_whole`): an
   occurrence that begins or ends inside a word, or inside a number at a decimal point or a thousands separator, is
   passed over, and a later whole occurrence is still found. A cited figure must have been offered; `core/numcheck`
   requires every number a statement writes to appear in its excerpts or figures (a number glued to B, bn, M or mm
   is read as an amount; a percentage governed by a word of decline does not match a cited figure the backend
   computed and printed with a plus sign). A finding with no surviving quote
   or figure, or an unmatched number, is withheld and counted. A verified finding's reason, a claim's commentary,
   the unknowns and the next steps are checked the same way: a reason or commentary with an unmatched number is
   replaced by a note, an unknown or next step is dropped; a model summary with an unmatched number is replaced by
   the template. Every quote is counted as found or rejected (`quotes_found + quotes_rejected == quotes_offered`).
9. **Check meaning** (when a `Checker` is configured). In the worker that assessed the claim, right after its gate,
   one request per claim shows a second model (`ANTHROPIC_CHECK_MODEL`, default `claude-haiku-5-5`) each verified
   finding's statement, stance, excerpts and cited figures, never the engine's rationale or confidence
   (`core/meaning.check_items`). "supported" marks the finding passed, "partly" keeps it marked partly, and
   "not_supported" withholds it with the checker's reason and drops its evidence. A checker failure leaves that
   claim's findings unchecked, adds one error line and a coverage limit, and never fails the run; neither "partly"
   nor a failed check makes a run partial. A checker on the engine's own model is recorded as a coverage limit.
   Then `core/periods.check_periods` reads the years each verified finding's statement names and looks for each
   in the finding's excerpts, its cited figures and the period of each filing quoted, with the company's fiscal
   calendar (read with the facts, `NumbersResult.calendar`). The result is recorded on the finding and counted in
   `Run.coverage`. It withholds nothing and changes no verdict or status (`docs/period-check.md`).
10. **Decide.** `policy.claim_verdict` sets each verdict from verified findings only, and after the summary from the
   claim's computed test too (a test that holds counts as support, one that fails as a challenge, one that cannot be
   computed as nothing), so the summariser is shown the verdicts of the findings alone and a recorded request stays
   as recorded. Then a template summary is written again from the final verdicts, and a model's summary is kept and
   followed by `Brief.verdicts_after_summary`, a line written by `policy.verdicts_after_summary` that names each
   claim whose verdict the computed tests set or changed (0.14.1). A computed test compares stored values; its
   arithmetic line and margin are printed with as many decimals as make the printed comparison the one made
   (`claim_eval.compared_sides`); a finding that rests on
   reported figures alone counts as its stance only when the meaning check passed it, and as context otherwise
   (`Finding.counted_as`, `count_note`). `policy.run_status` sets complete, partial (with each reason and its
   denominator) or failed; a filing mostly outside numbered Items (`Source.item_coverage` below
   `MIN_ITEM_COVERAGE`) or unreadable XBRL facts make a run partial. `policy.provenance_note` writes the run's
   provenance from the sources it read (`Brief.provenance_note`). The 300-second limit is checked before every
   source and each round of claims; a claim not started in time is reported as not assessed. Then, reported and
   never withheld, changing no verdict or status: a verified finding gets `predated_by` for each 8-K filed after every
   filing it cites whose item is of a category of its claim; a claim whose supporting or challenging finding is
   predated gets a `caution`; a claim of a substantive category gets an `event_note` saying what the 8-Ks since the
   annual report do and do not report on it ("No 8-K filed since ... reports ...; anything later is not in the
   record"), never that the claim is false.
11. **Analyse** (version 0.14.2, `services/analysis.analyse_run`, `docs/analysis.md`). After the verdicts are final,
   while the stage stays `verifying` (its detail says what is being analysed). Code decides which measures bear
   on each claim (`core/relevance`: test operand, cited by a finding, named in the claim, or a part of the
   business the claim names as the newest filings tag it) and the headline: the figures the claims are about.
   The parts are read once per run from the tags the cache keeps or the HTML the run fetched, never by a
   fetch (`ingest` keeps a fetched filing's HTML until then). Every analytic (`core/analytics`, one
   `AnalyticsProvider`, "facts") answers a stated question about a claim on the claim's own basis, with its
   id, formula, inputs with their filings and a templated reading; none is computed for the thesis at large,
   and one the facts cannot give stays on the record with why. A run that can reach EDGAR also asks two
   providers that read it (`services/view_providers`): the outside view (the base rate of each computed claim's
   test among other filers, the company's standing in its industry) and the market view (price to earnings, the
   free cash flow yield and the growth the last 13F price implies, about the company as a whole). Each has a
   time budget (20 s and 15 s); one that runs out, or that EDGAR does not answer, is named in
   `Run.analysis.providers_failed` with its reason and the run carries on. Both honour `as_of`. Both read the
   reference pack shipped with the app first (`sources/reference`), so a host with an empty cache has them at
   once, and both are started, with the request for the corollaries, as soon as the claims are computed
   (`start_background`), so that they run beside the assessments. `Run.timings` records how long each stage
   and each of these took. The odds a quarterly test holds in each of the
   next four quarters (`core/persistence`, 10,000 resampled paths, seed 20261118). Then, with an analysing
   model (`engines/analyser`, `ANTHROPIC_ANALYSIS_MODEL`, default the engine's model, the engine's transport
   or cassette): one `propose` request for every claim's corollaries, read by the grammar and the proposer's
   typed form and computed by code (`core/corollaries`), then the argument: one `analyse` request
   per claim, up to three at once, and one `conclude` request for the thesis, which is shown the claims'
   audited arguments (4,000 output tokens and 60 seconds each). Every sentence is `{text, cites}`, audited by
   code (`core/analysis_audit`: ids, evidence, numbers by `core/numcheck`); an unverified sentence is kept
   and marked. A claim whose request fails has no argument and says why, and the others stand.
   `Run.analysis` records what became of each step (`not_asked`, `failed`, `partial`, `answered`, and how
   many claims were answered); whenever the record holds less than a model's analysis (no
   model, no time, a failed request, a cassette without the answer) it says why and `run.errors` gets one
   line. It never changes a verdict or the status. The watcher's runs get no analysing model.

Saves: the run is saved at each stage, after each source and after each claim. A save while the status is `running`
is a progress save, not synced to disk on its own; the final save is synced and carries those before it. A power cut
can lose an unfinished run, never corrupt the file. `new_run(request, thesis_id)` makes the running record; `thesis_id`
ties it to a saved thesis.

After a run, outside `execute_run`: **review** (`core/review.build_review`): a reviewer accepts or rejects a verified
finding; a claim's reviewed verdict is `policy.claim_verdict` over its accepted findings and its computed test, so
reviewer and engine follow one rule; other decisions are ignored; the review is computed per request, not stored. **Compare**
(`core/compare.compare_runs`): two runs of one thesis, claims matched by text: verdict moved or not, excerpts added and
dropped, filings new or gone.

## The watcher (version 13, `docs/watch.md`)

A second process (`python -m app.watch`, the `watch` service of the compose file, started by `make up`) shares the
data directory with the app. Each cycle (every `EVIDENCE_DESK_WATCH_INTERVAL_SECONDS`, default 900, floor 300) it:

1. **Polls.** For each watched company, once however many theses watch it, one request lists its 10-K, 10-Q, 8-K and
   8-K/A filings (`EdgarClient.recent_filings`, same client and rate limit as a run). A filing a watch has not seen is
   marked seen and a job queued, in one transaction. On the first watch, what is listed is marked seen with no job.
2. **Settles** jobs whose 900-second lease ran out (their worker died): queued again, or failed after four attempts.
3. **Works** each ready job, claimed by one atomic `UPDATE ... RETURNING`: `core/triage` decides which claims the filing
   bears on. None: an inbox item "seen, not relevant", no run. Some: with policy `auto` and a slot under the daily cap,
   the thesis is run (`services/theses`, `thesis_run.execute_run`, as the run button does) and `core/watch_report`
   compares it with the previous finished run; otherwise the item holds a run waiting for its owner. A job that
   raises is retried after 60, 300 and 1,800 seconds, then stays failed with its reason.
4. **Beats.** The cycle's counts and time go to the cache; `GET /api/watch/health` is alive while the newest beat is
   at most two intervals and a minute old.

Nothing new is installed: the queue is a SQLite table with an atomic claim and a lease, and the loop is the standard
library. The app starts a waiting run in its own executor, like any run, and writes what moved into the item when it
ends.

## The outside view and the market view (not part of a run yet)

Two families of results that need data beyond the one company (`docs/outside-view.md`,
`docs/market-view.md`). They are computed on demand, stored nowhere, and not called by
`execute_run`: wiring them into a run is a later step, for which each family has an adapter
(`services/view_analytics.outside_analytics`, `market_analytics`) returning its results in the
analytic shape `{id, provider, data_origin, kind, label, claim_ids, measure, period, value, unit,
display, formula, inputs[{ref_kind, id, label, value, display, accession, form, filed}], reading,
reading_origin: "code", available, note}`.

- **Outside view** (`data_origin: sec_frames`): the claim is compiled by `core/claimtest`, read on
  fiscal years, and counted over a reference class from SEC's annual frames; the company's standing
  among its SIC code's filers. Frames carry no filing date, so as of a date only periods that ended
  a year before it are read.
- **Market view** (`data_origin: market_prices`): a `PriceProvider` gives one dated price (the
  newest quarter-end price public from a Form 13F by the date, or the user's own); the facts are
  cut at the price's date; `core/valuation` and `core/reverse_dcf` do the arithmetic; the frames
  give the comparisons. A reaction to an 8-K takes daily closes from the request or a file.
- Routes, read-only, every input bounded by the schema: `GET /api/companies/{ticker}/outside`,
  `/market`, `/analytics`, `POST /api/companies/{ticker}/market/reactions`. Payloads:
  `docs/examples/market/`.
- Outside hosts: `data.sec.gov` and `www.sec.gov` through the EDGAR client, and
  `fred.stlouisfed.org` only when a request asks for the S&P 500 as an index. Bodies are kept under
  `data/cache/frames`, `data/cache/13f` and `data/cache/prices`, all disposable.

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
  /api/meta`; the export and the CLI import them (review findings F1, F8). The watch keeps its own in
  `core/watch_policy.py`, served by `GET /api/watch/meta`, so that the contract test of `limits.py` is not widened.

New routes in `api.py`: `GET /api/runs/{id}/review`; `PUT /api/runs/{id}/findings/{fid}/decision` (404 unknown run or
finding, 409 while running, 422 withheld finding); `GET .../export.md?reviewed=true`; `/api/theses`, `/api/theses/{id}`,
`POST /api/theses/{id}/runs`, `GET /api/theses/{id}/changes`. Version 13, in `watch/routes.py` (added by one call at
the end of `create_app`, which takes an injectable `wall_clock`): `PUT` and `DELETE /api/theses/{id}/watch`,
`GET /api/watch`, `/api/watch/health`, `/api/watch/meta`, `GET /api/inbox`, `/api/inbox/{id}`, `POST /api/inbox/read`,
`POST /api/inbox/{id}/run`. Payloads and every field: `docs/examples/v13/`.

## Where a change goes

- **A new source format** (XBRL facts, a PDF exhibit): an adapter in `sources/` returning `core.documents.Document`
  (text plus sections that are exact substrings), called from `services/ingest.py`. Nothing downstream changes.
- **A change to the verdict or status rule**: `core/policy.py` and its tests only.
- **A new output view**: a module that reads a `Run` (and a `Review` if it shows decisions) and the wording in
  `core/policy.py`, as `services/export.py` does; serve it from `api.py`.
- **A new analytic**: a function in `core/analytics.py` returning an `Analytic` with the question it answers,
  called from `FactsProvider` for the claims it bears on (`BEARS_ON`), with a test whose expected value comes
  from the definition (`tests/test_analytics.py`) and, where the facts allow, from a company's raw facts
  (`tests/test_analytics_recorded.py`). If no claim would ask its question, it does not belong. The count in
  the tripwire's coverage stage moves: `make golden-baseline`, `make examples-analysis`, read both diffs.
  Analytics from another source: an `AnalyticsProvider` added in `services/view_providers.run_providers`,
  with its own `provider`, `data_origin` and, if it reads a network, `budget_seconds`; which of the outside
  or market view's results a run keeps is decided there too.
- **A change to the analysis prompts or schemas** (`engines/analyser.py`): the recorded `propose` and
  `analyse` answers no longer match, and a replay falls back to the computed analysis. `make record-analysis`
  (API), read the answers, then `make examples-analysis` and `make golden-baseline`.
- **A new metric**: its computation in `core/metrics.py` (writing the formula out); if the engine should see it, its
  key in `services/numbers.FIGURE_KEYS`. The gate and numeric check apply unchanged; re-baseline the tripwire.
- **A prompt or schema change** (`engines/claude.py`): the tripwire's `prompts` stage moves and the replay finds no
  answers. The checker's prompt (`engines/checker.py`) is not in the `prompts` stage: a change to it shows only as
  pending `check` requests in the replay. Re-record the cassette (`docs/cassettes.md`), review the answers, `make golden-baseline`, read the diff of
  `tests/golden/`, commit together.
- **A new engine**: a class with `name`, `plan`, `assess`, `summarize` in `engines/`, chosen in `wiring.py`. The gate
  and the policy apply to it unchanged.
- **A schema change to the record** (`RECORD_SCHEMA` in `store.py`): it only creates missing tables and there is no
  migration code, so write the migration with the change. `make backup` first, `make restore-check` after; the app
  skips a record that no longer validates with a warning, and `restore-check` fails on one, naming it. The cache needs no care: delete it.
- **A new kind of reviewer decision**: a value in `DecisionValue` (`core/models.py`), its label in
  `policy.DECISION_LABELS`, its effect in `core/review.build_review`, then the page and export. Decisions are stored
  as JSON, so no new column. Back up first.
- **A new retrieval variant**: a `Variant` in `VARIANTS` in `evaluation/retrieval_eval.py`. Measure it on the golden
  set (`make eval ARGS='run --variant NAME'`) before it is wired into `retrieval/search.py` or the pipeline.
- **A change to how two filings are compared** (the threshold for "reworded", what counts as a table row): `core/filing_diff.py`, whose constants sit at its top, with `tests/test_filing_diff.py`. The comparison is separate from a thesis run: `GET /api/companies/{ticker}/changes` and `make changes` both call `services/filing_changes.filing_changes`. Read the pairs a new threshold adds before keeping it (`docs/filing-changes.md`).
- **A change to which changed paragraphs are listed under a claim** (how many words must be shared, how many are listed, how repeats are folded): `core/claim_changes.py`, whose two constants sit at its top, with `tests/test_claim_changes.py`. It is computed on demand by `GET /api/runs/{id}/changes` from the filings the run read and is not part of the run record, so the tripwire does not move. After a change, run `make sample-run-changes` and read what each claim now lists (`docs/claim-changes.md`).
- **A change to how reported periods are placed** (the length of a quarter, what is a fiscal year, another revenue concept): `core/facts.py` and `core/metrics.py`. Run `make figures` on the eight probe companies before and after and read which lines moved (`docs/evidence/figures-eight-companies.md`); a change that moves a company's figures invalidates the recorded answers of its golden cases.
- **A change to what counts as a year, or to what evidence carries one**: `core/periods.py`, with `tests/test_periods.py`. What is a year and what is a quantity is decided once, in `core/numcheck.py`, and the period check reads it from there. Measure before and after with the checked evaluation, which also plants wrong years (`eval/README.md`); a rule that starts withholding findings is a change to `core/policy.py` and to every recorded verdict.
- **A change to which tagged figures a run offers** (the cap, the order, another breakdown): `core/tagged_figures.py` and `MAX_TAGGED_FIGURES_OFFERED` in `core/limits.py`, with `tests/test_tagged_figures.py`. It changes the prompts of every run that asks for them, so `demo/cassettes/nvda-example-tagged` must be recorded again.
- **A change to the claim compiler** (a phrase, a form, a metric): `core/claimtest.py` with `tests/test_claimtest.py`
  and `tests/test_whole_sentence.py`; a phrase the grammar reads must also be among the words its test explains
  (`_explaining`), or the whole-sentence rule refuses the claim. A new form or measure also goes into the model
  parser's validation (`core/claim_reading.py`) and prompt (`engines/claim_reader.py`), the normal form
  (`core/claim_normal.py`), and golden cases worked out by the oracle (`evaluation/claim_oracle.py`);
  `tests/test_forms.py` shows the pattern.
  Score `make claim-labels` before and after on the development labels; the held-out labels have been scored twice
  and may not be scored again. A change to how a test is computed: `core/claim_eval.py`, checked against
  `eval/claim-results.json` (`tests/test_claim_results.py`), whose expected values come from
  `evaluation/claim_oracle.py`; never edit an expected value. Either moves verdicts: `make golden-baseline` and
  `make examples`, and read both diffs.
- **A change to which facts a date admits**: `facts.filed_by` in `core/facts.py`. `tests/test_facts_as_of.py` checks
  the metrics on every periodic filing date of three companies against a payload pruned independently.
- **A change to the 8-K rules** (an item's category, what counts as substantive, the claim lexicon, how many 8-Ks are
  read or offered): `core/events.py` and the three `EVENT`/`MAX_EVENTS_READ` limits in `core/limits.py`, with
  `tests/test_events.py`. A change to the claim lexicon is scored with `make event-categories` on the labels in
  `eval/claim-categories.json`, before and after; change a label only on purpose and say why. A change to the 8-K
  splitter (`sources/current_report.py`) is measured with `make events-probe` on the eight probe companies, before
  and after (`docs/events.md`). An 8-K offered to a claim changes its prompt: if a claim of the example thesis ever
  gains a category, `demo/cassettes/nvda-example*` must be recorded again (`tests/test_events_run.py` pins that none has).
- **A change to the standing watch.** What bears on a claim: `core/triage.py` with `tests/test_triage.py`; the
  categories it reads are the 8-K rules above, shared with the run. Measure a change with `make watch-replay` (live,
  no model) against the labels in `eval/watch-replay-nvda.json`, before and after, and never change a label to fit.
  A further triage rule goes in `EXTRA_TRIAGE_RULES` (`watch/service.py`); it is empty, because a compiled claim's
  change of outcome needs the company facts, which triage does not fetch; that change is reported after the run, in
  `WhatMoved.computed` (`core/watch_report.py`). Numbers and wording:
  `core/watch_policy.py`. A new watch table: `WATCH_SCHEMA` in `watch/store.py` and `WATCH_KINDS` (so backup and
  restore-check cover it); `make backup` first, `make restore-check` after. A change to a payload: `make
  watch-examples`, then `tests/test_watch_examples.py` says whether the README still names every field.
- **A change to the outside view** (a measure, a class, which years a date admits): `core/frames.py`
  (`MEASURES`, `admitted_years`), `core/base_rates.py`, `core/peers.py`, with `tests/test_outside_view.py`,
  whose expected counts are made by hand from `tests/outside_fakes.py`: change the table's comments
  with the numbers. Then `make market-check` on the eight probe companies, before and after, and
  `make market-examples`.
- **A change to the market view.** The price: `core/thirteenf.py` (the name match, the unit) and
  `sources/thirteenf.MANAGERS`, with `tests/test_thirteenf.py`; another source is a class with
  `name` and `price(company, as_of)` (`sources/prices.PriceProvider`), which must never return a
  price dated or known after the date. The valuation: `core/valuation.py` with
  `tests/test_valuation.py`. The model: `core/reverse_dcf.py` and the defaults at the top of
  `services/market_view.py`; `tests/test_market_examples.py` rebuilds the example's value by two
  routes that do not call the solver. A change to what the fixtures must hold: `make fixtures-market
  REFRESH=1` (live, on purpose), then `make market-examples` and read the diff.
- **A change to the breakdowns** (another axis, another revenue concept, a new shape of nested members): `core/breakdowns.py`, whose specifications and constants sit at its top, with `tests/test_breakdowns.py`; a number format the reader does not know: `sources/ixbrl.py` with `tests/test_ixbrl.py`. Start from a failing test built on a small excerpt of the real filing, then run `make breakdowns` on the eight probe companies, annual and quarterly, and check that every breakdown still adds up to its tagged total (`docs/breakdowns.md`).

## The boundary

The backend computes every result: verified excerpts, verdicts, status, every count in `Run.coverage`, the reviewed
verdicts and the comparison, and each computed test with its arithmetic, margin and history. The frontend collects input and decisions, polls, and draws the record with the wording
from `/api/meta`; it computes no verdict and no excerpt context. Placing record dates on the time line, a series' values in
a sparkline, and setting a negative number in its colour by the sign of the record's value are drawing; the page has two
themes, Paper and Terminal, over one layout (`docs/design.md`). The same holds for the records that are not
part of a run (the comparison of two filings, the changed paragraphs listed under each claim, the tagged breakdowns,
a company's 8-Ks since its annual report, `GET /api/companies/{ticker}/events`, a company's restatement ledger,
`GET /api/companies/{ticker}/restatements`, and the watch's list, health and inbox, whose headlines, labels, counts
and comparisons the backend writes):
each arrives with its counts, its links and what they open, its column headings, its cells and its changes already
computed and formatted, and the page only places them. Requests are validated at the API: the schema in
`core/models`, extra URLs (public, distinct) in `api.py`, the ticker against EDGAR. Refusals are 422 `{"error",
"details": [{"field", "message"}]}`; EDGAR unreachable is 503; a valid request the state forbids is 409. Filing and
page text reaches the model only as escaped data inside `<passage>` elements, and the gate, not the model, decides
what counts. Filings come only from `www.sec.gov` and `data.sec.gov` (7 requests per second, 30 s, 40 MB, retries on
429/503); extra pages go through the private-address-safe fetcher. The key stays in `.env`.

## Verification and operation

- `make verify`: image build, ruff, `node --check`, the offline tests, `tests/smoke.py` against the live container
  (no internet), and `make uitest` (headless Chromium renders the sample runs, the sample filing comparison and the breakdowns; `uitests/`
  checks the DOM against their JSON; `uitests/keys.html`, loaded from disk with the same-origin rule off for that page
  only, presses the page's keys in a frame and records what happened; `uitests/watch.html` does the same for the inbox and the watch
  controls, answering the page's watch requests with the example payloads and the README's refusal shapes; `uitests/v14.html` drives the version 14 states the examples do not show: three readers with a dissent, a disagreement and a refusal, a test of two parts joined by "and", the ledger lookup's answers, a run sent as of a date, the watch API's version 14 fields). Offline tests use `tests/fakes.py`; `make fixtures` re-records EDGAR responses.
- `make golden-check` compares the offline example run with `tests/golden/golden.json` and names the first stage that
  moved; `make golden-baseline` rewrites it. `make profile` and `make bench` time the offline run (`docs/testing.md`,
  `docs/speed.md`).
- `make eval-validate` checks each golden case against its pinned filing; `make eval ARGS='run --variant claim'`
  scores retrieval into `eval/results/`; `ARGS='fetch'` fills `eval/cache`. `make probe TICKERS="AAPL"` checks how a
  filer's filings split.
- `make watch-once` does one watcher cycle and `make watch-status` prints its health and each watch; `make
  watch-examples`, `watch-replay` and `watch-contention` write the example payloads, replay a year of NVIDIA's filings
  live and time a run beside a watcher. `tests/test_watch_contention.py`, in the gate, has a run and watcher cycles
  write one record from two processes at once.
- `make up` serves `http://127.0.0.1:8766` and starts the watcher; `make up-recorded` replays model answers from
  `demo/cassettes/nvda-example` (EDGAR, no key; compose passes `EVIDENCE_DESK_CASSETTE` through). `make run
  ARGS='example'` runs the CLI; `make demo` runs the example live. `READERS=models` (or `model`, `grammar`) on
  `make up`, `up-recorded` or `run` adds `docker/readers.yaml`, which sets `EVIDENCE_DESK_CLAIM_READER` for that
  command (compose's `environment` wins over its `env_file`); without it that file is not loaded and `.env` decides.
  `make readers-check` tests both, with `docker/readers-check.yaml` and `docker/readers-check.env` standing in for an owner's setting.
- `make live-walk`: the app recorded, then `tests/live_walk.py` over HTTP with live EDGAR: a run, decisions, the
  reviewed brief, a thesis run twice (the second from the cache) and the comparison.

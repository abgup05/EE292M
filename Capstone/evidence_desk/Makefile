.PHONY: help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe lock logs shell clean replay golden-check golden-baseline profile bench eval eval-validate backup restore-check up-recorded live-walk changes breakdowns sample-run-changes golden-sheet backup-status figures two-writers header-cut-check time-live events events-probe event-categories facts-load restatements claim-labels claim-results-key examples claim-foreign watch-once watch-status watch-examples watch-replay watch-contention sample-inbox sample-v14 sample-analysis look measures-probe readers-echo readers-check examples-analysis record-analysis market-probe outside-view market-view fixtures-market market-examples market-check reference-pack time-analysis look-print gate-edge-audit audit-recount

export COMPOSE_PROJECT_NAME := ee292m-evidence-desk
export LOCAL_UID := $(shell id -u)
export LOCAL_GID := $(shell id -g)
COMPOSE := docker compose -f docker/compose.yaml
RUN := $(COMPOSE) run --rm --no-deps app

# The claim readers for one command, without editing .env: `make run READERS=models ARGS=...`,
# `make up READERS=models` (grammar, model or models). Given, it is passed into the containers
# through docker/readers.yaml; not given, that file is not loaded and EVIDENCE_DESK_CLAIM_READER
# in .env stands. READER_FILES is for `make readers-check`, which tests both.
READERS_VALUES := grammar model models
ifneq ($(filter-out $(READERS_VALUES),$(READERS)),)
$(error READERS is one of: $(READERS_VALUES))
endif
READER_FILES ?=
WITH_READERS = $(if $(READERS),EVIDENCE_DESK_CLAIM_READER=$(READERS) )$(COMPOSE) $(READER_FILES) $(if $(READERS),-f docker/readers.yaml)
READER_ECHO := python -c "import os; print('readers:', os.environ.get('EVIDENCE_DESK_CLAIM_READER', '(unset)'))"

help:
	@echo 'Everyday: build up down verify clean (verify-fresh: clone the committed branch under results/ and verify it)'
	@echo 'Claim readers for one command: up, up-recorded or run with READERS=models (or model, grammar); without it .env decides. readers-check tests that inside the containers'
	@echo 'Outside and market views (live EDGAR, no key): outside-view T=NVDA CLAIM="..." [AS_OF=], market-view T=NVDA [PRICE= PRICE_DATE=] [AS_OF=] [PRICES=closes.csv INDEX=fred], market-check (both on the eight probe companies), market-probe (every outside source asked once); fixtures-market (live, on purpose) and market-examples (offline) write docs/examples/market'
	@echo 'Recorded demo: up-recorded (the app with model answers replayed from demo/cassettes/nvda-example: Load example, then Test the thesis; needs EDGAR, no key)'
	@echo 'Live walk: live-walk (the running app over HTTP with live EDGAR and recorded answers: a run, decisions, the reviewed brief, a saved thesis run twice, the comparison)'
	@echo 'Development: test lint fmt smoke logs shell (test T=tests/test_x.py; lint/fmt FILES="src/app/x.py")'
	@echo "Command line: run ARGS='example' or ARGS='run --ticker NVDA --decision \"...\" --claim \"...\"' (synchronous; writes results/<run-id>.json and .md)"
	@echo 'Dependencies: lock'
	@echo 'Demonstration: demo (live NVIDIA example through the HTTP API: real EDGAR, configured engine; writes results/demo-<UTC>.json and .md)'
	@echo 'Screenshots: screenshots (headless Chromium renders the first screen, the samples, the recorded inbox, the computed claims, the as-of run, the restatement ledger and the specimen page, in the Paper and Terminal themes and at phone width, into docs/screenshots)'
	@echo 'Looking while changing the page: look (captures the pages LOOK names, each name@width,height@query, into results/; nothing committed)'
	@echo 'Browser test: uitest (headless Chromium renders the sample records, the recorded inbox and the version 14 examples, drives the keys and themes in uitests/keys.html, every answer of the watch routes in uitests/watch.html, the version 14 variants in uitests/v14.html, the frame at 1440x900, 1280x800, 900x800 and 360x740 in uitests/frame.html and the print layout in uitests/print.html; pytest uitests checks the DOM against the JSON); look-print (the note as a PDF and as a capture of its print layout, into results/)'
	@echo "Replay: replay ARGS='--out demo' (the example thesis on recorded filings with model answers from the cassette; no network, no key)"
	@echo 'Quote gate: gate-edge-audit (offline: every committed record of a run under demo, docs/examples, src/web and tests/golden, and each excerpt today'"'"'s gate would refuse; reads only)'
	@echo 'Analysis audit: audit-recount (offline: the two live samples'"'"' argued sentences audited again by today'"'"'s rule, each mark that would change; ARGS="path.json ..." for other records; reads only)'
	@echo 'Tripwire: golden-check (the offline example run against tests/golden/golden.json; names the first stage that moved)'
	@echo 'Tripwire: golden-baseline (rewrite tests/golden/golden.json, and replay.json when the replay has nothing pending; read the diff before committing a new baseline)'
	@echo 'Speed: profile (the offline example run timed stage by stage, then cProfile of it, to results/profile-<UTC>.txt); bench RUNS=12 (the offline run with and without the parser'"'"'s header cut, in alternating pairs: the median saving and its spread, to results/bench-<UTC>.txt)'
	@echo 'Speed: time-live RUNS=5 (live, no key: the example run timed stage by stage inside the run, with a cold and a warm filing cache, without and with the tagged figures; to results/live-timing-<UTC>.txt)'
	@echo "Evaluation: eval ARGS='run --variant claim' (score retrieval on the golden set; ARGS='fetch' fills eval/cache from EDGAR), eval-validate (check every golden case against its filing)"
	@echo "Filing changes: changes ARGS='NVDA --form 10-K' (what was added, removed and reworded between a company's two latest annual or quarterly reports)"
	@echo 'Tagged facts: breakdowns ARGS="NVDA --form 10-K" (segments, geographies and customers from a filing'\''s inline XBRL)'
	@echo 'Current reports: events T=NVDA (live: the 8-Ks filed since the annual report, their items, opening sentences and the roles a 5.02 names; writes results/events-<ticker>-<UTC>.txt and .json)'
	@echo 'Current reports: event-categories (offline: precision and recall of the claim-category rule on eval/claim-categories.json)'
	@echo "Facts: restatements T=NVDA (live: every metric and period whose value differs between the company's filings, with each filing and the change; ARGS='--as-of 2020-01-01'; writes results/restatements-<ticker>-<UTC>.txt and .json)"
	@echo "Claims: claim-labels (offline: the claim compiler against eval/claim-tests.json, development set; ARGS='--set held_out' scores the held-out set, at most twice ever)"
	@echo "Claims: claim-results-key (offline: the expected results of eval/claim-results.json from the raw facts, by a route that never calls the evaluator; ARGS='--write' writes them)"
	@echo "Claims: claim-foreign (offline: the claim compiler on 120 claims another model wrote, eval/claim-tests-foreign.json, against the judgements in eval/claim-tests-foreign-judgements.json, for all and for each half; ARGS='--write eval/results/FILE.txt' records it; exits 1 while a reading is unjudged)"
	@echo "Claims: eval ARGS='compiler-vs-model' (the claim compiler and a model, given the same reported-figure lines, scored on eval/claim-results.json; prints the calls it would make first; ARGS='compiler-vs-model --record --max-calls 70' asks the API for missing answers, refusing above the cap)"
	@echo "Claims: eval ARGS='claim-readers --set eval/claim-tests-foreign.json' (the grammar's and the model parser's reading of each claim, and whether they agree, one row per claim to eval/results/claim-readers-<set>.csv for a judge; prints the calls first; --record --max-calls N asks the API for missing answers, refusing above the cap)"
	@echo 'Facts: facts-load TICKERS="NVDA AAPL" (live: every us-gaap fact of each company, with the filing that reported it and its SIC code, into data/facts/facts.sqlite; disposable)'
	@echo 'Fixtures: fixtures-facts(record XBRL company facts of NVDA, AAPL, MSFT under tests/fixtures/edgar; REFRESH=1 to overwrite)'
	@echo 'Fixtures: fixtures (record SEC EDGAR responses for NVIDIA under tests/fixtures/edgar; REFRESH=1 to overwrite)'
	@echo 'Examples: examples (offline: the version 14 payloads in docs/examples/v14, made from the recorded fixtures with the extractive engine; tests/test_examples_v14.py fails when they are out of date), sample-v14 (copies run.json, as-of-run.json, restatements.json and run-readers.json, unedited, into the page'"'"'s samples ?sample=computed, ?sample=as-of, ?sample=restatements and ?sample=readers)'
	@echo 'Reference pack and timings: reference-pack (live EDGAR, slow the first time: rebuilds src/app/reference, the SEC frames and 13F tables the outside and market views read first; docs/reference-pack.md), time-analysis (offline: five claims against stand-ins that wait as requests do, with the run'"'"'s timings; SCALE=0.1 for a quick look)'
	@echo 'Analysis (0.14.2): examples-analysis (offline: docs/examples/analysis, the computed analysis of the live NVIDIA sample'"'"'s claims, a scripted argument showing every shape, and a model'"'"'s argument when its answers are recorded), record-analysis (API: the analysis model'"'"'s answers for the example thesis into demo/cassettes/nvda-example and for the analysis example into demo/cassettes/analysis-example: 1 request for the corollaries, 1 per claim and 1 for the thesis each, 14 in all; sends only what a cassette lacks and never more than MAX_CALLS, default all)'
	@echo 'Analysis sample: sample-analysis (copies the hand-built example of docs/examples/analysis, unedited, into the page as ?sample=analysis-shapes; run it after examples-analysis)'
	@echo 'Diagnostics: figures TICKERS="COST AMZN" (live: each company'"'"'s quarters as a run sees them; MISSING=1 lists every metric without a value); header-cut-check TICKERS="..." (live: each filing parsed with and without the header cut, the whole documents compared)'
	@echo 'Diagnostics: measures-probe TICKERS="..." (live, the eight probe companies by default: each claim-test measure'"'"'s newest fiscal year, how many have it and why the rest do not, and the parts each newest 10-K tags; writes results/measures-<UTC>.md)'
	@echo 'Diagnostics: probe TICKERS="AAPL MSFT" (live: parse each company'"'"'s latest 10-K and 10-Q, report Item coverage; writes results/probe-<UTC>.md)'
	@echo 'Diagnostics: events-probe TICKERS="..." (live: every 8-K of the last 12 months of the eight probe companies, each listed item found or missed by the splitter; writes results/events-probe-<UTC>.md)'
	@echo 'Backup: backup (the record, online, to backups/record-<UTC>.sqlite with its .sha256, and backups/decisions-<UTC>.jsonl)'
	@echo 'Backup: restore-check (restore the newest backup into a temporary directory and compare it with the live record, record by record, and fail on any record this version cannot read; PASS with the backup'"'"'s age, or FAIL)'
	@echo 'Two writers: two-writers (starts the app on a scratch record under results/ and has it and a one-off container write that record at once; integrity and every row checked)'
	@echo 'Backup: backup-status (one line: how old the newest backup is and how many runs, decisions and theses were made or changed since)'
	@echo 'Standing watch: watch-once (one watcher cycle, then exit), watch-status (the watcher'"'"'s health, the queue and each watch); make up starts the watcher beside the app'
	@echo 'Standing watch: watch-examples (offline: writes the API payloads of a scenario to docs/examples/v13), sample-inbox (copies them, unedited, into the page'"'"'s recorded inbox, ?sample=inbox), watch-replay (live EDGAR, no model: NVIDIA'"'"'s last twelve months of filings fed to triage one at a time, against the labels in eval/watch-replay-nvda.json)'

build:
	$(COMPOSE) build app

up:
	$(WITH_READERS) up --build --force-recreate -d app watch
	@-$(COMPOSE) exec -T app python -m app.backup status

up-recorded:
	EVIDENCE_DESK_CASSETTE=demo/cassettes/nvda-example $(WITH_READERS) up --build --force-recreate -d app

# What the readers setting is inside a container started the way run and up start one.
readers-echo:
	@$(WITH_READERS) run --rm --no-deps -T app $(READER_ECHO)

# The compose behaviour READERS relies on, against docker/readers-check.env standing in for an
# owner's .env that says "model": without READERS it stands; with READERS it gives way.
readers-check:
	@out=$$($(MAKE) -s --no-print-directory readers-echo READERS= READER_FILES="-f docker/readers-check.yaml" 2>/dev/null | tail -1); \
	echo "without READERS: $$out"; test "$$out" = "readers: model"
	@out=$$($(MAKE) -s --no-print-directory readers-echo READERS=models READER_FILES="-f docker/readers-check.yaml" 2>/dev/null | tail -1); \
	echo "READERS=models:  $$out"; test "$$out" = "readers: models"
	@out=$$($(MAKE) -s --no-print-directory readers-echo READERS=grammar READER_FILES="-f docker/readers-check.yaml" 2>/dev/null | tail -1); \
	echo "READERS=grammar: $$out"; test "$$out" = "readers: grammar"
	@echo "readers-check: PASS"

live-walk:
	EVIDENCE_DESK_CASSETTE=demo/cassettes/nvda-example $(COMPOSE) up --build --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python tests/live_walk.py

down:
	$(COMPOSE) down

verify: build lint test smoke uitest

verify-fresh:
	@mkdir -p results
	@checkout=$$(mktemp -d "$(CURDIR)/results/verify.XXXXXX"); \
	git clone --quiet --no-hardlinks "$(CURDIR)/../.." "$$checkout" && \
	$(MAKE) -C "$$checkout/Capstone/evidence_desk" COMPOSE_PROJECT_NAME=ee292m-evidence-desk-fresh verify && \
	rm -rf "$$checkout"

test:
	$(RUN) pytest -q -p no:cacheprovider $(or $(T),tests)

lint:
	$(RUN) ruff check --no-cache --config docker/pyproject.toml $(or $(FILES),src tests)
	$(RUN) ruff format --check --config docker/pyproject.toml $(or $(FILES),src tests)
	$(COMPOSE) run --rm --no-deps jscheck

fmt:
	$(RUN) ruff check --fix --no-cache --config docker/pyproject.toml $(or $(FILES),src tests)
	$(RUN) ruff format --config docker/pyproject.toml $(or $(FILES),src tests)

smoke:
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python tests/smoke.py

# The keyboard and theme check (uitests/keys.html) is a local page that drives the app in a frame
# and writes what happened into its own DOM. Reading a frame of another origin needs the browser's
# same-origin rule off: these flags are for that one test page and no other capture.
KEYS_FLAGS := --disable-web-security --disable-site-isolation-trials --disable-features=IsolateOrigins,site-per-process --allow-file-access-from-files --user-data-dir=/tmp/keys-profile
# The frame check (uitests/frame.html) loads the page ten times at four sizes, so it is given more
# (virtual) time than one page load, and a window larger than its largest frame.
FRAME_FLAGS := --virtual-time-budget=60000 --window-size=1600,1000
uitest:
	@mkdir -p results
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) exec -T app python uitests/wait_ready.py && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=synthetic" > results/dom-synthetic.html 2> results/dom-synthetic.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample" > results/dom-sample.html 2> results/dom-sample.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=changes" > results/dom-changes.html 2> results/dom-changes.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=breakdowns" > results/dom-breakdowns.html 2> results/dom-breakdowns.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample#claim-c4-changes" > results/dom-sample-claim.html 2> results/dom-sample-claim.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=breakdowns-gap" > results/dom-breakdowns-gap.html 2> results/dom-breakdowns-gap.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=run-tagged" > results/dom-run-tagged.html 2> results/dom-run-tagged.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=run-events" > results/dom-run-events.html 2> results/dom-run-events.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample&theme=terminal" > results/dom-sample-terminal.html 2> results/dom-sample-terminal.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=inbox" > results/dom-inbox.html 2> results/dom-inbox.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=inbox-page-2&theme=terminal" > results/dom-inbox-page-2.html 2> results/dom-inbox-page-2.log && \
	$(COMPOSE) run --rm -T shots $(KEYS_FLAGS) --dump-dom "file:///work/uitests/keys.html" > results/dom-keys.html 2> results/dom-keys.log && \
	$(COMPOSE) run --rm -T shots $(KEYS_FLAGS) --dump-dom "file:///work/uitests/watch.html" > results/dom-watch.html 2> results/dom-watch.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=computed" > results/dom-computed.html 2> results/dom-computed.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=as-of&theme=terminal" > results/dom-as-of.html 2> results/dom-as-of.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=restatements" > results/dom-restatements.html 2> results/dom-restatements.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=run-live" > results/dom-run-live.html 2> results/dom-run-live.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=readers&theme=terminal" > results/dom-readers.html 2> results/dom-readers.log && \
	$(COMPOSE) run --rm -T shots $(KEYS_FLAGS) --dump-dom "file:///work/uitests/v14.html" > results/dom-v14.html 2> results/dom-v14.log && \
	$(COMPOSE) run --rm -T shots $(KEYS_FLAGS) $(FRAME_FLAGS) --dump-dom "file:///work/uitests/frame.html" > results/dom-frame.html 2> results/dom-frame.log && \
	$(COMPOSE) run --rm -T shots $(KEYS_FLAGS) --dump-dom "file:///work/uitests/print.html" > results/dom-print.html 2> results/dom-print.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=run-costco" > results/dom-run-costco.html 2> results/dom-run-costco.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=analysis-shapes&theme=terminal" > results/dom-analysis-shapes.html 2> results/dom-analysis-shapes.log && \
	$(COMPOSE) run --rm -T shots $(KEYS_FLAGS) $(FRAME_FLAGS) --dump-dom "file:///work/uitests/analysis.html" > results/dom-analysis.html 2> results/dom-analysis.log
	$(RUN) pytest -q -p no:cacheprovider uitests

run:
	$(WITH_READERS) run --rm --no-deps app python -m app.cli $(ARGS)

demo: build
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python -m app.demo

# Headless Chromium exits 0 when its GPU process dies on a very tall capture and writes no file,
# so no capture is taller than 3600 px and the target fails unless every file was written anew.
# It also paints nothing after a scroll, so a deep link into a claim cannot be captured: the page
# test reads its DOM instead (uitests/test_run_changes_dom.py).
# One capture per line: name@width,height@address. A run is captured as the window shows it
# (1440x900, 1280x800, 900x800: the page does not scroll, so that is the whole of it), with the
# claim and tab named in the address; a phone capture and the specimen are documents and are
# captured tall. frame-* are the same live run on each tab and at each width.
SHOT_SPECS := \
	first-screen@1440,900@?theme=paper \
	first-screen-terminal@1440,900@?theme=terminal \
	sample-live@1440,900@?sample=run-live&theme=paper \
	sample-live-terminal@1440,900@?sample=run-live&theme=terminal \
	sample-live-phone@390,3600@?sample=run-live&theme=paper \
	sample-costco@1440,900@?sample=run-costco&theme=paper \
	sample-costco-terminal@1440,900@?sample=run-costco&theme=terminal \
	analysis-thesis@1440,2800@?sample=run-live&theme=paper \
	analysis-thesis-terminal@1440,2800@?sample=run-live&theme=terminal \
	analysis-claim@1440,900@?sample=run-live&theme=paper&claim=c4 \
	analysis-claim-terminal@1440,900@?sample=run-costco&theme=terminal&claim=c1 \
	analysis-claim-tall@1440,3400@?sample=run-live&theme=paper&claim=c3 \
	analysis-claim-tall-terminal@1440,3400@?sample=run-costco&theme=terminal&claim=c2 \
	analysis-1280@1280,800@?sample=run-costco&theme=paper&claim=c4 \
	analysis-1280-terminal@1280,800@?sample=run-live&theme=terminal&claim=c2 \
	analysis-tablet@900,800@?sample=run-live&theme=paper \
	analysis-phone@390,844@?sample=run-costco&theme=paper&claim=c2 \
	analysis-phone-terminal@390,3600@?sample=run-live&theme=terminal \
	analysis-no-model@1440,900@?sample=computed&theme=paper \
	analysis-no-model-terminal@1440,900@?sample=computed&theme=terminal&claim=c1 \
	analysis-shapes@1440,900@?sample=analysis-shapes&theme=paper&claim=c2 \
	method@1440,1500@?sample=run-live&theme=paper&tab=method \
	method-terminal@1440,900@?sample=run-costco&theme=terminal&tab=method \
	method-no-model@1440,900@?sample=computed&theme=paper&tab=method \
	overview@1440,900@?sample=run-live&theme=paper&tab=overview \
	overview-terminal@1440,900@?sample=run-costco&theme=terminal&tab=overview \
	frame-claim@1440,900@?sample=run-live&theme=paper&claim=c2&tab=overview \
	frame-claim-terminal@1440,900@?sample=run-live&theme=terminal&claim=c2&tab=overview \
	frame-figures-claim@1440,900@?sample=run-live&theme=paper&claim=c3&tab=figures \
	frame-evidence@1440,900@?sample=run-live&theme=paper&claim=c1&tab=evidence \
	frame-evidence-terminal@1440,900@?sample=run-live&theme=terminal&claim=c1&tab=evidence \
	frame-thesis-evidence@1440,900@?sample=run-live&theme=paper&tab=evidence \
	frame-time@1440,900@?sample=run-live&theme=paper&tab=time \
	frame-time-terminal@1440,900@?sample=run-live&theme=terminal&claim=c2&tab=time \
	frame-events@1440,900@?sample=run-live&theme=paper&tab=events \
	frame-events-terminal@1440,900@?sample=run-live&theme=terminal&tab=events \
	frame-figures@1440,900@?sample=run-live&theme=paper&tab=figures \
	frame-figures-terminal@1440,900@?sample=run-live&theme=terminal&tab=figures \
	frame-limits-terminal@1440,900@?sample=run-live&theme=terminal&tab=limits \
	frame-1280@1280,800@?sample=run-live&theme=paper&claim=c3&tab=overview \
	frame-1280-terminal@1280,800@?sample=run-live&theme=terminal&claim=c4&tab=overview \
	frame-tablet@900,800@?sample=run-live&theme=paper&claim=c2&tab=evidence \
	frame-tablet-terminal@900,800@?sample=run-live&theme=terminal&tab=overview \
	frame-phone@390,844@?sample=run-live&theme=paper&tab=overview \
	frame-phone-terminal@390,844@?sample=run-live&theme=terminal&tab=overview \
	sample-run@1440,900@?sample&theme=paper \
	sample-run-terminal@1440,900@?sample&theme=terminal&claim=c1 \
	sample-run-phone@390,1400@?sample&theme=paper \
	sample-run-phone-terminal@390,1400@?sample&theme=terminal \
	sample-synthetic@1440,900@?sample=synthetic&theme=paper \
	sample-synthetic-terminal@1440,900@?sample=synthetic&theme=terminal&claim=c2&tab=evidence \
	sample-changes@1440,900@?sample=changes&theme=paper \
	sample-changes-terminal@1440,900@?sample=changes&theme=terminal \
	sample-changes-phone@390,2600@?sample=changes&theme=paper \
	sample-breakdowns@1440,900@?sample=breakdowns&theme=paper \
	sample-breakdowns-terminal@1440,900@?sample=breakdowns&theme=terminal \
	tagged-figures@1440,900@?sample=run-tagged&theme=paper&tab=figures \
	sample-events@1440,900@?sample=run-events&theme=paper&claim=c1 \
	sample-events-terminal@1440,900@?sample=run-events&theme=terminal&tab=events \
	sample-events-phone@390,2400@?sample=run-events&theme=paper \
	sample-inbox@1440,900@?sample=inbox&theme=paper \
	sample-inbox-terminal@1440,900@?sample=inbox&theme=terminal \
	sample-inbox-phone@390,3400@?sample=inbox&theme=paper \
	sample-computed@1440,900@?sample=computed&theme=paper&claim=c1&tab=overview \
	sample-computed-terminal@1440,900@?sample=computed&theme=terminal&tab=time \
	sample-computed-phone@390,3600@?sample=computed&theme=paper \
	sample-as-of@1440,900@?sample=as-of&theme=paper&tab=overview \
	sample-as-of-terminal@1440,900@?sample=as-of&theme=terminal&tab=time \
	sample-restatements@1440,900@?sample=restatements&theme=paper \
	sample-restatements-terminal@1440,900@?sample=restatements&theme=terminal \
	specimen@1280,3600@specimen.html?theme=paper \
	specimen-terminal@1280,3600@specimen.html?theme=terminal \
	specimen-frame@1280,700@specimen.html?theme=paper&only=frame \
	specimen-v14@1280,3600@specimen.html?theme=paper&only=v14 \
	specimen-v14-terminal@1280,3600@specimen.html?theme=terminal&only=v14 \
	specimen-v14-phone@390,3600@specimen.html?theme=paper&only=v14 \
	specimen-note@1280,3600@specimen.html?theme=paper&only=note \
	specimen-note-terminal@1280,3600@specimen.html?theme=terminal&only=note \
	specimen-views@1280,2400@specimen.html?theme=paper&only=views \
	specimen-phone@390,3000@specimen.html?theme=paper \
	computed-readers@1280,1500@specimen.html?theme=paper&only=v14 \
	computed-readers-terminal@1280,1500@specimen.html?theme=terminal&only=v14
SHOTS := $(foreach s,$(SHOT_SPECS),$(firstword $(subst @, ,$(s))))
screenshots:
	@mkdir -p docs/screenshots results
	@touch results/.screenshots-started
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) exec -T app python uitests/wait_ready.py && \
	for spec in $(foreach s,$(SHOT_SPECS),'$(s)'); do \
	  name=$${spec%%@*}; rest=$${spec#*@}; size=$${rest%%@*}; url=$${rest#*@}; \
	  $(COMPOSE) run --rm shots --window-size=$$size --screenshot=/work/docs/screenshots/$$name.png "http://app:8000/$$url" 2>/dev/null || exit 1; \
	done
	@for name in $(SHOTS); do \
		test docs/screenshots/$$name.png -nt results/.screenshots-started \
		|| { echo "screenshots: docs/screenshots/$$name.png was not written"; exit 1; }; \
	done

# Captures for looking at the page while changing it, into results/ (disposable, not committed):
# make look LOOK='live@1280,3600@?sample=run-live&theme=paper live-phone@390,3600@?sample=run-live'
LOOK ?= look@1280,3600@?sample=run-live&theme=paper
look:
	@mkdir -p results
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) exec -T app python uitests/wait_ready.py && \
	for spec in $(foreach l,$(LOOK),'$(l)'); do \
	  name=$${spec%%@*}; rest=$${spec#*@}; size=$${rest%%@*}; url=$${rest#*@}; \
	  $(COMPOSE) run --rm shots --window-size=$$size --screenshot=/work/results/$$name.png "http://app:8000/$$url" 2>/dev/null && echo "results/$$name.png"; \
	done

# The note as it prints, as a PDF in results/ (disposable, not committed): the print stylesheet
# lays the workspace out as a document, which no screenshot shows.
# make look-print PRINT='?sample=run-live'
# It also captures results/print.png: uitests/print.html showing the live-run sample under the
# print rules, on a screen (the first PRINT_HEIGHT pixels of it), for when no PDF reader is at hand.
PRINT ?= ?sample=run-live
PRINT_HEIGHT ?= 3400
look-print:
	@mkdir -p results
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) exec -T app python uitests/wait_ready.py && \
	$(COMPOSE) run --rm shots --no-pdf-header-footer --print-to-pdf=/work/results/print.pdf "http://app:8000/$(PRINT)" 2>/dev/null && echo "results/print.pdf" && \
	$(COMPOSE) run --rm shots $(KEYS_FLAGS) --window-size=794,$(PRINT_HEIGHT) --screenshot=/work/results/print.png "file:///work/uitests/print.html#keep" 2>/dev/null && echo "results/print.png"

fixtures:
	$(RUN) python -m app.record_fixtures $(if $(filter 1,$(REFRESH)),--refresh,)

replay:
	$(RUN) python -m tests.replay_run $(ARGS)

examples:
	$(RUN) python -m tests.examples_v14 $(ARGS)

examples-analysis:
	$(RUN) python -m tests.examples_analysis $(ARGS)

# Records the analysis model's answers through the API, for the example thesis (into
# demo/cassettes/nvda-example) and the analysis example (into demo/cassettes/analysis-example):
# for each, 1 request for the corollaries, 1 per claim and 1 for the thesis, 14 in all. Needs
# ANTHROPIC_API_KEY in .env. Only a request a cassette lacks is sent, and never more than
# MAX_CALLS (default: all 14); the number is printed before anything is sent.
record-analysis:
	$(RUN) python -m tests.record_analysis $(if $(MAX_CALLS),--max-calls $(MAX_CALLS),) $(ARGS)

eval-validate:
	$(RUN) python -m app.evaluation validate $(ARGS)

golden-sheet:
	$(RUN) python -m app.evaluation.reading_sheet $(ARGS)

eval:
	$(RUN) python -m app.evaluation run $(ARGS)

# Every committed record of a run (demo/, docs/examples/, src/web/, tests/golden/): which of
# its excerpts today's quote gate would refuse. Reads only; a record is never edited.
gate-edge-audit:
	$(RUN) python -m tests.gate_edge_audit $(ARGS)

# Recorded runs' argued analysis audited again by today's rule (default: the page's two live
# samples). Reads only: a record of a real run keeps the audit of its day.
audit-recount:
	$(RUN) python -m tests.audit_recount $(ARGS)

golden-check:
	$(RUN) pytest -q -p no:cacheprovider tests/test_golden.py

golden-baseline:
	$(RUN) python -m tests.golden_run --write

profile:
	$(RUN) python -m tests.speed_run profile

bench:
	$(RUN) python -m tests.speed_run bench $(if $(RUNS),--runs $(RUNS),) $(if $(filter 1,$(COLLECTOR)),--collector,)

time-live:
	$(RUN) python -m tests.live_timing $(if $(RUNS),--runs $(RUNS),)

fixtures-facts:
	$(RUN) python -m app.record_facts $(if $(filter 1,$(REFRESH)),--refresh,)

changes:
	$(RUN) python -m app.changes $(ARGS)

breakdowns:
	$(RUN) python -m app.breakdowns $(ARGS)

sample-run-changes:
	$(RUN) python -m tests.sample_run_changes $(ARGS)

probe:
	$(RUN) python -m app.probe $(if $(filter 1,$(OUTLINE)),--outline,) $(or $(TICKERS),NVDA)

events:
	$(RUN) python -m app.events $(or $(T),NVDA) $(ARGS)

events-probe:
	$(RUN) python -m app.events_probe $(or $(TICKERS),NVDA AAPL MSFT KO JPM TSLA COST AMZN)

event-categories:
	$(RUN) python -m app.evaluation.claim_categories $(ARGS)

figures:
	$(RUN) python -m app.figures $(if $(filter 1,$(MISSING)),--missing,) $(or $(TICKERS),NVDA)

measures-probe:
	$(RUN) python -m app.measures_probe $(or $(TICKERS),NVDA AAPL MSFT KO JPM TSLA COST AMZN)

facts-load:
	$(RUN) python -m app.facts_load $(or $(TICKERS),NVDA)

restatements:
	$(RUN) python -m app.restatements $(or $(T),NVDA) $(ARGS)

claim-labels:
	$(RUN) python -m app.evaluation.claim_tests $(ARGS)

claim-foreign:
	$(RUN) python -m app.evaluation.foreign_claims $(ARGS)

claim-results-key:
	$(RUN) python -m app.evaluation.claim_oracle $(ARGS)

header-cut-check:
	$(RUN) python -m tests.header_cut_check $(or $(TICKERS),NVDA)

lock:
	$(COMPOSE) build lock
	$(COMPOSE) run --rm --no-deps lock lock

logs:
	$(COMPOSE) logs -f app

shell:
	$(COMPOSE) run --rm --no-deps app sh

clean:
	$(COMPOSE) down --rmi local --remove-orphans

backup:
	$(RUN) python -m app.backup backup

backup-status:
	@$(RUN) python -m app.backup status

# The app and a one-off container write one record at the same time, on a scratch record under
# results/ (never the real one). Starts the app, so only one session may run it at a time.
SCRATCH_DATA := /work/results/two-writers
two-writers:
	@rm -rf results/two-writers
	EVIDENCE_DESK_DATA_DIR=$(SCRATCH_DATA) $(COMPOSE) up --build --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; EVIDENCE_DESK_DATA_DIR=$(SCRATCH_DATA) $(RUN) python -m tests.two_writers $(ARGS)

restore-check:
	$(RUN) python -m app.backup restore-check

# The standing watch (version 13). The watcher itself runs as the `watch` service (make up).
watch-once:
	$(RUN) python -m app.watch once

watch-status:
	@$(RUN) python -m app.watch status

watch-examples:
	$(RUN) python -m tests.watch_examples

# The page's recorded inbox (?sample=inbox): the payloads watch-examples wrote, copied unedited.
# Run it after watch-examples; uitests/test_inbox_dom.py fails while a copy differs from its source.
INBOX_SAMPLES := inbox inbox-page-2 watches health meta
sample-inbox:
	@for name in $(INBOX_SAMPLES); do \
	  case $$name in inbox|inbox-page-2) out=sample-$$name.json ;; *) out=sample-inbox-$$name.json ;; esac; \
	  cp docs/examples/v13/$$name.json src/web/$$out && echo "src/web/$$out <- docs/examples/v13/$$name.json"; \
	done

# The page's version 14 samples (?sample=computed, as-of, restatements, readers): the payloads
# `make examples` wrote, copied unedited. Run it after examples; uitests/test_v14_dom.py fails while
# a copy differs.
V14_SAMPLES := run:computed as-of-run:as-of restatements:restatements run-readers:readers
sample-v14:
	@for pair in $(V14_SAMPLES); do \
	  src=$${pair%%:*}; out=sample-$${pair##*:}.json; \
	  cp docs/examples/v14/$$src.json src/web/$$out && echo "src/web/$$out <- docs/examples/v14/$$src.json"; \
	done

# The page's sample of every shape the analysis can take (?sample=analysis-shapes): the hand-built
# example of `make examples-analysis`, copied unedited. Run it after examples-analysis;
# uitests/test_analysis_dom.py fails while the copy differs.
sample-analysis:
	@cp docs/examples/analysis/run-hand-built-argument.json src/web/sample-analysis-shapes.json && echo "src/web/sample-analysis-shapes.json <- docs/examples/analysis/run-hand-built-argument.json"

watch-replay:
	$(RUN) python -m tests.watch_replay $(ARGS)

watch-contention:
	$(RUN) python -m tests.watch_contention $(if $(PAIRS),--pairs $(PAIRS),)

# The outside view and the market view (docs/outside-view.md, docs/market-view.md).
market-probe:
	$(RUN) python -m app.market_probe $(ARGS)

outside-view:
	$(RUN) python -m app.outside $(or $(T),NVDA) --claim "$(CLAIM)" $(if $(AS_OF),--as-of "$(AS_OF)",) $(ARGS)

# The price is the newest quarter-end price SEC's 13F filings give (docs/market-view.md);
# PRICE=... PRICE_DATE=YYYY-MM-DD gives your own instead. AS_OF=YYYY-MM-DD reads as of a day.
# PRICES=path/to/closes.csv adds the reactions to the 8-Ks of the claim's categories; INDEX=fred
# (FRED's S&P 500, read live) or INDEX=path/to/index.csv is the index they are measured against.
market-view:
	$(RUN) python -m app.market $(or $(T),NVDA) --claim "$(CLAIM)" $(if $(PRICE),--price "$(PRICE)" --price-date "$(PRICE_DATE)",) $(if $(AS_OF),--as-of "$(AS_OF)",) $(if $(PRICES),--prices "$(PRICES)",) $(if $(INDEX),--index "$(INDEX)",) $(ARGS)

# Offline: one run of five claims with stand-ins that wait as model requests do, its
# timings, and the same requests in the old order. SCALE=0.1 for a quick look.
time-analysis:
	$(RUN) python -m tests.timing_run --scale $(or $(SCALE),1)

# Live, on purpose, and slow the first time (one request for each of several thousand filers'
# industry codes; everything fetched is kept, so a second run is quick): the reference pack of
# SEC frames and 13F tables that ships in src/app/reference (docs/reference-pack.md).
reference-pack:
	$(RUN) python -m app.build_reference $(ARGS)

# Live, on purpose: the frames, SIC list and company facts the offline example reads
# (tests/fixtures/frames/manifest.json says what and when). REFRESH=1 writes over them.
fixtures-market:
	$(RUN) python -m app.record_market $(if $(filter 1,$(REFRESH)),--refresh,)

# Offline: docs/examples/market from the recorded fixtures; tests/test_market_examples.py
# fails when they are out of date.
market-examples:
	$(RUN) python -m tests.market_examples $(ARGS)

# Live: both views on the eight probe companies, with the 13F quarter-end price and what
# each could not compute. Writes results/market-check-<UTC>.md. TICKERS="..." for others.
market-check:
	$(RUN) python -m app.market_check $(TICKERS) $(ARGS)

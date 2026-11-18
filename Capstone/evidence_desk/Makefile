.PHONY: help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe lock logs shell clean replay golden-check golden-baseline profile bench eval eval-validate backup restore-check up-recorded live-walk changes breakdowns sample-run-changes golden-sheet backup-status figures two-writers header-cut-check time-live events events-probe event-categories facts-load restatements claim-labels claim-results-key examples claim-foreign watch-once watch-status watch-examples watch-replay watch-contention sample-inbox sample-v14 measures-probe

export COMPOSE_PROJECT_NAME := ee292m-evidence-desk
export LOCAL_UID := $(shell id -u)
export LOCAL_GID := $(shell id -g)
COMPOSE := docker compose -f docker/compose.yaml
RUN := $(COMPOSE) run --rm --no-deps app

help:
	@echo 'Everyday: build up down verify clean (verify-fresh: clone the committed branch under results/ and verify it)'
	@echo 'Recorded demo: up-recorded (the app with model answers replayed from demo/cassettes/nvda-example: Load example, then Test the thesis; needs EDGAR, no key)'
	@echo 'Live walk: live-walk (the running app over HTTP with live EDGAR and recorded answers: a run, decisions, the reviewed brief, a saved thesis run twice, the comparison)'
	@echo 'Development: test lint fmt smoke logs shell (test T=tests/test_x.py; lint/fmt FILES="src/app/x.py")'
	@echo "Command line: run ARGS='example' or ARGS='run --ticker NVDA --decision \"...\" --claim \"...\"' (synchronous; writes results/<run-id>.json and .md)"
	@echo 'Dependencies: lock'
	@echo 'Demonstration: demo (live NVIDIA example through the HTTP API: real EDGAR, configured engine; writes results/demo-<UTC>.json and .md)'
	@echo 'Screenshots: screenshots (headless Chromium renders the first screen, the samples, the recorded inbox, the computed claims, the as-of run, the restatement ledger and the specimen page, in the Paper and Terminal themes and at phone width, into docs/screenshots)'
	@echo 'Browser test: uitest (headless Chromium renders the sample records, the recorded inbox and the version 14 examples, drives the keys and themes in uitests/keys.html, every answer of the watch routes in uitests/watch.html and the version 14 variants in uitests/v14.html; pytest uitests checks the DOM against the JSON)'
	@echo "Replay: replay ARGS='--out demo' (the example thesis on recorded filings with model answers from the cassette; no network, no key)"
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
	@echo "Claims: eval ARGS='compiler-vs-model' (the claim compiler and a model, given the same reported-figure lines, scored on eval/claim-results.json; prints the calls it would make first; ARGS='compiler-vs-model --record --max-calls 60' asks the API for missing answers, refusing above the cap)"
	@echo "Claims: eval ARGS='claim-readers --set eval/claim-tests-foreign.json' (the grammar's and the model parser's reading of each claim, and whether they agree, one row per claim to eval/results/claim-readers-<set>.csv for a judge; prints the calls first; --record --max-calls N asks the API for missing answers, refusing above the cap)"
	@echo 'Facts: facts-load TICKERS="NVDA AAPL" (live: every us-gaap fact of each company, with the filing that reported it and its SIC code, into data/facts/facts.sqlite; disposable)'
	@echo 'Fixtures: fixtures-facts(record XBRL company facts of NVDA, AAPL, MSFT under tests/fixtures/edgar; REFRESH=1 to overwrite)'
	@echo 'Fixtures: fixtures (record SEC EDGAR responses for NVIDIA under tests/fixtures/edgar; REFRESH=1 to overwrite)'
	@echo 'Examples: examples (offline: the version 14 payloads in docs/examples/v14, made from the recorded fixtures with the extractive engine; tests/test_examples_v14.py fails when they are out of date), sample-v14 (copies run.json, as-of-run.json and restatements.json, unedited, into the page'"'"'s samples ?sample=computed, ?sample=as-of and ?sample=restatements)'
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
	$(COMPOSE) up --build --force-recreate -d app watch
	@-$(COMPOSE) exec -T app python -m app.backup status

up-recorded:
	EVIDENCE_DESK_CASSETTE=demo/cassettes/nvda-example $(COMPOSE) up --build --force-recreate -d app

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
	$(COMPOSE) run --rm -T shots $(KEYS_FLAGS) --dump-dom "file:///work/uitests/v14.html" > results/dom-v14.html 2> results/dom-v14.log
	$(RUN) pytest -q -p no:cacheprovider uitests

run:
	$(RUN) python -m app.cli $(ARGS)

demo: build
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python -m app.demo

# Headless Chromium exits 0 when its GPU process dies on a very tall capture and writes no file,
# so no capture is taller than 3600 px and the target fails unless every file was written anew.
# It also paints nothing after a scroll, so a deep link into a claim cannot be captured: the page
# test reads its DOM instead (uitests/test_run_changes_dom.py).
SHOTS := first-screen sample-run sample-run-phone sample-synthetic sample-changes sample-changes-phone sample-breakdowns tagged-figures \
	first-screen-terminal sample-run-terminal sample-run-phone-terminal sample-events sample-events-terminal sample-events-phone \
	sample-synthetic-terminal sample-changes-terminal sample-breakdowns-terminal specimen specimen-terminal specimen-v14 specimen-note specimen-note-terminal specimen-views specimen-phone \
	sample-inbox sample-inbox-terminal sample-inbox-phone \
	sample-computed sample-computed-terminal sample-computed-phone specimen-v14-terminal specimen-v14-phone \
	sample-as-of sample-as-of-terminal sample-restatements sample-restatements-terminal
screenshots:
	@mkdir -p docs/screenshots results
	@touch results/.screenshots-started
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) exec -T app python uitests/wait_ready.py && \
	$(COMPOSE) run --rm shots --window-size=1280,1000 --screenshot=/work/docs/screenshots/first-screen.png "http://app:8000/?theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-run.png "http://app:8000/?sample&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=390,1400 --screenshot=/work/docs/screenshots/sample-run-phone.png "http://app:8000/?sample&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-synthetic.png "http://app:8000/?sample=synthetic&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-changes.png "http://app:8000/?sample=changes&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=390,2600 --screenshot=/work/docs/screenshots/sample-changes-phone.png "http://app:8000/?sample=changes&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,2400 --screenshot=/work/docs/screenshots/sample-breakdowns.png "http://app:8000/?sample=breakdowns&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/tagged-figures.png "http://app:8000/?sample=run-tagged&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,1000 --screenshot=/work/docs/screenshots/first-screen-terminal.png "http://app:8000/?theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-run-terminal.png "http://app:8000/?sample&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=390,1400 --screenshot=/work/docs/screenshots/sample-run-phone-terminal.png "http://app:8000/?sample&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-events.png "http://app:8000/?sample=run-events&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-events-terminal.png "http://app:8000/?sample=run-events&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=390,2400 --screenshot=/work/docs/screenshots/sample-events-phone.png "http://app:8000/?sample=run-events&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-synthetic-terminal.png "http://app:8000/?sample=synthetic&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=1280,2400 --screenshot=/work/docs/screenshots/sample-changes-terminal.png "http://app:8000/?sample=changes&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=1280,2400 --screenshot=/work/docs/screenshots/sample-breakdowns-terminal.png "http://app:8000/?sample=breakdowns&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/specimen.png "http://app:8000/specimen.html?theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/specimen-terminal.png "http://app:8000/specimen.html?theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/specimen-v14.png "http://app:8000/specimen.html?theme=paper&only=v14" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/specimen-note.png "http://app:8000/specimen.html?theme=paper&only=note" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/specimen-note-terminal.png "http://app:8000/specimen.html?theme=terminal&only=note" && \
	$(COMPOSE) run --rm shots --window-size=1280,2400 --screenshot=/work/docs/screenshots/specimen-views.png "http://app:8000/specimen.html?theme=paper&only=views" && \
	$(COMPOSE) run --rm shots --window-size=390,3000 --screenshot=/work/docs/screenshots/specimen-phone.png "http://app:8000/specimen.html?theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-inbox.png "http://app:8000/?sample=inbox&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-inbox-terminal.png "http://app:8000/?sample=inbox&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=390,3400 --screenshot=/work/docs/screenshots/sample-inbox-phone.png "http://app:8000/?sample=inbox&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-computed.png "http://app:8000/?sample=computed&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/sample-computed-terminal.png "http://app:8000/?sample=computed&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=390,3600 --screenshot=/work/docs/screenshots/sample-computed-phone.png "http://app:8000/?sample=computed&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3600 --screenshot=/work/docs/screenshots/specimen-v14-terminal.png "http://app:8000/specimen.html?theme=terminal&only=v14" && \
	$(COMPOSE) run --rm shots --window-size=390,3600 --screenshot=/work/docs/screenshots/specimen-v14-phone.png "http://app:8000/specimen.html?theme=paper&only=v14" && \
	$(COMPOSE) run --rm shots --window-size=1280,2400 --screenshot=/work/docs/screenshots/sample-as-of.png "http://app:8000/?sample=as-of&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,2400 --screenshot=/work/docs/screenshots/sample-as-of-terminal.png "http://app:8000/?sample=as-of&theme=terminal" && \
	$(COMPOSE) run --rm shots --window-size=1280,3000 --screenshot=/work/docs/screenshots/sample-restatements.png "http://app:8000/?sample=restatements&theme=paper" && \
	$(COMPOSE) run --rm shots --window-size=1280,3000 --screenshot=/work/docs/screenshots/sample-restatements-terminal.png "http://app:8000/?sample=restatements&theme=terminal"
	@for name in $(SHOTS); do \
		test docs/screenshots/$$name.png -nt results/.screenshots-started \
		|| { echo "screenshots: docs/screenshots/$$name.png was not written"; exit 1; }; \
	done

fixtures:
	$(RUN) python -m app.record_fixtures $(if $(filter 1,$(REFRESH)),--refresh,)

replay:
	$(RUN) python -m tests.replay_run $(ARGS)

examples:
	$(RUN) python -m tests.examples_v14 $(ARGS)

eval-validate:
	$(RUN) python -m app.evaluation validate $(ARGS)

golden-sheet:
	$(RUN) python -m app.evaluation.reading_sheet $(ARGS)

eval:
	$(RUN) python -m app.evaluation run $(ARGS)

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

# The page's version 14 samples (?sample=computed, as-of, restatements): the payloads `make examples`
# wrote, copied unedited. Run it after examples; uitests/test_v14_dom.py fails while a copy differs.
V14_SAMPLES := run:computed as-of-run:as-of restatements:restatements
sample-v14:
	@for pair in $(V14_SAMPLES); do \
	  src=$${pair%%:*}; out=sample-$${pair##*:}.json; \
	  cp docs/examples/v14/$$src.json src/web/$$out && echo "src/web/$$out <- docs/examples/v14/$$src.json"; \
	done

watch-replay:
	$(RUN) python -m tests.watch_replay $(ARGS)

watch-contention:
	$(RUN) python -m tests.watch_contention $(if $(PAIRS),--pairs $(PAIRS),)

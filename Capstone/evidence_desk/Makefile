.PHONY: help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe lock logs shell clean replay golden-check golden-baseline profile bench eval eval-validate backup restore-check up-recorded live-walk

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
	@echo 'Screenshots: screenshots (headless Chromium renders the first screen and the sample record into docs/screenshots)'
	@echo 'Browser test: uitest (headless Chromium renders both sample records; pytest uitests checks the DOM against the JSON)'
	@echo "Replay: replay ARGS='--out demo' (the example thesis on recorded filings with model answers from the cassette; no network, no key)"
	@echo 'Tripwire: golden-check (the offline example run against tests/golden/golden.json; names the first stage that moved)'
	@echo 'Tripwire: golden-baseline (rewrite tests/golden/golden.json, and replay.json when the replay has nothing pending; read the diff before committing a new baseline)'
	@echo 'Speed: profile (cProfile of the offline example run, top 25 by cumulative time, to results/profile-<UTC>.txt); bench RUNS=5 (median wall time of the offline run, in seconds)'
	@echo "Evaluation: eval ARGS='run --variant claim' (score retrieval on the golden set; ARGS='fetch' fills eval/cache from EDGAR), eval-validate (check every golden case against its filing)"
	@echo 'Fixtures: fixtures-facts (record XBRL company facts of NVDA, AAPL, MSFT under tests/fixtures/edgar; REFRESH=1 to overwrite)'
	@echo 'Fixtures: fixtures (record SEC EDGAR responses for NVIDIA under tests/fixtures/edgar; REFRESH=1 to overwrite)'
	@echo 'Diagnostics: probe TICKERS="AAPL MSFT" (live: parse each company'"'"'s latest 10-K and 10-Q, report Item coverage; writes results/probe-<UTC>.md)'
	@echo 'Backup: backup (the record, online, to backups/record-<UTC>.sqlite with its .sha256, and backups/decisions-<UTC>.jsonl)'
	@echo 'Backup: restore-check (restore the newest backup into a temporary directory and compare it with the live record; PASS or FAIL)'

build:
	$(COMPOSE) build app

up:
	$(COMPOSE) up --build --force-recreate -d app

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

uitest:
	@mkdir -p results
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) exec -T app python uitests/wait_ready.py && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample=synthetic" > results/dom-synthetic.html 2> results/dom-synthetic.log && \
	$(COMPOSE) run --rm -T shots --dump-dom "http://app:8000/?sample" > results/dom-sample.html 2> results/dom-sample.log
	$(RUN) pytest -q -p no:cacheprovider uitests

run:
	$(RUN) python -m app.cli $(ARGS)

demo: build
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python -m app.demo

screenshots:
	@mkdir -p docs/screenshots
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) exec -T app python uitests/wait_ready.py && \
	$(COMPOSE) run --rm shots --window-size=1280,720 --screenshot=/work/docs/screenshots/first-screen.png "http://app:8000/" && \
	$(COMPOSE) run --rm shots --window-size=1280,4500 --screenshot=/work/docs/screenshots/sample-run.png "http://app:8000/?sample" && \
	$(COMPOSE) run --rm shots --window-size=390,1400 --screenshot=/work/docs/screenshots/sample-run-phone.png "http://app:8000/?sample" && \
	$(COMPOSE) run --rm shots --window-size=1280,6900 --screenshot=/work/docs/screenshots/sample-synthetic.png "http://app:8000/?sample=synthetic"

fixtures:
	$(RUN) python -m app.record_fixtures $(if $(filter 1,$(REFRESH)),--refresh,)

replay:
	$(RUN) python -m tests.replay_run $(ARGS)

eval-validate:
	$(RUN) python -m app.evaluation validate $(ARGS)

eval:
	$(RUN) python -m app.evaluation run $(ARGS)

golden-check:
	$(RUN) pytest -q -p no:cacheprovider tests/test_golden.py

golden-baseline:
	$(RUN) python -m tests.golden_run --write

profile:
	$(RUN) python -m tests.speed_run profile

bench:
	$(RUN) python -m tests.speed_run bench $(if $(RUNS),--runs $(RUNS),)

fixtures-facts:
	$(RUN) python -m app.record_facts $(if $(filter 1,$(REFRESH)),--refresh,)

probe:
	$(RUN) python -m app.probe $(if $(filter 1,$(OUTLINE)),--outline,) $(or $(TICKERS),NVDA)

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

restore-check:
	$(RUN) python -m app.backup restore-check

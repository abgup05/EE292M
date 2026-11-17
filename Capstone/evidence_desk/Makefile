.PHONY: help build up down verify verify-fresh test lint fmt smoke run demo screenshots fixtures lock logs shell clean

export COMPOSE_PROJECT_NAME := ee292m-evidence-desk
export LOCAL_UID := $(shell id -u)
export LOCAL_GID := $(shell id -g)
COMPOSE := docker compose -f docker/compose.yaml
RUN := $(COMPOSE) run --rm --no-deps app

help:
	@echo 'Everyday: build up down verify clean (verify-fresh: clone the committed branch under results/ and verify it)'
	@echo 'Development: test lint fmt smoke logs shell (test T=tests/test_x.py; lint/fmt FILES="src/app/x.py")'
	@echo "Command line: run ARGS='example' or ARGS='run --ticker NVDA --decision \"...\" --claim \"...\"' (synchronous; writes results/<run-id>.json and .md)"
	@echo 'Dependencies: lock'
	@echo 'Demonstration: demo (live NVIDIA example through the HTTP API: real EDGAR, configured engine; writes results/demo-<UTC>.json and .md)'
	@echo 'Screenshots: screenshots (headless Chromium renders the first screen and the sample record into docs/screenshots)'
	@echo 'Fixtures: fixtures (record SEC EDGAR responses for NVIDIA under tests/fixtures/edgar; REFRESH=1 to overwrite)'

build:
	$(COMPOSE) build app

up:
	$(COMPOSE) up --build --force-recreate -d app

down:
	$(COMPOSE) down

verify: build lint test smoke

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

run:
	$(RUN) python -m app.cli $(ARGS)

demo: build
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python -m app.demo

screenshots:
	@mkdir -p docs/screenshots
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) run --rm shots --window-size=1280,720 --screenshot=/work/docs/screenshots/first-screen.png "http://app:8000/" && \
	$(COMPOSE) run --rm shots --window-size=1280,2600 --screenshot=/work/docs/screenshots/sample-run.png "http://app:8000/?sample" && \
	$(COMPOSE) run --rm shots --window-size=390,1400 --screenshot=/work/docs/screenshots/sample-run-phone.png "http://app:8000/?sample"

fixtures:
	$(RUN) python -m app.record_fixtures $(if $(filter 1,$(REFRESH)),--refresh,)

lock:
	$(COMPOSE) build lock
	$(COMPOSE) run --rm --no-deps lock lock

logs:
	$(COMPOSE) logs -f app

shell:
	$(COMPOSE) run --rm --no-deps app sh

clean:
	$(COMPOSE) down --rmi local --remove-orphans

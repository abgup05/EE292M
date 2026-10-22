.PHONY: help build up down verify verify-fresh test lint fmt smoke demo fixtures lock logs shell clean

export COMPOSE_PROJECT_NAME := ee292m-evidence-desk
export LOCAL_UID := $(shell id -u)
export LOCAL_GID := $(shell id -g)
COMPOSE := docker compose -f docker/compose.yaml
RUN := $(COMPOSE) run --rm --no-deps app

help:
	@echo 'Everyday: build up down verify clean (verify-fresh: clone the committed branch under results/ and verify it)'
	@echo 'Development: test lint fmt smoke logs shell'
	@echo 'Dependencies: lock'
	@echo 'Demonstration: demo (live run against the two real seed URLs; writes results/)'
	@echo 'Fixtures: fixtures (record the two real seed pages under tests/fixtures; REFRESH=1 to overwrite)'

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
	$(RUN) pytest -q -p no:cacheprovider tests

lint:
	$(RUN) ruff check --no-cache --config docker/pyproject.toml src tests
	$(RUN) ruff format --check --config docker/pyproject.toml src tests
	$(COMPOSE) run --rm --no-deps jscheck

fmt:
	$(RUN) ruff check --fix --no-cache --config docker/pyproject.toml src tests
	$(RUN) ruff format --config docker/pyproject.toml src tests

smoke:
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python tests/smoke.py

demo:
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python -m app.demo

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

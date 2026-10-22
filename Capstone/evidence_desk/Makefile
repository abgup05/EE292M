.PHONY: help build up down verify test lint fmt smoke demo lock logs shell clean

export COMPOSE_PROJECT_NAME := ee292m-evidence-desk
export LOCAL_UID := $(shell id -u)
export LOCAL_GID := $(shell id -g)
COMPOSE := docker compose -f docker/compose.yaml
RUN := $(COMPOSE) run --rm --no-deps app

help:
	@echo 'Everyday: build up down verify clean'
	@echo 'Development: test lint fmt smoke logs shell'
	@echo 'Dependencies: lock'
	@echo 'Demonstration: demo (live run against the two real seed URLs; writes results/)'

build:
	$(COMPOSE) build app

up:
	$(COMPOSE) up --build --force-recreate -d app

down:
	$(COMPOSE) down

verify: build lint test smoke

test:
	$(RUN) pytest -q -p no:cacheprovider tests

lint:
	$(RUN) ruff check --no-cache src tests
	$(RUN) ruff format --check src tests
	$(COMPOSE) run --rm --no-deps jscheck

fmt:
	$(RUN) ruff check --fix --no-cache src tests
	$(RUN) ruff format src tests

smoke:
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python tests/smoke.py

demo:
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python -m app.demo

lock:
	$(COMPOSE) build lock
	$(COMPOSE) run --rm --no-deps lock lock

logs:
	$(COMPOSE) logs -f app

shell:
	$(COMPOSE) run --rm --no-deps app sh

clean:
	$(COMPOSE) down --rmi local --remove-orphans

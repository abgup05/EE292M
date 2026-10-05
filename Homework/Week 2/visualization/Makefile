.PHONY: help build up down verify test lint fmt smoke lock clean logs shell data

export COMPOSE_PROJECT_NAME := ee292m-week2-radius
export LOCAL_UID := $(shell id -u)
export LOCAL_GID := $(shell id -g)
COMPOSE := docker compose -f docker/compose.yaml

help:
	@echo 'Everyday: build up down verify clean'
	@echo 'Development: test lint fmt smoke logs shell'
	@echo 'Dependencies: lock'
	@echo 'Official data: data (download once and inspect BEA snapshot)'

data:
	$(COMPOSE) run --rm --no-deps app python -m app.acquire

build:
	$(COMPOSE) build app

up:
	$(COMPOSE) up --build --force-recreate -d app

down:
	$(COMPOSE) down

verify: build lint test smoke

test:
	$(COMPOSE) run --rm --no-deps app pytest -q -p no:cacheprovider tests

lint:
	$(COMPOSE) run --rm --no-deps app ruff check --no-cache src tests
	$(COMPOSE) run --rm --no-deps jscheck

fmt:
	$(COMPOSE) run --rm --no-deps app ruff check --fix --no-cache src tests
	$(COMPOSE) run --rm --no-deps app ruff format src tests

smoke:
	$(COMPOSE) up --force-recreate -d app
	@trap '$(COMPOSE) down' EXIT; $(COMPOSE) exec -T app python tests/smoke.py

lock:
	$(COMPOSE) build lock
	$(COMPOSE) run --rm --no-deps lock lock

logs:
	$(COMPOSE) logs -f app

shell:
	$(COMPOSE) run --rm --no-deps app sh

clean:
	$(COMPOSE) down --rmi local --remove-orphans

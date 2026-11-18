.PHONY: help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe replay golden-check golden-baseline profile bench eval eval-validate golden-sheet backup restore-check up-recorded live-walk changes breakdowns lock clean data vercel-deps referee versions-up versions-down versions-status versions-logs pr pr-describe pr-merge site-survey site-run-v1 site-export site-index site-scan site-test site-browse site-check

# make <target> runs the capstone by default; make APP=week2 <target> runs the Week 2 app.
APP ?= capstone
APP_DIR_capstone := Capstone/evidence_desk
APP_DIR_week2 := Homework/Week 2/visualization
APP_DIR := $(APP_DIR_$(APP))

help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe replay golden-check golden-baseline profile bench eval eval-validate golden-sheet backup restore-check up-recorded live-walk changes breakdowns lock clean data vercel-deps:
	@test -n '$(APP_DIR)' || { echo "Unknown APP '$(APP)'; use capstone or week2"; exit 1; }
	@$(MAKE) -C '$(APP_DIR)' $@

# A hostile reading of the capstone by the referee agent (.claude/agents/referee.md), in a fresh
# headless Claude Code session. Run it from a checkout prepared as
# Capstone/evidence_desk/docs/reviews/README.md says, and keep what it prints:
#   make -s referee > referee.json
referee:
	@claude -p "Use the referee agent on this repository. When it has finished, reply with its findings exactly as it wrote them, with nothing added and nothing removed." --model sonnet --allowedTools "Agent" "Task" --max-turns 8 --output-format json < /dev/null

# The tagged versions side by side, each from its own checkout under .claude/worktrees/ and on
# its own port: version N at http://127.0.0.1:87NN (version 3 at 8703). Each keeps its data under
# its own checkout, so none of them reads or writes this checkout's record. This checkout, the
# newest, stays on 8766 (make up).
#   make versions-up                  versions 1 to 11
#   make versions-up VERSIONS="3 7"   only these
VERSIONS ?= 1 2 3 4 5 6 7 8 9 10 11
VERSIONS_DIR := .claude/worktrees

versions-up:
	@for n in $(VERSIONS); do \
	  tag="capstone-v$$n"; dir="$(VERSIONS_DIR)/v$$n"; port=$$(printf '87%02d' "$$n"); \
	  git rev-parse -q --verify "refs/tags/$$tag" > /dev/null || { echo "There is no tag $$tag"; exit 1; }; \
	  test -d "$$dir" || git worktree add --detach "$$dir" "$$tag" > /dev/null 2>&1 || { echo "Could not check out $$tag in $$dir"; exit 1; }; \
	  printf 'services:\n  app:\n    ports: !override\n      - "127.0.0.1:%s:8000"\n' "$$port" > "$(VERSIONS_DIR)/v$$n.port.yaml"; \
	  ( cd "$$dir/Capstone/evidence_desk" && LOCAL_UID=$$(id -u) LOCAL_GID=$$(id -g) docker compose -p "evidence-desk-v$$n" \
	      -f docker/compose.yaml -f "$(CURDIR)/$(VERSIONS_DIR)/v$$n.port.yaml" up --build -d app ) || exit 1; \
	done
	@$(MAKE) -s versions-status

versions-status:
	@for n in $(VERSIONS); do \
	  port=$$(printf '87%02d' "$$n"); \
	  code=$$(curl -s -o /dev/null -m 5 --retry 15 --retry-delay 1 --retry-all-errors -w '%{http_code}' "http://127.0.0.1:$$port/"); \
	  told=$$(curl -s -m 5 "http://127.0.0.1:$$port/api/health" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p'); \
	  echo "version $$n  http://127.0.0.1:$$port  HTTP $$code  the app says it is $${told:-(no version: it has no health address)}"; \
	done

versions-down:
	@for n in $(VERSIONS); do \
	  dir="$(VERSIONS_DIR)/v$$n"; test -d "$$dir" || continue; \
	  ( cd "$$dir/Capstone/evidence_desk" && docker compose -p "evidence-desk-v$$n" -f docker/compose.yaml down ); \
	done

# What each version's container is doing: its state, its published port and its last log lines.
versions-logs:
	@for n in $(VERSIONS); do \
	  dir="$(VERSIONS_DIR)/v$$n"; test -d "$$dir" || continue; \
	  echo "== version $$n"; \
	  ( cd "$$dir/Capstone/evidence_desk" && docker compose -p "evidence-desk-v$$n" -f docker/compose.yaml ps -a --format '{{.Name}}  {{.State}}  {{.Ports}}' \
	      && docker compose -p "evidence-desk-v$$n" -f docker/compose.yaml logs --no-log-prefix --tail 12 app ); \
	done

# main changes only by a pull request its owner has approved. make pr opens the one from this
# branch; make pr-merge merges it with a merge commit, so every tag stays in main's history.
#   make pr TITLE="..." BODY=path/to/body.md
# TITLE and BODY reach the recipes through the environment, so a title may hold any character.
export TITLE BODY
pr:
	@test -n "$$TITLE" && test -f "$$BODY" || { echo 'Usage: make pr TITLE="..." BODY=path/to/body.md'; exit 1; }
	@gh pr create --base main --head "$$(git branch --show-current)" --title "$$TITLE" --body-file "$$BODY"

# make pr-describe gives this branch's open pull request a new title and description, for when
# commits pushed after it was opened have made the old ones incomplete.
pr-describe:
	@test -n "$$TITLE" && test -f "$$BODY" || { echo 'Usage: make pr-describe TITLE="..." BODY=path/to/body.md'; exit 1; }
	@gh pr edit "$$(git branch --show-current)" --title "$$TITLE" --body-file "$$BODY"

pr-merge:
	@gh pr merge "$$(git branch --show-current)" --merge

# The website (the Week 2 app's Vercel project) serves a recorded, read-only snapshot of each
# capstone version N at /vN/ and the table of versions at /versions. The snapshots are exported
# from the running versions (make versions-up; version N at http://127.0.0.1:87NN) by
# tools/snapshots/export.py, in a Python container that uses the standard library only.
#   make site-export                     every tag capstone-vN (integers only) that is running
#   make site-export VERSIONS="13 14"    only these; the others stay as they are
#   make site-survey                     what each instance holds, without writing anything
#   make site-scan                       fail on anything that looks like a secret or personal data
#   make site-check URL=https://...      the deployed site: /, /versions and each /vN/
SITE_DIR := Homework/Week 2/visualization/snapshots
SITE_IMAGE := python:3.14-slim
SITE_TAGS := $(shell git tag -l 'capstone-v*' | sed -n 's/^capstone-v\([0-9][0-9]*\)$$/\1/p' | sort -n)
SITE_VERSIONS = $(if $(filter command line environment,$(origin VERSIONS)),$(VERSIONS),$(SITE_TAGS))
SITE_PY_STDIN := docker run --rm -i --user "$$(id -u):$$(id -g)" -v "$(CURDIR):/repo:ro" -w /repo $(SITE_IMAGE) python -B -I
SITE_PY := docker run --rm --user "$$(id -u):$$(id -g)" -v "$(CURDIR):/repo" -w /repo \
	--add-host=host.docker.internal:host-gateway $(SITE_IMAGE) python -B -I

site-survey:
	@$(SITE_PY) tools/snapshots/export.py --survey --out '$(SITE_DIR)' $(SITE_VERSIONS)

# Version 1's page has no sample. When its instance holds no run, this starts one live run of the
# page's own seed example (tools/snapshots/v1-example.json, copied from its app.js) through its
# HTTP API; with no key in that checkout it plans from a template and quotes extractively.
site-run-v1:
	@curl -sS -f -m 30 -X POST -H 'content-type: application/json' \
	  --data @tools/snapshots/v1-example.json http://127.0.0.1:8701/api/research; echo
	@for i in $$(seq 1 60); do \
	  status=$$(curl -sS -m 10 http://127.0.0.1:8701/api/research | grep -o '"status": *"[a-z]*"' | head -1 | sed 's/.*"\([a-z]*\)"$$/\1/'); \
	  test "$$status" != running && { echo "version 1's newest run: $$status"; exit 0; }; sleep 5; \
	done; echo "the run is still running after 5 minutes"; exit 1

site-export:
	@$(SITE_PY) tools/snapshots/export.py --out '$(SITE_DIR)' $(SITE_VERSIONS)
	@$(MAKE) -s site-index
	@$(MAKE) -s site-scan

site-index:
	@$(SITE_PY) tools/snapshots/versions_page.py docs/versions.md '$(SITE_DIR)'

site-scan:
	@$(SITE_PY) tools/snapshots/scan.py '$(SITE_DIR)' docs/versions.md

site-test:
	@$(SITE_PY) -m unittest discover -s tools/snapshots -p 'test_*.py'
	@docker run --rm -v "$(CURDIR):/repo:ro" -w /repo node:24-slim sh -c \
	  'node --test tools/snapshots/test_shim.mjs && for f in "$(SITE_DIR)"/v*/snapshot.js; do node --check "$$f" || exit 1; done'

# Each snapshot as a browser renders it, served by the Week 2 app on 127.0.0.1:8765 (started
# and stopped here): headless Chromium dumps the DOM of /vN/ and, from version 2 on, /vN/?sample,
# and tools/snapshots/browse_check.py checks the banner, that every call the page made on load
# was answered, and that the recorded run is shown.
SITE_CHROME := docker run --rm --add-host=host.docker.internal:host-gateway zenika/alpine-chrome:124 \
	--headless --no-sandbox --disable-gpu --virtual-time-budget=8000 --dump-dom

site-browse:
	@$(MAKE) -s APP=week2 up > /dev/null
	@trap '$(MAKE) -s APP=week2 down > /dev/null 2>&1' EXIT; \
	curl -s -o /dev/null -m 5 --retry 30 --retry-delay 1 --retry-all-errors http://127.0.0.1:8765/versions || exit 1; \
	failed=0; for n in $(SITE_VERSIONS); do \
	  $(SITE_CHROME) "http://host.docker.internal:8765/v$$n/" 2> /dev/null \
	    | $(SITE_PY_STDIN) tools/snapshots/browse_check.py "$$n" page '$(SITE_DIR)' || failed=1; \
	  test -f '$(SITE_DIR)'/v$$n/sample-run.json || continue; \
	  $(SITE_CHROME) "http://host.docker.internal:8765/v$$n/?sample" 2> /dev/null \
	    | $(SITE_PY_STDIN) tools/snapshots/browse_check.py "$$n" sample '$(SITE_DIR)' || failed=1; \
	done; exit $$failed

site-check:
	@test -n '$(URL)' || { echo 'Usage: make site-check URL=https://ee292m-visualization.vercel.app'; exit 1; }
	@$(SITE_PY) tools/snapshots/check.py '$(URL)' '$(SITE_DIR)'

.PHONY: help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe replay golden-check golden-baseline profile bench eval eval-validate golden-sheet backup restore-check up-recorded live-walk changes breakdowns lock clean data vercel-deps referee versions-up versions-down versions-status versions-logs pr pr-merge

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
#   make versions-up                  versions 1 to 10
#   make versions-up VERSIONS="3 7"   only these
VERSIONS ?= 1 2 3 4 5 6 7 8 9 10
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
pr:
	@test -n '$(TITLE)' && test -f '$(BODY)' || { echo 'Usage: make pr TITLE="..." BODY=path/to/body.md'; exit 1; }
	@gh pr create --base main --head "$$(git branch --show-current)" --title '$(TITLE)' --body-file '$(BODY)'

pr-merge:
	@gh pr merge "$$(git branch --show-current)" --merge

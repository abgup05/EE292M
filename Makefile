.PHONY: help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe replay golden-check golden-baseline profile bench eval eval-validate golden-sheet backup restore-check up-recorded live-walk changes breakdowns lock clean data vercel-deps referee

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

.PHONY: help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe replay golden-check golden-baseline profile bench eval eval-validate backup restore-check up-recorded live-walk changes lock clean data vercel-deps

# make <target> runs the capstone by default; make APP=week2 <target> runs the Week 2 app.
APP ?= capstone
APP_DIR_capstone := Capstone/evidence_desk
APP_DIR_week2 := Homework/Week 2/visualization
APP_DIR := $(APP_DIR_$(APP))

help build up down verify verify-fresh test lint fmt smoke uitest run demo screenshots fixtures fixtures-facts probe replay golden-check golden-baseline profile bench eval eval-validate backup restore-check up-recorded live-walk changes lock clean data vercel-deps:
	@test -n '$(APP_DIR)' || { echo "Unknown APP '$(APP)'; use capstone or week2"; exit 1; }
	@$(MAKE) -C '$(APP_DIR)' $@

.PHONY: help build up down verify test lint fmt smoke lock clean data

APP_DIR := Homework/Week 2/visualization

help build up down verify test lint fmt smoke lock clean data:
	@$(MAKE) -C '$(APP_DIR)' $@

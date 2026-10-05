.PHONY: help build up down verify test lint fmt smoke lock clean

APP_DIR := Homework/Week 2/visualization

help build up down verify test lint fmt smoke lock clean:
	@$(MAKE) -C '$(APP_DIR)' $@

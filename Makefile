.DEFAULT_GOAL := help

PYTHON ?= python
REPORT ?= video-dedup-report.json
PLAN ?= video-dedup-plan.json
HOST ?= 127.0.0.1
PORT ?= 8765
NO_BROWSER ?= 0

NO_BROWSER_ARG := $(if $(filter 1 true yes,$(NO_BROWSER)),--no-browser,)

.PHONY: help start doctor test ui-build ui-bundle ui-lint check

help:
	@echo "Video Dedup commands:"
	@echo "  make start      Start browser review using the default report and plan"
	@echo "  make doctor     Check Python, FFmpeg, and safe-write defaults"
	@echo "  make test       Run the Python test suite"
	@echo "  make check      Run Python tests plus frontend build and lint"
	@echo "  make ui-bundle  Rebuild the checked-in self-contained review UI"
	@echo ""
	@echo "Startup overrides:"
	@echo "  make start REPORT=duplicates.json PLAN=decisions.json PORT=0"
	@echo "  make start NO_BROWSER=1"

start:
	$(PYTHON) video_dedup.py web-review "$(REPORT)" --plan "$(PLAN)" --host "$(HOST)" --port "$(PORT)" $(NO_BROWSER_ARG)

doctor:
	$(PYTHON) video_dedup.py doctor

test:
	$(PYTHON) -m unittest discover -s tests -v

ui-build:
	pnpm -C review-ui build

ui-bundle:
	pnpm -C review-ui bundle

ui-lint:
	pnpm -C review-ui lint

check: test ui-build ui-lint

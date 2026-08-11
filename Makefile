# Cross-platform Makefile for iCode (package: openjiuwen-icode)

.PHONY: help test test-report smoke sync

PYTHON ?= python
TESTFLAGS ?= tests/cli/unit -q
REPORT_DIR ?= reports

help:
	@echo "make sync         - uv sync"
	@echo "make test         - run CLI unit tests"
	@echo "make test-report  - unit tests + HTML report + coverage"
	@echo "make smoke        - import SDK + icode"

sync:
	uv sync

test:
	uv run pytest $(TESTFLAGS)

test-report:
	mkdir -p $(REPORT_DIR)
	uv run pytest tests/cli/unit \
		--cov=openjiuwen_icode \
		--cov-report=term-missing \
		--cov-report=html:$(REPORT_DIR)/coverage \
		--html=$(REPORT_DIR)/test-report.html \
		--self-contained-html \
		-q
	@echo "HTML report: $(REPORT_DIR)/test-report.html"
	@echo "Coverage:    $(REPORT_DIR)/coverage/index.html"

smoke:
	uv run python -c "from openjiuwen.harness import create_deep_agent; from openjiuwen_icode import __version__; from openjiuwen_icode.events import EventBus; print('ok', __version__)"

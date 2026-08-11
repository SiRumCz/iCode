# Cross-platform Makefile for iCode (package: openjiuwen-icode)

.PHONY: help test test-report test-all test-e2e-smoke test-e2e-llm smoke sync \
	acp-smoke extension-test extension-package

PYTHON ?= python
TESTFLAGS ?= tests/cli/unit -q
REPORT_DIR ?= reports
COVERAGE_RC ?= $(CURDIR)/.coveragerc
EXT_DIR ?= extensions/vscode-icode

# Shared pytest args for HTML + coverage reports.
PYTEST_REPORT_ARGS = \
	--cov=openjiuwen_icode \
	--cov-report=term-missing \
	--cov-report=html:$(REPORT_DIR)/coverage \
	--html=$(REPORT_DIR)/test-report.html \
	--self-contained-html

# Paths for the full suite (skip broken auto_harness modules on this SDK).
TEST_ALL_PATHS = tests/cli/unit tests/cli/integration tests/cli/e2e tests/unit_tests
TEST_ALL_IGNORES = \
	--ignore=tests/cli/e2e/test_auto_harness.py \
	--ignore=tests/unit_tests/cli/test_auto_harness_cli.py \
	--ignore=tests/unit_tests/cli/test_auto_harness_repl.py

help:
	@echo "make sync           - uv sync"
	@echo "make test           - run CLI unit tests"
	@echo "make test-report    - unit tests + HTML report + coverage"
	@echo "make test-all       - unit+integration+e2e + HTML report + coverage"
	@echo "make test-e2e-smoke - no-LLM CLI/TUI smoke (subprocess + Pilot)"
	@echo "make test-e2e-llm   - real LLM e2e (needs ICODE_E2E_API_KEY)"
	@echo "make smoke          - import SDK + icode"
	@echo "make acp-smoke      - ACP initialize handshake via icode acp --demo"
	@echo "make extension-test - compile + unit-test VS Code extension"
	@echo "make extension-package - build icode-*.vsix"

sync:
	uv sync

test:
	uv run pytest $(TESTFLAGS)

test-report:
	mkdir -p $(REPORT_DIR)
	uv run pytest tests/cli/unit $(PYTEST_REPORT_ARGS) -q
	@echo "HTML report: $(REPORT_DIR)/test-report.html"
	@echo "Coverage:    $(REPORT_DIR)/coverage/index.html"

test-all:
	mkdir -p $(REPORT_DIR)
	@if [ -z "$$ICODE_E2E_API_KEY" ]; then \
		echo "Note: ICODE_E2E_API_KEY unset — LLM e2e tests will be skipped with a reminder."; \
	fi
	# COVERAGE_PROCESS_START lets subprocess CLI runs join coverage (needs
	# coverage.process_startup via the .pth installed below if missing).
	@uv run python -c "import pathlib,site,coverage; p=pathlib.Path(site.getsitepackages()[0])/'icode_coverage_startup.pth'; p.write_text('import coverage; coverage.process_startup()\n'); print('coverage startup:', p)"
	COVERAGE_PROCESS_START=$(COVERAGE_RC) \
	uv run pytest $(TEST_ALL_PATHS) $(TEST_ALL_IGNORES) $(PYTEST_REPORT_ARGS) -q
	@echo "HTML report: $(REPORT_DIR)/test-report.html"
	@echo "Coverage:    $(REPORT_DIR)/coverage/index.html"

test-e2e-smoke:
	uv run pytest tests/cli/e2e -m smoke -q \
		--ignore=tests/cli/e2e/test_auto_harness.py

test-e2e-llm:
	@if [ -z "$$ICODE_E2E_API_KEY" ]; then \
		echo "Reminder: export ICODE_E2E_API_KEY=... (see tests/cli/e2e/models.yaml)"; \
	fi
	uv run pytest tests/cli/e2e -m llm -v

smoke:
	uv run python -c "from openjiuwen.harness import create_deep_agent; from openjiuwen_icode import __version__; from openjiuwen_icode.events import EventBus; print('ok', __version__)"

acp-smoke:
	uv run python scripts/acp_smoke.py

extension-test:
	cd $(EXT_DIR) && npm install && npm test

extension-package:
	cd $(EXT_DIR) && npm install && npm run package
	@ls -la $(EXT_DIR)/*.vsix

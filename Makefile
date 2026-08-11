# Cross-platform Makefile for iCode (package: openjiuwen-icode)

.PHONY: help test smoke sync

PYTHON ?= python
TESTFLAGS ?= tests/cli/unit -q

help:
	@echo "make sync   - uv sync (editable openjiuwen + icode)"
	@echo "make test   - run CLI unit tests"
	@echo "make smoke  - import SDK + icode"

sync:
	uv sync

test:
	uv run pytest $(TESTFLAGS)

smoke:
	uv run python -c "from openjiuwen.harness import create_deep_agent; from openjiuwen_icode import __version__; from openjiuwen_icode.events import EventBus; print('ok', __version__)"

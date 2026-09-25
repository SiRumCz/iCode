# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""E2E-03 / E2E-04: ``--output-format json`` and ``stream-json`` (LLM)."""

from __future__ import annotations

import json

import pytest

from tests.cli.e2e.conftest import ModelPreset, run_cli


pytestmark = pytest.mark.llm


def test_run_json_format(
    model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    result = run_cli(
        "run", "-f", "json", "What is 2+2?", env=llm_env
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "result" in data and len(data["result"]) > 0
    assert isinstance(data["chunks"], int) and data["chunks"] > 0
    assert "model" in data


def test_run_stream_json_format(
    model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    result = run_cli(
        "run", "-f", "stream-json", "Say hello", env=llm_env
    )
    assert result.returncode == 0, result.stderr
    lines = [
        line
        for line in result.stdout.strip().split("\n")
        if line.strip()
    ]
    assert len(lines) >= 1

    # EventBus JSONL: one object per event (see host.bus_runner.event_to_dict).
    types: set[str] = set()
    for line in lines:
        data = json.loads(line)
        assert "type" in data
        assert "event_id" in data
        assert "timestamp" in data
        types.add(data["type"])
    assert "TurnStarted" in types
    assert "TurnFinished" in types or "TurnFailed" in types
    assert "AgentMessage" in types

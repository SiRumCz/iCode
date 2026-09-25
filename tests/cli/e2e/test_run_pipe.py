# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""E2E-05: Pipe mode via stdin (LLM)."""

from __future__ import annotations

import pytest

from tests.cli.e2e.conftest import ModelPreset, run_cli


pytestmark = pytest.mark.llm


def test_run_pipe_mode(
    model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    result = run_cli(
        "run",
        "-",
        input="What is 3+3? Reply with just the number.",
        env=llm_env,
    )
    assert result.returncode == 0, result.stderr
    assert "6" in result.stdout


def test_run_auto_stdin_detection(
    model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    result = run_cli(
        "run",
        input="What is 3+3? Reply with just the number.",
        env=llm_env,
    )
    assert result.returncode == 0, result.stderr
    assert "6" in result.stdout

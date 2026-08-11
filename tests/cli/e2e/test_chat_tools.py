# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""E2E-07: Agent tool calls (Bash / File / Grep) — LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.e2e.conftest import (
    ModelPreset,
    agent_message_text,
    run_cli,
)


pytestmark = pytest.mark.llm


def test_tool_bash(
    tmp_path: Path, model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    result = run_cli(
        "run",
        "Run 'echo hello_from_test' and tell me the output",
        cwd=str(tmp_path),
        env=llm_env,
    )
    assert result.returncode == 0, result.stderr
    assert "hello_from_test" in result.stdout


def test_tool_read_file(
    tmp_path: Path, model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_text("line1\nline2\nline3\n")

    result = run_cli(
        "run",
        f"Read the file {test_file} and show its contents",
        cwd=str(tmp_path),
        env=llm_env,
    )
    assert result.returncode == 0, result.stderr
    assert "line1" in result.stdout
    assert "line2" in result.stdout


def test_tool_grep(
    tmp_path: Path, model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    (tmp_path / "code.py").write_text(
        "def hello():\n    return 'world'\n",
        encoding="utf-8",
    )

    result = run_cli(
        "run",
        "Use a search/grep tool to find the string 'def hello' "
        "in the current working directory. In your final answer, "
        "print the exact filename that contains it (code.py).",
        cwd=str(tmp_path),
        env=llm_env,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    joined = agent_message_text(out)
    assert "code.py" in out or "code.py" in joined, out
    assert (
        "ToolCall" in out
        or "grep" in out.lower()
        or "search" in out.lower()
    ), out

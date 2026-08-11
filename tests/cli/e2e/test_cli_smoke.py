# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""No-LLM CLI smoke tests (true subprocess)."""

from __future__ import annotations

import os
import re
import shutil
import tempfile

import pytest

from tests.cli.e2e.conftest import PROJECT_ROOT, run_cli, run_icode


pytestmark = pytest.mark.smoke


def test_module_version() -> None:
    result = run_cli("--version", timeout=15)
    assert result.returncode == 0
    out = (result.stdout + result.stderr).lower()
    assert "icode" in out or "openjiuwen" in out
    assert re.search(r"\d+\.\d+\.\d+", result.stdout + result.stderr)
    assert "traceback" not in out


def test_icode_console_script_version() -> None:
    assert shutil.which("icode"), "icode console script missing (uv sync?)"
    result = run_icode("--version", timeout=15)
    assert result.returncode == 0
    assert re.search(r"\d+\.\d+\.\d+", result.stdout + result.stderr)


def test_help_lists_core_commands() -> None:
    result = run_icode("--help", timeout=15)
    assert result.returncode == 0
    text = result.stdout.lower()
    assert "tui" in text or "chat" in text
    assert "run" in text


def test_tui_help() -> None:
    result = run_icode("tui", "--help", timeout=15)
    assert result.returncode == 0
    assert "--demo" in result.stdout


def test_run_help() -> None:
    result = run_icode("run", "--help", timeout=15)
    assert result.returncode == 0


def test_bad_command_exits_nonzero() -> None:
    result = run_icode("not-a-real-command", timeout=15)
    assert result.returncode != 0


def test_run_without_api_key_fails_cleanly() -> None:
    """Missing credentials → non-zero exit and an API key hint."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("OPENJIUWEN_", "ICODE_"))
    }
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["HOME"] = "/tmp/icode_e2e_smoke_no_key"
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_cli(
            "run", "hello", env=env, timeout=20, cwd=tmpdir
        )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "api key" in combined

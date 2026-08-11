# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""E2E-14: API error handling (no valid LLM key required)."""

from __future__ import annotations

import os
import tempfile

import pytest

from tests.cli.e2e.conftest import PROJECT_ROOT, run_cli


pytestmark = pytest.mark.smoke


def test_invalid_api_key() -> None:
    """Invalid API key produces empty output or error message."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("OPENJIUWEN_", "ICODE_"))
    }
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["OPENJIUWEN_API_KEY"] = "invalid_key_xyz"
    env["ICODE_API_KEY"] = "invalid_key_xyz"
    env["OPENJIUWEN_API_BASE"] = "https://api.openlux.ai/v1"
    env["ICODE_API_BASE"] = env["OPENJIUWEN_API_BASE"]
    env["OPENJIUWEN_MODEL"] = "deepseek-v4-pro"
    env["ICODE_MODEL"] = "deepseek-v4-pro"
    env["OPENJIUWEN_PROVIDER"] = "OpenAI"
    env["ICODE_PROVIDER"] = "OpenAI"
    env["HOME"] = "/tmp/icode_e2e_invalid_key"
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_cli(
            "run", "hello", env=env, cwd=tmpdir, timeout=60
        )
    combined = (result.stderr + result.stdout).lower()
    has_error_kw = any(
        kw in combined
        for kw in ["401", "unauthorized", "error", "failed", "no output"]
    )
    has_empty_output = len(result.stdout.strip()) == 0
    assert has_error_kw or has_empty_output or result.returncode != 0, (
        f"Expected error or empty output, got: {result.stdout[:200]!r}"
    )


def test_no_api_key() -> None:
    """Missing API key -> non-zero exit, helpful message."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("OPENJIUWEN_", "ICODE_"))
    }
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["HOME"] = "/tmp/icode_e2e_no_key"
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_cli(
            "run", "hello", env=env, timeout=15, cwd=tmpdir
        )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "api key" in combined

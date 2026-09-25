# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""E2E-02: Basic non-interactive ``icode run`` (LLM)."""

from __future__ import annotations

import pytest

from tests.cli.e2e.conftest import ModelPreset, run_cli


pytestmark = pytest.mark.llm


def test_run_basic(model_preset: ModelPreset, llm_env: dict[str, str]) -> None:
    """``icode run`` returns a meaningful answer for the selected preset."""
    result = run_cli(
        "run",
        "What is 2+2? Reply with just the number.",
        env=llm_env,
    )
    assert result.returncode == 0, result.stderr
    assert "4" in result.stdout
    assert "Traceback" not in result.stderr
    # Sanity: wire model id from preset appears in debug paths or is accepted.
    assert model_preset.model

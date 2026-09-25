# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""E2E session run smoke (LLM).

SessionStore JSON persistence is covered in ``tests/cli/unit/test_session_store.py``.
This file only checks that a real ``icode run`` completes for the selected model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.e2e.conftest import ModelPreset, run_cli


pytestmark = pytest.mark.llm


def test_run_completes(
    tmp_path: Path, model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    result = run_cli(
        "run",
        "Reply with exactly: ok",
        cwd=str(tmp_path),
        env=llm_env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert "Traceback" not in result.stderr

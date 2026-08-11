# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""E2E-13: OPENJIUWEN.md affects agent behavior (LLM)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.cli.e2e.conftest import (
    ModelPreset,
    agent_message_text,
    run_cli,
)


pytestmark = pytest.mark.llm


def test_memory_affects_behavior(
    tmp_path: Path, model_preset: ModelPreset, llm_env: dict[str, str]
) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=False,
    )
    (tmp_path / "OPENJIUWEN.md").write_text(
        "# Project rules (mandatory)\n"
        "- Your entire reply MUST contain the exact token "
        "MAGIC_MARKER_XYZ somewhere.\n"
        "- Prefer ending the reply with MAGIC_MARKER_XYZ on its own line.\n",
        encoding="utf-8",
    )

    result = run_cli(
        "run",
        "Say hello in one short sentence. "
        "Obey every rule in Project Memory / OPENJIUWEN.md.",
        cwd=str(tmp_path),
        env=llm_env,
    )
    assert result.returncode == 0, result.stderr
    joined = agent_message_text(result.stdout)
    assert "MAGIC_MARKER_XYZ" in joined, result.stdout

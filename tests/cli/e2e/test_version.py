# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""E2E-01: ``icode --version`` / module entry."""

from __future__ import annotations

import re

import pytest

from tests.cli.e2e.conftest import run_cli, run_icode


pytestmark = pytest.mark.smoke


def test_version() -> None:
    """--version prints the version string and exits cleanly."""
    result = run_cli("--version", timeout=10)
    assert result.returncode == 0
    combined = (result.stdout + result.stderr).lower()
    assert "icode" in combined or "openjiuwen" in combined
    assert re.search(r"\d+\.\d+\.\d+", result.stdout + result.stderr)
    assert "traceback" not in combined


def test_icode_script_version() -> None:
    result = run_icode("--version", timeout=10)
    assert result.returncode == 0
    assert re.search(r"\d+\.\d+\.\d+", result.stdout + result.stderr)

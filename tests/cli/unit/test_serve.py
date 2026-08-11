# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for browser TUI serve helpers."""

from __future__ import annotations

from openjiuwen_icode.serve import (
    build_tui_command,
    effective_public_url,
)


def test_build_tui_command_includes_demo() -> None:
    cmd = build_tui_command(demo=True)
    assert "tui" in cmd
    assert "--demo" in cmd


def test_build_tui_command_with_project() -> None:
    cmd = build_tui_command(project="/tmp/proj")
    assert "--project" in cmd
    assert "/tmp/proj" in cmd
    assert cmd.rstrip().endswith("tui") or " tui" in cmd


def test_effective_public_url_passthrough() -> None:
    assert (
        effective_public_url(
            host="0.0.0.0",
            port=8000,
            public_url="http://example:8000/",
        )
        == "http://example:8000"
    )


def test_effective_public_url_wildcard_without_override() -> None:
    assert (
        effective_public_url(host="0.0.0.0", port=8000, public_url=None)
        is None
    )

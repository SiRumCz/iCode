# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for /subagents status formatting."""

from __future__ import annotations

from types import SimpleNamespace

from openjiuwen_icode.features.subagent_status import (
    collect_subagent_items,
    format_subagent_status_text,
)
from openjiuwen.harness.tools.subagent.session_tools import SessionToolkit


def test_collect_merges_toolkit_rows() -> None:
    toolkit = SessionToolkit()
    toolkit.upsert_running(
        "task-1",
        "sess_sub_1",
        "find auth module",
        subagent_type="explore_agent",
    )
    agent = SimpleNamespace(_session_toolkit=toolkit)
    items = collect_subagent_items(agent, "parent-sess")
    assert len(items) == 1
    assert items[0]["source"] == "async"
    assert items[0]["subagent_type"] == "explore_agent"


def test_format_empty_session() -> None:
    text = format_subagent_status_text(None, "cli-abc")
    assert "No sub-agent activity" in text

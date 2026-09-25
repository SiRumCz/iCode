# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for /subagents status formatting."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    )
    agent = SimpleNamespace(_session_toolkit=toolkit)
    items = collect_subagent_items(agent, "parent-sess")
    assert len(items) == 1
    assert items[0]["source"] == "async"
    assert items[0]["task_id"] == "task-1"
    # SessionTaskRow on agent-core icode has no subagent_type field.
    assert items[0]["subagent_type"] == ""


def test_format_empty_session() -> None:
    text = format_subagent_status_text(None, "cli-abc")
    assert "No sub-agent activity" in text


def test_audit_entries_formatting(tmp_path: Path) -> None:
    sess = "cli-audit"
    audit_dir = tmp_path / "sessions" / sess
    audit_dir.mkdir(parents=True)
    log = audit_dir / "sub_agents.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "phase": "started",
                        "agent_name": "code_agent",
                        "invocation_id": "inv-1",
                        "transport": "async",
                        "ok": True,
                    }
                ),
                "not-json",
                json.dumps(
                    {
                        "phase": "finished",
                        "agent_name": "code_agent",
                        "invocation_id": "inv-1",
                        "transport": "async",
                        "ok": True,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    fake_project = SimpleNamespace(sessions_dir=tmp_path / "sessions")
    with patch(
        "openjiuwen_icode.paths.IcodeProject.open",
        return_value=fake_project,
    ):
        items = collect_subagent_items(None, sess)
        text = format_subagent_status_text(None, sess)

    assert len(items) == 2
    assert items[0]["source"] == "audit"
    assert "Recent lifecycle" in text
    assert "inv-1" in text
    assert "[async]" in text
    assert "code_agent" in text

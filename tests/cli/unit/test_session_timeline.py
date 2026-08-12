# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for session timeline reconstruction from events.jsonl."""

from __future__ import annotations

from pathlib import Path

from openjiuwen_icode.features.session_timeline import (
    session_timeline,
    timeline_from_events,
)
from openjiuwen_icode.storage.event_log import SessionEventLog
from openjiuwen_icode.storage.session_store import StoredMessage


def test_timeline_merges_thinking_and_tools() -> None:
    events = [
        {"type": "UserMessage", "text": "hi"},
        {"type": "AgentThinking", "text": "think "},
        {"type": "AgentThinking", "text": "more"},
        {
            "type": "ToolCallStart",
            "tool_name": "read_file",
            "tool_args": {"path": "a.py"},
        },
        {
            "type": "ToolCallResult",
            "tool_name": "read_file",
            "tool_success": True,
            "result": {"ok": True},
        },
        {"type": "UsageUpdate", "input_tokens": 1, "output_tokens": 2},
        {"type": "AgentMessage", "text": "Hello "},
        {"type": "AgentMessage", "text": "world"},
        {"type": "TurnFinished"},
    ]
    rows = timeline_from_events(events)
    assert [r["role"] for r in rows] == [
        "user",
        "thought",
        "tool",
        "tool",
        "system",
        "assistant",
    ]
    assert rows[1]["content"] == "think more"
    assert rows[2]["title"] == "▶ read_file"
    assert "a.py" in rows[2]["content"]
    assert rows[3]["title"] == "■ read_file completed"
    assert rows[4]["content"] == "Tokens in=1 out=2"
    assert rows[5]["content"] == "Hello world"


def test_session_timeline_reads_events_jsonl(tmp_path: Path) -> None:
    sid = "acp-tl1"
    log = SessionEventLog.for_session(tmp_path, sid)
    log.append({"type": "UserMessage", "text": "q", "session_id": sid})
    log.append(
        {
            "type": "ToolCallStart",
            "tool_name": "list_files",
            "tool_args": {"path": "."},
            "session_id": sid,
        }
    )
    log.append(
        {
            "type": "ToolCallResult",
            "tool_name": "list_files",
            "tool_success": True,
            "result": "ok",
            "session_id": sid,
        }
    )
    log.append({"type": "AgentMessage", "text": "done", "session_id": sid})
    rows = session_timeline(tmp_path, sid, fallback_messages=[])
    assert any(r["role"] == "tool" and r["title"].startswith("▶") for r in rows)
    assert any(r["role"] == "assistant" and r["content"] == "done" for r in rows)


def test_session_timeline_falls_back_to_messages(tmp_path: Path) -> None:
    rows = session_timeline(
        tmp_path,
        "missing",
        fallback_messages=[
            StoredMessage(role="user", content="u", timestamp="t"),
            StoredMessage(role="assistant", content="a", timestamp="t"),
        ],
    )
    assert rows == [
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ]

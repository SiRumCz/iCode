# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for session event log + OpenCode-compatible export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjiuwen_icode.events.bus import EventBus
from openjiuwen_icode.events.types import (
    ToolCallStart,
    TurnStarted,
)
from openjiuwen_icode.branding import PRODUCT_NAME
from openjiuwen_icode.export.opencode import (
    _ms,
    _parse_model,
    _sanitize_obj,
    _sanitize_text,
    _tool_title,
    build_opencode_export,
    export_session_opencode,
    resolve_export_agent_profile,
    write_opencode_export,
)
from openjiuwen_icode.storage.event_log import SessionEventLog
from openjiuwen_icode.storage.session_store import (
    SessionStore,
    StoredMessage,
    StoredSession,
)


class TestSessionEventLog:
    def test_appends_and_reads(self, tmp_path: Path) -> None:
        log = SessionEventLog.for_session(tmp_path, "cli-abc")
        bus = EventBus()
        bus.add_tap(log.record_event)

        import asyncio

        async def _run() -> None:
            await bus.publish(
                TurnStarted(text="hi", session_id="cli-abc")
            )
            await bus.publish(
                ToolCallStart(
                    tool_name="bash",
                    tool_args={"command": "pwd"},
                    tool_call_id="call-1",
                    session_id="cli-abc",
                )
            )

        asyncio.run(_run())
        rows = log.read_all()
        assert len(rows) == 2
        assert rows[0]["type"] == "TurnStarted"
        assert rows[1]["tool_call_id"] == "call-1"


class TestOpenCodeHelpers:
    def test_ms_and_parse_model(self) -> None:
        assert _ms(1_700_000_000) == 1_700_000_000_000
        assert _ms(1_700_000_000_000) == 1_700_000_000_000
        assert _ms("2026-01-01T00:00:00+00:00") > 0
        assert _ms("") > 0
        assert _ms(None) > 0
        assert _parse_model("openai/gpt-4o") == ("openai", "gpt-4o")
        assert _parse_model("solo") == ("unknown", "solo")
        assert _parse_model("")[1] == "unknown"

    def test_sanitize_and_tool_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        home = str(Path.home())
        assert _sanitize_text(f"{home}/proj", enabled=False) == f"{home}/proj"
        out = _sanitize_text(f"{home}/secret/file.py", enabled=True)
        assert "~" in out or "[redacted:path]" in out
        assert _sanitize_obj({"a": f"{home}/x", "b": [1]}, enabled=True)["b"] == [1]
        assert _tool_title("bash", {"command": "ls"}) == "bash ls"
        assert _tool_title("read", {}) == "read"

    def test_resolve_export_agent_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = StoredSession(
            session_id="s",
            model="m",
            created_at="t",
            agent_profile="from-session",
        )
        assert resolve_export_agent_profile(session) == "from-session"
        assert (
            resolve_export_agent_profile(session, agent_profile="override")
            == "override"
        )
        monkeypatch.setattr(
            "openjiuwen_icode.export.opencode.active_agent_profile_id",
            lambda: "",
        )
        empty = StoredSession(session_id="s", model="m", created_at="t")
        assert resolve_export_agent_profile(empty) == "code"


class TestOpenCodeExport:
    def test_text_only_from_session_store(self) -> None:
        session = StoredSession(
            session_id="cli-text",
            model="deepseek/deepseek-v4-pro",
            created_at="2026-01-01T00:00:00+00:00",
            title="demo",
            messages=[
                StoredMessage(
                    role="user",
                    content="hello",
                    timestamp="2026-01-01T00:00:01+00:00",
                ),
                StoredMessage(
                    role="assistant",
                    content="world",
                    timestamp="2026-01-01T00:00:02+00:00",
                ),
            ],
        )
        doc = build_opencode_export(session=session, directory="/tmp/proj")
        assert set(doc) >= {"info", "messages", "harness"}
        assert doc["harness"]["fidelity"] == "text"
        assert doc["info"]["id"] == "cli-text"
        assert "name=None" not in doc["info"]["title"]
        assert len(doc["messages"]) == 2
        assert doc["messages"][0]["info"]["role"] == "user"
        assert doc["messages"][0]["parts"][0]["type"] == "text"
        assert doc["messages"][1]["parts"][0]["type"] == "step-start"
        assert any(
            p["type"] == "text" and p.get("text") == "world"
            for p in doc["messages"][1]["parts"]
        )

    def test_export_agent_profile_and_product(self) -> None:
        session = StoredSession(
            session_id="cli-agent",
            model="deepseek-v4-pro",
            created_at="2026-01-01T00:00:00+00:00",
            title="demo",
            agent_profile="code",
            messages=[
                StoredMessage(
                    role="user",
                    content="hi",
                    timestamp="2026-01-01T00:00:01+00:00",
                ),
            ],
        )
        doc = build_opencode_export(session=session)
        assert doc["messages"][0]["info"]["agent"] == "code"
        assert doc["harness"]["product"] == PRODUCT_NAME
        assert doc["harness"]["agent_profile"] == "code"

    def test_export_title_ignores_corrupt_llm_title(self) -> None:
        session = StoredSession(
            session_id="cli-bad",
            model="deepseek-v4-pro",
            created_at="2026-01-01T00:00:00+00:00",
            title="role='assistant' content='' name=None…",
            messages=[
                StoredMessage(
                    role="user",
                    content="看看 agent-core 架构",
                    timestamp="2026-01-01T00:00:01+00:00",
                ),
            ],
        )
        doc = build_opencode_export(session=session, directory="/tmp")
        assert "agent-core" in doc["info"]["title"]
        assert "name=None" not in doc["info"]["title"]

    def test_full_from_events(self) -> None:
        session = StoredSession(
            session_id="cli-full",
            model="openai/gpt-4o",
            created_at="2026-01-01T00:00:00+00:00",
            title="tools",
            messages=[],
        )
        events = [
            {
                "type": "TurnStarted",
                "timestamp": 1_700_000_000.0,
                "text": "list files",
                "session_id": "cli-full",
            },
            {
                "type": "ToolCallStart",
                "timestamp": 1_700_000_001.0,
                "tool_name": "bash",
                "tool_args": {"command": "ls"},
                "tool_call_id": "call-abc",
                "session_id": "cli-full",
            },
            {
                "type": "ToolCallResult",
                "timestamp": 1_700_000_002.0,
                "tool_name": "bash",
                "result": "a.txt\n",
                "tool_call_id": "call-abc",
                "tool_success": True,
                "session_id": "cli-full",
            },
            {
                "type": "AgentMessage",
                "timestamp": 1_700_000_003.0,
                "text": "done",
                "session_id": "cli-full",
            },
            {
                "type": "ModelUsage",
                "timestamp": 1_700_000_004.0,
                "input_tokens": 10,
                "output_tokens": 4,
                "call_index": 1,
                "session_id": "cli-full",
            },
            {
                "type": "TurnFinished",
                "timestamp": 1_700_000_005.0,
                "session_id": "cli-full",
            },
        ]
        doc = build_opencode_export(
            session=session, events=events, directory="/work"
        )
        assert doc["harness"]["fidelity"] == "full"
        assert len(doc["messages"]) == 2
        assistant_parts = doc["messages"][1]["parts"]
        types = [p["type"] for p in assistant_parts]
        assert "step-start" in types
        assert "tool" in types
        assert "text" in types
        assert "step-finish" in types
        tool = next(p for p in assistant_parts if p["type"] == "tool")
        assert tool["callID"] == "call-abc"
        assert tool["state"]["status"] == "completed"
        assert tool["state"]["output"] == "a.txt\n"
        finish = next(p for p in assistant_parts if p["type"] == "step-finish")
        assert finish["tokens"]["input"] == 10
        assert finish["tokens"]["output"] == 4

    def test_export_writes_file(self, tmp_path: Path) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("cli-e1", "demo-model")
        store.add_message("user", "ping")
        store.add_message("assistant", "pong")
        log = SessionEventLog.for_session(tmp_path, "cli-e1")
        log.append(
            {
                "type": "TurnStarted",
                "timestamp": 100.0,
                "text": "ping",
                "session_id": "cli-e1",
            }
        )
        log.append(
            {
                "type": "AgentMessage",
                "timestamp": 101.0,
                "text": "pong",
                "session_id": "cli-e1",
            }
        )
        log.append(
            {
                "type": "TurnFinished",
                "timestamp": 102.0,
                "session_id": "cli-e1",
            }
        )
        doc = export_session_opencode(store, "cli-e1", directory="/x")
        out = write_opencode_export(doc, tmp_path / "cli-e1" / "out.json")
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["info"]["id"] == "cli-e1"
        assert loaded["messages"][0]["parts"][0]["text"] == "ping"


@pytest.mark.asyncio
async def test_tool_tracker_includes_call_id() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from openjiuwen_icode.rails.tool_tracker import ToolTrackingRail

    session = SimpleNamespace(write_stream=AsyncMock())
    ctx = SimpleNamespace(
        session=session,
        inputs=SimpleNamespace(
            tool_name="bash",
            tool_args={"command": "echo"},
            tool_call=SimpleNamespace(id="tc-99"),
            tool_result="ok",
        ),
    )
    rail = ToolTrackingRail()
    await rail.before_tool_call(ctx)
    await rail.after_tool_call(ctx)
    start_payload = session.write_stream.await_args_list[0].args[0].payload
    end_payload = session.write_stream.await_args_list[1].args[0].payload
    assert start_payload["tool_call_id"] == "tc-99"
    assert end_payload["tool_call_id"] == "tc-99"


@pytest.mark.asyncio
async def test_token_tracker_emits_model_usage() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from openjiuwen_icode.rails.token_tracker import TokenTrackingRail

    session = SimpleNamespace(write_stream=AsyncMock())
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=2)
    ctx = SimpleNamespace(
        session=session,
        inputs=SimpleNamespace(
            response=SimpleNamespace(usage=usage),
        ),
    )
    rail = TokenTrackingRail()
    await rail.after_model_call(ctx)
    chunk = session.write_stream.await_args.args[0]
    assert chunk.type == "model_usage"
    assert chunk.payload["input_tokens"] == 3
    assert chunk.payload["output_tokens"] == 2
    assert rail.get_summary()["last_input_tokens"] == 3

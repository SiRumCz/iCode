# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Sub-agent lifecycle chunks, mapping, and settings-backed concurrency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjiuwen.core.session.stream.base import OutputSchema
from openjiuwen_icode.events import (
    SubAgentFailed,
    SubAgentFinished,
    SubAgentStarted,
    chunk_to_events,
)
from openjiuwen_icode.subagents import load_subagent_concurrency_config
from openjiuwen.harness.tools.subagent.lifecycle import record_subagent_audit


class TestSubagentChunkMapping:
    def test_lifecycle_started_chunk_carries_ids(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="subagent.started",
                index=0,
                payload={
                    "agent_name": "explore_agent",
                    "task": "find auth",
                    "invocation_id": "inv-abc",
                    "sub_session_id": "sess_sub_x",
                    "transport": "sync",
                },
            )
        )
        assert len(events) == 1
        ev = events[0]
        assert isinstance(ev, SubAgentStarted)
        assert ev.invocation_id == "inv-abc"
        assert ev.transport == "sync"

    def test_lifecycle_finished_failure_maps_to_subagent_failed(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="subagent.finished",
                index=0,
                payload={
                    "agent_name": "plan_agent",
                    "result": "timeout",
                    "ok": False,
                    "invocation_id": "inv-1",
                    "transport": "async",
                },
            )
        )
        from openjiuwen_icode.events import SubAgentPaused

        assert len(events) == 2
        assert isinstance(events[0], SubAgentFailed)
        assert isinstance(events[1], SubAgentPaused)
        assert "timeout" in events[0].error

    def test_task_tool_result_does_not_emit_premature_finished(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="tool_result",
                index=0,
                payload={
                    "tool_name": "task_tool",
                    "tool_success": True,
                    "tool_result": "done",
                },
            )
        )
        assert not any(isinstance(e, SubAgentFinished) for e in events)

    def test_legacy_agent_tool_still_finishes(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="tool_result",
                index=0,
                payload={
                    "tool_name": "code_agent",
                    "tool_result": "ok",
                },
            )
        )
        assert any(isinstance(e, SubAgentFinished) for e in events)

    def test_sessions_spawn_failure_emits_subagent_failed(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="tool_result",
                index=0,
                payload={
                    "tool_name": "sessions_spawn",
                    "tool_success": False,
                    "tool_error": "limit",
                    "tool_args": {"subagent_type": "explore_agent"},
                },
            )
        )
        failed = [e for e in events if isinstance(e, SubAgentFailed)]
        assert len(failed) == 1
        assert failed[0].agent_name == "explore_agent"


    def test_subagent_tool_chunk_maps_to_events(self) -> None:
        from openjiuwen_icode.events import (
            SubAgentToolCallResult,
            SubAgentToolCallStart,
        )

        start = chunk_to_events(
            OutputSchema(
                type="subagent.tool_call",
                index=0,
                payload={
                    "agent_name": "explore_agent",
                    "tool_name": "read_file",
                    "invocation_id": "inv-1",
                    "transport": "sync",
                },
            )
        )
        assert isinstance(start[0], SubAgentToolCallStart)
        end = chunk_to_events(
            OutputSchema(
                type="subagent.tool_result",
                index=0,
                payload={
                    "agent_name": "explore_agent",
                    "tool_name": "read_file",
                    "result": "ok",
                },
            )
        )
        assert isinstance(end[0], SubAgentToolCallResult)

    def test_audit_appends_jsonl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ICODE_PROJECT", str(tmp_path / "proj"))
        record_subagent_audit(
            "parent-1",
            phase="started",
            agent_name="explore_agent",
            invocation_id="inv-1",
        )
        log = (
            tmp_path
            / "proj"
            / "sessions"
            / "parent-1"
            / "sub_agents.jsonl"
        )
        assert log.exists()
        row = json.loads(log.read_text(encoding="utf-8").strip())
        assert row["phase"] == "started"
        assert row["invocation_id"] == "inv-1"


class TestSubagentSettings:
    def test_load_concurrency_from_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "subagents": {
                        "max_total": 4,
                        "max_per_type": 3,
                        "per_agent": {"explore_agent": 1},
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.delenv("OPENJIUWEN_SUBAGENT_MAX_TOTAL", raising=False)
        monkeypatch.delenv("OPENJIUWEN_SUBAGENT_MAX_PER_TYPE", raising=False)
        from openjiuwen_icode.agent import config as agent_config

        monkeypatch.setattr(agent_config, "SETTINGS_PATH", settings)
        loaded = load_subagent_concurrency_config()
        assert loaded.max_total == 4
        assert loaded.per_agent_default == 3
        assert loaded.per_agent["explore_agent"] == 1

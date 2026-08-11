# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""AWAITING sub-agent marker and EventBus mapping."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openjiuwen.core.session.stream.base import OutputSchema
from openjiuwen_icode.events import (
    SubAgentsAwaiting,
    SubAgentsIdle,
    chunk_to_events,
)
from openjiuwen.harness.tools.subagent.awaiting import (
    list_running_async_tasks,
    write_awaiting_marker,
)
from openjiuwen.harness.tools.subagent.session_tools import SessionToolkit


class TestAwaitingMapping:
    def test_maps_awaiting_chunk(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="subagent.awaiting",
                index=0,
                payload={"count": 1, "items": [{"task_id": "abc"}]},
            )
        )
        assert len(events) == 1
        assert isinstance(events[0], SubAgentsAwaiting)
        assert events[0].count == 1

    def test_maps_idle_chunk(self) -> None:
        events = chunk_to_events(
            OutputSchema(type="subagent.idle", index=0, payload={})
        )
        assert isinstance(events[0], SubAgentsIdle)


class TestAwaitingMarker:
    def test_marker_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ICODE_PROJECT", str(tmp_path / "proj"))
        write_awaiting_marker(
            "sess-1",
            [{"task_id": "t1", "invocation_id": "t1"}],
        )
        path = (
            tmp_path
            / "proj"
            / "sessions"
            / "sess-1"
            / "awaiting_subagents.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["invocation_ids"] == ["t1"]


def test_list_running_filters_completed() -> None:
    toolkit = SessionToolkit()
    toolkit.upsert_running("a", "sub1", "job", subagent_type="plan_agent")
    toolkit.mark_completed("a", "done")
    toolkit.upsert_running("b", "sub2", "job2", subagent_type="explore_agent")
    agent = SimpleNamespace(_session_toolkit=toolkit)
    running = list_running_async_tasks(agent)
    assert len(running) == 1
    assert running[0]["task_id"] == "b"

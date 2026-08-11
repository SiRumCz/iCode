# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Unit tests for sub-agent abort/retry EventBus helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openjiuwen_icode.events import (
    EventBus,
    SubAgentAborted,
    SubAgentResumed,
    SubAgentStarted,
    SystemNotice,
)
from openjiuwen_icode.features import subagent_control_bus as bus_mod


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


class TestHasControlFalse:
    @pytest.mark.asyncio
    async def test_abort_publishes_unavailable_notice(
        self,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bus_mod, "_HAS_CONTROL", False)
        notices: list[SystemNotice] = []

        async def _on(ev: SystemNotice) -> None:
            notices.append(ev)

        await event_bus.subscribe(SystemNotice, _on)
        await bus_mod.handle_subagent_abort(
            event_bus,
            backend=SimpleNamespace(agent=None),
            invocation_id="inv-1",
            session_id="sess-1",
        )
        assert len(notices) == 1
        assert notices[0].kind == "error"
        assert "abort is unavailable" in notices[0].text.lower()
        assert notices[0].session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_retry_publishes_unavailable_notice(
        self,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bus_mod, "_HAS_CONTROL", False)
        notices: list[SystemNotice] = []

        async def _on(ev: SystemNotice) -> None:
            notices.append(ev)

        await event_bus.subscribe(SystemNotice, _on)
        await bus_mod.handle_subagent_retry(
            event_bus,
            backend=SimpleNamespace(agent=None),
            invocation_id="inv-1",
            session_id="sess-1",
        )
        assert len(notices) == 1
        assert notices[0].kind == "error"
        assert "retry is unavailable" in notices[0].text.lower()


class TestHasControlTrueAbort:
    @pytest.mark.asyncio
    async def test_abort_success_publishes_aborted(
        self,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bus_mod, "_HAS_CONTROL", True)
        abort = AsyncMock(return_value=(True, "aborted ok", "plan_agent"))
        monkeypatch.setattr(bus_mod, "abort_subagent_invocation", abort)
        publish_awaiting = AsyncMock()
        monkeypatch.setattr(
            bus_mod, "publish_subagent_awaiting_state", publish_awaiting
        )

        aborted: list[SubAgentAborted] = []
        notices: list[SystemNotice] = []

        async def _on_aborted(ev: SubAgentAborted) -> None:
            aborted.append(ev)

        async def _on_notice(ev: SystemNotice) -> None:
            notices.append(ev)

        await event_bus.subscribe(SubAgentAborted, _on_aborted)
        await event_bus.subscribe(SystemNotice, _on_notice)

        agent = SimpleNamespace(_loop_session="sess-obj")
        backend = SimpleNamespace(agent=agent)
        await bus_mod.handle_subagent_abort(
            event_bus, backend, "inv-9", "sid"
        )

        abort.assert_awaited_once()
        assert abort.await_args.kwargs["parent_session"] == "sess-obj"
        assert abort.await_args.kwargs["reason"] == "user_abort"
        publish_awaiting.assert_awaited_once()
        assert len(aborted) == 1
        assert aborted[0].invocation_id == "inv-9"
        assert aborted[0].agent_name == "plan_agent"
        assert aborted[0].reason == "user_abort"
        assert notices[-1].kind == "info"
        assert notices[-1].text == "aborted ok"

    @pytest.mark.asyncio
    async def test_abort_failure_skips_aborted_event(
        self,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bus_mod, "_HAS_CONTROL", True)
        monkeypatch.setattr(
            bus_mod,
            "abort_subagent_invocation",
            AsyncMock(return_value=(False, "gone", "")),
        )
        monkeypatch.setattr(
            bus_mod,
            "publish_subagent_awaiting_state",
            AsyncMock(),
        )

        aborted: list[SubAgentAborted] = []
        notices: list[SystemNotice] = []

        async def _on_aborted(ev: SubAgentAborted) -> None:
            aborted.append(ev)

        async def _on_notice(ev: SystemNotice) -> None:
            notices.append(ev)

        await event_bus.subscribe(SubAgentAborted, _on_aborted)
        await event_bus.subscribe(SystemNotice, _on_notice)

        await bus_mod.handle_subagent_abort(
            event_bus,
            SimpleNamespace(agent=None),
            "inv-x",
            None,
        )
        assert aborted == []
        assert notices[-1].kind == "error"
        assert "Abort failed: gone" in notices[-1].text


class TestHasControlTrueRetry:
    @pytest.mark.asyncio
    async def test_retry_requires_parent_session(
        self,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bus_mod, "_HAS_CONTROL", True)
        notices: list[SystemNotice] = []

        async def _on(ev: SystemNotice) -> None:
            notices.append(ev)

        await event_bus.subscribe(SystemNotice, _on)
        await bus_mod.handle_subagent_retry(
            event_bus,
            SimpleNamespace(agent=SimpleNamespace()),
            "inv-1",
            "sid",
        )
        assert len(notices) == 1
        assert notices[0].kind == "error"
        assert "active agent session" in notices[0].text.lower()

    @pytest.mark.asyncio
    async def test_retry_success_emits_started_and_resumed(
        self,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bus_mod, "_HAS_CONTROL", True)
        sess = object()
        agent = SimpleNamespace(_loop_session=sess)
        retry = AsyncMock(
            return_value=(True, "retried", "explore_agent", "new-inv")
        )
        emit = AsyncMock()
        monkeypatch.setattr(bus_mod, "retry_subagent_invocation", retry)
        monkeypatch.setattr(bus_mod, "emit_subagent_chunk", emit)
        monkeypatch.setattr(
            bus_mod,
            "publish_subagent_awaiting_state",
            AsyncMock(),
        )

        resumed: list[SubAgentResumed] = []
        started: list[SubAgentStarted] = []
        notices: list[SystemNotice] = []

        async def _on_resumed(ev: SubAgentResumed) -> None:
            resumed.append(ev)

        async def _on_started(ev: SubAgentStarted) -> None:
            started.append(ev)

        async def _on_notice(ev: SystemNotice) -> None:
            notices.append(ev)

        await event_bus.subscribe(SubAgentResumed, _on_resumed)
        await event_bus.subscribe(SubAgentStarted, _on_started)
        await event_bus.subscribe(SystemNotice, _on_notice)

        await bus_mod.handle_subagent_retry(
            event_bus,
            SimpleNamespace(agent=agent),
            "old-inv",
            "sid",
        )

        retry.assert_awaited_once_with(agent, "old-inv", sess)
        emit.assert_awaited_once()
        assert emit.await_args.args[0] is sess
        assert emit.await_args.args[1] == "subagent.started"
        assert resumed[0].invocation_id == "new-inv"
        assert started[0].invocation_id == "new-inv"
        assert started[0].task == "retry of old-inv"
        assert notices[-1].kind == "info"
        assert notices[-1].text == "retried"

    @pytest.mark.asyncio
    async def test_retry_failure_skips_lifecycle_events(
        self,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bus_mod, "_HAS_CONTROL", True)
        sess = object()
        agent = SimpleNamespace(_loop_session=sess)
        monkeypatch.setattr(
            bus_mod,
            "retry_subagent_invocation",
            AsyncMock(return_value=(False, "boom", "", None)),
        )
        emit = AsyncMock()
        monkeypatch.setattr(bus_mod, "emit_subagent_chunk", emit)
        monkeypatch.setattr(
            bus_mod,
            "publish_subagent_awaiting_state",
            AsyncMock(),
        )

        resumed: list[SubAgentResumed] = []
        notices: list[SystemNotice] = []

        async def _on_resumed(ev: SubAgentResumed) -> None:
            resumed.append(ev)

        async def _on_notice(ev: SystemNotice) -> None:
            notices.append(ev)

        await event_bus.subscribe(SubAgentResumed, _on_resumed)
        await event_bus.subscribe(SystemNotice, _on_notice)

        await bus_mod.handle_subagent_retry(
            event_bus,
            SimpleNamespace(agent=agent),
            "old-inv",
            None,
        )
        emit.assert_not_awaited()
        assert resumed == []
        assert notices[-1].kind == "error"
        assert "Retry failed: boom" in notices[-1].text


class TestParentSession:
    def test_reads_loop_session(self) -> None:
        agent = SimpleNamespace(_loop_session="sess")
        assert bus_mod._parent_session(agent) == "sess"

    def test_missing_attr_returns_none(self) -> None:
        assert bus_mod._parent_session(SimpleNamespace()) is None

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Unit tests for CLI EventBus shell (P0/P1)."""

from __future__ import annotations

import asyncio

import pytest

from openjiuwen.core.session.stream.base import OutputSchema
from openjiuwen_icode.events import (
    AgentMessage,
    ApprovalRequest,
    EventBus,
    QuestionToUser,
    TodoListUpdated,
    ToolCallResult,
    ToolCallStart,
    TurnFailed,
    TurnFinished,
    TurnStarted,
    UsageUpdate,
    UserApproval,
    UserAskAnswer,
    UserFollowUp,
    UserInject,
    UserInjectCancel,
    UserInjectResult,
    UserMessage,
    UserRetry,
    chunk_to_events,
)
from openjiuwen_icode.host.bus_runner import format_event, run_via_bus
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.session_host import SessionHost


class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscribe_awaits_inline(self) -> None:
        bus = EventBus()
        seen: list[str] = []

        async def handler(event: UserMessage) -> None:
            seen.append(event.text)

        await bus.subscribe(UserMessage, handler)
        await bus.publish(UserMessage(text="hi"))
        assert seen == ["hi"]

    @pytest.mark.asyncio
    async def test_stream_is_lossless(self) -> None:
        bus = EventBus()
        async with bus.stream(AgentMessage) as stream:
            await bus.publish(AgentMessage(text="a"))
            await bus.publish(AgentMessage(text="b"))
            await bus.publish(TurnStarted(text="x"))
            first = await asyncio.wait_for(stream.__anext__(), timeout=1)
            second = await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert isinstance(first, AgentMessage) and first.text == "a"
        assert isinstance(second, AgentMessage) and second.text == "b"


class TestChunkMapping:
    def test_maps_llm_and_tools(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="llm_output",
                index=0,
                payload={"content": "hello"},
            )
        )
        assert len(events) == 1
        assert isinstance(events[0], AgentMessage)
        assert events[0].text == "hello"

        start = chunk_to_events(
            OutputSchema(
                type="tool_call",
                index=1,
                payload={"tool_name": "bash", "tool_args": {"c": "ls"}},
            )
        )
        assert isinstance(start[0], ToolCallStart)
        assert start[0].tool_name == "bash"

        result = chunk_to_events(
            OutputSchema(
                type="tool_result",
                index=2,
                payload={"tool_name": "bash", "tool_result": "ok"},
            )
        )
        assert isinstance(result[0], ToolCallResult)
        assert result[0].result == "ok"

    def test_maps_approval_interaction(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="__interaction__",
                index=0,
                payload={
                    "interaction_id": "tc-1",
                    "tool_name": "write_file",
                    "tool_args": {"path": "a.py"},
                    "message": "Approve?",
                },
            )
        )
        assert len(events) == 1
        assert isinstance(events[0], ApprovalRequest)
        assert events[0].interaction_id == "tc-1"
        assert events[0].tool_name == "write_file"

    def test_maps_ask_user_interaction(self) -> None:
        from openjiuwen.core.session.interaction.interaction import (
            InteractionOutput,
        )

        events = chunk_to_events(
            OutputSchema(
                type="__interaction__",
                index=0,
                payload=InteractionOutput(
                    id="ask-1",
                    value=type(
                        "Req",
                        (),
                        {
                            "tool_name": "ask_user",
                            "questions": [{"question": "Pick?"}],
                            "message": "",
                        },
                    )(),
                ),
            )
        )
        assert isinstance(events[0], QuestionToUser)
        assert events[0].interaction_id == "ask-1"

        nested = chunk_to_events(
            OutputSchema(
                type="__interaction__",
                index=0,
                payload={
                    "id": "ask-2",
                    "value": {
                        "tool_name": "ask_user",
                        "questions": [{"question": "Pick?"}],
                    },
                },
            )
        )
        assert isinstance(nested[0], QuestionToUser)
        assert nested[0].interaction_id == "ask-2"

    def test_maps_todo_updated(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="todo.updated",
                index=0,
                payload={"items": [{"id": "1", "status": "pending"}]},
            )
        )
        assert isinstance(events[0], TodoListUpdated)

    def test_skips_task_completion_controller_dump(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="controller_output",
                index=0,
                payload=(
                    "type=<EventType.TASK_COMPLETION: 'task_completion'> "
                    "data=[JsonDataFrame(...)]"
                ),
            )
        )
        assert events == []

    def test_llm_output_marked_stream(self) -> None:
        events = chunk_to_events(
            OutputSchema(
                type="llm_output",
                index=0,
                payload={"content": "你"},
            )
        )
        assert events[0].stream is True
        answer = chunk_to_events(
            OutputSchema(
                type="answer",
                index=1,
                payload={"content": "你好"},
            )
        )
        assert answer[0].stream is False


class TestSessionHost:
    @pytest.mark.asyncio
    async def test_user_message_drives_demo_turn(self) -> None:
        bus = EventBus()
        host = SessionHost(bus, DemoBackend(), session_id="s1")
        collected: list[object] = []

        async with bus.stream(
            TurnStarted,
            AgentMessage,
            ToolCallStart,
            ToolCallResult,
            UsageUpdate,
            TurnFinished,
            TurnFailed,
        ) as stream:

            async def consume() -> None:
                async for event in stream:
                    collected.append(event)
                    if isinstance(event, (TurnFinished, TurnFailed)):
                        break

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(UserMessage(text="ping", session_id="s1"))
            await consumer
            await host.stop()

        types = [type(e).__name__ for e in collected]
        assert types[0] == "TurnStarted"
        assert "AgentMessage" in types
        assert "ToolCallStart" in types
        assert "ToolCallResult" in types
        assert "UsageUpdate" in types
        assert types[-1] == "TurnFinished"

    @pytest.mark.asyncio
    async def test_auto_approve_resumes_interaction(self) -> None:
        bus = EventBus()
        host = SessionHost(
            bus,
            DemoBackend(),
            session_id="s1",
            auto_approve=True,
        )
        collected: list[object] = []

        async with bus.stream(
            TurnStarted,
            AgentMessage,
            ApprovalRequest,
            UsageUpdate,
            TurnFinished,
            TurnFailed,
        ) as stream:

            async def consume() -> None:
                async for event in stream:
                    collected.append(event)
                    if isinstance(event, (TurnFinished, TurnFailed)):
                        break

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(
                UserMessage(text="NEED_APPROVAL:x", session_id="s1")
            )
            await consumer
            await host.stop()

        types = [type(e).__name__ for e in collected]
        assert "ApprovalRequest" in types
        assert "TurnFinished" in types
        assert any(
            isinstance(e, AgentMessage)
            and "resumed" in e.text
            for e in collected
        )

    @pytest.mark.asyncio
    async def test_manual_approval_resume(self) -> None:
        bus = EventBus()
        host = SessionHost(
            bus,
            DemoBackend(),
            session_id="s1",
            auto_approve=False,
        )
        collected: list[object] = []

        async with bus.stream(
            TurnStarted,
            AgentMessage,
            ApprovalRequest,
            TurnFinished,
            TurnFailed,
        ) as stream:

            async def consume() -> None:
                async for event in stream:
                    collected.append(event)
                    if isinstance(event, ApprovalRequest):
                        await bus.publish(
                            UserApproval(
                                interaction_id=event.interaction_id,
                                approved=True,
                                session_id="s1",
                            )
                        )
                    if isinstance(event, (TurnFinished, TurnFailed)):
                        break

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(
                UserMessage(text="NEED_APPROVAL:x", session_id="s1")
            )
            await asyncio.wait_for(consumer, timeout=3)
            await host.stop()

        assert any(isinstance(e, TurnFinished) for e in collected)

    @pytest.mark.asyncio
    async def test_inject_during_turn(self) -> None:
        bus = EventBus()

        class GatedBackend(DemoBackend):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def run_streaming(
                self,
                query: object,
                session_id: str | None = None,
            ):
                user_inputs = getattr(query, "user_inputs", None)
                if isinstance(user_inputs, dict) and user_inputs:
                    async for chunk in DemoBackend.run_streaming(
                        self, query, session_id
                    ):
                        yield chunk
                    return
                self.started.set()
                await self.release.wait()
                yield OutputSchema(
                    type="llm_output",
                    index=0,
                    payload={"content": "[demo] after inject\n"},
                )

            async def steer(self, msg: str) -> None:
                await super().steer(msg)
                self.release.set()

        backend = GatedBackend()
        host = SessionHost(bus, backend, session_id="s1")
        results: list[UserInjectResult] = []

        async with bus.stream(
            TurnStarted, UserInjectResult, TurnFinished, TurnFailed
        ) as stream:

            async def consume() -> None:
                async for event in stream:
                    if isinstance(event, UserInjectResult):
                        results.append(event)
                    if isinstance(event, (TurnFinished, TurnFailed)):
                        break

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(UserMessage(text="ping", session_id="s1"))
            await asyncio.wait_for(backend.started.wait(), timeout=2)
            await bus.publish(
                UserInject(
                    text="nudge",
                    inject_id="inj-1",
                    session_id="s1",
                )
            )
            await asyncio.wait_for(consumer, timeout=3)
            await host.stop()

        assert results and results[0].consumed is True
        assert backend.steered == ["nudge"]

    @pytest.mark.asyncio
    async def test_inject_cancel_before_consume(self) -> None:
        bus = EventBus()

        class GatedBackend(DemoBackend):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def run_streaming(
                self,
                query: object,
                session_id: str | None = None,
            ):
                self.started.set()
                await self.release.wait()
                yield OutputSchema(
                    type="llm_output",
                    index=0,
                    payload={"content": "[demo] done\n"},
                )

        backend = GatedBackend()
        host = SessionHost(bus, backend, session_id="s1")
        results: list[UserInjectResult] = []

        async with bus.stream(
            UserInjectResult, TurnFinished, TurnFailed
        ) as stream:

            async def consume() -> None:
                async for event in stream:
                    if isinstance(event, UserInjectResult):
                        results.append(event)
                    if isinstance(event, (TurnFinished, TurnFailed)):
                        break

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(UserMessage(text="ping", session_id="s1"))
            await asyncio.wait_for(backend.started.wait(), timeout=2)
            await bus.publish(
                UserInjectCancel(inject_id="inj-x", session_id="s1")
            )
            await bus.publish(
                UserInject(
                    text="should-not-steer",
                    inject_id="inj-x",
                    session_id="s1",
                )
            )
            backend.release.set()
            await asyncio.wait_for(consumer, timeout=3)
            await host.stop()

        assert results and results[0].consumed is False
        assert backend.steered == []

    @pytest.mark.asyncio
    async def test_follow_up_during_gated_turn(self) -> None:
        bus = EventBus()

        class GatedBackend(DemoBackend):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def run_streaming(
                self,
                query: object,
                session_id: str | None = None,
            ):
                self.started.set()
                await self.release.wait()
                yield OutputSchema(
                    type="llm_output",
                    index=0,
                    payload={"content": "[demo] after follow_up\n"},
                )

            async def follow_up(self, msg: str) -> None:
                await super().follow_up(msg)
                self.release.set()

        backend = GatedBackend()
        host = SessionHost(bus, backend, session_id="s1")

        async with bus.stream(TurnFinished, TurnFailed) as stream:
            consumer = asyncio.create_task(
                asyncio.wait_for(stream.__anext__(), timeout=3)
            )
            await host.start()
            await bus.publish(UserMessage(text="ping", session_id="s1"))
            await asyncio.wait_for(backend.started.wait(), timeout=2)
            await bus.publish(
                UserFollowUp(text="more", session_id="s1")
            )
            done = await consumer
            await host.stop()

        assert isinstance(done, TurnFinished)
        assert backend.follow_ups == ["more"]

    @pytest.mark.asyncio
    async def test_retry_replays_last_text(self) -> None:
        bus = EventBus()
        host = SessionHost(bus, DemoBackend(), session_id="s1")
        finished = 0

        async with bus.stream(TurnFinished, TurnFailed) as stream:

            async def consume() -> None:
                nonlocal finished
                async for event in stream:
                    if isinstance(event, TurnFinished):
                        finished += 1
                        if finished >= 2:
                            break

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(UserMessage(text="first", session_id="s1"))
            # Wait for first turn to finish before retry.
            while finished < 1:
                await asyncio.sleep(0.01)
            await bus.publish(UserRetry(session_id="s1"))
            await asyncio.wait_for(consumer, timeout=3)
            await host.stop()

        assert finished == 2


class TestBusRunner:
    @pytest.mark.asyncio
    async def test_demo_run_via_bus(self) -> None:
        code = await run_via_bus(None, "hello", demo=True)
        assert code == 0

    @pytest.mark.asyncio
    async def test_demo_auto_approve_path(self) -> None:
        code = await run_via_bus(
            None, "NEED_APPROVAL:file", demo=True, auto_approve=True
        )
        assert code == 0

    def test_format_event(self) -> None:
        line = format_event(TurnStarted(text="hi"))
        assert line.startswith("[TurnStarted]")
        line2 = format_event(
            ApprovalRequest(interaction_id="1", tool_name="write_file")
        )
        assert "write_file" in line2

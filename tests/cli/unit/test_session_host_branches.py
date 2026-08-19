# coding: utf-8
"""Branch coverage for SessionHost remaining paths."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openjiuwen.core.session.interaction.interactive_input import (
    InteractiveInput,
)

from openjiuwen_icode.events import (
    AgentMessage,
    ApprovalRequest,
    EventBus,
    QuestionToUser,
    TurnFailed,
    TurnFinished,
    UserApproval,
    UserAskAnswer,
    UserFollowUp,
    UserInject,
    UserInjectCancel,
    UserInjectResult,
    UserInterrupt,
    UserMessage,
    UserRetry,
    UserSubAgentAbort,
    UserSubAgentRetry,
)
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.session_host import (
    SessionHost,
    _apply_interaction_answer,
)
from openjiuwen_icode.storage.session_store import SessionStore


class _EmptyUsageBackend(DemoBackend):
    def get_usage(self) -> dict[str, Any] | None:
        return None


class _NoUsageBackend(DemoBackend):
    pass


# Remove get_usage if present on protocol — DemoBackend has it; use a bare stub.
class _BareBackend:
    def __init__(self) -> None:
        self.aborted = False
        self.steered: list[str] = []
        self.follow_ups: list[str] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run_streaming(
        self, query: object, session_id: str | None = None
    ) -> AsyncIterator[Any]:
        if False:
            yield None
        return
        yield  # pragma: no cover

    async def abort(self) -> None:
        self.aborted = True

    async def steer(self, msg: str) -> None:
        self.steered.append(msg)

    async def follow_up(self, msg: str) -> None:
        self.follow_ups.append(msg)


@pytest.mark.asyncio
async def test_properties_and_stop_idempotent(tmp_path: Path) -> None:
    bus = EventBus()
    store = SessionStore(store_dir=tmp_path / "sessions")
    host = SessionHost(
        bus,
        DemoBackend(),
        session_id="s1",
        session_store=store,
        model_name="m",
    )
    assert host.session_id == "s1"
    assert host.session_store is store
    assert host.workdirs is not None
    assert host.event_log is not None
    assert host.mutations is not None
    assert host.turn_active is False

    await host.stop()  # not started
    await host.start()
    await host.start()  # idempotent
    await host.stop()


@pytest.mark.asyncio
async def test_concurrent_turn_and_retry_guards() -> None:
    bus = EventBus()
    failed: list[TurnFailed] = []

    class Gated(DemoBackend):
        def __init__(self) -> None:
            super().__init__()
            self.gate = asyncio.Event()

        async def run_streaming(
            self, query: object, session_id: str | None = None
        ):
            await self.gate.wait()
            async for c in DemoBackend.run_streaming(self, query, session_id):
                yield c

    backend = Gated()
    host = SessionHost(bus, backend, session_id="s1")

    async with bus.stream(TurnFailed, TurnFinished) as stream:
        consumer = asyncio.create_task(asyncio.wait_for(stream.__anext__(), timeout=3))
        await host.start()
        await bus.publish(UserMessage(text="a", session_id="s1"))
        await asyncio.sleep(0.02)
        await bus.publish(UserMessage(text="b", session_id="s1"))
        first = await consumer
        assert isinstance(first, TurnFailed)
        assert "already in progress" in first.error

        async with bus.stream(TurnFailed) as s2:
            c2 = asyncio.create_task(asyncio.wait_for(s2.__anext__(), timeout=2))
            await bus.publish(UserRetry(session_id="s1"))
            retry_fail = await c2
            assert "cannot retry" in retry_fail.error

        backend.gate.set()
        await asyncio.sleep(0.05)
        await host.stop()


@pytest.mark.asyncio
async def test_retry_nothing_and_follow_up_inactive() -> None:
    bus = EventBus()
    host = SessionHost(bus, DemoBackend(), session_id="s1")
    await host.start()

    async with bus.stream(TurnFailed) as stream:
        consumer = asyncio.create_task(
            asyncio.wait_for(stream.__anext__(), timeout=2)
        )
        await bus.publish(UserRetry(session_id="s1"))
        ev = await consumer
        assert "nothing to retry" in ev.error

    finished = asyncio.Event()

    async def on_fin(_: TurnFinished) -> None:
        finished.set()

    await bus.subscribe(TurnFinished, on_fin)
    await bus.publish(UserFollowUp(text="late", session_id="s1"))
    await asyncio.wait_for(finished.wait(), timeout=2)
    await bus.publish(UserFollowUp(text="  ", session_id="s1"))
    await host.stop()


@pytest.mark.asyncio
async def test_inject_inactive_and_cancel_after_consume() -> None:
    bus = EventBus()
    host = SessionHost(bus, DemoBackend(), session_id="s1")
    await host.start()
    results: list[UserInjectResult] = []

    async def on_res(ev: UserInjectResult) -> None:
        results.append(ev)

    await bus.subscribe(UserInjectResult, on_res)
    await bus.publish(
        UserInject(text="x", inject_id="i1", session_id="s1")
    )
    await asyncio.sleep(0.02)
    assert results and results[0].consumed is False

    # cancel after consume is no-op path
    host._consumed_injects.add("i2")
    await bus.publish(UserInjectCancel(inject_id="i2", session_id="s1"))
    assert "i2" not in host._cancelled_injects
    await host.stop()


@pytest.mark.asyncio
async def test_interrupt_cancels_turn() -> None:
    bus = EventBus()

    class Gated(DemoBackend):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def run_streaming(
            self, query: object, session_id: str | None = None
        ):
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                raise
            if False:  # pragma: no cover
                yield None
            return

    backend = Gated()
    host = SessionHost(bus, backend, session_id="s1")
    failed: list[TurnFailed] = []

    async def on_fail(ev: TurnFailed) -> None:
        failed.append(ev)

    await bus.subscribe(TurnFailed, on_fail)
    await host.start()
    await bus.publish(UserMessage(text="ping", session_id="s1"))
    await asyncio.wait_for(backend.started.wait(), timeout=2)
    await bus.publish(UserInterrupt(session_id="s1"))
    await asyncio.sleep(0.05)
    assert backend._aborted is True
    await host.stop()


@pytest.mark.asyncio
async def test_auto_approve_question_and_ask_answer() -> None:
    bus = EventBus()

    class AskBackend(DemoBackend):
        async def run_streaming(
            self, query: object, session_id: str | None = None
        ):
            user_inputs = getattr(query, "user_inputs", None)
            if isinstance(user_inputs, dict) and user_inputs:
                from openjiuwen.core.foundation.llm import OutputSchema

                yield OutputSchema(
                    type="llm_output",
                    index=0,
                    payload={"content": "answered\n"},
                )
                return
            from openjiuwen.core.foundation.llm import OutputSchema

            yield OutputSchema(
                type="__interaction__",
                index=0,
                payload=SimpleNamespace(
                    id="ask-1",
                    value={"questions": [{"question": "Q?"}]},
                ),
            )

    # Prefer emitting QuestionToUser via chunk_to_events — use Approval path
    # with auto_approve Question via _auto_resolve directly.
    host = SessionHost(
        bus, DemoBackend(), session_id="s1", auto_approve=True
    )
    await host.start()
    await host._auto_resolve(
        QuestionToUser(interaction_id="q1", questions=[{"q": "x"}]),
        "s1",
    )
    # Manual ask answer
    fut = asyncio.get_running_loop().create_future()
    host._pending_answers["q2"] = fut
    await host._on_user_ask_answer(
        UserAskAnswer(interaction_id="q2", answer="yes", session_id="s1")
    )
    assert fut.result().answer == "yes"
    await host.stop()


@pytest.mark.asyncio
async def test_subagent_control_handlers() -> None:
    bus = EventBus()
    host = SessionHost(bus, DemoBackend(), session_id="s1")
    await host.start()
    with patch(
        "openjiuwen_icode.features.subagent_control_bus.handle_subagent_abort",
        AsyncMock(),
    ) as abort, patch(
        "openjiuwen_icode.features.subagent_control_bus.handle_subagent_retry",
        AsyncMock(),
    ) as retry:
        await bus.publish(
            UserSubAgentAbort(invocation_id="inv", session_id="s1")
        )
        await bus.publish(
            UserSubAgentRetry(invocation_id="inv", session_id="s1")
        )
        await asyncio.sleep(0.02)
        abort.assert_awaited()
        retry.assert_awaited()
    await host.stop()


@pytest.mark.asyncio
async def test_publish_usage_and_title_edges(tmp_path: Path) -> None:
    bus = EventBus()
    store = SessionStore(store_dir=tmp_path / "s")
    host = SessionHost(
        bus,
        _EmptyUsageBackend(),
        session_id="s1",
        session_store=store,
    )
    await host._publish_usage("s1")
    bare = SessionHost(bus, _BareBackend(), session_id="s2")
    # Bare has no get_usage
    await bare._publish_usage("s2")

    host2 = SessionHost(bus, DemoBackend(), session_id=None)
    await host2._publish_title_if_any(sid="x")
    await host2._maybe_refine_title("x", "u", "a")


def test_apply_interaction_answer_branches() -> None:
    interactive = InteractiveInput()
    q = QuestionToUser(interaction_id="q1", questions=[])
    _apply_interaction_answer(
        interactive,
        q,
        UserAskAnswer(interaction_id="q1", answers={"a": "1"}),
    )
    interactive2 = InteractiveInput()
    _apply_interaction_answer(
        interactive2,
        q,
        UserAskAnswer(interaction_id="q1", answer="plain"),
    )
    interactive3 = InteractiveInput()
    _apply_interaction_answer(interactive3, q, "raw")

    appr = ApprovalRequest(
        interaction_id="a1", tool_name="write_file", tool_args={}
    )
    interactive4 = InteractiveInput()
    _apply_interaction_answer(
        interactive4,
        appr,
        UserApproval(interaction_id="a1", approved=False, feedback="no"),
    )
    interactive5 = InteractiveInput()
    _apply_interaction_answer(interactive5, appr, True)


@pytest.mark.asyncio
async def test_bind_mutations_from_workdir(tmp_path: Path) -> None:
    bus = EventBus()
    store = SessionStore(store_dir=tmp_path / "sessions")
    backend = DemoBackend()
    backend.cfg = SimpleNamespace(cwd=str(tmp_path))  # type: ignore[attr-defined]
    host = SessionHost(
        bus,
        backend,
        session_id="s1",
        session_store=store,
    )
    assert host.mutations is not None
    host._bind_mutations(None)
    assert host.mutations is None
    host._on_event_log_tap(UserMessage(text="x"))  # no log


@pytest.mark.asyncio
async def test_implement_tool_crash_continues_instead_of_turn_failed() -> None:
    """ENAMETOOLONG-style backend crashes must not skip implement continuations."""
    from openjiuwen_icode.features.implement_gate import (
        INCOMPLETE_IMPLEMENT_ERROR,
        TOOL_RUNTIME_NUDGE,
    )

    bus = EventBus()
    queries: list[object] = []

    class BoomThenOk(DemoBackend):
        async def run_streaming(
            self, query: object, session_id: str | None = None
        ):
            queries.append(query)
            if len(queries) == 1:
                raise OSError(36, "File name too long")
            async for chunk in DemoBackend.run_streaming(
                self, query, session_id
            ):
                yield chunk

    backend = BoomThenOk()
    host = SessionHost(
        bus, backend, session_id="s1", auto_approve=True
    )
    failed: list[TurnFailed] = []
    done = asyncio.Event()

    async def on_fail(ev: TurnFailed) -> None:
        failed.append(ev)
        done.set()

    async def on_fin(_: TurnFinished) -> None:
        done.set()

    await bus.subscribe(TurnFailed, on_fail)
    await bus.subscribe(TurnFinished, on_fin)
    await host.start()
    await bus.publish(
        UserMessage(
            text="Implement a new AutoToc rule in src/rules/auto-toc.ts",
            session_id="s1",
        )
    )
    await asyncio.wait_for(done.wait(), timeout=5)
    await host.stop()

    assert len(queries) >= 2
    assert any(
        isinstance(q, str) and TOOL_RUNTIME_NUDGE[:40] in q for q in queries[1:]
    )
    assert failed
    assert INCOMPLETE_IMPLEMENT_ERROR in failed[-1].error
    assert "File name too long" not in failed[-1].error


@pytest.mark.asyncio
async def test_non_implement_tool_crash_still_turn_failed() -> None:
    bus = EventBus()

    class Boom(DemoBackend):
        async def run_streaming(
            self, query: object, session_id: str | None = None
        ):
            raise OSError(36, "File name too long")
            if False:  # pragma: no cover
                yield None

    host = SessionHost(bus, Boom(), session_id="s1", auto_approve=True)
    failed: list[TurnFailed] = []
    done = asyncio.Event()

    async def on_fail(ev: TurnFailed) -> None:
        failed.append(ev)
        done.set()

    await bus.subscribe(TurnFailed, on_fail)
    await host.start()
    await bus.publish(UserMessage(text="What is Ruff?", session_id="s1"))
    await asyncio.wait_for(done.wait(), timeout=3)
    await host.stop()
    assert failed
    assert "File name too long" in failed[0].error


@pytest.mark.asyncio
async def test_explore_abort_cancelled_continues_implement_turn() -> None:
    """CodeEditNudgeRail abort must soft-continue, not TurnFailed('turn cancelled')."""
    from openjiuwen_icode.features.implement_gate import (
        INCOMPLETE_IMPLEMENT_ERROR,
        ZERO_MUTATION_NUDGE,
    )

    bus = EventBus()
    queries: list[object] = []

    class AbortThenOk(DemoBackend):
        async def run_streaming(
            self, query: object, session_id: str | None = None
        ):
            queries.append(query)
            if len(queries) == 1:
                raise asyncio.CancelledError()
            async for chunk in DemoBackend.run_streaming(
                self, query, session_id
            ):
                yield chunk

    backend = AbortThenOk()
    host = SessionHost(
        bus, backend, session_id="s1", auto_approve=True
    )
    failed: list[TurnFailed] = []
    done = asyncio.Event()

    async def on_fail(ev: TurnFailed) -> None:
        failed.append(ev)
        done.set()

    async def on_fin(_: TurnFinished) -> None:
        done.set()

    await bus.subscribe(TurnFailed, on_fail)
    await bus.subscribe(TurnFinished, on_fin)
    await host.start()
    await bus.publish(
        UserMessage(
            text="Implement a new AutoToc rule in src/rules/auto-toc.ts",
            session_id="s1",
        )
    )
    await asyncio.wait_for(done.wait(), timeout=5)
    await host.stop()

    assert len(queries) >= 2
    assert any(
        isinstance(q, str) and ZERO_MUTATION_NUDGE[:40] in q
        for q in queries[1:]
    )
    assert failed
    assert INCOMPLETE_IMPLEMENT_ERROR in failed[-1].error
    assert "turn cancelled" not in failed[-1].error


@pytest.mark.asyncio
async def test_user_interrupt_still_turn_cancelled() -> None:
    """Outer turn-task cancel (UserInterrupt) must keep failing the turn."""
    bus = EventBus()

    class Hang(DemoBackend):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def run_streaming(
            self, query: object, session_id: str | None = None
        ):
            self.started.set()
            await asyncio.Event().wait()
            if False:  # pragma: no cover
                yield None

    backend = Hang()
    host = SessionHost(
        bus, backend, session_id="s1", auto_approve=True
    )
    failed: list[TurnFailed] = []
    done = asyncio.Event()

    async def on_fail(ev: TurnFailed) -> None:
        failed.append(ev)
        done.set()

    await bus.subscribe(TurnFailed, on_fail)
    await host.start()
    await bus.publish(
        UserMessage(
            text="Implement typed bindings in the parser",
            session_id="s1",
        )
    )
    await asyncio.wait_for(backend.started.wait(), timeout=2)
    assert host._turn_task is not None
    host._turn_task.cancel()
    await asyncio.wait_for(done.wait(), timeout=3)
    await host.stop()
    assert failed
    assert "turn cancelled" in failed[0].error

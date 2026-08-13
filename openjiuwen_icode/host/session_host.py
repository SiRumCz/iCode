# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""SessionHost — translates EventBus user events into agent runs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional, Protocol

from openjiuwen.core.session.interaction.interactive_input import (
    InteractiveInput,
)
from openjiuwen_icode.events import (
    AgentMessage,
    ApprovalRequest,
    Event,
    EventBus,
    QuestionToUser,
    SessionTitleUpdated,
    ToolCallResult,
    ToolCallStart,
    TurnFailed,
    TurnFinished,
    TurnStarted,
    UsageUpdate,
    UserApproval,
    UserAskAnswer,
    UserCommand,
    UserFollowUp,
    UserInject,
    UserInjectCancel,
    UserInjectResult,
    UserInterrupt,
    UserMessage,
    UserRetry,
    UserSubAgentAbort,
    UserSubAgentRetry,
    chunk_to_events,
)
from openjiuwen_icode.features.session_title import (
    TITLE_LLM,
    TITLE_PROVISIONAL,
    refine_title_with_llm,
)
from openjiuwen_icode.host.commands import handle_user_command
from openjiuwen_icode.host.workdirs import WorkdirRegistry
from openjiuwen_icode.storage.event_log import SessionEventLog
from openjiuwen_icode.storage.session_store import SessionStore
from openjiuwen_icode.features.mutations import MutationTracker


class AgentBackendLike(Protocol):
    """Backend surface used by SessionHost."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def run_streaming(
        self,
        query: Any,
        session_id: Optional[str] = None,
    ) -> Any: ...

    async def abort(self) -> None: ...

    async def steer(self, msg: str) -> None: ...

    async def follow_up(self, msg: str) -> None: ...

    def get_usage(self) -> dict[str, Any] | None: ...


class SessionHost:
    """Long-lived adapter: EventBus ``User*`` ↔ agent backend stream.

    TUI/CLI frontends only publish/subscribe on the bus; they never call the
    backend directly.

    User turns run in a background task so ``publish(UserMessage)`` returns
    quickly and the UI event loop stays responsive (Chrys-style).

    Args:
        auto_approve: When True (headless BYPASS), confirm/ask interactions
            are resolved immediately without waiting for the frontend.
    """

    def __init__(
        self,
        bus: EventBus,
        backend: AgentBackendLike,
        *,
        session_id: str | None = None,
        auto_approve: bool = False,
        session_store: SessionStore | None = None,
        model_name: str | None = None,
        workdirs: WorkdirRegistry | None = None,
    ) -> None:
        self._bus = bus
        self._backend = backend
        self._session_id = session_id
        self._auto_approve = auto_approve
        self._store = session_store
        self._model_name = model_name or "unknown"
        self._workdirs = workdirs if workdirs is not None else WorkdirRegistry()
        self._started = False
        self._turn_active = False
        self._turn_task: asyncio.Task[None] | None = None
        self._last_user_text: str = ""
        self._pending_answers: dict[str, asyncio.Future[Any]] = {}
        self._cancelled_injects: set[str] = set()
        self._consumed_injects: set[str] = set()
        self._event_log: SessionEventLog | None = None
        self._event_log_tap = self._on_event_log_tap
        self._mutations: MutationTracker | None = None
        if self._store is not None and self._session_id:
            if self._store.current is None:
                self._store.new_session(self._session_id, self._model_name)
            self._bind_event_log(self._session_id)
            self._bind_mutations(self._session_id)

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def turn_active(self) -> bool:
        return self._turn_active

    @property
    def session_store(self) -> SessionStore | None:
        return self._store

    @property
    def workdirs(self) -> WorkdirRegistry:
        return self._workdirs

    @property
    def event_log(self) -> SessionEventLog | None:
        return self._event_log

    @property
    def mutations(self) -> MutationTracker | None:
        return self._mutations

    def _bind_mutations(self, session_id: str | None) -> None:
        self._mutations = None
        if self._store is None or not session_id:
            return
        workspace = None
        if self._workdirs.primary:
            workspace = Path(self._workdirs.primary)
        else:
            cfg = getattr(self._backend, "cfg", None)
            cwd = getattr(cfg, "cwd", None) if cfg else None
            if cwd:
                workspace = Path(str(cwd))
        self._mutations = MutationTracker(
            self._store.store_dir / session_id / "mutations",
            workspace=workspace,
        )

    def _bind_event_log(self, session_id: str | None) -> None:
        """Point the EventBus tap at ``sessions/<id>/events.jsonl``."""
        if self._event_log is not None:
            self._bus.remove_tap(self._event_log_tap)
            self._event_log = None
        if self._store is None or not session_id:
            return
        self._event_log = SessionEventLog.for_session(
            self._store.store_dir, session_id
        )
        self._bus.add_tap(self._event_log_tap)
        self._bind_mutations(session_id)

    def _on_event_log_tap(self, event: Event) -> None:
        if self._event_log is None:
            return
        self._event_log.record_event(event)

    async def start(self) -> None:
        """Start the backend and subscribe to frontend events."""
        if self._started:
            return
        await self._backend.start()
        await self._bus.subscribe(UserMessage, self._on_user_message)
        await self._bus.subscribe(UserInterrupt, self._on_user_interrupt)
        await self._bus.subscribe(UserApproval, self._on_user_approval)
        await self._bus.subscribe(UserAskAnswer, self._on_user_ask_answer)
        await self._bus.subscribe(UserInject, self._on_user_inject)
        await self._bus.subscribe(
            UserInjectCancel, self._on_user_inject_cancel
        )
        await self._bus.subscribe(UserFollowUp, self._on_user_follow_up)
        await self._bus.subscribe(UserRetry, self._on_user_retry)
        await self._bus.subscribe(UserSubAgentAbort, self._on_user_subagent_abort)
        await self._bus.subscribe(UserSubAgentRetry, self._on_user_subagent_retry)
        await self._bus.subscribe(UserCommand, self._on_user_command)
        self._started = True

    async def stop(self) -> None:
        """Unsubscribe, cancel an in-flight turn, and stop the backend."""
        self._bind_event_log(None)
        if not self._started:
            return
        await self._bus.unsubscribe(UserMessage, self._on_user_message)
        await self._bus.unsubscribe(UserInterrupt, self._on_user_interrupt)
        await self._bus.unsubscribe(UserApproval, self._on_user_approval)
        await self._bus.unsubscribe(UserAskAnswer, self._on_user_ask_answer)
        await self._bus.unsubscribe(UserInject, self._on_user_inject)
        await self._bus.unsubscribe(
            UserInjectCancel, self._on_user_inject_cancel
        )
        await self._bus.unsubscribe(UserFollowUp, self._on_user_follow_up)
        await self._bus.unsubscribe(UserRetry, self._on_user_retry)
        await self._bus.unsubscribe(
            UserSubAgentAbort, self._on_user_subagent_abort
        )
        await self._bus.unsubscribe(
            UserSubAgentRetry, self._on_user_subagent_retry
        )
        await self._bus.unsubscribe(UserCommand, self._on_user_command)
        if self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()
            try:
                await self._turn_task
            except asyncio.CancelledError:
                pass
        self._turn_task = None
        self._turn_active = False
        self._fail_pending("host stopped")
        await self._backend.stop()
        self._started = False

    def _fail_pending(self, reason: str) -> None:
        for fut in self._pending_answers.values():
            if not fut.done():
                fut.set_exception(RuntimeError(reason))
        self._pending_answers.clear()

    async def _on_user_message(self, event: UserMessage) -> None:
        if self._turn_active:
            await self._bus.publish(
                TurnFailed(
                    error="turn already in progress",
                    session_id=self._session_id,
                )
            )
            return

        self._last_user_text = event.text
        if self._store is not None:
            before = (
                self._store.current.title if self._store.current else ""
            )
            self._store.add_message("user", event.text)
            after = (
                self._store.current.title if self._store.current else ""
            )
            if after and after != before:
                await self._publish_title_if_any(
                    sid=event.session_id or self._session_id
                )
        self._turn_active = True
        self._turn_task = asyncio.create_task(
            self._run_turn(event),
            name="session-host-turn",
        )

    async def _run_turn(self, event: UserMessage) -> None:
        sid = event.session_id or self._session_id
        query: Any = event.text
        assistant_parts: list[str] = []
        mutate_attempted = False
        verify_attempted = False
        submit_attempted = False
        shallow_only = True
        continuation_attempts = 0
        # Allow zero-mutation → shallow → verify → submit chain in headless.
        max_continuations = 3 if self._auto_approve else 0
        if self._mutations is not None and sid:
            self._mutations.begin_turn(sid)
        try:
            from openjiuwen_icode.features.implement_gate import (
                edit_args_look_shallow,
                extract_bash_command,
                looks_like_submit_command,
                looks_like_verify_command,
                next_implement_continuation,
            )
            from openjiuwen_icode.features.mutations import MUTATING_TOOLS
            from openjiuwen_icode.features.stream_stall import (
                StreamStallError,
            )

            await self._bus.publish(
                TurnStarted(text=event.text, session_id=sid)
            )
            while True:
                pending: list[ApprovalRequest | QuestionToUser] = []
                saw_stream_text = False
                try:
                    stream = self._backend.run_streaming(
                        query,
                        session_id=sid,
                    )
                    async for chunk in stream:
                        for ev in chunk_to_events(chunk, session_id=sid):
                            if isinstance(ev, AgentMessage) and ev.text:
                                if ev.stream:
                                    saw_stream_text = True
                                    assistant_parts.append(ev.text)
                                elif saw_stream_text:
                                    # Skip answer/message duplicates of llm_output.
                                    continue
                                else:
                                    assistant_parts.append(ev.text)
                            if isinstance(ev, ToolCallStart):
                                if ev.tool_name in MUTATING_TOOLS:
                                    mutate_attempted = True
                                    if not edit_args_look_shallow(
                                        ev.tool_args
                                    ):
                                        shallow_only = False
                                elif ev.tool_name == "bash":
                                    cmd = extract_bash_command(
                                        ev.tool_args
                                    )
                                    if looks_like_verify_command(cmd):
                                        verify_attempted = True
                                    if looks_like_submit_command(cmd):
                                        submit_attempted = True
                                if self._mutations:
                                    self._mutations.record_tool_mutation(
                                        ev.tool_name, ev.tool_args
                                    )
                            if isinstance(ev, ToolCallResult) and self._mutations:
                                self._mutations.refresh_after_hashes()
                            if isinstance(ev, (ApprovalRequest, QuestionToUser)):
                                loop = asyncio.get_running_loop()
                                fut: asyncio.Future[Any] = loop.create_future()
                                self._pending_answers[ev.interaction_id] = fut
                                pending.append(ev)
                                await self._bus.publish(ev)
                                if self._auto_approve:
                                    await self._auto_resolve(ev, sid)
                            else:
                                if (
                                    isinstance(ev, AgentMessage)
                                    and not ev.stream
                                    and saw_stream_text
                                ):
                                    continue
                                await self._bus.publish(ev)
                except StreamStallError:
                    if continuation_attempts < max_continuations:
                        nudge = next_implement_continuation(
                            user_text=event.text,
                            mutate_attempted=mutate_attempted,
                            verify_attempted=verify_attempted,
                            submit_attempted=submit_attempted,
                            shallow_only=shallow_only,
                        )
                        if nudge is not None:
                            continuation_attempts += 1
                            query = nudge
                            continue
                    raise

                if pending:
                    interactive = InteractiveInput()
                    for pev in pending:
                        fut = self._pending_answers[pev.interaction_id]
                        try:
                            answer = await fut
                        finally:
                            self._pending_answers.pop(
                                pev.interaction_id, None
                            )
                        _apply_interaction_answer(interactive, pev, answer)
                    query = interactive
                    continue

                # Headless code tasks: require mutate → (full edit) → verify
                # → submit when the user asked for an implement/deliver task.
                if continuation_attempts < max_continuations:
                    nudge = next_implement_continuation(
                        user_text=event.text,
                        mutate_attempted=mutate_attempted,
                        verify_attempted=verify_attempted,
                        submit_attempted=submit_attempted,
                        shallow_only=shallow_only,
                    )
                    if nudge is not None:
                        continuation_attempts += 1
                        query = nudge
                        continue

                break

            if self._store is not None and assistant_parts:
                self._store.add_message(
                    "assistant", "".join(assistant_parts)
                )
            await self._publish_usage(sid)
            await self._bus.publish(TurnFinished(session_id=sid))
            from openjiuwen_icode.features.subagent_awaiting import (
                publish_subagent_awaiting_state,
            )

            await publish_subagent_awaiting_state(
                self._bus, self._backend, sid
            )
            # Fire-and-forget LLM title refine (never blocks the turn).
            asyncio.create_task(
                self._maybe_refine_title(
                    sid,
                    event.text,
                    "".join(assistant_parts),
                ),
                name="session-title-refine",
            )
        except asyncio.CancelledError:
            self._fail_pending("turn cancelled")
            await self._bus.publish(
                TurnFailed(error="turn cancelled", session_id=sid)
            )
            raise
        except Exception as exc:
            self._fail_pending(str(exc))
            await self._bus.publish(
                TurnFailed(error=str(exc), session_id=sid)
            )
        finally:
            self._cancelled_injects.clear()
            self._consumed_injects.clear()
            if self._mutations is not None and self._mutations._current is not None:
                # Failed/cancelled turn: still persist any recorded files.
                self._mutations.refresh_after_hashes()
                self._mutations.end_turn()
            self._turn_active = False
            self._turn_task = None

    async def _auto_resolve(
        self,
        ev: ApprovalRequest | QuestionToUser,
        sid: str | None,
    ) -> None:
        if isinstance(ev, ApprovalRequest):
            await self._bus.publish(
                UserApproval(
                    interaction_id=ev.interaction_id,
                    approved=True,
                    feedback="",
                    session_id=sid,
                )
            )
            return
        await self._bus.publish(
            UserAskAnswer(
                interaction_id=ev.interaction_id,
                answers={},
                answer="(auto)",
                session_id=sid,
            )
        )

    async def _publish_usage(self, sid: str | None) -> None:
        get_usage = getattr(self._backend, "get_usage", None)
        if get_usage is None:
            return
        summary = get_usage()
        if not summary:
            return
        await self._bus.publish(
            UsageUpdate(
                input_tokens=int(summary.get("input_tokens", 0) or 0),
                output_tokens=int(summary.get("output_tokens", 0) or 0),
                total_tokens=int(summary.get("total_tokens", 0) or 0),
                model_calls=int(summary.get("model_calls", 0) or 0),
                last_input_tokens=int(
                    summary.get("last_input_tokens", 0) or 0
                ),
                last_output_tokens=int(
                    summary.get("last_output_tokens", 0) or 0
                ),
                session_id=sid,
            )
        )

    async def _publish_title_if_any(self, *, sid: str | None) -> None:
        """Emit SessionTitleUpdated when the store has a display title."""
        if self._store is None or self._store.current is None:
            return
        title = self._store.current.title
        if not title:
            return
        await self._bus.publish(
            SessionTitleUpdated(
                title=title,
                source=self._store.current.title_source or TITLE_PROVISIONAL,
                session_id=sid or self._session_id,
            )
        )

    async def _maybe_refine_title(
        self,
        sid: str | None,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """Async LLM refine; silent on failure / manual lock."""
        if self._store is None or self._store.current is None:
            return
        cur = self._store.current
        if cur.title_source not in {"", TITLE_PROVISIONAL}:
            return
        # Only refine once per session (first successful turn with reply).
        user_msgs = [m for m in cur.messages if m.role == "user"]
        asst_msgs = [m for m in cur.messages if m.role == "assistant"]
        if len(user_msgs) != 1 or len(asst_msgs) < 1:
            return
        cfg = getattr(self._backend, "cfg", None)
        refined = await refine_title_with_llm(user_text, assistant_text, cfg)
        if not refined:
            return
        if self._store.set_title(refined, source=TITLE_LLM):
            await self._bus.publish(
                SessionTitleUpdated(
                    title=refined,
                    source=TITLE_LLM,
                    session_id=sid or self._session_id,
                )
            )

    async def _on_user_command(self, event: UserCommand) -> None:
        await handle_user_command(self, event)

    async def _on_user_subagent_abort(self, event: UserSubAgentAbort) -> None:
        from openjiuwen_icode.features.subagent_control_bus import (
            handle_subagent_abort,
        )

        sid = event.session_id or self._session_id
        await handle_subagent_abort(
            self._bus,
            self._backend,
            event.invocation_id,
            sid,
        )

    async def _on_user_subagent_retry(self, event: UserSubAgentRetry) -> None:
        from openjiuwen_icode.features.subagent_control_bus import (
            handle_subagent_retry,
        )

        sid = event.session_id or self._session_id
        await handle_subagent_retry(
            self._bus,
            self._backend,
            event.invocation_id,
            sid,
        )

    async def _on_user_interrupt(self, event: UserInterrupt) -> None:
        await self._backend.abort()
        task = self._turn_task
        if task is not None and not task.done():
            task.cancel()

    async def _on_user_approval(self, event: UserApproval) -> None:
        fut = self._pending_answers.get(event.interaction_id)
        if fut is not None and not fut.done():
            fut.set_result(event)

    async def _on_user_ask_answer(self, event: UserAskAnswer) -> None:
        fut = self._pending_answers.get(event.interaction_id)
        if fut is not None and not fut.done():
            fut.set_result(event)

    async def _on_user_inject(self, event: UserInject) -> None:
        inject_id = event.inject_id or event.event_id
        sid = event.session_id or self._session_id
        if inject_id in self._cancelled_injects:
            await self._bus.publish(
                UserInjectResult(
                    inject_id=inject_id,
                    consumed=False,
                    session_id=sid,
                )
            )
            return
        if not self._turn_active:
            await self._bus.publish(
                UserInjectResult(
                    inject_id=inject_id,
                    consumed=False,
                    session_id=sid,
                )
            )
            return
        await self._backend.steer(event.text)
        self._consumed_injects.add(inject_id)
        await self._bus.publish(
            UserInjectResult(
                inject_id=inject_id,
                consumed=True,
                session_id=sid,
            )
        )

    async def _on_user_inject_cancel(
        self, event: UserInjectCancel
    ) -> None:
        if event.inject_id in self._consumed_injects:
            return
        self._cancelled_injects.add(event.inject_id)

    async def _on_user_follow_up(self, event: UserFollowUp) -> None:
        text = (event.text or "").strip()
        if not text:
            return
        if not self._turn_active:
            # Late follow-up: start a normal user turn instead of dropping.
            await self._on_user_message(
                UserMessage(
                    text=text,
                    session_id=event.session_id or self._session_id,
                )
            )
            return
        await self._backend.follow_up(text)

    async def _on_user_retry(self, event: UserRetry) -> None:
        if self._turn_active:
            await self._bus.publish(
                TurnFailed(
                    error="cannot retry while turn is active",
                    session_id=event.session_id or self._session_id,
                )
            )
            return
        text = (event.text or self._last_user_text or "").strip()
        if not text:
            await self._bus.publish(
                TurnFailed(
                    error="nothing to retry",
                    session_id=event.session_id or self._session_id,
                )
            )
            return
        await self._on_user_message(
            UserMessage(
                text=text,
                session_id=event.session_id or self._session_id,
            )
        )


def _apply_interaction_answer(
    interactive: InteractiveInput,
    pending: ApprovalRequest | QuestionToUser,
    answer: Any,
) -> None:
    iid = pending.interaction_id
    if isinstance(pending, QuestionToUser):
        if isinstance(answer, UserAskAnswer):
            if answer.answers:
                interactive.update(iid, {"answers": answer.answers})
            else:
                interactive.update(
                    iid, {"answer": answer.answer or ""}
                )
            return
        interactive.update(iid, {"answer": str(answer)})
        return

    if isinstance(answer, UserApproval):
        interactive.update(
            iid,
            {
                "approved": answer.approved,
                "feedback": (
                    ""
                    if answer.approved
                    else (answer.feedback or "User rejected")
                ),
                "auto_confirm": False,
            },
        )
        return
    interactive.update(
        iid,
        {
            "approved": bool(answer),
            "feedback": "",
            "auto_confirm": False,
        },
    )

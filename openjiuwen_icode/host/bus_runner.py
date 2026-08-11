# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Non-interactive runner that drives the agent via EventBus."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from openjiuwen_icode.agent.config import CLIConfig
from openjiuwen_icode.events import (
    AgentMessage,
    AgentThinking,
    ApprovalRequest,
    ErrorEvent,
    Event,
    ModelUsage,
    QuestionToUser,
    TodoListUpdated,
    ToolCallResult,
    ToolCallStart,
    TurnFailed,
    TurnFinished,
    TurnStarted,
    UsageUpdate,
    UserInjectResult,
    UserMessage,
)
from openjiuwen_icode.host.bootstrap import build_host_bundle

_WATCH_TYPES = (
    TurnStarted,
    TurnFinished,
    TurnFailed,
    AgentMessage,
    AgentThinking,
    ToolCallStart,
    ToolCallResult,
    ApprovalRequest,
    QuestionToUser,
    TodoListUpdated,
    UsageUpdate,
    UserInjectResult,
    ErrorEvent,
)


def format_event(event: Event) -> str:
    """Human-readable one-line rendering of an EventBus event."""
    name = type(event).__name__
    if isinstance(event, TurnStarted):
        return f"[{name}] text={event.text!r}"
    if isinstance(event, TurnFinished):
        return f"[{name}]"
    if isinstance(event, TurnFailed):
        return f"[{name}] error={event.error!r}"
    if isinstance(event, AgentMessage):
        return f"[{name}] {event.text!r}"
    if isinstance(event, AgentThinking):
        return f"[{name}] {event.text!r}"
    if isinstance(event, ToolCallStart):
        return (
            f"[{name}] tool={event.tool_name!r} "
            f"args={event.tool_args!r}"
        )
    if isinstance(event, ToolCallResult):
        preview = event.result
        if len(preview) > 120:
            preview = preview[:117] + "..."
        return f"[{name}] tool={event.tool_name!r} result={preview!r}"
    if isinstance(event, ApprovalRequest):
        return (
            f"[{name}] id={event.interaction_id!r} "
            f"tool={event.tool_name!r}"
        )
    if isinstance(event, QuestionToUser):
        return f"[{name}] id={event.interaction_id!r}"
    if isinstance(event, TodoListUpdated):
        return f"[{name}] items={event.items!r}"
    if isinstance(event, UsageUpdate):
        return (
            f"[{name}] in={event.input_tokens} "
            f"out={event.output_tokens} total={event.total_tokens}"
        )
    if isinstance(event, UserInjectResult):
        return (
            f"[{name}] id={event.inject_id!r} "
            f"consumed={event.consumed}"
        )
    if isinstance(event, ErrorEvent):
        return f"[{name}] {event.message!r}"
    return f"[{name}]"


def event_to_dict(event: Event) -> dict[str, Any]:
    """JSON-serializable dict for stream-json output."""
    data: dict[str, Any] = {
        "type": type(event).__name__,
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "session_id": event.session_id,
    }
    if isinstance(event, TurnStarted):
        data["text"] = event.text
    elif isinstance(event, TurnFailed):
        data["error"] = event.error
    elif isinstance(event, (AgentMessage, AgentThinking)):
        data["text"] = event.text
    elif isinstance(event, ToolCallStart):
        data["tool_name"] = event.tool_name
        data["tool_args"] = event.tool_args
        data["tool_call_id"] = event.tool_call_id
    elif isinstance(event, ToolCallResult):
        data["tool_name"] = event.tool_name
        data["result"] = event.result
        data["tool_call_id"] = event.tool_call_id
        if event.tool_success is not None:
            data["tool_success"] = event.tool_success
    elif isinstance(event, ModelUsage):
        data["input_tokens"] = event.input_tokens
        data["output_tokens"] = event.output_tokens
        data["call_index"] = event.call_index
    elif isinstance(event, ApprovalRequest):
        data["interaction_id"] = event.interaction_id
        data["tool_name"] = event.tool_name
        data["tool_args"] = event.tool_args
        data["message"] = event.message
    elif isinstance(event, QuestionToUser):
        data["interaction_id"] = event.interaction_id
        data["questions"] = event.questions
        data["message"] = event.message
    elif isinstance(event, TodoListUpdated):
        data["items"] = event.items
    elif isinstance(event, UsageUpdate):
        data["input_tokens"] = event.input_tokens
        data["output_tokens"] = event.output_tokens
        data["total_tokens"] = event.total_tokens
        data["model_calls"] = event.model_calls
    elif isinstance(event, UserInjectResult):
        data["inject_id"] = event.inject_id
        data["consumed"] = event.consumed
    elif isinstance(event, ErrorEvent):
        data["message"] = event.message
    return data


async def run_via_bus(
    cfg: CLIConfig | None,
    prompt: str,
    *,
    demo: bool = False,
    output_format: str = "text",
    auto_approve: bool = True,
    session_id: str | None = None,
    workdir: str | None = None,
    agent_profile: str | None = None,
    result_json: bool = False,
) -> int:
    """Run one turn through EventBus + SessionHost.

    Args:
        cfg: CLI config (required unless ``demo=True``).
        prompt: User prompt.
        demo: Use :class:`DemoBackend` (no API key / LLM).
        output_format: ``text``, ``stream-json``, or ``json`` (legacy summary).
        auto_approve: Headless BYPASS for confirm/ask (default True).
        session_id: Optional session to restore before the turn.
        workdir: Optional primary directory to apply for this run.
        agent_profile: Optional agent profile id (persisted for this process).
        result_json: If True, print Chrys-compatible
            ``{session_id, result, duration}`` (``--json``).

    Returns:
        Process exit code (0 success, 1 failure).
    """
    import time

    if agent_profile:
        from openjiuwen_icode.host.profiles import (
            get_agent_profile,
            switch_agent_profile_in_settings,
        )

        row = get_agent_profile(agent_profile)
        if row is None:
            raise ValueError(f"Agent profile not found: {agent_profile}")
        switch_agent_profile_in_settings(agent_profile)

    bundle = build_host_bundle(
        cfg,
        demo=demo,
        auto_approve=auto_approve,
        session_id=session_id,
    )
    bus = bundle.bus
    host = bundle.host
    sid = bundle.session_id
    model_name = (
        "demo"
        if demo
        else (cfg.model if cfg is not None else "unknown")
    )
    failed = False
    agent_text_parts: list[str] = []
    event_count = 0
    started = time.monotonic()

    if workdir:
        from openjiuwen_icode.host.workdirs import (
            apply_workdir_to_backend,
        )

        try:
            path = host.workdirs.use(workdir)
        except ValueError:
            # Not yet in registry — add then use.
            path = host.workdirs.add(workdir)
            host.workdirs.use(path)
        apply_workdir_to_backend(host._backend, path)

    if session_id and host.session_store is not None:
        from openjiuwen_icode.features.session_resume import (
            align_backend_session_after_resume,
        )

        try:
            stored = host.session_store.switch_session(session_id)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        await align_backend_session_after_resume(host, stored)
        sid = stored.session_id
        bind = getattr(host, "_bind_event_log", None)
        if callable(bind):
            bind(sid)

    # Quiet event printing when emitting Chrys final --json.
    emit_events = not result_json
    fmt = output_format if emit_events else "none"

    async with bus.stream(*_WATCH_TYPES) as stream:

        async def _consume() -> None:
            nonlocal failed, event_count
            async for event in stream:
                event_count += 1
                if isinstance(event, AgentMessage):
                    agent_text_parts.append(event.text)

                if fmt == "stream-json":
                    print(
                        json.dumps(
                            event_to_dict(event), ensure_ascii=False
                        )
                    )
                elif fmt == "text":
                    print(format_event(event))
                # json / none: accumulate silently until end

                if isinstance(event, TurnFailed):
                    failed = True
                    break
                if isinstance(event, TurnFinished):
                    break

        consumer = asyncio.create_task(_consume())
        try:
            await host.start()
            await bus.publish(
                UserMessage(text=prompt, session_id=sid)
            )
            await consumer
        finally:
            if not consumer.done():
                consumer.cancel()
                try:
                    await consumer
                except asyncio.CancelledError:
                    pass
            await host.stop()

    duration = round(time.monotonic() - started, 3)
    result_text = "".join(agent_text_parts)

    if result_json:
        payload = {
            "session_id": sid,
            "result": result_text,
            "duration": duration,
        }
        if failed:
            payload["ok"] = False
        print(json.dumps(payload, ensure_ascii=False))
    elif output_format == "json":
        output = {
            "session_id": sid,
            "result": result_text,
            "duration": duration,
            "chunks": event_count,
            "model": model_name,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))

    return 1 if failed else 0

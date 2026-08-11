# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""EventBus helpers for sub-agent abort/retry."""

from __future__ import annotations

from typing import Any

from openjiuwen.core.session.agent import Session
from openjiuwen_icode.events import (
    EventBus,
    SubAgentAborted,
    SubAgentResumed,
    SubAgentStarted,
    SystemNotice,
)
from openjiuwen_icode.features.subagent_awaiting import (
    publish_subagent_awaiting_state,
)
from openjiuwen.harness.tools.subagent.control import (
    abort_subagent_invocation,
    retry_subagent_invocation,
)
from openjiuwen.harness.tools.subagent.lifecycle import emit_subagent_chunk


def _parent_session(agent: Any) -> Session | None:
    return getattr(agent, "_loop_session", None)


async def handle_subagent_abort(
    bus: EventBus,
    backend: Any,
    invocation_id: str,
    session_id: str | None,
) -> None:
    agent = getattr(backend, "agent", None)
    sess = _parent_session(agent)
    ok, msg, agent_name = await abort_subagent_invocation(
        agent,
        invocation_id,
        parent_session=sess,
        reason="user_abort",
    )
    await publish_subagent_awaiting_state(bus, backend, session_id)
    if ok:
        await bus.publish(
            SubAgentAborted(
                agent_name=agent_name,
                invocation_id=invocation_id,
                reason="user_abort",
                session_id=session_id,
            )
        )
    await bus.publish(
        SystemNotice(
            text=msg if ok else f"Abort failed: {msg}",
            kind="info" if ok else "error",
            session_id=session_id,
        )
    )


async def handle_subagent_retry(
    bus: EventBus,
    backend: Any,
    invocation_id: str,
    session_id: str | None,
) -> None:
    agent = getattr(backend, "agent", None)
    sess = _parent_session(agent)
    if sess is None:
        await bus.publish(
            SystemNotice(
                text="Retry requires an active agent session (start a turn first).",
                kind="error",
                session_id=session_id,
            )
        )
        return
    ok, msg, agent_name, new_id = await retry_subagent_invocation(
        agent, invocation_id, sess
    )
    await publish_subagent_awaiting_state(bus, backend, session_id)
    if ok and new_id:
        await emit_subagent_chunk(
            sess,
            "subagent.started",
            agent_name=agent_name,
            invocation_id=new_id,
            sub_session_id="",
            transport="async",
            task=f"retry of {invocation_id}",
        )
        await bus.publish(
            SubAgentResumed(
                agent_name=agent_name,
                invocation_id=new_id,
                session_id=session_id,
            )
        )
        await bus.publish(
            SubAgentStarted(
                agent_name=agent_name,
                task=f"retry of {invocation_id}",
                invocation_id=new_id,
                transport="async",
                session_id=session_id,
            )
        )
    await bus.publish(
        SystemNotice(
            text=msg if ok else f"Retry failed: {msg}",
            kind="info" if ok else "error",
            session_id=session_id,
        )
    )


__all__ = ["handle_subagent_abort", "handle_subagent_retry"]

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Publish sub-agent awaiting state on the EventBus."""

from __future__ import annotations

from typing import Any

from openjiuwen_icode.events import (
    EventBus,
    SubAgentsAwaiting,
    SubAgentsIdle,
)
from openjiuwen.harness.tools.subagent.awaiting import (
    list_running_async_tasks,
    write_awaiting_marker,
)


async def publish_subagent_awaiting_state(
    bus: EventBus,
    backend: Any,
    session_id: str | None,
) -> None:
    """Emit ``SubAgentsAwaiting`` or ``SubAgentsIdle`` after a turn or spawn."""
    sid = session_id or ""
    agent = getattr(backend, "agent", None)
    running = list_running_async_tasks(agent)
    if sid:
        write_awaiting_marker(sid, running)
    if running:
        await bus.publish(
            SubAgentsAwaiting(
                count=len(running),
                items=running,
                session_id=sid or None,
            )
        )
    else:
        await bus.publish(SubAgentsIdle(session_id=sid or None))


__all__ = ["publish_subagent_awaiting_state"]

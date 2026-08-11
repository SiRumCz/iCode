# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Publish sub-agent awaiting state on the EventBus."""

from __future__ import annotations

import logging
from typing import Any

from openjiuwen_icode.events import (
    EventBus,
    SubAgentsAwaiting,
    SubAgentsIdle,
)

logger = logging.getLogger(__name__)

try:
    from openjiuwen.harness.tools.subagent.awaiting import (
        list_running_async_tasks,
        write_awaiting_marker,
    )

    _HAS_AWAITING = True
except ImportError:  # pragma: no cover - older SDK
    _HAS_AWAITING = False

    def list_running_async_tasks(agent: Any) -> list[dict[str, Any]]:
        return []

    def write_awaiting_marker(
        session_id: str, running: list[dict[str, Any]]
    ) -> None:
        return None


async def publish_subagent_awaiting_state(
    bus: EventBus,
    backend: Any,
    session_id: str | None,
) -> None:
    """Emit ``SubAgentsAwaiting`` or ``SubAgentsIdle`` after a turn or spawn."""
    if not _HAS_AWAITING:
        logger.debug(
            "tools.subagent.awaiting unavailable; emitting SubAgentsIdle"
        )
        await bus.publish(SubAgentsIdle(session_id=session_id))
        return

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

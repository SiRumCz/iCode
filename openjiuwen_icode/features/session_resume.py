# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Align SessionHost / LocalBackend with SessionStore on ``/resume``."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openjiuwen_icode.storage.session_store import StoredMessage, StoredSession

logger = logging.getLogger(__name__)

# agent_context values published on SessionRestored / status text
AGENT_CONTEXT_CHECKPOINT = "checkpoint"
AGENT_CONTEXT_SEEDED = "seeded"
AGENT_CONTEXT_SKIPPED = "skipped"
AGENT_CONTEXT_UNAVAILABLE = "unavailable"
AGENT_CONTEXT_METADATA_ONLY = "metadata_only"


@dataclass(frozen=True)
class SessionResumeResult:
    """Outcome of post-:func:`resume` backend alignment."""

    session_id: str
    agent_context: str
    store_messages: int
    context_messages: int = 0


def stored_messages_to_llm_messages(
    messages: list[StoredMessage],
) -> list[Any]:
    """Convert persisted transcript rows to foundation chat messages."""
    from openjiuwen.core.foundation.llm.schema.message import (
        AssistantMessage,
        UserMessage,
    )

    out: list[Any] = []
    for msg in messages:
        text = (msg.content or "").strip()
        if not text:
            continue
        if msg.role == "user":
            out.append(UserMessage(content=msg.content))
        elif msg.role == "assistant":
            out.append(AssistantMessage(content=msg.content))
    return out


def _count_dialogue_messages(context_messages: Any) -> int:
    if not context_messages:
        return 0
    count = 0
    for item in context_messages:
        role = getattr(item, "role", None)
        if role is None and isinstance(item, dict):
            role = item.get("role")
        if role in ("user", "assistant"):
            count += 1
    return count


async def align_backend_session_after_resume(
    host: Any,
    session: StoredSession,
) -> SessionResumeResult:
    """Point backend at *session* and seed DeepAgent context when checkpoint is empty."""
    sid = session.session_id
    host._session_id = sid

    from openjiuwen_icode.features.session_metadata import (
        apply_stored_workdir_to_host,
    )

    apply_stored_workdir_to_host(host, session)

    backend = getattr(host, "_backend", None)
    if backend is not None and hasattr(backend, "_session_id"):
        backend._session_id = sid

    history = stored_messages_to_llm_messages(list(session.messages))

    agent = getattr(backend, "agent", None) if backend is not None else None
    if agent is None:
        return SessionResumeResult(
            session_id=sid,
            agent_context=AGENT_CONTEXT_UNAVAILABLE,
            store_messages=len(history),
        )

    context_count = 0
    try:
        ctx_msgs = agent.get_current_context(session_id=sid)
        context_count = _count_dialogue_messages(ctx_msgs)
    except Exception:
        context_count = 0

    if context_count > 0:
        return SessionResumeResult(
            session_id=sid,
            agent_context=AGENT_CONTEXT_CHECKPOINT,
            store_messages=len(history),
            context_messages=context_count,
        )

    if not history:
        return SessionResumeResult(
            session_id=sid,
            agent_context=AGENT_CONTEXT_SKIPPED,
            store_messages=0,
            context_messages=0,
        )

    try:
        await agent.create_new_context_engine(
            session_id=sid,
            messages=history,
        )
        return SessionResumeResult(
            session_id=sid,
            agent_context=AGENT_CONTEXT_SEEDED,
            store_messages=len(history),
            context_messages=len(history),
        )
    except Exception:
        logger.exception(
            "Failed to seed DeepAgent context for session %s", sid
        )
        return SessionResumeResult(
            session_id=sid,
            agent_context=AGENT_CONTEXT_METADATA_ONLY,
            store_messages=len(history),
            context_messages=0,
        )


def format_resume_agent_context_note(result: SessionResumeResult) -> str:
    """Human-readable suffix for SystemNotice after resume."""
    if result.agent_context == AGENT_CONTEXT_CHECKPOINT:
        return (
            f"Agent context restored from checkpoint "
            f"({result.context_messages} dialogue messages)."
        )
    if result.agent_context == AGENT_CONTEXT_SEEDED:
        return (
            f"Agent context seeded from session store "
            f"({result.store_messages} messages)."
        )
    if result.agent_context == AGENT_CONTEXT_SKIPPED:
        return "No transcript messages to seed; agent starts fresh."
    if result.agent_context == AGENT_CONTEXT_METADATA_ONLY:
        return (
            "Transcript loaded in UI; agent context seed failed "
            "(next turn may not see full history)."
        )
    return "Agent context sync skipped (demo / no DeepAgent)."

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for unified session resume (store + DeepAgent context)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from openjiuwen_icode.features.session_resume import (
    AGENT_CONTEXT_CHECKPOINT,
    AGENT_CONTEXT_SEEDED,
    AGENT_CONTEXT_UNAVAILABLE,
    align_backend_session_after_resume,
    stored_messages_to_llm_messages,
)
from openjiuwen_icode.storage.session_store import (
    StoredMessage,
    StoredSession,
)


class TestStoredMessagesToLlm:
    def test_skips_empty(self) -> None:
        msgs = stored_messages_to_llm_messages(
            [
                StoredMessage(role="user", content="  ", timestamp="t"),
                StoredMessage(role="assistant", content="hi", timestamp="t"),
            ]
        )
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"


@pytest.mark.asyncio
async def test_align_unavailable_when_no_agent() -> None:
    host = MagicMock()
    host._backend = MagicMock(agent=None)
    session = StoredSession(
        session_id="cli-a",
        model="m",
        created_at="t",
        messages=[
            StoredMessage(role="user", content="hello", timestamp="t"),
        ],
    )
    result = await align_backend_session_after_resume(host, session)
    assert host._session_id == "cli-a"
    assert result.agent_context == AGENT_CONTEXT_UNAVAILABLE


@pytest.mark.asyncio
async def test_align_uses_checkpoint_when_present() -> None:
    agent = MagicMock()
    agent.get_current_context.return_value = [
        MagicMock(role="user"),
        MagicMock(role="assistant"),
    ]
    host = MagicMock()
    host._backend = MagicMock(agent=agent, _session_id="old")
    session = StoredSession(
        session_id="cli-b",
        model="m",
        created_at="t",
        messages=[
            StoredMessage(role="user", content="hello", timestamp="t"),
        ],
    )
    result = await align_backend_session_after_resume(host, session)
    assert result.agent_context == AGENT_CONTEXT_CHECKPOINT
    assert result.context_messages == 2
    agent.create_new_context_engine.assert_not_called()


@pytest.mark.asyncio
async def test_align_seeds_when_checkpoint_empty() -> None:
    agent = MagicMock()
    agent.get_current_context.side_effect = RuntimeError("no context")
    agent.create_new_context_engine = AsyncMock()
    host = MagicMock()
    host._backend = MagicMock(agent=agent, _session_id="old")
    session = StoredSession(
        session_id="cli-c",
        model="m",
        created_at="t",
        messages=[
            StoredMessage(role="user", content="hello", timestamp="t"),
            StoredMessage(role="assistant", content="world", timestamp="t"),
        ],
    )
    result = await align_backend_session_after_resume(host, session)
    assert result.agent_context == AGENT_CONTEXT_SEEDED
    agent.create_new_context_engine.assert_awaited_once()
    call_kw = agent.create_new_context_engine.await_args.kwargs
    assert call_kw["session_id"] == "cli-c"
    assert len(call_kw["messages"]) == 2

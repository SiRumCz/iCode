# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for sub-agent auto-retry and SubAgentRetryAttempt mapping."""

from __future__ import annotations

import pytest

from openjiuwen.core.session.stream.base import OutputSchema
from openjiuwen_icode.events import SubAgentRetryAttempt, chunk_to_events
from openjiuwen.harness.tools.subagent import auto_retry as auto_retry_mod
from openjiuwen.harness.tools.subagent.auto_retry import (
    is_retryable_subagent_error,
    load_subagent_max_retries,
    run_with_subagent_retries,
)


def test_maps_retry_attempt_chunk() -> None:
    events = chunk_to_events(
        OutputSchema(
            type="subagent.retry_attempt",
            index=0,
            payload={
                "agent_name": "explore_agent",
                "invocation_id": "inv-1",
                "message": "timeout",
                "attempt": 1,
                "max_attempts": 2,
                "delay_seconds": 1,
                "transport": "sync",
            },
        )
    )
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, SubAgentRetryAttempt)
    assert ev.attempt == 1
    assert ev.max_attempts == 2
    assert ev.delay_seconds == 1
    assert "timeout" in ev.message


def test_non_retryable_concurrency() -> None:
    assert not is_retryable_subagent_error(
        RuntimeError("Sub-agent concurrency limit reached")
    )
    assert is_retryable_subagent_error(TimeoutError("stream stalled"))


@pytest.mark.asyncio
async def test_run_with_retries_succeeds_after_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENJIUWEN_SUBAGENT_MAX_RETRIES", "2")
    calls = {"n": 0}
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(auto_retry_mod.asyncio, "sleep", _fake_sleep)

    async def _invoke() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("transient")
        return "ok"

    result = await run_with_subagent_retries(
        _invoke,
        session=None,
        agent_name="explore_agent",
        invocation_id="inv-x",
        max_retries=2,
    )
    assert result == "ok"
    assert calls["n"] == 2
    assert sleeps == [1]


@pytest.mark.asyncio
async def test_run_with_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(auto_retry_mod.asyncio, "sleep", _fake_sleep)

    async def _invoke() -> str:
        raise TimeoutError("always")

    with pytest.raises(TimeoutError):
        await run_with_subagent_retries(
            _invoke,
            session=None,
            agent_name="plan_agent",
            invocation_id="inv-y",
            max_retries=1,
        )


def test_load_max_retries_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENJIUWEN_SUBAGENT_MAX_RETRIES", "5")
    assert load_subagent_max_retries() == 5

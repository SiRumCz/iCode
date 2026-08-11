# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for Chrys-aligned CLI sub-agents."""

from __future__ import annotations

import pytest

from openjiuwen_icode.subagents import build_cli_subagents
from openjiuwen.harness.subagents.concurrency import (
    SubagentConcurrencyConfig,
    SubagentConcurrencyLimiter,
)
from openjiuwen.harness.tools.subagent.session_tools import SessionToolkit


class _FakeModel:
    pass


def test_roster_filter_from_settings() -> None:
    built = build_cli_subagents(
        _FakeModel(),
        include_browser=True,
        include_research=True,
        roster_names=["explore_agent"],
    )
    assert [s.agent_card.name for s in built] == ["explore_agent"]


def test_build_cli_subagents_chrys_roster() -> None:
    names = [
        s.agent_card.name
        for s in build_cli_subagents(
            _FakeModel(),
            include_browser=False,
            include_research=False,
        )
    ]
    assert names == ["explore_agent", "plan_agent"]


def test_concurrency_limiter_total_cap() -> None:
    limiter = SubagentConcurrencyLimiter(
        SubagentConcurrencyConfig(max_total=1, per_agent_default=2)
    )
    toolkit = SessionToolkit()
    toolkit.upsert_running("t1", "s1", "job", subagent_type="explore_agent")
    err = limiter.check_spawn("plan_agent", toolkit=toolkit)
    assert err is not None
    assert "concurrency limit" in err.lower()


@pytest.mark.asyncio
async def test_concurrency_acquire_release_sync() -> None:
    limiter = SubagentConcurrencyLimiter(
        SubagentConcurrencyConfig(max_total=2, per_agent_default=1)
    )
    err = await limiter.acquire_sync("explore_agent", None)
    assert err is None
    err2 = await limiter.acquire_sync("explore_agent", None)
    assert err2 is not None
    limiter.release_sync("explore_agent")
    err3 = await limiter.acquire_sync("explore_agent", None)
    assert err3 is None
    limiter.release_sync("explore_agent")

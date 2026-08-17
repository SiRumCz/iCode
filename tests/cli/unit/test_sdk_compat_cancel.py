# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for DeepAgent cancel-cycle runtime patch."""

from __future__ import annotations

import asyncio

import pytest

from openjiuwen_icode import sdk_compat_cancel as cancel_patch


@pytest.mark.asyncio
async def test_patched_cancel_skips_await_when_self() -> None:
    """Self-cancel must not await current_task (RecursionError footgun)."""
    cancel_patch._PATCHED = False
    assert cancel_patch.patch_deep_agent_cancel_cycle()

    from openjiuwen.harness.deep_agent import DeepAgent

    agent = DeepAgent.__new__(DeepAgent)
    finished = asyncio.Event()

    async def _as_stream_process() -> str:
        agent._stream_process_task = asyncio.current_task()
        await DeepAgent._cancel_stream_process_task(agent)
        finished.set()
        # Deliver the self-cancel without awaiting self in the helper.
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            return "cancelled-ok"
        return "still-running"

    task = asyncio.create_task(_as_stream_process())
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result == "cancelled-ok"
    assert finished.is_set()


@pytest.mark.asyncio
async def test_patched_cancel_awaits_other_task() -> None:
    cancel_patch._PATCHED = False
    assert cancel_patch.patch_deep_agent_cancel_cycle()

    from openjiuwen.harness.deep_agent import DeepAgent

    agent = DeepAgent.__new__(DeepAgent)
    blocker = asyncio.Event()

    async def _background() -> None:
        await blocker.wait()

    bg = asyncio.create_task(_background())
    agent._stream_process_task = bg
    await DeepAgent._cancel_stream_process_task(agent)
    assert bg.done()

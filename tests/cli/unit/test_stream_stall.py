# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for stream stall retry helper."""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from openjiuwen_icode.features.stream_stall import (
    StreamStallError,
    iter_with_stall_retry,
)


@pytest.mark.asyncio
async def test_retries_when_first_chunk_stalls() -> None:
    calls = {"n": 0}

    def open_stream() -> AsyncIterator[Any]:
        calls["n"] += 1

        async def _gen() -> AsyncIterator[Any]:
            if calls["n"] == 1:
                await __import__("asyncio").sleep(10)
                yield "late"
                return
            yield "ok"

        return _gen()

    retries: list[int] = []

    async def on_retry(attempt: int, stall: float) -> None:
        retries.append(attempt)

    out: list[Any] = []
    async for chunk in iter_with_stall_retry(
        open_stream,
        stall_seconds=0.05,
        max_retries=2,
        on_retry=on_retry,
    ):
        out.append(chunk)
    assert out == ["ok"]
    assert retries == [1]


@pytest.mark.asyncio
async def test_midstream_stall_retries_when_enabled() -> None:
    calls = {"n": 0}

    def open_stream() -> AsyncIterator[Any]:
        calls["n"] += 1

        async def _gen() -> AsyncIterator[Any]:
            if calls["n"] == 1:
                yield "a"
                await __import__("asyncio").sleep(10)
                yield "b"
                return
            yield "continued"

        return _gen()

    out: list[Any] = []
    async for chunk in iter_with_stall_retry(
        open_stream,
        stall_seconds=0.05,
        max_retries=2,
        retry_midstream=True,
    ):
        out.append(chunk)
    assert out == ["a", "continued"]
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_midstream_stall_raises_when_disabled() -> None:
    def open_stream() -> AsyncIterator[Any]:
        async def _gen() -> AsyncIterator[Any]:
            yield "a"
            await __import__("asyncio").sleep(10)
            yield "b"

        return _gen()

    with pytest.raises(StreamStallError):
        async for _ in iter_with_stall_retry(
            open_stream,
            stall_seconds=0.05,
            max_retries=3,
            retry_midstream=False,
        ):
            pass


@pytest.mark.asyncio
async def test_stall_aclose_survives_cancel_cycle_recursion() -> None:
    """Stall retry must not die if prior-stream aclose hits RecursionError."""
    calls = {"n": 0}

    class _Stream:
        def __init__(self, gen: AsyncIterator[Any]) -> None:
            self._gen = gen

        def __aiter__(self) -> "_Stream":
            return self

        async def __anext__(self) -> Any:
            return await self._gen.__anext__()

        async def aclose(self) -> None:
            raise RecursionError("maximum recursion depth exceeded")

    def open_stream() -> AsyncIterator[Any]:
        calls["n"] += 1

        async def _gen() -> AsyncIterator[Any]:
            if calls["n"] == 1:
                yield "a"
                await __import__("asyncio").sleep(10)
                yield "never"
                return
            yield "recovered"

        return _Stream(_gen())

    out: list[Any] = []
    async for chunk in iter_with_stall_retry(
        open_stream,
        stall_seconds=0.05,
        max_retries=2,
        retry_midstream=True,
    ):
        out.append(chunk)
    assert out == ["a", "recovered"]
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_stall_timeout_uses_sibling_anext_task() -> None:
    """Stall must time out via wait() on a sibling task, not wait_for(anext).

    Using wait_for(anext) cancels the consumer and injects CancelledError into
    DeepAgent, which historically triggered a Task.cancel RecursionError.
    """
    import asyncio

    def open_stream() -> AsyncIterator[Any]:
        async def _gen() -> AsyncIterator[Any]:
            yield "a"
            await asyncio.sleep(10)
            yield "b"

        return _gen()

    with pytest.raises(StreamStallError):
        async for _ in iter_with_stall_retry(
            open_stream,
            stall_seconds=0.05,
            max_retries=1,
            retry_midstream=True,
        ):
            pass

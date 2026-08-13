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

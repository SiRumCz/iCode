# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Stream idle / stall detection with limited retries (T-43)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Awaitable, Callable

logger = logging.getLogger(__name__)

DEFAULT_STALL_SECONDS = 90.0
DEFAULT_MAX_RETRIES = 3


class StreamStallError(TimeoutError):
    """Raised when no stream chunk arrives within the idle window."""


async def iter_with_stall_retry(
    open_stream: Callable[[], AsyncIterator[Any]],
    *,
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    on_retry: Callable[[int, float], Awaitable[None] | None] | None = None,
) -> AsyncIterator[Any]:
    """Yield chunks from *open_stream*, restarting on idle stall.

    Retries only when **zero** chunks were received for the attempt (true hang
    before first token). Mid-stream stalls raise after retries are exhausted
    so partial UI state is not silently replayed.
    """
    attempt = 0
    while True:
        attempt += 1
        received = 0
        stream = open_stream()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        stream.__anext__(),
                        timeout=stall_seconds,
                    )
                except StopAsyncIteration:
                    return
                except asyncio.TimeoutError as exc:
                    if received == 0 and attempt <= max_retries:
                        logger.warning(
                            "Stream stall before first chunk "
                            "(attempt %s/%s, idle=%.0fs); retrying",
                            attempt,
                            max_retries,
                            stall_seconds,
                        )
                        if on_retry is not None:
                            maybe = on_retry(attempt, stall_seconds)
                            if maybe is not None and hasattr(maybe, "__await__"):
                                await maybe
                        break
                    raise StreamStallError(
                        f"stream stalled after {received} chunks "
                        f"(idle {stall_seconds:.0f}s, attempt {attempt})"
                    ) from exc
                received += 1
                yield chunk
            else:
                return
            continue
        finally:
            aclose = getattr(stream, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception:  # noqa: BLE001
                    pass


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_STALL_SECONDS",
    "StreamStallError",
    "iter_with_stall_retry",
]

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Stream idle / stall detection with limited retries (T-43)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Awaitable, Callable

from openjiuwen_icode.sdk_compat_cancel import (
    detach_task_waiter,
    wait_abandon,
)

logger = logging.getLogger(__name__)

DEFAULT_STALL_SECONDS = 90.0
DEFAULT_MAX_RETRIES = 3
_ACLOSE_TIMEOUT_SECONDS = 5.0


class StreamStallError(TimeoutError):
    """Raised when no stream chunk arrives within the idle window."""


async def _safe_aclose(stream: Any) -> None:
    """Close a stream without letting cancel-cycle bugs abort the process.

    DeepAgent stream cancel can form an asyncio ``Task.cancel`` parent
    cycle (``RecursionError``). Bound the wait and swallow that failure so
    stall retries can reopen a fresh stream. Must not use ``wait_for``:
    its timer callback ``task.cancel()`` hangs forever on a waiter cycle.
    """
    aclose = getattr(stream, "aclose", None)
    if not callable(aclose):
        return
    try:
        closer = asyncio.ensure_future(aclose())
    except Exception:  # noqa: BLE001
        logger.debug("stream aclose schedule failed", exc_info=True)
        return
    try:
        await wait_abandon(closer, timeout=_ACLOSE_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        raise
    except RecursionError:
        logger.warning(
            "stream aclose hit RecursionError (asyncio cancel cycle); "
            "abandoning prior stream"
        )
    except Exception:  # noqa: BLE001
        logger.debug("stream aclose failed", exc_info=True)


async def iter_with_stall_retry(
    open_stream: Callable[[], AsyncIterator[Any]],
    *,
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_midstream: bool = True,
    on_retry: Callable[[int, float], Awaitable[None] | None] | None = None,
) -> AsyncIterator[Any]:
    """Yield chunks from *open_stream*, restarting on idle stall.

    Retries when the stream hangs before the first chunk, and (when
    ``retry_midstream`` is True) also when it hangs after some chunks have
    already arrived — common with long reasoning / tool-loop model calls.
    Callers should supply a continuation query on reopen via *open_stream*
    closure state so work is not blindly replayed from scratch.

    Idle detection uses a sibling ``asyncio.Task`` for ``__anext__`` so a
    stall timeout does not cancel the consumer task itself (which used to
    inject ``CancelledError`` into DeepAgent and trigger a cancel-cycle
    ``RecursionError``).
    """
    attempt = 0
    while True:
        attempt += 1
        received = 0
        stream = open_stream()
        try:
            while True:
                anext_task = asyncio.create_task(stream.__anext__())
                try:
                    done, _pending = await asyncio.wait(
                        {anext_task},
                        timeout=stall_seconds,
                    )
                except asyncio.CancelledError:
                    detach_task_waiter(anext_task)
                    try:
                        anext_task.cancel()
                    except RecursionError:
                        pass
                    await wait_abandon(
                        anext_task, timeout=_ACLOSE_TIMEOUT_SECONDS
                    )
                    raise

                if not done:
                    detach_task_waiter(anext_task)
                    try:
                        anext_task.cancel()
                    except RecursionError:
                        logger.warning(
                            "RecursionError cancelling stalled __anext__; abandoning"
                        )
                    await wait_abandon(
                        anext_task, timeout=_ACLOSE_TIMEOUT_SECONDS
                    )
                    can_retry = attempt <= max_retries and (
                        received == 0 or retry_midstream
                    )
                    if can_retry:
                        logger.warning(
                            "Stream stall "
                            "(attempt %s/%s, idle=%.0fs, received=%s); retrying",
                            attempt,
                            max_retries,
                            stall_seconds,
                            received,
                        )
                        if on_retry is not None:
                            maybe = on_retry(attempt, stall_seconds)
                            if maybe is not None and hasattr(maybe, "__await__"):
                                await maybe
                        break
                    raise StreamStallError(
                        f"stream stalled after {received} chunks "
                        f"(idle {stall_seconds:.0f}s, attempt {attempt})"
                    )

                try:
                    chunk = anext_task.result()
                except StopAsyncIteration:
                    return
                received += 1
                yield chunk
            else:
                return
            continue
        finally:
            await _safe_aclose(stream)


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_STALL_SECONDS",
    "StreamStallError",
    "iter_with_stall_retry",
]

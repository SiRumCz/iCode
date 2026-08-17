# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Runtime patches for known openjiuwen cancel-cycle bugs.

DeepAgent ``_cancel_stream_process_task`` used to ``await`` the current
task when stall/abort cancelled a live stream. That creates an asyncio
``Task.cancel`` parent cycle and surfaces as
``RecursionError: maximum recursion depth exceeded`` (seen in DeepSWE
aiomonitor runs after the 90s stream-stall window).

When the installed openjiuwen build still has the unsafe method, this
module replaces it. Safe to call repeatedly.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_PATCHED = False


def patch_deep_agent_cancel_cycle() -> bool:
    """Patch DeepAgent cancel helper if it lacks a self-await guard.

    Returns:
        True when a patch was applied (or already applied).
    """
    global _PATCHED
    if _PATCHED:
        return True
    try:
        from openjiuwen.harness.deep_agent import DeepAgent
    except Exception as exc:  # noqa: BLE001
        logger.debug("DeepAgent unavailable for cancel patch: %s", exc)
        return False

    original = getattr(DeepAgent, "_cancel_stream_process_task", None)
    if original is None:
        return False

    # Prefer the upstream fix when present (source mentions current_task).
    try:
        import inspect

        src = inspect.getsource(original)
    except Exception:  # noqa: BLE001
        src = ""
    if "current_task" in src and "RecursionError" in src:
        _PATCHED = True
        return True

    async def _cancel_stream_process_task(self) -> None:
        task = self._stream_process_task
        if task is None or task.done():
            return
        if task is asyncio.current_task():
            task.cancel()
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except RecursionError:
            logger.warning(
                "RecursionError while awaiting cancelled stream process "
                "task; leaving task for the event loop"
            )
        except Exception:
            logger.debug(
                "stream process task raised during cancel",
                exc_info=True,
            )

    DeepAgent._cancel_stream_process_task = _cancel_stream_process_task
    _PATCHED = True
    logger.info("patched DeepAgent._cancel_stream_process_task cancel-cycle guard")
    return True


__all__ = ["patch_deep_agent_cancel_cycle"]

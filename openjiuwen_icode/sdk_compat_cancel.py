# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Runtime patches for known openjiuwen cancel-cycle bugs.

DeepAgent ``_cancel_stream_process_task`` used to ``await`` the current
task when stall/abort cancelled a live stream. That creates an asyncio
``Task.cancel`` parent cycle and surfaces as
``RecursionError: maximum recursion depth exceeded`` (seen in DeepSWE
aiomonitor / obsidian-linter runs after the 90s stream-stall window).

Stall abort can also leave in-flight ``tool:*`` tasks whose waiters form
a cycle with ``_stream_process``. ``asyncio.runners._cancel_all_tasks``
then walks that cycle during process shutdown and SIGSEGVs (exit 139).

When the installed openjiuwen build still has the unsafe method, this
module replaces it. Safe to call repeatedly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_PATCHED_DEEP_AGENT = False
_PATCHED_TASK_CANCEL = False
_PATCHED_CANCEL_ALL = False
_ORIG_TASK_CANCEL = None
_CANCEL_GUARD: set[int] = set()

# Keep the old name so existing tests that flip ``_PATCHED`` still compile.
_PATCHED = False


def detach_task_waiter(task: asyncio.Task) -> None:
    """Drop ``_fut_waiter`` so ``Task.cancel`` cannot walk a parent cycle.

    CPython ``Task.cancel`` is immutable, so we cannot patch it. Clearing
    the waiter first makes cancel() a local flag flip instead of unbounded
    ``child.cancel()`` recursion (obsidian-linter stall abort).

    Non-Task waiters (Events, I/O futures) are cancelled so the task can
    still wake. Peer Tasks are left alone — the caller detaches every
    victim before abandoning the set.
    """
    waiter = None
    try:
        waiter = task._fut_waiter  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        waiter = None
    try:
        task._fut_waiter = None  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    if waiter is None or isinstance(waiter, asyncio.Task):
        return
    try:
        waiter.cancel()
    except RecursionError:
        pass
    except Exception:  # noqa: BLE001
        pass


async def wait_abandon(
    tasks: asyncio.Task | Iterable[asyncio.Task],
    *,
    timeout: float,
) -> None:
    """Wait up to *timeout* seconds without ``wait_for`` cancel-on-expiry.

    ``asyncio.wait_for`` fires ``Timeout._on_timeout`` → ``task.cancel()``.
    If that task is in a waiter cycle, cancel RecursionErrors in the timer
    callback and ``wait_for`` never resumes — the 5400s Pier hang.
    ``asyncio.wait`` times out without cancelling.
    """
    if isinstance(tasks, asyncio.Task):
        pending_set = {tasks}
    else:
        pending_set = {task for task in tasks if task is not None}
    pending_set = {task for task in pending_set if not task.done()}
    if not pending_set:
        return
    _done, leftover = await asyncio.wait(pending_set, timeout=timeout)
    if leftover:
        logger.warning(
            "abandoning %s leftover tasks after %.1fs "
            "(not cancelling; Task.cancel waiter cycle)",
            len(leftover),
            timeout,
        )


def patch_deep_agent_cancel_cycle() -> bool:
    """Patch DeepAgent cancel helper if it lacks a self-await guard.

    Returns:
        True when a patch was applied (or already applied).
    """
    global _PATCHED, _PATCHED_DEEP_AGENT
    if _PATCHED:
        _PATCHED_DEEP_AGENT = True
        return True
    try:
        from openjiuwen.harness.deep_agent import DeepAgent
    except Exception as exc:  # noqa: BLE001
        logger.debug("DeepAgent unavailable for cancel patch: %s", exc)
        return False

    original = getattr(DeepAgent, "_cancel_stream_process_task", None)
    if original is None:
        return False

    async def _cancel_stream_process_task(self) -> None:
        task = self._stream_process_task
        if task is None or task.done():
            return
        detach_task_waiter(task)
        if task is asyncio.current_task():
            try:
                task.cancel()
            except RecursionError:
                logger.warning(
                    "RecursionError self-cancelling stream process task"
                )
            return
        try:
            task.cancel()
        except RecursionError:
            logger.warning(
                "RecursionError cancelling stream process task; abandoning"
            )
            return
        await wait_abandon(task, timeout=5.0)

    DeepAgent._cancel_stream_process_task = _cancel_stream_process_task
    _PATCHED_DEEP_AGENT = True
    _PATCHED = True
    logger.info("patched DeepAgent._cancel_stream_process_task cancel-cycle guard")
    return True


def patch_task_cancel_cycle() -> bool:
    """Best-effort: CPython ``_asyncio.Task`` is immutable, so this may no-op.

    Shutdown RecursionError is handled by ``patch_cancel_all_tasks`` and
    ``cancel_in_flight_agent_tasks`` instead.
    """
    global _PATCHED_TASK_CANCEL, _ORIG_TASK_CANCEL
    if _PATCHED_TASK_CANCEL:
        return True
    orig = getattr(asyncio.Task, "cancel", None)
    if orig is None:
        return False
    _ORIG_TASK_CANCEL = orig

    def _cancel(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        ident = id(self)
        if ident in _CANCEL_GUARD:
            return False
        _CANCEL_GUARD.add(ident)
        try:
            return orig(self, *args, **kwargs)
        except RecursionError:
            logger.warning(
                "Task.cancel RecursionError (wait cycle); skipping subtree"
            )
            return False
        finally:
            _CANCEL_GUARD.discard(ident)

    try:
        asyncio.Task.cancel = _cancel  # type: ignore[method-assign]
    except TypeError:
        logger.info(
            "asyncio.Task.cancel is immutable; relying on shutdown RecursionError guards"
        )
        return False
    _PATCHED_TASK_CANCEL = True
    logger.info("patched asyncio.Task.cancel against waiter cycles")
    return True


def patch_cancel_all_tasks() -> bool:
    """Swallow RecursionError in asyncio runner shutdown cancel."""
    global _PATCHED_CANCEL_ALL
    if _PATCHED_CANCEL_ALL:
        return True
    try:
        import asyncio.runners as runners
    except Exception as exc:  # noqa: BLE001
        logger.debug("asyncio.runners unavailable: %s", exc)
        return False
    original = getattr(runners, "_cancel_all_tasks", None)
    if original is None:
        return False

    def _cancel_all_tasks(loop) -> None:  # type: ignore[no-untyped-def]
        try:
            original(loop)
        except RecursionError:
            logger.warning(
                "asyncio._cancel_all_tasks RecursionError "
                "(Task.cancel cycle); abandoning leftover tasks"
            )

    runners._cancel_all_tasks = _cancel_all_tasks
    _PATCHED_CANCEL_ALL = True
    logger.info("patched asyncio.runners._cancel_all_tasks RecursionError guard")
    return True


def patch_cancel_cycle_guards() -> bool:
    """Install all cancel-cycle runtime patches. Safe to call repeatedly."""
    applied = (
        patch_deep_agent_cancel_cycle(),
        patch_task_cancel_cycle(),
        patch_cancel_all_tasks(),
    )
    return any(applied)


def _is_agent_inflight_task(task: asyncio.Task) -> bool:
    name = ""
    try:
        name = task.get_name() or ""
    except Exception:  # noqa: BLE001
        name = ""
    if name.startswith("tool:"):
        return True
    coro = getattr(task, "get_coro", lambda: None)()
    coro_name = getattr(coro, "__qualname__", "") or ""
    if "_stream_process" in coro_name or "_execute_task_wrapper" in coro_name:
        return True
    if "TaskScheduler.schedule" in coro_name:
        return True
    return False


async def cancel_in_flight_agent_tasks(
    *,
    timeout: float = 5.0,
    extra: Optional[Iterable[asyncio.Task]] = None,
) -> None:
    """Cancel leftover DeepAgent tool / stream tasks after stall abort.

    Must not await a task that is the current task. Failures including
    ``RecursionError`` are swallowed so stall retry can reopen a stream.
    """
    current = asyncio.current_task()
    victims: list[asyncio.Task] = []
    seen: set[int] = set()
    for task in list(asyncio.all_tasks()):
        if task is current or task.done():
            continue
        if not _is_agent_inflight_task(task):
            continue
        ident = id(task)
        if ident in seen:
            continue
        seen.add(ident)
        victims.append(task)
    if extra is not None:
        for task in extra:
            if task is None or task is current or task.done():
                continue
            ident = id(task)
            if ident in seen:
                continue
            seen.add(ident)
            victims.append(task)
    if not victims:
        return
    for task in victims:
        detach_task_waiter(task)
    for task in victims:
        try:
            task.cancel()
        except RecursionError:
            logger.warning(
                "RecursionError cancelling leftover task %s",
                task.get_name(),
            )
        except Exception:  # noqa: BLE001
            logger.debug("cancel leftover task failed", exc_info=True)
    await wait_abandon(victims, timeout=timeout)


__all__ = [
    "cancel_in_flight_agent_tasks",
    "detach_task_waiter",
    "patch_cancel_all_tasks",
    "patch_cancel_cycle_guards",
    "patch_deep_agent_cancel_cycle",
    "patch_task_cancel_cycle",
    "wait_abandon",
]

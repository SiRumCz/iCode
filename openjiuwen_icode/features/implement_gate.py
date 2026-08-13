# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Detect implement-style tasks and build continuation nudges."""

from __future__ import annotations

_IMPLEMENT_HINTS = (
    "implement",
    "fix ",
    "fix the",
    "add support",
    "add a",
    "edit ",
    "modify ",
    "refactor",
    "patch",
    "write ",
    "create ",
    "lolbench-submit",
    "solution.patch",
    "change the code",
    "update the code",
    "make the following",
)

STALL_CONTINUATION_NUDGE = (
    "Your previous response stalled mid-stream. Continue the same task now. "
    "If code changes were requested, call `edit_file` or `write_file` "
    "immediately — do not only search or read files."
)

ZERO_MUTATION_NUDGE = (
    "You analyzed the codebase but did not modify any files. "
    "The user asked you to implement changes. Call `edit_file` or "
    "`write_file` now to apply a concrete patch in the worktree. "
    "Do not stop after another design essay. When the patch is in place, "
    "run any required submit/deliver command (for example `lolbench-submit`)."
)


def looks_like_implement_task(text: str) -> bool:
    """Return True when *text* looks like a coding implementation request."""
    if not text or not str(text).strip():
        return False
    lower = str(text).lower()
    return any(hint in lower for hint in _IMPLEMENT_HINTS)


__all__ = [
    "STALL_CONTINUATION_NUDGE",
    "ZERO_MUTATION_NUDGE",
    "looks_like_implement_task",
]

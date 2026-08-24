# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Helpers for Chrys-aligned headless ``openjiuwen run``."""

from __future__ import annotations

import os
from pathlib import Path


class TaskFileError(Exception):
    """Raised when ``--task`` cannot be loaded."""

    def __init__(self, message: str, *, code: str = "task_file_error") -> None:
        super().__init__(message)
        self.code = code


def apply_workdir(cwd: str | None) -> str | None:
    """Resolve and ``chdir`` into *cwd*. Returns absolute path or ``None``."""
    if not cwd:
        return None
    path = Path(cwd).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise FileNotFoundError(f"Working directory does not exist: {cwd}") from exc
    if not resolved.is_dir():
        raise NotADirectoryError(f"Working directory is not a directory: {resolved}")
    os.chdir(resolved)
    return os.fspath(resolved)


def read_task_file(task: str, *, relative_to: str | None = None) -> str:
    """Read prompt text from *task* (path relative to *relative_to* / cwd)."""
    if task == "-":
        raise TaskFileError(
            "Task file does not exist: -",
            code="task_file_not_found",
        )
    path = Path(task).expanduser()
    if not path.is_absolute() and relative_to:
        path = Path(relative_to) / path
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise TaskFileError(
            f"Task file does not exist: {task}",
            code="task_file_not_found",
        ) from exc
    except OSError as exc:
        raise TaskFileError(
            f"Failed to read task file: {path}: {exc}",
            code="task_file_read_failed",
        ) from exc
    if not resolved.is_file():
        raise TaskFileError(
            f"Task path is not a file: {resolved}",
            code="task_file_not_file",
        )
    try:
        return resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Best-effort fallback for non-utf8 task files.
        return resolved.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        raise TaskFileError(
            f"Failed to read task file: {resolved}: {exc}",
            code="task_file_read_failed",
        ) from exc


def resolve_prompt(
    *,
    prompt: str | None,
    task: str | None,
    workdir: str | None = None,
) -> str:
    """Return the user prompt from positional arg or ``--task`` file.

    Implement-looking prompts are wrapped with a headless task envelope so
    models do not misread ``## Configuration`` / Execution rules as system
    setup and greet instead of coding.
    """
    if (prompt is None) == (task is None):
        # Both set or both missing — caller should validate with click.
        if prompt is not None and task is not None:
            raise ValueError("provide either a prompt or --task FILE, not both")
        raise ValueError("provide either a prompt or --task FILE")
    if task is not None:
        raw = read_task_file(task, relative_to=workdir)
    else:
        assert prompt is not None
        raw = prompt
    from openjiuwen_icode.features.implement_gate import (
        wrap_headless_implement_prompt,
    )

    return wrap_headless_implement_prompt(raw)


__all__ = [
    "TaskFileError",
    "apply_workdir",
    "read_task_file",
    "resolve_prompt",
]

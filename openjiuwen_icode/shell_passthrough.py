# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Local shell passthrough (no agent) for REPL / TUI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

# ASCII and fullwidth bang (Chrys-style shell-mode toggle).
SHELL_BANGS = frozenset({"!", "！"})


@dataclass(frozen=True)
class ShellResult:
    """Outcome of a local shell command."""

    command: str
    returncode: int
    stdout: str
    stderr: str


def is_shell_toggle(text: str) -> bool:
    """Return True when *text* is only a shell-mode bang."""
    return text.strip() in SHELL_BANGS


def shell_command_from_bang_line(text: str) -> str | None:
    """Parse ``!cmd`` / ``！cmd`` one-shot lines.

    Returns:
        Command string (may be empty for toggle-only), or ``None`` if the
        line is not a bang-prefixed shell line.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if stripped[0] not in SHELL_BANGS:
        return None
    return stripped[1:].lstrip()


async def run_shell_command(
    cmd: str,
    *,
    cwd: str | None = None,
    max_chars: int = 50_000,
) -> ShellResult:
    """Run *cmd* via the user shell; capture stdout/stderr.

    Args:
        cmd: Shell command string (passed to ``create_subprocess_shell``).
        cwd: Optional working directory.
        max_chars: Truncate each stream beyond this many characters.
    """
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode(errors="replace")
    stderr = stderr_b.decode(errors="replace")
    if len(stdout) > max_chars:
        stdout = stdout[: max_chars - 1] + "…"
    if len(stderr) > max_chars:
        stderr = stderr[: max_chars - 1] + "…"
    return ShellResult(
        command=cmd,
        returncode=int(proc.returncode or 0),
        stdout=stdout,
        stderr=stderr,
    )


def format_shell_user_message(cmd: str) -> str:
    """History line for the shell command the user ran."""
    return f"$ {cmd}"


def format_shell_result_message(result: ShellResult) -> str:
    """History line for shell stdout/stderr / exit code."""
    parts: list[str] = ["[shell]"]
    out = result.stdout.rstrip("\n")
    err = result.stderr.rstrip("\n")
    if out:
        parts.append(out)
    if err:
        parts.append(err)
    if result.returncode != 0:
        parts.append(f"(exit {result.returncode})")
    if len(parts) == 1:
        parts.append("(no output)")
    return "\n".join(parts)


def persist_shell_turn(store: Any, result: ShellResult) -> None:
    """Append shell command + result to a session store (if present)."""
    if store is None:
        return
    add = getattr(store, "add_message", None)
    if add is None:
        return
    add("user", format_shell_user_message(result.command))
    add("assistant", format_shell_result_message(result))


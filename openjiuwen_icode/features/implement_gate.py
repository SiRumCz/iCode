# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Detect implement-style tasks and build continuation nudges."""

from __future__ import annotations

import json
import re
from typing import Any

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

_VERIFY_HINTS = (
    "cargo check",
    "cargo test",
    "cargo build",
    "cargo clippy",
    "pytest",
    "python -m pytest",
    "npm test",
    "npm run test",
    "pnpm test",
    "yarn test",
    "go test",
    "make test",
    "make check",
    "mvn test",
    "gradle test",
    "tsc ",
    "mypy",
    "ruff check",
    "unittest",
)

_SUBMIT_HINTS = (
    "lolbench-submit",
    "solution.patch",
)

_LOGIC_MARKERS = (
    "return ",
    "if ",
    "match ",
    "let ",
    "for ",
    "while ",
    "parse",
    "anyhow",
    "Ok(",
    "Err(",
    "Result<",
    ".push(",
    "from_str",
    "value_parser",
)

_DEF_MARKERS = ("fn ", "struct ", "enum ", "impl ", "trait ", "mod ")

STALL_CONTINUATION_NUDGE = (
    "Your previous response stalled mid-stream. Continue the same task now. "
    "If code changes were requested, call `edit_file` or `write_file` "
    "immediately — do not only search or read files."
)

ZERO_MUTATION_NUDGE = (
    "You analyzed the codebase but did not modify any files. "
    "The user asked you to implement changes. Call `edit_file` or "
    "`write_file` now to apply a concrete patch in the worktree. "
    "Do not search git history for an upstream PR — this checkout is often "
    "at a pruned base commit with no solution commits to find. "
    "Do not stop after another design essay. When the patch is in place, "
    "run any required submit/deliver command (for example `lolbench-submit`)."
)

INCOMPLETE_IMPLEMENT_ERROR = (
    "implement task incomplete: no qualifying code changes / verify / submit "
    "before headless continuations were exhausted"
)

SHALLOW_EDIT_NUDGE = (
    "Your edits look like signature/docs-only changes (for example renaming "
    "`Option<PathBuf>` to `Vec<String>` without adding parsers, validation, "
    "or apply/resolve wiring). That is not a complete implementation. "
    "Continue: implement the full behavior the user requested, update all "
    "call sites, then run a compile/check command via `bash` (for Rust: "
    "`cargo check` or a targeted `cargo test`). Do not stop after type-only "
    "edits."
)

VERIFY_NUDGE = (
    "You modified files but have not verified the build/tests. "
    "Call `bash` now to run a compile or targeted test command appropriate "
    "for this repo (for Rust: `cargo check` or a focused `cargo test`). "
    "Fix any errors that appear, then continue. If the user required a "
    "submit/deliver command (for example `lolbench-submit`), run it after "
    "verification succeeds."
)

SUBMIT_NUDGE = (
    "Code changes look underway and verification was attempted, but the "
    "required deliverable is still missing. Run the submit/deliver command "
    "the user named (for example `lolbench-submit`) so "
    "`/logs/artifacts/solution.patch` (or the named artifact) exists. "
    "Do not finish without that step."
)


def looks_like_implement_task(text: str) -> bool:
    """Return True when *text* looks like a coding implementation request."""
    if not text or not str(text).strip():
        return False
    lower = str(text).lower()
    return any(hint in lower for hint in _IMPLEMENT_HINTS)


def task_requires_submit(text: str) -> bool:
    """Return True when the user named an explicit submit/deliver step."""
    if not text or not str(text).strip():
        return False
    lower = str(text).lower()
    return any(hint in lower for hint in _SUBMIT_HINTS)


def extract_bash_command(tool_args: Any) -> str:
    """Best-effort extract of a shell command from bash tool args."""
    args = tool_args
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args.strip()
    if isinstance(args, dict):
        for key in ("command", "cmd", "script"):
            val = args.get(key)
            if val:
                return str(val).strip()
    return ""


def looks_like_verify_command(command: str) -> bool:
    """Return True when *command* looks like compile/test verification."""
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    return any(hint in lower for hint in _VERIFY_HINTS)


def looks_like_submit_command(command: str) -> bool:
    """Return True when *command* looks like a submit/deliver step."""
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    return any(hint in lower for hint in _SUBMIT_HINTS)


def is_shallow_signature_edit(old_string: str, new_string: str) -> bool:
    """Return True when an edit looks like type/docs-only field churn."""
    old = old_string or ""
    new = new_string or ""
    if not old.strip() or not new.strip():
        return False
    # Large or logic-heavy edits are not shallow.
    if len(new) > 900 or new.count("\n") > 30:
        return False
    if any(m in new for m in _LOGIC_MARKERS):
        return False
    for marker in _DEF_MARKERS:
        if marker in new and marker not in old:
            return False

    # Classic Option<…> → Vec<…> (or bare field type) swaps.
    old_has_option = bool(re.search(r"\bOption\s*<", old))
    new_has_vec = bool(re.search(r"\bVec\s*<", new))
    if old_has_option and new_has_vec:
        return True

    # Tiny field-decl replacements: `pub foo: T,` → `pub foo: U,`
    field_re = re.compile(
        r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?\w+\s*:\s*.+,\s*$",
        re.MULTILINE,
    )
    old_fields = field_re.findall(old)
    new_fields = field_re.findall(new)
    if old_fields and new_fields and len(new.strip().splitlines()) <= 4:
        return True

    return False


def edit_args_look_shallow(tool_args: Any) -> bool:
    """Return True when edit_file/write args look like a shallow signature edit."""
    args = tool_args
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return False
    if not isinstance(args, dict):
        return False
    old = str(args.get("old_string") or args.get("old_str") or "")
    new = str(args.get("new_string") or args.get("new_str") or "")
    if old or new:
        return is_shallow_signature_edit(old, new)
    # write_file with tiny type-only content is uncommon; treat as non-shallow.
    return False


def next_implement_continuation(
    *,
    user_text: str,
    mutate_attempted: bool,
    verify_attempted: bool,
    submit_attempted: bool,
    shallow_only: bool,
) -> str | None:
    """Pick the next headless continuation nudge, or None if done."""
    if not looks_like_implement_task(user_text):
        return None
    if not mutate_attempted:
        return ZERO_MUTATION_NUDGE
    if shallow_only:
        return SHALLOW_EDIT_NUDGE
    if not verify_attempted:
        return VERIFY_NUDGE
    if task_requires_submit(user_text) and not submit_attempted:
        return SUBMIT_NUDGE
    return None


def looks_like_git_archaeology(command: str) -> bool:
    """Return True when *command* is mostly historical git archaeology."""
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    if "git " not in lower and not lower.startswith("git"):
        return False
    archaeology = (
        "git log",
        "git blame",
        "git show ",
        "git for-each-ref",
        "git branch",
        "git rev-list",
        "git reflog",
    )
    return any(tok in lower for tok in archaeology)


__all__ = [
    "INCOMPLETE_IMPLEMENT_ERROR",
    "SHALLOW_EDIT_NUDGE",
    "STALL_CONTINUATION_NUDGE",
    "SUBMIT_NUDGE",
    "VERIFY_NUDGE",
    "ZERO_MUTATION_NUDGE",
    "edit_args_look_shallow",
    "extract_bash_command",
    "is_shallow_signature_edit",
    "looks_like_git_archaeology",
    "looks_like_implement_task",
    "looks_like_submit_command",
    "looks_like_verify_command",
    "next_implement_continuation",
    "task_requires_submit",
]

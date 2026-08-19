# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Detect implement-style tasks and build continuation nudges."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from pathlib import Path

from openjiuwen_icode.features.mutations import (
    mutation_path_from_args,
    path_under_workspace,
)

_IMPLEMENT_HINTS = (
    "implement",
    "fix ",
    "fix the",
    "add ",
    "add support",
    "add a",
    "edit ",
    "edit files",
    "modify ",
    "refactor",
    "patch",
    "write ",
    "create ",
    "ensure ",
    "support ",
    "expected feature",
    "work on this",
    "please work on",
    "execution rules",
    "repository under evaluation",
    "lolbench-submit",
    "solution.patch",
    "change the code",
    "update the code",
    "make the following",
)

_ORIGINAL_TASK_MARKER = (
    "Original task (still applies — implement this in the repo):\n"
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
    "go build",
    "go vet",
    "make test",
    "make check",
    "mvn test",
    "gradle test",
    "tsc ",
    "mypy",
    "ruff check",
    "unittest",
    "compileall",
)

_NATIVE_SOURCE_SUFFIXES = (
    ".c",
    ".h",
    ".cpp",
    ".cc",
    ".cxx",
    ".rs",
)

_PYTHON_SOURCE_SUFFIXES = (".py",)

_GO_SOURCE_SUFFIXES = (".go",)

_TYPESCRIPT_SOURCE_SUFFIXES = (".ts", ".tsx")

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

_DEF_MARKERS = (
    "fn ",
    "struct ",
    "enum ",
    "impl ",
    "trait ",
    "mod ",
    "func ",
    "type ",
    "package ",
)

# Common English / task words that look like identifiers but are not APIs.
_SYMBOL_STOPWORDS = frozenset(
    {
        "implement",
        "improve",
        "create",
        "update",
        "change",
        "modify",
        "refactor",
        "write",
        "read",
        "return",
        "require",
        "support",
        "handle",
        "report",
        "preserve",
        "prefer",
        "please",
        "expected",
        "outcome",
        "outcomes",
        "example",
        "examples",
        "following",
        "behavior",
        "behaviors",
        "script",
        "scripts",
        "module",
        "modules",
        "cache",
        "debug",
        "trace",
        "error",
        "errors",
        "message",
        "messages",
        "string",
        "strings",
        "value",
        "values",
        "entry",
        "entries",
        "path",
        "paths",
        "file",
        "files",
        "directory",
        "directories",
        "environment",
        "runtime",
        "invocation",
        "option",
        "options",
        "argument",
        "arguments",
        "command",
        "commands",
        "public",
        "entrypoint",
        "entrypoints",
        "internal",
        "helper",
        "helpers",
        "function",
        "functions",
        "signature",
        "signatures",
        "implementation",
        "implementations",
        "important",
        "execution",
        "rules",
        "repository",
        "evaluation",
        "working",
        "leaves",
        "leave",
        "commit",
        "committed",
        "harness",
        "captures",
        "adapter",
        "truthy",
        "normalize",
        "deduplicate",
        "canonical",
        "absolute",
        "relative",
        "equivalent",
        "deterministic",
        "discovery",
        "loading",
        "loader",
        "cyclic",
        "cycle",
        "import",
        "imports",
        "resolve",
        "resolution",
        "candidate",
        "candidates",
        "precedence",
        "fallback",
        "stderr",
        "stdout",
        "stdio",
        "index",
        "main",
        "test",
        "tests",
        "assert",
        "true",
        "false",
        "null",
        "none",
        "todo",
        "note",
        "notes",
    }
)

_EDIT_TOOL_NAMES = frozenset(
    {"edit_file", "Edit", "edit"}
)
_WRITE_TOOL_NAMES = frozenset(
    {"write_file", "Write", "write"}
)

STALL_CONTINUATION_NUDGE = (
    "Your previous response stalled mid-stream. Continue the same task now. "
    "If code changes were requested, call `edit_file` or `write_file` "
    "immediately — do not only search or read files."
)

TOOL_RUNTIME_NUDGE = (
    "A file/tool call crashed inside the harness instead of returning a "
    "normal tool error. Do not stop. Call `write_file` or `edit_file` again "
    "with `file_path` as a plain path string (for example `/app/src/foo.ts`) "
    "and `content` as a separate string field — never put the whole JSON "
    "object into `file_path`. Then continue the original task."
)

ZERO_MUTATION_NUDGE = (
    "You analyzed the codebase but did not modify any files. "
    "The user asked you to implement changes. Call `edit_file` or "
    "`write_file` now to apply a concrete patch in the worktree. "
    "Do not run another round of grep, git log, go test, or go build "
    "before the first successful edit. "
    "Do not search git history for an upstream PR — this checkout is often "
    "at a pruned base commit with no solution commits to find. "
    "Do not stop after another design essay. When the patch is in place, "
    "run any required submit/deliver command (for example `lolbench-submit`)."
)

WORKTREE_NUDGE = (
    "Your edit/write tools did not change any files in the worktree "
    "(wrong path, failed edit, or read-only target). Call `edit_file` or "
    "`write_file` on the real source paths under the repo cwd, confirm the "
    "files actually changed, then run verification again."
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
    "`cargo check` or a targeted `cargo test`; for Go: `go test` / "
    "`go build` on the touched packages). Do not stop after type-only "
    "edits."
)

INTEGRATION_NUDGE = (
    "You added or rewrote files with `write_file` but did not `edit_file` "
    "existing call sites / entrypoints. Do not invent a parallel module that "
    "is never wired in (for example a new loader that never updates "
    "`requireFn`, `GetFns`, or `BeginRepl`). Edit the existing files that must "
    "register or invoke your helpers, then verify with `bash` "
    "(`go test` / `go build` for Go; `cargo check` for Rust)."
)

PROMPT_SYMBOL_NUDGE_TEMPLATE = (
    "Your patch is missing symbols/APIs the user named: {symbols}. "
    "Wire those into the existing code (register builtins, update call "
    "sites, parse CLI flags as required). Do not leave helpers unused. "
    "Then verify with `bash`."
)

VERIFY_NUDGE = (
    "You modified files but have not verified the build/tests. "
    "Call `bash` now to run a compile or targeted test command appropriate "
    "for this repo (for Python: `pytest` on the relevant tests — "
    "`compileall` alone is not enough; "
    "for Rust: `cargo check` or a focused `cargo test`; "
    "for Go: `go test` / `go build` on the packages you touched; "
    "for CPython/C: `make -j2` or a targeted object rebuild; "
    "for CPython grammar: `make regen-pegen regen-ast` then "
    "`CCACHE_DISABLE=1 make -j2 python`). "
    "Fix any errors that appear, then continue. If the user required a "
    "submit/deliver command (for example `lolbench-submit`), run it only "
    "after verification succeeds."
)

VERIFY_FAILED_NUDGE = (
    "Your last compile/check command failed (non-zero exit). "
    "Read the errors, fix the code, and run verification again via `bash` "
    "(for Python: re-run the failing `pytest` cases; "
    "for C extensions: `make -j2` or rebuild the touched `.o`; for Rust: "
    "`cargo check`; for Go: `go test` / `go build`). Do not run "
    "submit/deliver until the build/check passes."
)

SUBMIT_NUDGE = (
    "Code changes look underway and verification was attempted, but the "
    "required deliverable is still missing. Run the submit/deliver command "
    "the user named (for example `lolbench-submit`) so "
    "`/logs/artifacts/solution.patch` (or the named artifact) exists. "
    "Do not finish without that step."
)

NATIVE_BUILD_NUDGE = (
    "You edited native/C extension sources (.c/.h or similar). "
    "Python-only tests or `compileall` do not rebuild those objects. "
    "Run a native build via `bash` (`make -j2`, rebuild touched `.o` "
    "files, or `cargo check` for Rust) and fix compile errors before "
    "submit/deliver."
)

PYTHON_SUITE_NUDGE = (
    "You edited Python sources but have not run a real test suite for this "
    "feature. `compileall`, `python -c`, typecheck-only commands, and "
    "pre-existing tests that already passed (for example `tests/test_monitor.py` "
    "on a snapshot task) are not enough. Tests you wrote this session alone "
    "are not enough either — run the project's existing integration/functional "
    "tests (`tests/functional/`, `pytest -k <feature>`) or invoke the CLI "
    "entrypoint you changed with representative flags. Prefer the repo's "
    "canonical runner (`python -m stestr run` on OpenStack-style projects, "
    "`python -m pytest tests/` elsewhere) without piping through `head`/`tail`/"
    "`grep` so failures are visible. Do not install a fake `pytest` shim into "
    "site-packages when the project ships `stestr`. Call `bash` with a full "
    "suite command, fix failures, and re-run until it passes before finishing."
)

GO_SUITE_NUDGE = (
    "You edited Go sources but have not run `go test` on the packages you "
    "touched. `go build` / `go vet` compile or lint only — they do not run "
    "tests. Call `bash` now with a targeted `go test` (for example "
    "`go test ./evaluator ./parser -count=1`), fix failures, and re-run "
    "until tests pass. Do not leave build output binaries (e.g. `./main`, "
    "`./abs`) in the repo — use `/tmp` or remove them before finishing."
)

TS_SUITE_NUDGE = (
    "You edited TypeScript sources but have not run a real test suite. "
    "`tsc --noEmit`, `npm run build`, or typecheck-only commands are not "
    "enough. Do not treat test files you wrote this session as sufficient "
    "verification — run the project's full suite via `bash` (Deno repos: "
    "`deno task test` or `deno test` on the module's `test/` tree; Node "
    "repos: `npm test` or `npx jest --runInBand`), fix failures, and re-run "
    "until they pass before finishing."
)


def _message_text(msg: Any) -> str:
    """Extract plain text from a chat message object or dict."""
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        return " ".join(t for t in parts if t).strip()
    return ""


def is_headless_continuation_nudge(text: str) -> bool:
    """Return True when *text* is a SessionHost / stall continuation nudge."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    # Wrapped continuations embed the original task — not a bare nudge.
    if _ORIGINAL_TASK_MARKER in stripped:
        return False
    for marker in (
        ZERO_MUTATION_NUDGE,
        WORKTREE_NUDGE,
        STALL_CONTINUATION_NUDGE,
        TOOL_RUNTIME_NUDGE,
        SHALLOW_EDIT_NUDGE,
        INTEGRATION_NUDGE,
        VERIFY_NUDGE,
        VERIFY_FAILED_NUDGE,
        SUBMIT_NUDGE,
        NATIVE_BUILD_NUDGE,
        PYTHON_SUITE_NUDGE,
        GO_SUITE_NUDGE,
        TS_SUITE_NUDGE,
    ):
        if stripped == marker or stripped.startswith(marker[:48]):
            return True
    if stripped.startswith("Your patch is missing symbols/APIs the user named:"):
        return True
    return False


def is_wrapped_implement_continuation_query(text: str) -> bool:
    """Return True when *text* is a SessionHost continuation (nudge + original task)."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    head = stripped.split("\n", 1)[0]
    return is_headless_continuation_nudge(head)


def original_task_from_query(text: str) -> str:
    """Extract the user task from a plain or wrapped headless query."""
    stripped = (text or "").strip()
    if not stripped:
        return ""
    if _ORIGINAL_TASK_MARKER in stripped:
        return stripped.split(_ORIGINAL_TASK_MARKER, 1)[1].strip()
    return stripped


def primary_user_task_text(messages_or_ctx: Any) -> str:
    """Return the original user task, not a headless continuation nudge."""
    messages = messages_or_ctx
    if not isinstance(messages, list):
        messages = (
            getattr(getattr(messages_or_ctx, "inputs", None), "messages", None)
            or []
        )
    fallback = ""
    for msg in messages:
        role = getattr(msg, "role", None)
        if role is None and isinstance(msg, dict):
            role = msg.get("role")
        if role != "user":
            continue
        text = _message_text(msg)
        if not text:
            continue
        if is_wrapped_implement_continuation_query(text):
            orig = original_task_from_query(text)
            if orig:
                if looks_like_implement_task(orig):
                    return orig
                if not fallback:
                    fallback = orig
            continue
        if is_headless_continuation_nudge(text):
            continue
        if looks_like_implement_task(text):
            return text
        if not fallback:
            fallback = text
    return fallback


def tool_runtime_continuation_nudge(exc: BaseException | str) -> str:
    """Nudge used when a tool/backend exception would otherwise TurnFailed."""
    detail = str(exc).strip().replace("\n", " ")
    if len(detail) > 240:
        detail = detail[:240] + "..."
    if not detail:
        return TOOL_RUNTIME_NUDGE
    return f"{TOOL_RUNTIME_NUDGE}\n\nHarness error: {detail}"


def wrap_implement_continuation_query(original: str, nudge: str) -> str:
    """Attach the original task to a headless continuation nudge."""
    orig = (original or "").strip()
    ndg = (nudge or "").strip()
    if not ndg:
        return orig
    if not orig or ndg == orig or orig in ndg:
        return ndg
    body = orig if len(orig) <= 6000 else orig[:6000] + "\n...(truncated)"
    return (
        f"{ndg}\n\n"
        "---\n"
        "Original task (still applies — implement this in the repo):\n"
        f"{body}"
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
    if re.search(r"\bjest\b", lower):
        return True
    if any(hint in lower for hint in _VERIFY_HINTS):
        return True
    # CPython / autotools: make (interpreter or object rebuild).
    if re.search(r"\bmake\b", lower):
        return True
    # CPython grammar/AST regeneration after editing python.gram / Python.asdl.
    if re.search(r"\bregen-(?:pegen|ast|token|keyword)\b", lower):
        return True
    # Inline smoke tests (common on LoLBench CPython tasks).
    if re.search(r"(?:\./)?python(?:3(?:\.\d+)?)?\s+-c\b", lower):
        return True
    if re.search(r"(?:\./)?python(?:3(?:\.\d+)?)?\s+-m\b", lower):
        return True
    # Deno / Cliffy-style TypeScript workspaces.
    if looks_like_deno_test_command(command):
        return True
    return False


def looks_like_submit_command(command: str) -> bool:
    """Return True when *command* looks like a submit/deliver step."""
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    return any(hint in lower for hint in _SUBMIT_HINTS)


def is_native_source_path(path: str) -> bool:
    """Return True when *path* looks like a native/C/Rust source file."""
    if not path or not str(path).strip():
        return False
    lower = str(path).lower().split("?", 1)[0]
    return lower.endswith(_NATIVE_SOURCE_SUFFIXES)


def is_python_source_path(path: str) -> bool:
    """Return True when *path* looks like a Python source file."""
    if not path or not str(path).strip():
        return False
    lower = str(path).lower().split("?", 1)[0]
    return lower.endswith(_PYTHON_SOURCE_SUFFIXES)


def is_go_source_path(path: str) -> bool:
    """Return True when *path* looks like a Go source file."""
    if not path or not str(path).strip():
        return False
    lower = str(path).lower().split("?", 1)[0]
    return lower.endswith(_GO_SOURCE_SUFFIXES)


def is_typescript_source_path(path: str) -> bool:
    """Return True when *path* looks like a TypeScript source file."""
    if not path or not str(path).strip():
        return False
    lower = str(path).lower().split("?", 1)[0]
    return lower.endswith(_TYPESCRIPT_SOURCE_SUFFIXES)


def mutation_args_under_workspace(tool_args: Any, workspace: Path | None) -> bool:
    """Return True when edit/write args target a path inside *workspace*."""
    path = mutation_path_from_args(tool_args)
    if not path or workspace is None:
        return True
    return path_under_workspace(path, workspace)


def _mutation_args_touch_suffixes(
    tool_args: Any,
    *,
    predicate,
) -> bool:
    args = tool_args
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return bool(predicate(args))
    if not isinstance(args, dict):
        return False
    for key in ("path", "file_path", "file", "filename", "target"):
        val = args.get(key)
        if val and predicate(str(val)):
            return True
    return False


def mutation_args_touch_native(tool_args: Any) -> bool:
    """Return True when edit/write args target a native source file."""
    return _mutation_args_touch_suffixes(
        tool_args, predicate=is_native_source_path
    )


def mutation_args_touch_python(tool_args: Any) -> bool:
    """Return True when edit/write args target a Python source file."""
    return _mutation_args_touch_suffixes(
        tool_args, predicate=is_python_source_path
    )


def mutation_args_touch_go(tool_args: Any) -> bool:
    """Return True when edit/write args target a Go source file."""
    return _mutation_args_touch_suffixes(
        tool_args, predicate=is_go_source_path
    )


def mutation_args_touch_typescript(tool_args: Any) -> bool:
    """Return True when edit/write args target a TypeScript source file."""
    return _mutation_args_touch_suffixes(
        tool_args, predicate=is_typescript_source_path
    )


def looks_like_native_build_command(command: str) -> bool:
    """Return True when *command* rebuilds native/C extension objects."""
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    if re.search(r"\bmake\b", lower):
        return True
    if re.search(r"\bcargo\s+(check|build|test|clippy)\b", lower):
        return True
    if re.search(r"\b(gcc|clang|cc)\b", lower):
        return True
    if re.search(r"\bninja\b", lower):
        return True
    if re.search(r"\.o\b", lower):
        return True
    return False


def looks_like_python_suite_command(command: str) -> bool:
    """Return True when *command* runs a real Python test suite.

    `compileall`, bare `python -c`, and typecheck-only commands do not count.
    """
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    if "compileall" in lower:
        return False
    if re.search(r"\bpytest\b", lower) or re.search(r"\bpy\.test\b", lower):
        return True
    if re.search(r"python(?:3(?:\.\d+)?)?\s+-m\s+pytest\b", lower):
        return True
    if re.search(r"python(?:3(?:\.\d+)?)?\s+-m\s+unittest\b", lower):
        return True
    # CPython's own regrtest driver.
    if re.search(r"(?:\./)?python(?:3(?:\.\d+)?)?\s+-m\s+test\b", lower):
        return True
    if re.search(r"\bstestr\b", lower) or re.search(
        r"python(?:3(?:\.\d+)?)?\s+-m\s+stestr\b", lower
    ):
        return True
    if re.search(r"\btox\b", lower) or re.search(r"\bnox\b", lower):
        return True
    return False


def looks_like_deno_test_command(command: str) -> bool:
    """Return True when *command* runs Deno tests (``deno test`` / ``deno task test``)."""
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    return bool(re.search(r"\bdeno\s+(?:task\s+)?test\b", lower))


def looks_like_go_suite_command(command: str) -> bool:
    """Return True when *command* runs Go tests.

    ``go build`` / ``go vet`` alone do not count — they compile or lint only.
    """
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    return bool(re.search(r"\bgo\s+test\b", lower))


def looks_like_typescript_suite_command(command: str) -> bool:
    """Return True when *command* runs a JS/TS test suite.

    ``tsc --noEmit``, ``npm run build``, and lint-only commands do not count.
    """
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    if re.search(r"\btsc\b", lower) and "test" not in lower:
        return False
    if re.search(r"\bnpm\s+run\s+build\b", lower):
        return False
    if re.search(r"\bnpm\s+run\s+lint\b", lower):
        return False
    suite = (
        "npm test",
        "npm run test",
        "pnpm test",
        "pnpm run test",
        "yarn test",
        "yarn run test",
        "npx jest",
        "npx mocha",
        "npx vitest",
        "nx test",
    )
    if any(tok in lower for tok in suite):
        return True
    if re.search(r"\bjest\b", lower):
        return True
    if re.search(r"\bmocha\b", lower):
        return True
    if re.search(r"\bvitest\b", lower):
        return True
    if looks_like_deno_test_command(command):
        return True
    return False


def is_full_typescript_suite_command(command: str) -> bool:
    """Return True when *command* runs the repo-wide JS/TS test suite."""
    if not command or not str(command).strip():
        return False
    lower = str(command).lower().strip()
    if re.search(r"\bnpm test\b", lower):
        if re.search(r"\.test\.(?:ts|tsx|js|jsx)\b", lower):
            return False
        match = re.search(r"\bnpm test\b(?:\s+--)?\s*(.*)$", lower)
        rest = (match.group(1) if match else "").strip()
        if not rest or rest in {"--", "--runinband"}:
            return True
        if re.fullmatch(r"-?-runinband", rest):
            return True
        return False
    if re.search(r"\b(?:npx\s+)?jest\b", lower):
        if re.search(r"\.test\.(?:ts|tsx|js|jsx)\b", lower):
            return False
        if re.search(r"--testpathignorepatterns=", lower):
            return True
        if re.search(r"(?:--runinband|--run-in-band)\b", lower):
            return True
        if re.fullmatch(r"(?:npx\s+)?jest", lower):
            return True
    if looks_like_deno_test_command(command):
        # Project tasks (``deno task test``, ``test:deno-v2``, …) run the
        # repo's canonical suite from ``deno.json``.
        if re.search(r"\bdeno\s+task\s+test\b", lower):
            return True
        # Single-file targets (including agent-authored ``*_test.ts``) are not
        # enough — hidden fail-to-pass tests may only exist at grading time.
        if re.search(
            r"[\w./-]+_(?:test|spec)\.(?:ts|tsx|js|jsx)\b", lower
        ):
            return False
        if re.search(r"[\w./-]+\.(?:test|spec)\.(?:ts|tsx|js|jsx)\b", lower):
            return False
        # Directory suites such as ``deno test … command/test/``.
        if re.search(r"/(?:test|tests)/", lower):
            return True
    return False


def is_full_python_suite_command(command: str) -> bool:
    """Return True when *command* runs a repo-wide Python test suite.

    Single-file pytest targets (including agent-authored ``test_*.py``) do
    not count — they can pass while hidden fail-to-pass tests still fail.
    """
    if not command or not looks_like_python_suite_command(command):
        return False
    lower = str(command).lower().strip()
    if re.search(r"tests/(?:[\w.-]+/)*test_[\w.-]+\.py", lower):
        return False
    if re.search(r"\b-k(?:=|\s+)(['\"]?)([\w.-]+)\1", lower):
        return False
    # ``stestr run tests.unit.foo`` is targeted; bare ``stestr run`` is full.
    if re.search(r"\bstestr\s+run\b", lower):
        match = re.search(r"\bstestr\s+run(?:\s+([^|&;]+))?", lower)
        tail = (match.group(1) if match else "") or ""
        tail = re.sub(r"\s+2>&1.*$", "", tail).strip()
        if not tail:
            return True
        return False
    if re.search(r"\btests(?:/[\w.-]+)*/?\b", lower):
        return True
    if re.fullmatch(
        r"(?:python(?:3(?:\.\d+)?)?\s+-m\s+)?pytest(?:\s|$)",
        lower,
    ):
        return True
    return False


def verify_command_targets_agent_authored_tests(
    command: str,
    agent_created_test_names: frozenset[str] | set[str],
) -> bool:
    """Return True when *command* verifies only tests the agent created this turn."""
    if not command or not agent_created_test_names:
        return False
    if is_full_typescript_suite_command(command):
        return False
    if is_full_python_suite_command(command):
        return False
    lower = str(command).lower()
    for name in agent_created_test_names:
        token = str(name or "").strip().lower()
        if not token:
            continue
        base = Path(token).name if "/" in token or "\\" in token else token
        stem = Path(base).stem if "." in base else base
        if base in lower or stem in lower:
            return True
    return False


def verify_command_qualifies_for_completion(
    command: str,
    *,
    native_mutated: bool,
    success: bool,
    python_mutated: bool = False,
    go_mutated: bool = False,
    typescript_mutated: bool = False,
    user_text: str = "",
    workspace_mutated: bool = True,
    agent_created_test_names: frozenset[str] | set[str] = frozenset(),
) -> bool:
    """Return True when a successful verify command completes the verify gate."""
    if not workspace_mutated:
        return False
    if not success or not looks_like_verify_command(command):
        return False
    if native_mutated and not looks_like_native_build_command(command):
        return False
    # Pure-Python edits: require a real suite, not compileall / python -c.
    if python_mutated and not native_mutated:
        if not looks_like_python_suite_command(command):
            return False
        if verify_command_targets_agent_authored_tests(
            command, agent_created_test_names
        ):
            return False
        if not user_text or not python_suite_command_matches_task_scope(
            user_text, command
        ):
            return False
        if not python_cli_integration_verify_matches(user_text, command):
            return False
    # Pure-Go edits: require go test, not go build / go vet alone.
    if go_mutated and not native_mutated:
        if not looks_like_go_suite_command(command):
            return False
        if user_text and not go_command_matches_task_scope(user_text, command):
            return False
    # Pure-TypeScript edits: require a real suite, not tsc/build alone.
    if typescript_mutated and not native_mutated:
        if not looks_like_typescript_suite_command(command):
            return False
        if verify_command_targets_agent_authored_tests(
            command, agent_created_test_names
        ):
            return False
        if user_text and not typescript_command_matches_task_scope(
            user_text, command
        ):
            return False
    return True


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


def extract_bash_command_from_result(result: Any) -> str:
    """Best-effort extract of the shell command from a bash tool result."""
    text = result if isinstance(result, str) else str(result or "")
    match = re.search(r"Command:\s*(.+?)(?:\n|$)", text)
    if match:
        return match.group(1).strip()
    return ""


def _bash_stdout_from_result(result: Any) -> str:
    """Extract stdout blob from a formatted bash tool result string."""
    text = result if isinstance(result, str) else str(result or "")
    match = re.search(r"Stdout:\s*(.*?)(?:\nStderr:|\nExit Code:|\Z)", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


def bash_output_indicates_failure(result: Any) -> bool:
    """Return True when captured bash stdout clearly shows a failed verify run.

    Piped commands such as ``jest … | tail -60`` often report exit code 0 even
    when the test runner failed; the summary lines in stdout are more reliable.
    """
    blob = _bash_stdout_from_result(result)
    if not blob.strip():
        return False

    # Jest / Vitest style summaries.
    if re.search(r"Test Suites:\s*[1-9]\d*\s+failed\b", blob, re.IGNORECASE):
        return True
    if re.search(r"Tests:\s*[1-9]\d*\s+failed\b", blob, re.IGNORECASE):
        return True
    if re.search(r"^FAIL\s+\S", blob, re.MULTILINE):
        return True
    if "Test suite failed to run" in blob:
        return True

    # pytest summary (``= 2 failed, 1 passed in 0.12s =``).
    if re.search(r"=\s*[1-9]\d*\s+failed\b", blob):
        return True
    if re.search(r"^FAILED\s+\S", blob, re.MULTILINE):
        return True

    # cargo test / Rust build failures.
    if re.search(r"test result: FAILED", blob, re.IGNORECASE):
        return True
    if re.search(r"^error(?:\[\w+\])?:", blob, re.MULTILINE):
        return True

    # go test failures.
    if re.search(r"^--- FAIL:", blob, re.MULTILINE):
        return True
    if re.search(r"^FAIL\s+\S", blob, re.MULTILINE):
        return True

    # deno test summary (``ok | 335 passed | 5 failed (1s)``).
    if re.search(r"\|\s*[1-9]\d*\s+failed\b", blob):
        return True
    if re.search(r"^FAILURES\b", blob, re.MULTILINE):
        return True
    if re.search(r"\.\.\.\s*FAILED\b", blob):
        return True

    # Python import / runner bootstrap failures (often masked by ``| head``).
    if re.search(r"No module named ['\"]?\w+", blob):
        return True
    if "ModuleNotFoundError" in blob or "ImportError:" in blob:
        return True

    # stestr / testtools summaries and per-test failures.
    if re.search(r"^\s*-\s+Failed:\s*[1-9]\d*\b", blob, re.MULTILINE):
        return True
    if "Failures during discovery" in blob:
        return True
    if "Failed to import test module" in blob:
        return True
    if re.search(r"^Failed \d+ tests\b", blob, re.MULTILINE):
        return True
    if re.search(r"\]\s*\.\.\.\s*FAILED\b", blob):
        return True

    # unittest / pytest-shim summaries.
    if re.search(r"^FAILED\s+\(", blob, re.MULTILINE):
        return True
    if re.search(r"^Ran \d+ tests in .+\n\nFAILED\b", blob, re.MULTILINE):
        return True

    return False


def bash_result_succeeded(
    result: Any,
    *,
    tool_success: bool | None = None,
) -> bool | None:
    """Return True/False for bash exit status, or None if unknown."""
    text = result if isinstance(result, str) else str(result or "")
    exit_ok: bool | None = None
    if tool_success is not None:
        exit_ok = bool(tool_success)
    else:
        match = re.search(r"Exit Code:\s*(\d+)", text, re.IGNORECASE)
        if match:
            exit_ok = int(match.group(1)) == 0

    if bash_output_indicates_failure(result):
        return False
    return exit_ok


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


def tool_is_edit_existing(tool_name: str) -> bool:
    """Return True when *tool_name* edits an existing file in place."""
    return str(tool_name or "") in _EDIT_TOOL_NAMES


def tool_is_write_file(tool_name: str) -> bool:
    """Return True when *tool_name* is a full-file write."""
    return str(tool_name or "") in _WRITE_TOOL_NAMES


def mutation_text_from_args(tool_args: Any) -> str:
    """Extract textual payload from edit/write tool args for symbol coverage."""
    args = tool_args
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args
    if not isinstance(args, dict):
        return ""
    parts: list[str] = []
    for key in (
        "new_string",
        "new_str",
        "content",
        "contents",
        "old_string",
        "old_str",
        "file_path",
        "path",
    ):
        val = args.get(key)
        if val:
            parts.append(str(val))
    return "\n".join(parts)


def _normalize_symbol_token(raw: str) -> str:
    tok = (raw or "").strip().strip("`\"'")
    if not tok:
        return ""
    # require_cache_info() / pkg.BeginRepl → strip call parens / keep leaf.
    if "(" in tok:
        tok = tok.split("(", 1)[0].strip()
    return tok


def _is_strong_symbol(tok: str, *, allow_short: bool = False) -> bool:
    """Keep API-like tokens; drop prose / short field names."""
    if not tok:
        return False
    if len(tok) < 4 and not (allow_short and len(tok) >= 2):
        return False
    lower = tok.lower()
    if lower in _SYMBOL_STOPWORDS:
        return False
    if "/" in tok or " " in tok:
        return False
    if tok.startswith("--") and len(tok) >= 5:
        return True
    if allow_short and re.match(r"^[a-z][a-z0-9_]*$", lower) and len(tok) >= 2:
        return True
    # ABS_MODULE_PATH / require_cache_info
    if "_" in tok and len(tok) >= 6:
        return True
    # BeginRepl / GetFns (reject Titlecase prose like "Expose")
    if re.match(r"^[A-Z][a-zA-Z0-9]{4,}$", tok):
        if re.match(r"^[A-Z][a-z]+$", tok):
            return False
        return True
    return False


def _symbol_present_in_blob(sym: str, blob: str) -> bool:
    """Return True when *sym* appears in *blob* as a whole token when short."""
    if len(sym) <= 3:
        return bool(re.search(rf"\b{re.escape(sym)}\b", blob))
    if sym in blob:
        return True
    return sym.lower() in blob.lower()


def _repeated_task_keywords(
    text: str,
    *,
    min_count: int = 3,
    min_len: int = 5,
) -> frozenset[str]:
    """Distinctive lowercase keywords repeated in an implement-style prompt."""
    words = re.findall(rf"\b[a-z][a-z0-9_]{{{min_len - 1},}}\b", text.lower())
    counts = Counter(
        w for w in words if w not in _SYMBOL_STOPWORDS and not w.isdigit()
    )
    return frozenset(w for w, n in counts.items() if n >= min_count)


def _shared_api_stems(text: str, *, min_count: int = 2, min_len: int = 5) -> frozenset[str]:
    """Parts shared across multiple snake_case APIs named in the task."""
    apis = re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", text.lower())
    part_counts: Counter[str] = Counter()
    for api in apis:
        seen_in_api: set[str] = set()
        for part in api.split("_"):
            if len(part) < min_len:
                continue
            stem = part.rstrip("s")
            if stem not in seen_in_api:
                seen_in_api.add(stem)
                part_counts[stem] += 1
                if stem != part:
                    part_counts[part] += 1
    return frozenset(p for p, n in part_counts.items() if n >= min_count)


_SCOPE_COMMAND_STOPWORDS = frozenset(
    {
        "pytest",
        "python",
        "python3",
        "bash",
        "cargo",
        "compileall",
        "edit_file",
        "write_file",
        "git",
        "diff",
        "head",
        "npm",
        "jest",
        "mocha",
        "vitest",
        "tsc",
        "eslint",
    }
)


def _backticked_scope_tokens(text: str, *, min_len: int = 5) -> frozenset[str]:
    """Feature identifiers quoted in the prompt (`` `aliases` ``, `` `capture_snapshot` ``)."""
    found: set[str] = set()
    for raw in re.findall(r"`([^`]+)`", text.lower()):
        tok = _normalize_symbol_token(raw)
        if not tok or any(ch in tok for ch in "/\\<>"):
            continue
        if " " in tok:
            continue
        if len(tok) < min_len or tok in _SYMBOL_STOPWORDS:
            continue
        if tok in _SCOPE_COMMAND_STOPWORDS:
            continue
        found.add(tok)
        if "_" in tok:
            for part in tok.split("_"):
                if (
                    len(part) >= min_len
                    and part not in _SYMBOL_STOPWORDS
                    and part not in _SCOPE_COMMAND_STOPWORDS
                ):
                    found.add(part)
                    found.add(part.rstrip("s"))
    return frozenset(found)


def _feature_scope_keywords(text: str) -> frozenset[str]:
    """Keywords that identify the *new* feature, not the host module.

    Repeated English words like ``monitor`` in ``aiomonitor`` / ``Monitor``
    must not make ``tests/test_monitor.py`` count as feature verification.
    Prefer snake_case API stems and backticked identifiers; fall back to
    repeated prompt words only when those are empty.
    """
    stems = _shared_api_stems(text)
    quoted = _backticked_scope_tokens(text)
    distinctive = frozenset(
        kw
        for kw in (stems | quoted)
        if kw not in _SYMBOL_STOPWORDS and kw not in _SCOPE_COMMAND_STOPWORDS
    )
    if distinctive:
        return distinctive
    return frozenset(
        kw
        for kw in _repeated_task_keywords(text)
        if kw not in _SCOPE_COMMAND_STOPWORDS
    )


def _keyword_in_command(keyword: str, command_lower: str) -> bool:
    """Match task keywords against pytest paths (snapshot ↔ snapshots)."""
    if keyword in command_lower:
        return True
    if keyword.endswith("s") and keyword[:-1] in command_lower:
        return True
    if f"{keyword}s" in command_lower:
        return True
    # async-initialization ↔ initialize / initializer / initialization
    if len(keyword) >= 6:
        root = keyword[:6]
        if root in command_lower:
            return True
    return False


def typescript_command_matches_task_scope(user_text: str, command: str) -> bool:
    """Return True when a targeted JS/TS test run matches the task feature area."""
    if not user_text or not command or not looks_like_typescript_suite_command(
        command
    ):
        return True
    if is_full_typescript_suite_command(command):
        return True
    stem_keywords = _shared_api_stems(user_text)
    repeated_keywords = _repeated_task_keywords(user_text)
    keywords = stem_keywords | repeated_keywords
    if not keywords:
        return True
    lower = str(command).lower()
    match = re.search(r"\b(?:-t|--testNamePattern=)(['\"]?)([\w.-]+)\1", lower)
    if match:
        expr = match.group(2)
        return any(_keyword_in_command(kw, expr) for kw in keywords)
    if re.search(r"__tests__/[\w./-]+\.test\.(?:ts|tsx|js)", lower):
        scoped = stem_keywords or repeated_keywords
        return any(_keyword_in_command(kw, lower) for kw in scoped)
    if re.search(r"\.test\.(?:ts|tsx|js)\b", lower):
        scoped = stem_keywords or repeated_keywords
        return any(_keyword_in_command(kw, lower) for kw in scoped)
    if re.search(r"_(?:test|spec)\.(?:ts|tsx|js|jsx)\b", lower):
        scoped = stem_keywords or repeated_keywords
        return any(_keyword_in_command(kw, lower) for kw in scoped)
    if re.search(r"/(?:test|tests)/", lower) and looks_like_deno_test_command(
        command
    ):
        return True
    if re.search(r"\b(?:describe|it)\(['\"][^'\"]+['\"]", lower):
        return any(_keyword_in_command(kw, lower) for kw in keywords)
    # Bare repo-wide npm test against an unchanged base is not enough.
    return any(_keyword_in_command(kw, lower) for kw in keywords)


def go_command_matches_task_scope(user_text: str, command: str) -> bool:
    """Return True when a targeted ``go test`` run matches the task's feature area.

    When the prompt names a distinctive feature area, ``go test`` must mention
    at least one repeated keyword in the command path or ``-run`` expression.
    Bare ``go test ./...`` against an unchanged base checkout is not enough —
    it can pass while new fail-to-pass tests (added only at grading time) still
    fail.
    """
    if not user_text or not command or not looks_like_go_suite_command(command):
        return True
    stem_keywords = _shared_api_stems(user_text)
    repeated_keywords = _repeated_task_keywords(user_text)
    keywords = stem_keywords | repeated_keywords
    if not keywords:
        return True
    lower = str(command).lower()
    match = re.search(r"\b-run(?:=|\s+)(['\"]?)([\w.-]+)\1", lower)
    if match:
        expr = match.group(2)
        return any(_keyword_in_command(kw, expr) for kw in keywords)
    if "./..." not in lower and re.search(
        r"\./[\w./-]+(?:\s|$)", lower
    ):
        # Targeted package paths (not repo-wide ./...) count as scoped.
        return True
    return any(_keyword_in_command(kw, lower) for kw in keywords)


def _cli_flag_count(text: str) -> int:
    """Count distinct CLI-style flags named in an implement prompt."""
    return len(set(re.findall(r"--[a-z][\w-]+", str(text or "").lower())))


def python_cli_integration_verify_matches(
    user_text: str, command: str
) -> bool:
    """Return True when verify covers CLI/integration behavior on flag-heavy tasks.

    Prompts that name many CLI flags usually need ``tests/functional/`` or a
    direct module/CLI invocation — not only unit tests the agent added.
    """
    if not user_text or not command:
        return True
    if _cli_flag_count(user_text) < 4:
        return True
    lower = str(command).lower()
    if re.search(r"tests/(?:[\w.-]+/)*functional/", lower):
        return True
    if re.search(
        r"\bpython(?:3(?:\.\d+)?)?\s+-m\s+(?!pytest\b)[\w.]+\b", lower
    ):
        return True
    if re.search(r"(?:^|\s)[\w.-]+\s+--[\w-]", lower):
        return True
    return False


def pytest_command_matches_task_scope(user_text: str, command: str) -> bool:
    """Return True when a targeted pytest run matches the task's feature area.

    When the prompt names a distinctive feature area, pytest must mention at
    least one feature keyword in the command, path, or ``-k`` expression.
    Bare ``pytest -q`` or pre-existing P2P files (``tests/test_monitor.py``
    on a snapshot task) against an unchanged base checkout are not enough —
    they can pass while new fail-to-pass tests (added only at grading time)
    still fail.
    """
    if not user_text or not command or not looks_like_python_suite_command(command):
        return True
    keywords = _feature_scope_keywords(user_text)
    if not keywords:
        return True
    lower = str(command).lower()
    if re.search(r"tests/(?:[\w.-]+/)*test_[\w.-]+\.py", lower):
        return any(_keyword_in_command(kw, lower) for kw in keywords)
    match = re.search(r"\b-k(?:=|\s+)(['\"]?)([\w.-]+)\1", lower)
    if match:
        expr = match.group(2)
        return any(_keyword_in_command(kw, expr) for kw in keywords)
    return any(_keyword_in_command(kw, lower) for kw in keywords)


def stestr_command_matches_task_scope(user_text: str, command: str) -> bool:
    """Return True when a stestr run matches the task's feature area."""
    if not user_text or not command:
        return True
    lower = str(command).lower()
    if "stestr" not in lower:
        return True
    keywords = _feature_scope_keywords(user_text)
    if not keywords:
        return True
    match = re.search(r"\bstestr\s+run(?:\s+([^\s|&;]+))?", lower)
    if match and (match.group(1) or "").strip():
        target = match.group(1).strip().strip("'\"")
        return any(_keyword_in_command(kw, target) for kw in keywords)
    return any(_keyword_in_command(kw, lower) for kw in keywords)


def python_suite_command_matches_task_scope(user_text: str, command: str) -> bool:
    """Scope check for pytest, stestr, or unittest suite commands."""
    if not looks_like_python_suite_command(command):
        return True
    lower = str(command).lower()
    if "stestr" in lower:
        return stestr_command_matches_task_scope(user_text, command)
    return pytest_command_matches_task_scope(user_text, command)


def extract_required_prompt_symbols(text: str) -> tuple[str, ...]:
    """Pull API / flag names the user likely expects to appear in the patch."""
    if not text or not str(text).strip():
        return ()
    found: list[str] = []

    def _add(token: str, *, allow_short: bool = False) -> None:
        tok = _normalize_symbol_token(token)
        if not _is_strong_symbol(tok, allow_short=allow_short):
            return
        if tok not in found:
            found.append(tok)
        if "." in tok:
            leaf = tok.rsplit(".", 1)[-1]
            if leaf != tok:
                _add(leaf, allow_short=allow_short)

    for m in re.finditer(r"`([^`]+)`", text):
        _add(m.group(1))
    for m in re.finditer(r"\b([A-Za-z_][\w]{3,})\(\)", text):
        _add(m.group(1))
    for m in re.finditer(r"\.([a-zA-Z_][\w]{2,})\(", text):
        _add(m.group(1), allow_short=True)
    for m in re.finditer(r"(--[a-zA-Z][\w-]{2,})", text):
        _add(m.group(1))
    # CamelCase entrypoints (BeginRepl) not already captured.
    for m in re.finditer(r"\b([A-Z][a-zA-Z0-9]{5,})\b", text):
        _add(m.group(1))
    # snake_case APIs common in Python tasks (capture_snapshot, max_snapshots).
    for m in re.finditer(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", text):
        _add(m.group(1))
    # Explicit field/member lists: "with id, name, running_count, and terminated_count".
    for m in re.finditer(
        r"(?:with|fields?|attributes?|members?|keys?)\s+"
        r"([a-z][a-z0-9_]*(?:\s*,\s*(?:and\s+)?[a-z][a-z0-9_]*)+)",
        text,
        re.IGNORECASE,
    ):
        for part in re.split(r"\s*,\s*|\s+and\s+", m.group(1)):
            _add(part.strip(), allow_short=True)
    # JSON-ish response keys: returns {id}, {added, removed, common}.
    for m in re.finditer(r"\{([^{}]+)\}", text):
        for part in m.group(1).split(","):
            _add(part.strip(), allow_short=True)

    # Cap so a long instruction cannot demand dozens of tokens.
    return tuple(found[:24])


def _extract_wiring_symbols(text: str) -> tuple[str, ...]:
    """Entrypoints explicitly wired via slash syntax (Monitor/start_monitor)."""
    found: list[str] = []
    for m in re.finditer(r"/([a-z][a-z0-9_]+)\b", text.lower()):
        tok = _normalize_symbol_token(m.group(1))
        if _is_strong_symbol(tok) and tok not in found:
            found.append(tok)
    return tuple(found)


def _extract_spec_field_names(text: str) -> tuple[str, ...]:
    """Short field names from explicit spec lists and JSON response shapes."""
    found: list[str] = []

    def _add_field(token: str) -> None:
        tok = _normalize_symbol_token(token)
        if _is_strong_symbol(tok, allow_short=True) and tok not in found:
            found.append(tok)

    for m in re.finditer(
        r"(?:with|fields?|attributes?|members?|keys?)\s+"
        r"([a-z][a-z0-9_]*(?:\s*,\s*(?:and\s+)?[a-z][a-z0-9_]*)+)",
        text,
        re.IGNORECASE,
    ):
        for part in re.split(r"\s*,\s*|\s+and\s+", m.group(1)):
            _add_field(part.strip())
    for m in re.finditer(r"\{([^{}]+)\}", text):
        for part in m.group(1).split(","):
            _add_field(part.strip())
    return tuple(found)


def missing_prompt_symbols(
    *,
    user_text: str,
    mutation_blob: str,
    min_required: int = 2,
    coverage_ratio: float = 0.5,
) -> tuple[str, ...]:
    """Return important prompt symbols still absent from mutation text.

    Requires at least *min_required* extracted symbols before gating, and
    only reports missing ones when coverage is below *coverage_ratio*.
    """
    required = extract_required_prompt_symbols(user_text)
    must_have = tuple(
        dict.fromkeys(
            (*_extract_wiring_symbols(user_text), *_extract_spec_field_names(user_text))
        )
    )
    if len(required) < min_required and not must_have:
        return ()
    blob = mutation_blob or ""
    must_missing = tuple(
        sym for sym in must_have if not _symbol_present_in_blob(sym, blob)
    )
    if must_missing:
        return must_missing[:8]
    missing = tuple(
        sym for sym in required if not _symbol_present_in_blob(sym, blob)
    )
    covered = len(required) - len(missing)
    if covered / max(len(required), 1) >= coverage_ratio:
        return ()
    return missing[:8]


def prompt_symbol_nudge(missing: tuple[str, ...] | list[str]) -> str:
    """Format a continuation nudge listing missing prompt symbols."""
    symbols = ", ".join(f"`{s}`" for s in missing)
    return PROMPT_SYMBOL_NUDGE_TEMPLATE.format(symbols=symbols or "(none)")


def zero_mutation_continuation_nudge(user_text: str) -> str:
    """Build a zero-mutation nudge, optionally listing APIs named in the task."""
    symbols = extract_required_prompt_symbols(user_text)[:6]
    if not symbols:
        return ZERO_MUTATION_NUDGE
    listed = ", ".join(f"`{sym}`" for sym in symbols)
    return (
        f"{ZERO_MUTATION_NUDGE}\n\n"
        f"The task names these APIs — wire them under the repo cwd with "
        f"`edit_file` / `write_file` (for example {listed})."
    )


def next_implement_continuation(
    *,
    user_text: str,
    mutate_attempted: bool,
    verify_attempted: bool,
    verify_succeeded: bool,
    submit_attempted: bool,
    shallow_only: bool,
    integration_attempted: bool = True,
    missing_symbols: tuple[str, ...] | list[str] = (),
    workspace_mutated: bool = True,
    native_mutated: bool = False,
    native_build_verified: bool = False,
    python_mutated: bool = False,
    python_suite_verified: bool = False,
    go_mutated: bool = False,
    go_suite_verified: bool = False,
    typescript_mutated: bool = False,
    typescript_suite_verified: bool = False,
) -> str | None:
    """Pick the next headless continuation nudge, or None if done."""
    if not looks_like_implement_task(user_text):
        return None
    if not mutate_attempted:
        return zero_mutation_continuation_nudge(user_text)
    if not workspace_mutated:
        return WORKTREE_NUDGE
    if shallow_only:
        return SHALLOW_EDIT_NUDGE
    if not integration_attempted:
        return INTEGRATION_NUDGE
    if missing_symbols:
        return prompt_symbol_nudge(tuple(missing_symbols))
    if native_mutated and not native_build_verified:
        return NATIVE_BUILD_NUDGE
    if go_mutated and not native_mutated and not go_suite_verified:
        return GO_SUITE_NUDGE
    if (
        typescript_mutated
        and not native_mutated
        and not typescript_suite_verified
    ):
        return TS_SUITE_NUDGE
    if python_mutated and not native_mutated and not python_suite_verified:
        return PYTHON_SUITE_NUDGE
    if not verify_succeeded:
        if verify_attempted:
            return VERIFY_FAILED_NUDGE
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


def looks_like_explore_bash(command: str) -> bool:
    """Return True when *command* is read-only inspection via ``bash``.

    These commands burn explore budget on implement tasks: agents often loop on
    ``go test ./...``, ``grep``, or ``cat`` without ever calling edit tools.
    """
    if not command or not str(command).strip():
        return False
    if looks_like_git_archaeology(command):
        return True
    lower = str(command).lower()
    explore = (
        "go test",
        "go build",
        "go vet",
        "go list",
        "go doc",
        "npm test",
        "npm run test",
        "npm install",
        "npm ci",
        "pnpm test",
        "pnpm run test",
        "pnpm install",
        "yarn test",
        "yarn run test",
        "yarn install",
        "npx jest",
        "npx mocha",
        "npx vitest",
        "npx tsc",
        "tsc ",
        "tsc\t",
        "npm run build",
        "npm run lint",
        "pnpm run build",
        "pnpm run lint",
        "yarn build",
        "yarn run build",
        "jest ",
        "jest\t",
        "mocha ",
        "mocha\t",
        "vitest ",
        "vitest\t",
        "nx test",
        "grep ",
        "grep\t",
        "rg ",
        "rg\t",
        "find ",
        "cat ",
        "head ",
        "tail ",
        "less ",
        "wc ",
        "ls ",
        "tree ",
        "fd ",
        "ag ",
    )
    if any(tok in lower for tok in explore):
        return True
    if re.search(r"(?:\./)?python(?:3(?:\.\d+)?)?\s+-c\b", lower):
        return True
    return False


__all__ = [
    "INCOMPLETE_IMPLEMENT_ERROR",
    "GO_SUITE_NUDGE",
    "TS_SUITE_NUDGE",
    "INTEGRATION_NUDGE",
    "NATIVE_BUILD_NUDGE",
    "PROMPT_SYMBOL_NUDGE_TEMPLATE",
    "PYTHON_SUITE_NUDGE",
    "SHALLOW_EDIT_NUDGE",
    "STALL_CONTINUATION_NUDGE",
    "TOOL_RUNTIME_NUDGE",
    "SUBMIT_NUDGE",
    "VERIFY_FAILED_NUDGE",
    "VERIFY_NUDGE",
    "WORKTREE_NUDGE",
    "wrap_implement_continuation_query",
    "zero_mutation_continuation_nudge",
    "ZERO_MUTATION_NUDGE",
    "bash_output_indicates_failure",
    "bash_result_succeeded",
    "edit_args_look_shallow",
    "extract_bash_command",
    "extract_bash_command_from_result",
    "extract_required_prompt_symbols",
    "is_go_source_path",
    "is_full_python_suite_command",
    "is_full_typescript_suite_command",
    "python_cli_integration_verify_matches",
    "is_typescript_source_path",
    "is_headless_continuation_nudge",
    "is_wrapped_implement_continuation_query",
    "is_native_source_path",
    "is_python_source_path",
    "is_shallow_signature_edit",
    "go_command_matches_task_scope",
    "looks_like_deno_test_command",
    "looks_like_explore_bash",
    "looks_like_git_archaeology",
    "looks_like_go_suite_command",
    "looks_like_typescript_suite_command",
    "looks_like_implement_task",
    "looks_like_native_build_command",
    "looks_like_python_suite_command",
    "looks_like_submit_command",
    "looks_like_verify_command",
    "missing_prompt_symbols",
    "mutation_args_touch_go",
    "mutation_args_touch_native",
    "mutation_args_touch_python",
    "mutation_args_touch_typescript",
    "mutation_args_under_workspace",
    "mutation_text_from_args",
    "next_implement_continuation",
    "original_task_from_query",
    "primary_user_task_text",
    "prompt_symbol_nudge",
    "pytest_command_matches_task_scope",
    "python_suite_command_matches_task_scope",
    "stestr_command_matches_task_scope",
    "typescript_command_matches_task_scope",
    "verify_command_targets_agent_authored_tests",
    "task_requires_submit",
    "tool_is_edit_existing",
    "tool_is_write_file",
    "tool_runtime_continuation_nudge",
    "verify_command_qualifies_for_completion",
]

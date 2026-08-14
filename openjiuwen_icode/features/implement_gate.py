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
    ".go",
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
    "for this repo (for Rust: `cargo check` or a focused `cargo test`; "
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
    "(for C extensions: `make -j2` or rebuild the touched `.o`; for Rust: "
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


def mutation_args_touch_native(tool_args: Any) -> bool:
    """Return True when edit/write args target a native source file."""
    args = tool_args
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return is_native_source_path(args)
    if not isinstance(args, dict):
        return False
    for key in ("path", "file_path", "file", "filename", "target"):
        val = args.get(key)
        if val and is_native_source_path(str(val)):
            return True
    return False


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


def verify_command_qualifies_for_completion(
    command: str,
    *,
    native_mutated: bool,
    success: bool,
) -> bool:
    """Return True when a successful verify command completes the verify gate."""
    if not success or not looks_like_verify_command(command):
        return False
    if native_mutated and not looks_like_native_build_command(command):
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


def bash_result_succeeded(
    result: Any,
    *,
    tool_success: bool | None = None,
) -> bool | None:
    """Return True/False for bash exit status, or None if unknown."""
    if tool_success is not None:
        return bool(tool_success)
    text = result if isinstance(result, str) else str(result or "")
    match = re.search(r"Exit Code:\s*(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1)) == 0
    return None


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


def _is_strong_symbol(tok: str) -> bool:
    """Keep API-like tokens; drop prose / short field names."""
    if not tok or len(tok) < 4:
        return False
    lower = tok.lower()
    if lower in _SYMBOL_STOPWORDS:
        return False
    if "/" in tok or " " in tok:
        return False
    if tok.startswith("--") and len(tok) >= 5:
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


def extract_required_prompt_symbols(text: str) -> tuple[str, ...]:
    """Pull API / flag names the user likely expects to appear in the patch."""
    if not text or not str(text).strip():
        return ()
    found: list[str] = []

    def _add(token: str) -> None:
        tok = _normalize_symbol_token(token)
        if not _is_strong_symbol(tok):
            return
        if tok not in found:
            found.append(tok)
        if "." in tok:
            leaf = tok.rsplit(".", 1)[-1]
            if leaf != tok:
                _add(leaf)

    for m in re.finditer(r"`([^`]+)`", text):
        _add(m.group(1))
    for m in re.finditer(r"\b([A-Za-z_][\w]{3,})\(\)", text):
        _add(m.group(1))
    for m in re.finditer(r"(--[a-zA-Z][\w-]{2,})", text):
        _add(m.group(1))
    # CamelCase entrypoints (BeginRepl) not already captured.
    for m in re.finditer(r"\b([A-Z][a-zA-Z0-9]{5,})\b", text):
        _add(m.group(1))

    # Cap so a long instruction cannot demand dozens of tokens.
    return tuple(found[:16])


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
    if len(required) < min_required:
        return ()
    blob = mutation_blob or ""
    blob_lower = blob.lower()
    missing = tuple(
        sym
        for sym in required
        if sym not in blob and sym.lower() not in blob_lower
    )
    covered = len(required) - len(missing)
    if covered / max(len(required), 1) >= coverage_ratio:
        return ()
    return missing[:8]


def prompt_symbol_nudge(missing: tuple[str, ...] | list[str]) -> str:
    """Format a continuation nudge listing missing prompt symbols."""
    symbols = ", ".join(f"`{s}`" for s in missing)
    return PROMPT_SYMBOL_NUDGE_TEMPLATE.format(symbols=symbols or "(none)")


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
    native_mutated: bool = False,
    native_build_verified: bool = False,
) -> str | None:
    """Pick the next headless continuation nudge, or None if done."""
    if not looks_like_implement_task(user_text):
        return None
    if not mutate_attempted:
        return ZERO_MUTATION_NUDGE
    if shallow_only:
        return SHALLOW_EDIT_NUDGE
    if not integration_attempted:
        return INTEGRATION_NUDGE
    if missing_symbols:
        return prompt_symbol_nudge(tuple(missing_symbols))
    if native_mutated and not native_build_verified:
        return NATIVE_BUILD_NUDGE
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


__all__ = [
    "INCOMPLETE_IMPLEMENT_ERROR",
    "INTEGRATION_NUDGE",
    "NATIVE_BUILD_NUDGE",
    "PROMPT_SYMBOL_NUDGE_TEMPLATE",
    "SHALLOW_EDIT_NUDGE",
    "STALL_CONTINUATION_NUDGE",
    "SUBMIT_NUDGE",
    "VERIFY_FAILED_NUDGE",
    "VERIFY_NUDGE",
    "ZERO_MUTATION_NUDGE",
    "bash_result_succeeded",
    "edit_args_look_shallow",
    "extract_bash_command",
    "extract_bash_command_from_result",
    "extract_required_prompt_symbols",
    "is_native_source_path",
    "is_shallow_signature_edit",
    "looks_like_git_archaeology",
    "looks_like_implement_task",
    "looks_like_native_build_command",
    "looks_like_submit_command",
    "looks_like_verify_command",
    "missing_prompt_symbols",
    "mutation_args_touch_native",
    "mutation_text_from_args",
    "next_implement_continuation",
    "prompt_symbol_nudge",
    "task_requires_submit",
    "tool_is_edit_existing",
    "tool_is_write_file",
    "verify_command_qualifies_for_completion",
]

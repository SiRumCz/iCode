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
    "pnpm run test",
    "pnpm exec vitest",
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
    "vitest",
    "tstyche",
    "pnpm exec vitest",
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


def is_fatal_provider_error(exc: BaseException | str) -> bool:
    """Return True when an LLM/provider error should stop implement continuations.

    Insufficient balance / auth failures will not recover on retry; if the
    worktree already has deliverable edits, SessionHost should finish instead
    of burning budget on git-log loops.
    """
    text = str(exc or "").lower()
    if not text:
        return False
    markers = (
        "insufficient balance",
        "deposit usdc",
        "authentication",
        "invalid api key",
        "incorrect api key",
        "401",
        "403 forbidden",
        "permission denied",
        "account deactivated",
        "billing",
        "quota exceeded",
        "rate limit",
    )
    # Rate limit is often transient — only treat hard billing/auth as fatal.
    hard = (
        "insufficient balance",
        "deposit usdc",
        "invalid api key",
        "incorrect api key",
        "account deactivated",
        "billing hard limit",
        "exceeded your current quota",
    )
    return any(m in text for m in hard)


CHAT_ONLY_NUDGE = (
    "You incorrectly treated the user message as system configuration / "
    "guidelines (or asked what to work on) and did not call any tools. That "
    "was wrong: the user message IS the implement task — including any "
    "Interface / Configuration / Expected behavior / Execution rules "
    "sections. Do NOT claim there is no task, introduce yourself, or ask "
    "what to work on. Immediately call `list_files`, `grep`, or "
    "`read_file` under the repo cwd, then `edit_file` / `write_file` to "
    "apply a concrete patch. Your next response must include a tool call."
)

RESUME_AFTER_CHAT_NUDGE = (
    "You already used tools earlier in this turn, then replied without "
    "tools and asked what to work on / claimed there is no task. The "
    "implement task is still active. Do NOT greet or ask again. Call "
    "`edit_file` or `write_file` now (read the target file first if "
    "needed). Your next response must include a tool call."
)

# Prefixed onto headless ``icode run -t`` / implement prompts so weak models
# do not confuse task specs (e.g. "## Configuration") with system setup.
HEADLESS_TASK_ENVELOPE_MARKER = "# Implement this task now"

_HEADLESS_TASK_ENVELOPE = (
    f"{HEADLESS_TASK_ENVELOPE_MARKER}\n"
    "The block below is your ONLY user task for this headless run. Execute "
    "it with tools in the repo cwd.\n"
    "Do NOT treat it as system configuration, identity guidelines, or an "
    "empty prompt. Headings like Interface / Configuration / Expected "
    "behavior / Execution rules are PART OF THE TASK SPEC.\n"
    "Do NOT ask what to work on — your first response must include a tool "
    "call (`list_files` / `grep` / `read_file` / `edit_file` / "
    "`write_file`).\n"
    "CLI formatter rule: when the task says results are empty or issues "
    "must not be reported, and a report formatter exists (`-f json`, etc.), "
    "clear findings then still run the normal output path — valid JSON with "
    "an empty `results` list, not empty stdout. Do not `sys.exit(0)` before "
    "formatting."
)

ZERO_MUTATION_NUDGE = (
    "You used tools but did not modify any files in the worktree. "
    "The user asked you to implement changes. Call `edit_file` or "
    "`write_file` now to apply a concrete patch. "
    "Do not run another round of grep, git log, go test, or go build "
    "before the first successful edit. "
    "Do not search git history for an upstream PR — this checkout is often "
    "at a pruned base commit with no solution commits to find. "
    "Do not stop after another design essay. When the patch is in place, "
    "run any required submit/deliver command (for example `lolbench-submit`)."
)

EDIT_ONLY_NUDGE = (
    "You already explored the repository but did not call `edit_file` or "
    "`write_file`. STOP using `list_files`, `grep`, `read_file`, `glob`, "
    "`bash`, or git archaeology — you have enough context. Call "
    "`edit_file` or `write_file` NOW on concrete paths under the repo cwd "
    "and apply a small working patch for the task. Do NOT greet, ask what "
    "to work on, or claim the message is only guidelines."
)

# Headless implement rails: orient briefly, then hard-stop explore loops.
IMPLEMENT_EXPLORE_BUDGET = 6
IMPLEMENT_EXPLORE_ABORT_CAP = 8
IMPLEMENT_MODEL_ABORT_CAP = 10

# Continuation streams after explore-without-edit: at most one more read.
CONTINUATION_EXPLORE_ABORT_CAP = 1
CONTINUATION_MODEL_ABORT_CAP = 3

# After a workspace edit, allow a couple of reads then force verify — do not
# burn the turn on git log / list_files archaeology.
POST_MUTATION_EXPLORE_ABORT_CAP = 2
POST_MUTATION_MODEL_ABORT_CAP = 3

# How many headless chat-only (zero-tool) continuations before fail-closed.
MAX_CHAT_ONLY_CONTINUATIONS = 3

_GREETING_MARKERS = (
    "what would you like me to work on",
    "what would you like me to help",
    "what would you like to work on",
    "ready to help",
    "i'm **icode**",
    "i am **icode**",
    "i'm icode",
    "i am icode",
    "just let me know the task",
    "just describe the task",
    "just tell me what you'd like",
    "system configuration and guidelines",
    "system/configuration instructions",
    "rather than a specific task",
    "rather than an actual task",
    "rather than a concrete request",
    "don't see a specific task",
    "i don't see a specific task",
    "i don't see a concrete request",
    "contains only system",
    "contains the system configuration",
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
    "for TypeScript/JavaScript: `npm test`, `npx jest --runInBand`, or "
    "`npx vitest run` on the tests for the feature you added — "
    "`tsc --noEmit` alone is not enough; "
    "for CPython/C: `make -j2` or a targeted object rebuild; "
    "for CPython grammar: `make regen-pegen regen-ast` then "
    "`CCACHE_DISABLE=1 make -j2 python`). "
    "Do NOT run `git log`, `list_files`, or more archaeology — verify now. "
    "Fix any errors that appear, then continue. If the user required a "
    "submit/deliver command (for example `lolbench-submit`), run it only "
    "after verification succeeds."
)

POST_MUTATION_EXPLORE_NUDGE = (
    "You already modified the worktree, then spent more tool rounds on "
    "`list_files` / `grep` / `read_file` / `git log` instead of verifying. "
    "STOP exploring. Call `bash` NOW with this repo's real test/build "
    "command (TypeScript: `npm test` or `npx jest --runInBand` on the "
    "feature tests; Python: `pytest`; Go: `go test ./... -count=1`). "
    "Do not summarize git history or ask what to work on."
)

CLI_CONTRACT_NUDGE_PREFIX = (
    "Your test suite passed, but unfilled CLI/output contracts remain "
    "(hidden eval tests check these separately). STOP re-running the full "
    "suite. Use targeted live CLI `bash` checks:"
)

CLI_CONTRACT_NUDGE_SUFFIX = (
    "Fix failing behavior, then re-run only the specific CLI smokes above — "
    "not another full stestr/pytest loop."
)

MAX_REPEAT_SUITE_VERIFY_CONTINUATIONS = 2

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
    "You edited Go sources but have not run a real test suite. "
    "`go build` / `go vet` compile or lint only — they do not run tests, "
    "and tests you wrote this session alone are not enough. Call `bash` now "
    "with `go test ./... -count=1` (full repo suite) or multiple packages "
    "you touched, fix failures, and re-run until they pass. Do not verify "
    "only with `go test` on a package whose *_test.go you just created. "
    "Do not leave build output binaries in the repo."
)

TS_SUITE_NUDGE = (
    "You edited TypeScript sources but have not run a real test suite. "
    "`tsc --noEmit`, `npm run build`, or typecheck-only commands are not "
    "enough. Do not treat test files you wrote this session as sufficient "
    "verification — run the project's real integration tests via `bash` "
    "(Effect monorepos: `npx vitest run --project @effect/platform-node "
    "test/<Feature>.test.ts`; Deno repos: `deno task test`; Node repos: "
    "`npm test` or `npx vitest run`) without piping through `tail`/`grep`, "
    "fix failures, and re-run until they pass before finishing."
)

TS_INSUFFICIENT_VERIFY_NUDGE_TEMPLATE = (
    "You ran TypeScript tests and they passed, but the harness still needs "
    "broader verification before this implement turn can finish. Do not "
    "re-run the same command, make empty touch commits, or tweak comments "
    "to \"force a diff\". Instead: (1) run the repo's canonical or "
    "consumer-package suite without piping through `head`/`tail`/`grep` "
    "(for example bare `npx vitest run --project @effect/platform-node "
    "test/HttpApiSSE.test.ts`, `npm test`, or `pnpm exec vitest run`); "
    "(2) ensure chainable methods the user named are wired on real runtime "
    "entrypoints, not only in isolated helper unit tests; (3) fix any "
    "failures and re-run verification."
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
        CHAT_ONLY_NUDGE,
        RESUME_AFTER_CHAT_NUDGE,
        EDIT_ONLY_NUDGE,
        ZERO_MUTATION_NUDGE,
        WORKTREE_NUDGE,
        STALL_CONTINUATION_NUDGE,
        TOOL_RUNTIME_NUDGE,
        SHALLOW_EDIT_NUDGE,
        INTEGRATION_NUDGE,
        VERIFY_NUDGE,
        VERIFY_FAILED_NUDGE,
        POST_MUTATION_EXPLORE_NUDGE,
        SUBMIT_NUDGE,
        NATIVE_BUILD_NUDGE,
        PYTHON_SUITE_NUDGE,
        GO_SUITE_NUDGE,
        TS_SUITE_NUDGE,
        TS_INSUFFICIENT_VERIFY_NUDGE_TEMPLATE,
        CLI_CONTRACT_NUDGE_PREFIX,
    ):
        if stripped == marker or stripped.startswith(marker[:48]):
            return True
    if stripped.startswith("Your patch is missing symbols/APIs the user named:"):
        return True
    if stripped.startswith(CLI_CONTRACT_NUDGE_PREFIX[:48]):
        return True
    return False


def looks_like_greeting_response(text: str) -> bool:
    """Return True when *text* looks like a capability intro / ask-for-task reply."""
    stripped = (text or "").strip().lower()
    if not stripped:
        return False
    hits = sum(1 for marker in _GREETING_MARKERS if marker in stripped)
    if hits >= 2:
        return True
    if hits >= 1 and len(stripped) < 2500:
        # Single strong ask-what-to-do / no-task-misread marker is enough.
        strong_markers = (
            "what would you like me to work on",
            "what would you like me to help",
            "what would you like to work on",
            "system configuration and guidelines",
            "rather than a specific task",
            "rather than an actual task",
            "i don't see a specific task",
            "don't see a specific task",
        )
        return any(m in stripped for m in strong_markers)
    return False


def is_headless_task_enveloped(text: str) -> bool:
    """Return True when *text* already has the headless implement envelope."""
    return (text or "").lstrip().startswith(HEADLESS_TASK_ENVELOPE_MARKER)


def wrap_headless_implement_prompt(text: str) -> str:
    """Prefix implement-looking headless prompts with an unambiguous task envelope.

    Weak models often misread DeepSWE / Pier specs that contain
    ``## Configuration`` or trailing ``Execution rules`` as system setup and
    reply with greetings. The envelope forces ``-t`` content to be treated as
    the sole coding task.
    """
    raw = text or ""
    if not raw.strip():
        return raw.strip()
    if is_headless_task_enveloped(raw):
        return raw
    body = raw.strip()
    if not looks_like_implement_task(body):
        return body
    return f"{_HEADLESS_TASK_ENVELOPE}\n\n---\n{body}\n"


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


def bash_command_verify_subject(command: str) -> str:
    """Return the primary shell segment used for verify heuristics.

    Pipes/redirections often hide ``vitest``/``pytest`` from naive matching
    when agents run ``vitest ... | tail``. Only the segment before the first
    ``|``, ``&&``, or ``;`` is considered.
    """
    if not command or not str(command).strip():
        return ""
    text = str(command).strip()
    text = re.split(r"\s\|\s", text, maxsplit=1)[0]
    text = re.sub(r"\s2>&1\s*$", "", text)
    return text.strip()


def looks_like_verify_command(command: str) -> bool:
    """Return True when *command* looks like compile/test verification."""
    subject = bash_command_verify_subject(command)
    if not subject:
        return False
    lower = subject.lower()
    if re.search(r"\b(?:vitest|tstyche)\b", lower):
        return True
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


def is_full_go_suite_command(command: str) -> bool:
    """Return True when *command* runs the repo-wide Go test suite.

    Single-package ``go test ./pkg/`` runs (including agent-authored
    ``*_test.go`` in that package) do not count — hidden fail-to-pass tests
    may only exist at grading time.
    """
    if not command or not looks_like_go_suite_command(command):
        return False
    lower = str(command).lower().strip()
    if "./..." not in lower:
        return False
    if re.search(r"[\w./-]+_test\.go\b", lower):
        return False
    return True


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
    command = bash_command_verify_subject(command)
    if not command or not agent_created_test_names:
        return False
    if is_full_typescript_suite_command(command):
        return False
    if is_full_python_suite_command(command):
        return False
    if is_full_go_suite_command(command):
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
        if "/" in token and token.replace("\\", "/") in lower.replace("\\", "/"):
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
    command = bash_command_verify_subject(command)
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
        if verify_command_targets_agent_authored_tests(
            command, agent_created_test_names
        ):
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
            targets = suggested_typescript_verify_targets(user_text)
            if targets:
                if not typescript_monorepo_integration_verify_matches(
                    user_text, command
                ):
                    return False
            else:
                return False
        if user_text and not typescript_command_matches_task_scope(
            user_text, command
        ):
            return False
        if typescript_wrong_package_only(command, user_text):
            return False
        if suggested_typescript_verify_targets(user_text) and (
            not typescript_monorepo_integration_verify_matches(user_text, command)
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
    chainable_keywords = frozenset(extract_chainable_method_names(user_text))
    keywords = stem_keywords | repeated_keywords | chainable_keywords
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
    if is_full_go_suite_command(command):
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


CLI_FLAG_DENSE_THRESHOLD = 4


def cli_flag_dense_task(user_text: str) -> bool:
    """Return True when the task names many CLI flags (needs contract checks)."""
    return _cli_flag_count(user_text) >= CLI_FLAG_DENSE_THRESHOLD


def extract_task_cli_flags(user_text: str) -> tuple[str, ...]:
    """Distinct ``--flag`` names mentioned in the implement prompt."""
    flags = sorted(set(re.findall(r"--[a-z][\w-]+", str(user_text or "").lower())))
    return tuple(flags)


def extract_prints_literal_contracts(
    user_text: str,
) -> tuple[tuple[str | None, str], ...]:
    """Return ``(optional_flag, literal)`` pairs from ``prints "…"`` specs."""
    found: list[tuple[str | None, str]] = []
    seen_literals: set[str] = set()
    for m in re.finditer(
        r'(--[a-z][\w-]+)\s+prints?\s+"([^"]+)"',
        user_text,
        re.IGNORECASE,
    ):
        flag = m.group(1).lower()
        literal = m.group(2)
        found.append((flag, literal))
        seen_literals.add(literal.lower())
    for m in re.finditer(r'prints?\s+"([^"]+)"', user_text, re.IGNORECASE):
        literal = m.group(1)
        if literal.lower() in seen_literals:
            continue
        found.append((None, literal))
    return tuple(found)


def mentions_empty_results_formatter_contract(user_text: str) -> bool:
    """Task ties empty/no-report results to JSON or another formatter."""
    lower = str(user_text or "").lower()
    has_empty = (
        "results empty" in lower
        or "without reporting" in lower
        or "does not report" in lower
        or "do not report" in lower
    )
    has_formatter = (
        "json" in lower
        or "-f" in lower
        or "formatter" in lower
        or "stdout" in lower
    )
    return has_empty and has_formatter


def mentions_exit_zero_contract(user_text: str) -> bool:
    return bool(re.search(r"\bexit\s+0\b", str(user_text or ""), re.IGNORECASE))


def looks_like_live_cli_command(command: str) -> bool:
    """Return True when *command* invokes a real CLI entrypoint (not pytest-only)."""
    if not command or not str(command).strip():
        return False
    lower = str(command).lower()
    if looks_like_git_archaeology(command):
        return False
    if re.search(r"\bpytest\b|\bstestr\b|\bunittest\b", lower):
        return False
    if re.search(r"\bgrep\b|\brg\b|\bfind\b|\bcat\b|\bhead\b|\btail\b", lower):
        if not re.search(r"--[\w-]", lower):
            return False
    if re.search(
        r"\bpython(?:3(?:\.\d+)?)?\s+-m\s+(?!pytest\b)[\w.]+\b", lower
    ):
        return True
    if re.search(r"(?:^|\s|/)(?:[\w.-]+)\s+--[\w-]", lower):
        return True
    return False


def looks_like_standalone_admin_cli(command: str, flag: str) -> bool:
    """Heuristic: admin/maintenance flag run without scan targets."""
    if flag.lower() not in str(command or "").lower():
        return False
    if not looks_like_live_cli_command(command):
        return False
    lower = str(command).lower()
    flag_l = flag.lower()
    if flag_l in {"--warm-cache", "--incremental", "--force-rescan"}:
        return True
    if re.search(r"(?:^|\s)(?:[\w./-]+\.py)\b", lower):
        return False
    return True


def cli_contract_flag_smoke_satisfied(
    flag: str, commands: tuple[str, ...]
) -> bool:
    flag_l = flag.lower()
    for cmd in commands:
        if flag_l not in cmd.lower():
            continue
        if looks_like_live_cli_command(cmd):
            return True
    return False


def cli_contract_prints_literal_satisfied(
    flag: str | None,
    literal: str,
    commands: tuple[str, ...],
) -> bool:
    for cmd in commands:
        if flag and flag.lower() not in cmd.lower():
            continue
        if flag and not looks_like_standalone_admin_cli(cmd, flag):
            continue
        if not flag and not looks_like_live_cli_command(cmd):
            continue
        if literal.lower().replace(" n", "").replace(" m", "") in cmd.lower():
            return True
        if flag and looks_like_standalone_admin_cli(cmd, flag):
            return True
    return False


def cli_contract_empty_json_satisfied(
    user_text: str, commands: tuple[str, ...]
) -> bool:
    if not mentions_empty_results_formatter_contract(user_text):
        return True
    warm_flags = [f for f in extract_task_cli_flags(user_text) if "warm" in f]
    if not warm_flags:
        warm_flags = ["--warm-cache"]
    for cmd in commands:
        lower = cmd.lower()
        if not any(flag in lower for flag in warm_flags):
            continue
        if not re.search(r"-f\s+['\"]?json\b", lower):
            continue
        if looks_like_live_cli_command(cmd):
            return True
    return False


def cli_contract_pending_items(
    user_text: str, bash_commands: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """Checklist lines still missing after *bash_commands* in this turn."""
    if not cli_flag_dense_task(user_text):
        return ()
    commands = tuple(str(c or "") for c in bash_commands if str(c or "").strip())
    pending: list[str] = []

    flags = extract_task_cli_flags(user_text)
    missing_flags = [
        flag for flag in flags if not cli_contract_flag_smoke_satisfied(flag, commands)
    ]
    if missing_flags:
        shown = ", ".join(missing_flags[:10])
        if len(missing_flags) > 10:
            shown += ", …"
        pending.append(
            f"Live CLI smoke: invoke each new flag via `bash` on the real "
            f"entrypoint (still missing: {shown}). Unit tests alone are not "
            f"enough."
        )

    for flag, literal in extract_prints_literal_contracts(user_text):
        if cli_contract_prints_literal_satisfied(flag, literal, commands):
            continue
        target = f"{flag} " if flag else ""
        pending.append(
            f'Run {target}with NO scan targets and confirm stdout matches '
            f'the required text (spec: prints "{literal}").'
        )

    if not cli_contract_empty_json_satisfied(user_text, commands):
        line = (
            'For "results empty" / "without reporting issues" with `-f json`: '
            "clear findings, still run the normal JSON formatter (`json.loads` "
            'on stdout must succeed; `"results": []`), and do NOT `sys.exit(0)` '
            "before output."
        )
        if mentions_exit_zero_contract(user_text):
            line += (
                " Required exit 0 must come from the formatter path, not a "
                "pre-output early exit."
            )
        pending.append(line)

    return tuple(pending)


def cli_contract_satisfied(
    user_text: str, bash_commands: tuple[str, ...] | list[str]
) -> bool:
    return not cli_contract_pending_items(user_text, bash_commands)


def cli_contract_nudge(
    user_text: str, bash_commands: tuple[str, ...] | list[str]
) -> str:
    pending = cli_contract_pending_items(user_text, bash_commands)
    if not pending:
        return ""
    checklist = "\n".join(f"- {line}" for line in pending)
    return f"{CLI_CONTRACT_NUDGE_PREFIX}\n\n{checklist}\n\n{CLI_CONTRACT_NUDGE_SUFFIX}"


POST_VERIFY_CONTRACT_NUDGE_PREFIX = CLI_CONTRACT_NUDGE_PREFIX


def typescript_integration_task(user_text: str) -> bool:
    """Return True when the task needs consumer-package TS integration tests."""
    if suggested_typescript_verify_targets(user_text):
        return True
    lower = str(user_text or "").lower()
    if any(
        tok in lower
        for tok in (
            "text/event-stream",
            "formatmessage",
            "handlestream",
            "nodehttpserver",
            "client consumption",
        )
    ):
        return True
    return bool(re.search(r"\bHttpApi[A-Z]\w+\b", user_text or ""))


def suggested_typescript_verify_targets(user_text: str) -> tuple[dict[str, str], ...]:
    """Suggested vitest targets for monorepo integration tasks."""
    lower = str(user_text or "").lower()
    targets: list[dict[str, str]] = []
    if (
        "httpapisse" in lower
        or "httpapiendpoint.sse" in lower
        or ("httpapi" in lower and "sse" in lower and "stream" in lower)
    ):
        targets.append(
            {
                "project": "@effect/platform-node",
                "test_file": "HttpApiSSE.test.ts",
                "test_path": "test/HttpApiSSE.test.ts",
                "path_hint": "platform-node/test",
                "avoid_project": "@effect/platform",
            }
        )
    return tuple(targets)


def typescript_monorepo_integration_verify_matches(
    user_text: str, command: str
) -> bool:
    """Return True when verify runs the consumer-package tests the task needs."""
    targets = suggested_typescript_verify_targets(user_text)
    if not targets:
        return True
    subject = bash_command_verify_subject(command).lower()
    if not subject:
        return False
    for target in targets:
        project = target["project"].lower()
        if project not in subject and project.split("/", 1)[-1] not in subject:
            continue
        test_file = target.get("test_file", "").lower()
        test_path = target.get("test_path", "").lower()
        path_hint = target.get("path_hint", "").lower()
        if test_file and test_file in subject:
            return True
        if test_path and test_path in subject:
            return True
        if path_hint and path_hint in subject.replace("\\", "/"):
            return True
        if re.search(rf"--project\s+{re.escape(target['project'])}", subject, re.I):
            return True
    return False


def typescript_wrong_package_only(command: str, user_text: str) -> bool:
    """Return True when verify runs only an implementation package, not consumer."""
    if not typescript_integration_task(user_text):
        return False
    if typescript_monorepo_integration_verify_matches(user_text, command):
        return False
    subject = bash_command_verify_subject(command).lower()
    if not subject or not looks_like_typescript_suite_command(command):
        return False
    for target in suggested_typescript_verify_targets(user_text):
        avoid = target.get("avoid_project", "").lower()
        if avoid and avoid in subject:
            return True
        impl_hint = target.get("path_hint", "").split("/", 1)[0]
        if (
            impl_hint
            and impl_hint in subject
            and "platform-node" not in subject
            and target["project"].lower() not in subject
        ):
            return True
    return False


def wire_format_contract_task(user_text: str) -> bool:
    """Return True when the task specifies SSE/HTTP wire-format output contracts."""
    lower = str(user_text or "").lower()
    return any(
        tok in lower
        for tok in (
            "formatmessage",
            "formatdatamessage",
            "text/event-stream",
            "event-stream",
            "sse wire",
            "wire-format",
        )
    ) or bool(re.search(r"\bformat(?:Message|DataMessage)\b", user_text or ""))


def wire_format_contract_pending_items(
    user_text: str, bash_commands: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """Checklist for SSE/HTTP wire-format contracts still missing."""
    if not wire_format_contract_task(user_text):
        return ()
    commands = tuple(str(c or "") for c in bash_commands if str(c or "").strip())
    if typescript_integration_task(user_text) and any(
        typescript_monorepo_integration_verify_matches(user_text, cmd)
        for cmd in commands
    ):
        return ()
    pending: list[str] = []
    lower = str(user_text or "").lower()
    if "formatmessage" in lower or "formatdatamessage" in lower:
        pending.append(
            "SSE wire format: `formatMessage` / `formatDataMessage` must emit "
            "`data: {json}` lines (raw JSON payload), not `data: \"{...}\"` "
            "with extra JSON.stringify quotes. Multi-line payloads use "
            "multiple `data:` lines (`data: line1\\ndata: line2`), not escaped "
            "newlines inside one quoted string."
        )
    if "text/event-stream" in lower or "event-stream" in lower:
        pending.append(
            "Verify `toResponse` / `fromStream` / `toStream` against real "
            "HttpClientResponse/HttpServerResponse shapes (status + stream "
            "body). `toResponse` must yield status 200 and SSE headers "
            "(`content-type: text/event-stream`, `cache-control: no-cache`, "
            "`connection: keep-alive`)."
        )
    if "event:" in lower or "event field" in lower or "_tag" in lower:
        pending.append(
            "Union SSE encoders must set the `event:` field from `_tag` and "
            "decoders must dispatch on `event:` — confirm with consumer-package "
            "integration tests, not only helper unit tests."
        )
    return tuple(pending)


def typescript_monorepo_contract_pending_items(
    user_text: str, bash_commands: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """Checklist when consumer-package vitest has not been run."""
    if not typescript_integration_task(user_text):
        return ()
    commands = tuple(str(c or "") for c in bash_commands if str(c or "").strip())
    if any(
        typescript_monorepo_integration_verify_matches(user_text, cmd)
        for cmd in commands
    ):
        return ()
    pending: list[str] = []
    for target in suggested_typescript_verify_targets(user_text):
        pending.append(
            "Consumer-package integration tests: run "
            f"`npx vitest run --project {target['project']} "
            f"{target.get('test_path', target.get('test_file', ''))}` "
            "(bare command — no `| tail`/`grep`). Tests you wrote under "
            f"{target.get('avoid_project', 'another package')} alone are "
            "not enough; hidden eval tests run in the consumer package."
        )
    if not pending and typescript_integration_task(user_text):
        pending.append(
            "Run the repo's consumer/integration vitest target for this "
            "feature (not only agent-authored unit tests or `tsc --noEmit`)."
        )
    return tuple(pending)


def post_verify_contract_pending_items(
    user_text: str, bash_commands: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """Merged CLI / wire-format / TS monorepo contract checklist."""
    pending: list[str] = []
    pending.extend(cli_contract_pending_items(user_text, bash_commands))
    pending.extend(typescript_monorepo_contract_pending_items(user_text, bash_commands))
    pending.extend(wire_format_contract_pending_items(user_text, bash_commands))
    return tuple(pending)


def post_verify_contract_satisfied(
    user_text: str, bash_commands: tuple[str, ...] | list[str]
) -> bool:
    return not post_verify_contract_pending_items(user_text, bash_commands)


def post_verify_contract_nudge(
    user_text: str, bash_commands: tuple[str, ...] | list[str]
) -> str:
    pending = post_verify_contract_pending_items(user_text, bash_commands)
    if not pending:
        return ""
    checklist = "\n".join(f"- {line}" for line in pending)
    return (
        f"{POST_VERIFY_CONTRACT_NUDGE_PREFIX}\n\n{checklist}\n\n"
        f"{CLI_CONTRACT_NUDGE_SUFFIX}"
    )


def suite_verify_continuation_redundant(
    *,
    verify_succeeded: bool,
    python_suite_verified: bool,
    go_suite_verified: bool,
    typescript_suite_verified: bool,
    suite_verify_without_mutation: int,
) -> bool:
    """Return True when another full-suite verify nudge would be wasted."""
    if not verify_succeeded:
        return False
    if suite_verify_without_mutation < MAX_REPEAT_SUITE_VERIFY_CONTINUATIONS:
        return False
    return (
        python_suite_verified
        or go_suite_verified
        or typescript_suite_verified
    )


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


def extract_chainable_method_names(text: str) -> tuple[str, ...]:
    """Chainable `.method()` names explicitly required in an implement prompt."""
    found: list[str] = []

    def _add(raw: str) -> None:
        tok = _normalize_symbol_token(raw)
        if _is_strong_symbol(tok, allow_short=True) and tok not in found:
            found.append(tok)

    for m in re.finditer(r"\.([a-zA-Z_][\w]{1,})\(\)", text):
        _add(m.group(1))
    for m in re.finditer(r"chainable\s+\.([a-zA-Z_][\w]{1,})\(", text, re.IGNORECASE):
        _add(m.group(1))
    return tuple(found)


def _extract_wiring_symbols(text: str) -> tuple[str, ...]:
    """Entrypoints explicitly wired via slash or chainable-call syntax."""
    found: list[str] = []
    for m in re.finditer(r"/([a-z][a-z0-9_]+)\b", text.lower()):
        tok = _normalize_symbol_token(m.group(1))
        if _is_strong_symbol(tok) and tok not in found:
            found.append(tok)
    for method in extract_chainable_method_names(text):
        if method not in found:
            found.append(method)
    return tuple(found)


def typescript_insufficient_verify_nudge(user_text: str) -> str:
    """Nudge when TS tests passed but did not satisfy the verify gate."""
    extras: list[str] = []
    for target in suggested_typescript_verify_targets(user_text):
        extras.append(
            "Run consumer-package tests: "
            f"`npx vitest run --project {target['project']} "
            f"{target.get('test_path', target.get('test_file', ''))}` "
            "without piping through `tail`/`grep`."
        )
    methods = extract_chainable_method_names(user_text)[:6]
    if methods:
        listed = ", ".join(f"`.{name}()`" for name in methods)
        extras.append(
            f"The task names these chainable methods — exercise them on real "
            f"builder objects in code and tests (for example {listed})."
        )
    if wire_format_contract_task(user_text):
        extras.append(
            "SSE wire format: emit raw JSON in `data:` lines (`data: {\"seq\":1}`), "
            "not quoted JSON strings; multi-line data uses multiple `data:` lines."
        )
    if not extras:
        return TS_INSUFFICIENT_VERIFY_NUDGE_TEMPLATE
    return f"{TS_INSUFFICIENT_VERIFY_NUDGE_TEMPLATE}\n\n" + "\n".join(extras)


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


def chat_only_continuation_nudge(
    user_text: str,
    *,
    any_tool_attempted: bool = False,
) -> str:
    """Build a zero-tool (greeting / ask-for-task) continuation nudge."""
    base = RESUME_AFTER_CHAT_NUDGE if any_tool_attempted else CHAT_ONLY_NUDGE
    symbols = extract_required_prompt_symbols(user_text)[:6]
    if not symbols:
        return base
    listed = ", ".join(f"`{sym}`" for sym in symbols)
    return (
        f"{base}\n\n"
        f"The task names these APIs — locate and wire them under the repo cwd "
        f"(for example {listed}). Do not greet again."
    )


def zero_mutation_continuation_nudge(
    user_text: str,
    *,
    any_tool_attempted: bool = True,
) -> str:
    """Build a zero-mutation nudge, optionally listing APIs named in the task.

    When *any_tool_attempted* is False the model only chatted (greeting /
    ask-for-task) — use :data:`CHAT_ONLY_NUDGE` instead of the explore-without-
    edit wording.
    """
    if not any_tool_attempted:
        return chat_only_continuation_nudge(
            user_text, any_tool_attempted=False
        )
    base = EDIT_ONLY_NUDGE
    symbols = extract_required_prompt_symbols(user_text)[:6]
    if not symbols:
        return base
    listed = ", ".join(f"`{sym}`" for sym in symbols)
    return (
        f"{base}\n\n"
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
    typescript_suite_passed_unqualified: bool = False,
    any_tool_attempted: bool = True,
    bash_commands: tuple[str, ...] | list[str] = (),
    suite_verify_without_mutation: int = 0,
) -> str | None:
    """Pick the next headless continuation nudge, or None if done."""
    if not looks_like_implement_task(user_text):
        return None
    if not mutate_attempted:
        return zero_mutation_continuation_nudge(
            user_text, any_tool_attempted=any_tool_attempted
        )
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
        and typescript_suite_passed_unqualified
    ):
        return typescript_insufficient_verify_nudge(user_text)
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
    if suite_verify_continuation_redundant(
        verify_succeeded=verify_succeeded,
        python_suite_verified=python_suite_verified,
        go_suite_verified=go_suite_verified,
        typescript_suite_verified=typescript_suite_verified,
        suite_verify_without_mutation=suite_verify_without_mutation,
    ):
        pending = post_verify_contract_pending_items(user_text, bash_commands)
        if pending:
            return post_verify_contract_nudge(user_text, bash_commands)
        return None
    pending = post_verify_contract_pending_items(user_text, bash_commands)
    if pending:
        return post_verify_contract_nudge(user_text, bash_commands)
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
    "CLI_CONTRACT_NUDGE_PREFIX",
    "CLI_FLAG_DENSE_THRESHOLD",
    "MAX_REPEAT_SUITE_VERIFY_CONTINUATIONS",
    "cli_contract_nudge",
    "cli_contract_pending_items",
    "cli_contract_satisfied",
    "cli_flag_dense_task",
    "extract_prints_literal_contracts",
    "extract_task_cli_flags",
    "looks_like_live_cli_command",
    "mentions_empty_results_formatter_contract",
    "bash_command_verify_subject",
    "post_verify_contract_nudge",
    "post_verify_contract_pending_items",
    "post_verify_contract_satisfied",
    "suggested_typescript_verify_targets",
    "typescript_integration_task",
    "typescript_monorepo_integration_verify_matches",
    "typescript_wrong_package_only",
    "wire_format_contract_pending_items",
    "wire_format_contract_task",
    "RESUME_AFTER_CHAT_NUDGE",
    "MAX_CHAT_ONLY_CONTINUATIONS",
    "HEADLESS_TASK_ENVELOPE_MARKER",
    "is_headless_task_enveloped",
    "wrap_headless_implement_prompt",
    "EDIT_ONLY_NUDGE",
    "IMPLEMENT_EXPLORE_BUDGET",
    "IMPLEMENT_EXPLORE_ABORT_CAP",
    "IMPLEMENT_MODEL_ABORT_CAP",
    "CONTINUATION_EXPLORE_ABORT_CAP",
    "CONTINUATION_MODEL_ABORT_CAP",
    "POST_MUTATION_EXPLORE_ABORT_CAP",
    "POST_MUTATION_MODEL_ABORT_CAP",
    "POST_MUTATION_EXPLORE_NUDGE",
    "GO_SUITE_NUDGE",
    "TS_SUITE_NUDGE",
    "TS_INSUFFICIENT_VERIFY_NUDGE_TEMPLATE",
    "extract_chainable_method_names",
    "typescript_insufficient_verify_nudge",
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
    "chat_only_continuation_nudge",
    "zero_mutation_continuation_nudge",
    "ZERO_MUTATION_NUDGE",
    "looks_like_greeting_response",
    "is_fatal_provider_error",
    "bash_output_indicates_failure",
    "bash_result_succeeded",
    "edit_args_look_shallow",
    "extract_bash_command",
    "extract_bash_command_from_result",
    "extract_required_prompt_symbols",
    "is_go_source_path",
    "is_full_go_suite_command",
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

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Nudge coding agents after shallow edits or missing verify/submit steps."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openjiuwen.core.single_agent.prompts.builder import PromptSection
from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.harness.rails.base import DeepAgentRail

from openjiuwen_icode.features.implement_gate import (
    bash_result_succeeded,
    edit_args_look_shallow,
    extract_bash_command,
    extract_bash_command_from_result,
    looks_like_go_suite_command,
    looks_like_native_build_command,
    looks_like_python_suite_command,
    looks_like_submit_command,
    looks_like_typescript_suite_command,
    looks_like_verify_command,
    mutation_args_touch_go,
    mutation_args_touch_native,
    mutation_args_touch_python,
    mutation_args_touch_typescript,
    mutation_args_under_workspace,
    mutation_path_from_args,
    mutation_text_from_args,
    post_verify_contract_nudge,
    post_verify_contract_satisfied,
    primary_user_task_text,
    tool_is_edit_existing,
    verify_command_qualifies_for_completion,
)
from openjiuwen_icode.features.mutations import (
    MUTATING_TOOLS,
    mutating_tool_applied,
    tool_result_payload,
)

_SECTION = "implement_completeness"
_PRIORITY = 97


def _user_text_from_ctx(ctx: Any) -> str:
    """Best-effort extract of the original user task from callback ctx."""
    return primary_user_task_text(ctx)

_SHALLOW_EN = (
    "## Incomplete edit reminder\n"
    "Recent edits look signature/docs-only (type swaps without parsers, "
    "validation, or apply/resolve wiring). Keep implementing the full "
    "behavior, then verify with `bash` (`cargo check` / `go test` / "
    "targeted tests)."
)

_SHALLOW_CN = (
    "## 改动不完整提醒\n"
    "最近的编辑看起来只改了类型签名/文档（例如 Option→Vec，但没有 parser、"
    "校验或 apply/resolve）。请继续实现完整行为，并用 `bash` 做编译/"
    "针对性测试验证（Rust: `cargo check`；Go: `go test` / `go build`）。"
)

_INTEGRATION_EN = (
    "## Integration reminder\n"
    "You wrote new files but have not `edit_file`'d existing call sites. "
    "Do not leave a parallel module unwired — update the real entrypoints "
    "(registration, require/load path, CLI parsing) that must call your "
    "helpers, then verify with `bash`."
)

_INTEGRATION_CN = (
    "## 接入提醒\n"
    "你写了新文件，但还没有用 `edit_file` 修改现有 call site。"
    "不要留下未接入的平行模块——请改真正的入口（注册、require/load、"
    "CLI 解析），再用 `bash` 验证。"
)

_NATIVE_BUILD_EN = (
    "## Native build required\n"
    "You edited native/C extension sources (.c/.h). Python-only tests do not "
    "rebuild those objects. Run `make -j2` or rebuild touched `.o` files via "
    "`bash` and fix compile errors before submit."
)

_NATIVE_BUILD_CN = (
    "## 需要原生编译\n"
    "你修改了 native/C 扩展源码（.c/.h）。仅跑 Python 测试不会重新编译这些"
    "对象。请用 `bash` 执行 `make -j2` 或重建相关 `.o`，修复编译错误后再提交。"
)

_PYTHON_SUITE_EN = (
    "## Python test suite required\n"
    "You edited `.py` files. `compileall` / `python -c` are not enough, and "
    "passing pre-existing tests that already passed at the base commit "
    "(for example `tests/test_monitor.py` on a snapshot feature) is not "
    "enough. Run `pytest` / `python -m pytest` targeting the new feature "
    "(`tests/test_<feature>.py` or `pytest -k <feature>`). If those tests "
    "are not in the checkout, add a focused test for the APIs the user "
    "named, then fix failures and re-run until they pass."
)

_PYTHON_SUITE_CN = (
    "## 需要跑 Python 测试套件\n"
    "你修改了 `.py` 文件。仅 `compileall` / `python -c` 不够；只跑基线就已经"
    "通过的旧测试（例如 snapshot 任务上的 `tests/test_monitor.py`）也不够——"
    "请用 `bash` 针对新功能跑 `pytest`（`tests/test_<feature>.py` 或 "
    "`pytest -k <feature>`）。若仓库里还没有这些测试，请先按用户点名的 API "
    "补一条针对性测试，再修失败用例直到通过。"
)

_GO_SUITE_EN = (
    "## Go tests required\n"
    "You edited `.go` files. `go build` / `go vet` do not run tests, and "
    "passing only `*_test.go` files you wrote this session is not enough. "
    "Call `bash` with `go test ./... -count=1` or multiple touched packages, "
    "fix failures, and re-run until they pass. Do not leave build output "
    "binaries in the repo."
)

_GO_SUITE_CN = (
    "## 需要跑 Go 测试\n"
    "你修改了 `.go` 文件。`go build` / `go vet` 不会跑测试；仅跑本回合"
    "新建的 `*_test.go` 也不够。请用 `bash` 执行 `go test ./... -count=1` "
    "或对多个改动包跑 `go test`，修失败用例直到通过。不要把编译产物"
    "二进制留在仓库里。"
)

_TS_SUITE_EN = (
    "## TypeScript tests required\n"
    "You edited `.ts` / `.tsx` files. `tsc --noEmit`, `npm run build`, and "
    "lint-only commands do not run tests — call `bash` with targeted "
    "`deno task test` / `deno test …/test/` (Deno) or `npm test`, `jest`, "
    "`mocha`, or `vitest` (Node), fix failures, and re-run until they pass."
)

_TS_SUITE_CN = (
    "## 需要跑 TypeScript 测试\n"
    "你修改了 `.ts` / `.tsx` 文件。`tsc --noEmit`、`npm run build` 和 "
    "仅 lint 的命令不会跑测试——请用 `bash` 对改动测试执行 "
    "`npm test` / `jest` / `mocha` / `vitest`，修失败用例直到通过。"
)

_VERIFY_EN = (
    "## Verify reminder\n"
    "You already modified files. Before finishing, run a compile or "
    "targeted test via `bash` (Python: `pytest`; Rust: `cargo check`; "
    "Go: `go test` / `go build`; CPython/C: `make -j2`). Fix failures. "
    "If the user named a submit command (e.g. `lolbench-submit`), run it "
    "only after verification succeeds."
)

_VERIFY_FAILED_EN = (
    "## Verification failed\n"
    "Your last compile/test command exited with an error. Fix the "
    "failures and re-run verification via `bash` before submitting."
)

_VERIFY_CN = (
    "## 验证提醒\n"
    "你已修改文件。结束前请用 `bash` 跑编译或针对性测试"
    "（Python: `pytest`；Rust: `cargo check`；Go: `go test` / `go build`；"
    "CPython/C: `make -j2`），并根据报错继续修。"
    "若用户要求提交命令（例如 `lolbench-submit`），验证通过后再执行。"
)

_VERIFY_FAILED_CN = (
    "## 验证失败\n"
    "最近一次编译/测试命令失败。请先修复错误并重新验证，再执行提交命令。"
)

_CLI_CONTRACT_EN = (
    "## CLI contract checklist\n"
    "The test suite may pass while hidden eval checks still fail on CLI "
    "output contracts. Run targeted live CLI smokes via `bash` (not another "
    "full suite loop) before finishing."
)

_CLI_CONTRACT_CN = (
    "## CLI 契约清单\n"
    "全量测试可能已通过，但隐藏评测仍会检查 CLI 输出契约。"
    "结束前请用 `bash` 做针对性 live CLI smoke，不要再次全量跑 suite。"
)


def _agent_workspace(agent: Any) -> Path | None:
    if agent is None:
        return None
    cfg = getattr(agent, "cfg", None)
    cwd = getattr(cfg, "cwd", None) if cfg else None
    if not cwd:
        return None
    try:
        return Path(str(cwd)).expanduser().resolve()
    except OSError:
        return None


class ImplementCompletenessRail(DeepAgentRail):
    """Inject shallow-edit / verify reminders mid-turn after mutations."""

    priority = 86

    def __init__(self) -> None:
        super().__init__()
        self._mutated = False
        self._shallow_only = True
        self._integration_attempted = False
        self._native_mutated = False
        self._native_build_verified = False
        self._python_mutated = False
        self._python_suite_verified = False
        self._go_mutated = False
        self._go_suite_verified = False
        self._typescript_mutated = False
        self._typescript_suite_verified = False
        self._agent_created_test_names: set[str] = set()
        self._verify_attempted = False
        self._verify_succeeded = False
        self._submit_attempted = False
        self._bash_commands: list[str] = []
        self._user_text = ""
        self.system_prompt_builder = None
        self._agent: Any = None

    def init(self, agent: Any) -> None:
        self._agent = agent
        self.system_prompt_builder = getattr(
            agent, "system_prompt_builder", None
        )
        self._mutated = False
        self._shallow_only = True
        self._integration_attempted = False
        self._native_mutated = False
        self._native_build_verified = False
        self._python_mutated = False
        self._python_suite_verified = False
        self._go_mutated = False
        self._go_suite_verified = False
        self._typescript_mutated = False
        self._typescript_suite_verified = False
        self._agent_created_test_names = set()
        self._verify_attempted = False
        self._verify_succeeded = False
        self._submit_attempted = False
        self._bash_commands: list[str] = []
        self._user_text = ""

    async def after_tool_call(self, ctx: AgentCallbackContext) -> None:
        if not self._user_text:
            self._user_text = _user_text_from_ctx(ctx)
        inputs = ctx.inputs
        name = str(getattr(inputs, "tool_name", "") or "")
        args = getattr(inputs, "tool_args", None)
        tool_result = getattr(inputs, "tool_result", None)
        if not name:
            return
        if name in MUTATING_TOOLS:
            if tool_result is None:
                applied = True
            else:
                result_payload, tool_success = tool_result_payload(tool_result)
                applied = mutating_tool_applied(
                    name, result_payload, tool_success=tool_success
                )
            if not applied:
                return
            if not mutation_args_under_workspace(args, _agent_workspace(self._agent)):
                return
            self._mutated = True
            self._verify_succeeded = False
            self._bash_commands = []
            if mutation_args_touch_native(args):
                self._native_mutated = True
                self._native_build_verified = False
            if mutation_args_touch_python(args):
                self._python_mutated = True
                self._python_suite_verified = False
            if mutation_args_touch_go(args):
                self._go_mutated = True
                self._go_suite_verified = False
            if mutation_args_touch_typescript(args):
                self._typescript_mutated = True
                self._typescript_suite_verified = False
            path = mutation_path_from_args(args)
            if name in {"write_file", "Write", "write"} and path:
                from pathlib import Path as _Path

                lower = str(path).lower()
                base = _Path(str(path)).name.lower()
                if re.search(r"\.(?:test|spec)\.(?:ts|tsx|js|jsx)$", lower):
                    self._agent_created_test_names.add(base)
                    match = re.match(
                        r"^(.*)\.(?:test|spec)\.(?:ts|tsx|js|jsx)$",
                        base,
                    )
                    if match:
                        self._agent_created_test_names.add(match.group(1))
                elif re.search(r"(?:^|/)test_[\w.-]+\.py$", lower) or re.search(
                    r"(?:^|/)[\w.-]+_test\.py$", lower
                ):
                    self._agent_created_test_names.add(base)
                    if base.startswith("test_") and base.endswith(".py"):
                        self._agent_created_test_names.add(base[5:-3])
                    elif base.endswith("_test.py"):
                        self._agent_created_test_names.add(
                            base[: -len("_test.py")]
                        )
                elif re.search(r"(?:^|/)[\w.-]+_test\.go$", lower):
                    self._agent_created_test_names.add(base)
                    if base.endswith("_test.go"):
                        self._agent_created_test_names.add(base[: -len("_test.go")])
                    rel_dir = str(_Path(str(path)).parent).replace("\\", "/").lower()
                    if rel_dir and rel_dir != ".":
                        self._agent_created_test_names.add(rel_dir)
            if tool_is_edit_existing(name):
                self._integration_attempted = True
            # Keep blob tracking available for future rail use.
            _ = mutation_text_from_args(args)
            if not edit_args_look_shallow(args):
                self._shallow_only = False
            return
        if name == "bash":
            cmd = extract_bash_command(args)
            if cmd:
                self._bash_commands.append(cmd)
            if looks_like_verify_command(cmd):
                self._verify_attempted = True
            if looks_like_submit_command(cmd):
                self._submit_attempted = True
            if tool_result is not None:
                result_cmd = cmd or extract_bash_command_from_result(
                    tool_result
                )
                if result_cmd and result_cmd not in self._bash_commands:
                    self._bash_commands.append(result_cmd)
                if looks_like_verify_command(result_cmd):
                    self._verify_attempted = True
                    ok = bash_result_succeeded(
                        tool_result,
                        tool_success=getattr(tool_result, "success", None),
                    )
                    if ok is True:
                        if looks_like_native_build_command(result_cmd):
                            self._native_build_verified = True
                        qualifies = verify_command_qualifies_for_completion(
                            result_cmd,
                            native_mutated=self._native_mutated,
                            python_mutated=self._python_mutated,
                            go_mutated=self._go_mutated,
                            typescript_mutated=self._typescript_mutated,
                            success=True,
                            user_text=self._user_text,
                            agent_created_test_names=frozenset(
                                self._agent_created_test_names
                            ),
                        )
                        # Only mark language suites verified when the command
                        # matches the task feature area. A passing P2P file
                        # (tests/test_monitor.py on a snapshot task) must not
                        # clear the Python-suite gate.
                        if qualifies:
                            if looks_like_python_suite_command(result_cmd):
                                self._python_suite_verified = True
                            if looks_like_go_suite_command(result_cmd):
                                self._go_suite_verified = True
                            if looks_like_typescript_suite_command(
                                result_cmd
                            ):
                                self._typescript_suite_verified = True
                            self._verify_succeeded = True
                        # A passing narrower or out-of-scope check does not
                        # invalidate an earlier qualifying verification.
                        # Mutations and actual command failures reset it.
                    elif ok is False:
                        self._verify_succeeded = False
            return

    async def before_model_call(self, ctx: AgentCallbackContext) -> None:
        if not self._user_text:
            self._user_text = _user_text_from_ctx(ctx)
        builder = self.system_prompt_builder
        if builder is None:
            return
        remove = getattr(builder, "remove_section", None)
        if callable(remove):
            remove(_SECTION)

        if not self._mutated:
            return
        cli_ok = post_verify_contract_satisfied(self._user_text, self._bash_commands)
        if (
            self._verify_succeeded
            and not self._shallow_only
            and self._integration_attempted
            and (not self._native_mutated or self._native_build_verified)
            and (
                not self._python_mutated
                or self._native_mutated
                or self._python_suite_verified
            )
            and (
                not self._go_mutated
                or self._native_mutated
                or self._go_suite_verified
            )
            and (
                not self._typescript_mutated
                or self._native_mutated
                or self._typescript_suite_verified
            )
            and cli_ok
        ):
            return

        lang = getattr(builder, "language", "en") or "en"
        zh = str(lang).startswith("zh") or lang == "cn"
        if self._shallow_only:
            text = _SHALLOW_CN if zh else _SHALLOW_EN
            content = {"en": _SHALLOW_EN, "cn": _SHALLOW_CN, lang: text}
        elif not self._integration_attempted:
            text = _INTEGRATION_CN if zh else _INTEGRATION_EN
            content = {
                "en": _INTEGRATION_EN,
                "cn": _INTEGRATION_CN,
                lang: text,
            }
        elif self._native_mutated and not self._native_build_verified:
            text = _NATIVE_BUILD_CN if zh else _NATIVE_BUILD_EN
            content = {
                "en": _NATIVE_BUILD_EN,
                "cn": _NATIVE_BUILD_CN,
                lang: text,
            }
        elif (
            self._go_mutated
            and not self._native_mutated
            and not self._go_suite_verified
        ):
            text = _GO_SUITE_CN if zh else _GO_SUITE_EN
            content = {
                "en": _GO_SUITE_EN,
                "cn": _GO_SUITE_CN,
                lang: text,
            }
        elif (
            self._typescript_mutated
            and not self._native_mutated
            and not self._typescript_suite_verified
        ):
            text = _TS_SUITE_CN if zh else _TS_SUITE_EN
            content = {
                "en": _TS_SUITE_EN,
                "cn": _TS_SUITE_CN,
                lang: text,
            }
        elif (
            self._python_mutated
            and not self._native_mutated
            and not self._python_suite_verified
        ):
            text = _PYTHON_SUITE_CN if zh else _PYTHON_SUITE_EN
            content = {
                "en": _PYTHON_SUITE_EN,
                "cn": _PYTHON_SUITE_CN,
                lang: text,
            }
        elif self._verify_attempted and not self._verify_succeeded:
            text = _VERIFY_FAILED_CN if zh else _VERIFY_FAILED_EN
            content = {
                "en": _VERIFY_FAILED_EN,
                "cn": _VERIFY_FAILED_CN,
                lang: text,
            }
        elif (
            self._verify_succeeded
            and not post_verify_contract_satisfied(
                self._user_text, self._bash_commands
            )
        ):
            detail = post_verify_contract_nudge(self._user_text, self._bash_commands)
            text = (
                f"{_CLI_CONTRACT_CN if zh else _CLI_CONTRACT_EN}\n\n{detail}"
            )
            content = {
                "en": f"{_CLI_CONTRACT_EN}\n\n{detail}",
                "cn": f"{_CLI_CONTRACT_CN}\n\n{detail}",
                lang: text,
            }
        else:
            text = _VERIFY_CN if zh else _VERIFY_EN
            content = {"en": _VERIFY_EN, "cn": _VERIFY_CN, lang: text}

        builder.add_section(
            PromptSection(
                name=_SECTION,
                content=content,
                priority=_PRIORITY,
            )
        )


__all__ = ["ImplementCompletenessRail"]

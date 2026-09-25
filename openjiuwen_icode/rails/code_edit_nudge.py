# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Nudge coding agents to edit after a budget of explore-only tool calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openjiuwen.core.single_agent.prompts.builder import PromptSection
from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.harness.rails.base import DeepAgentRail

from openjiuwen_icode.features.implement_gate import (
    CONTINUATION_EXPLORE_ABORT_CAP,
    CONTINUATION_MODEL_ABORT_CAP,
    POST_MUTATION_EXPLORE_ABORT_CAP,
    POST_MUTATION_MODEL_ABORT_CAP,
    bash_result_succeeded,
    extract_bash_command,
    looks_like_explore_bash,
    looks_like_greeting_response,
    looks_like_implement_task,
    looks_like_verify_command,
    primary_user_task_text,
)
from openjiuwen_icode.features.mutations import (
    MUTATING_TOOLS,
    mutation_path_from_args,
    mutating_tool_applied,
    path_under_workspace,
    tool_result_payload,
)

_EXPLORE_TOOLS = frozenset(
    {
        "grep",
        "read_file",
        "glob",
        "list_dir",
        "list_files",
        "todo_create",
        "todo_list",
        "todo_get",
        "todo_modify",
        "memory_search",
    }
)

_SECTION = "code_edit_nudge"
_NO_GREETING_SECTION = "code_no_greeting"
_PRIORITY = 96
_NO_GREETING_PRIORITY = 95

_NUDGE_EN = (
    "## Edit-now reminder\n"
    "You have spent many tool rounds exploring without calling "
    "`edit_file` / `write_file`. The user asked for code changes. "
    "On this turn, stop searching and apply a concrete patch with "
    "`edit_file` or `write_file`. Prefer a small working change over "
    "more analysis."
)

_NUDGE_CN = (
    "## 立即改代码提醒\n"
    "你已连续多轮只做探索（读/搜），尚未调用 `edit_file` / `write_file`。"
    "用户要求修改代码。本轮请停止继续搜索，立刻用 `edit_file` 或 "
    "`write_file` 落一个小而可运行的补丁，而不是继续分析。"
)

_VERIFY_NUDGE_EN = (
    "## Verify-now reminder\n"
    "You already edited the worktree. Stop `git log` / `list_files` / "
    "more archaeology. Call `bash` with this repo's real tests "
    "(`npm test` / `npx jest` / `pytest` / `go test`) now."
)

_VERIFY_NUDGE_CN = (
    "## 立即验证提醒\n"
    "你已经改过工作区。停止 `git log` / `list_files` / 继续考古。"
    "立刻用 `bash` 跑仓库真正的测试（`npm test` / `npx jest` / "
    "`pytest` / `go test`）。"
)

_POST_VERIFY_NUDGE_EN = (
    "## Post-verification discipline\n"
    "A verification command already passed for the current worktree. Do not "
    "rerun the same unchanged command. Ensure the repo's real suite has run, "
    "then use remaining checks on requirement-derived edge cases or finish. "
    "Make manual/live probes executable with `assert`, `diff`, or an exact "
    "exit check so wrong output fails the command; visual inspection alone is "
    "not verification. If a probe exposes a mismatch, edit it, add a "
    "regression test, then rerun the targeted and full suites."
)

_POST_VERIFY_NUDGE_CN = (
    "## 验证通过后的检查纪律\n"
    "当前工作区已经通过一个验证命令。不要在没有改动时重复运行同一命令；"
    "确认仓库真实测试套件已经运行，再把剩余检查用于从需求推导出的边界情况，"
    "或直接结束。手工/live 探针必须用 `assert`、`diff` 或精确退出码把预期"
    "变成可执行检查，让错误输出导致命令失败；只目视输出不算验证。若探针发现"
    "不一致，先修复并添加回归测试，再运行相关测试和全量套件。"
)

_NO_GREETING_EN = (
    "## Do not greet on implement tasks\n"
    "The user already gave a concrete coding task (including any Interface / "
    "Configuration / Expected behavior / Execution rules sections). Those "
    "sections are part of the task — not system setup. Do NOT claim the "
    "message is only guidelines, introduce yourself, list capabilities, or "
    "ask what to work on. Your first action must be a tool call "
    "(`list_files` / `grep` / `read_file` / `edit_file` / `write_file`)."
)

_NO_GREETING_CN = (
    "## 实现任务禁止寒暄\n"
    "用户已经给出具体编码任务（含 Interface / Configuration / Expected "
    "behavior / Execution rules 等小节）。这些是题面的一部分，不是系统配置。"
    "不要声称消息只是 guidelines、不要自我介绍/罗列能力，或反问要做什么。"
    "第一步必须调用工具（`list_files` / `grep` / `read_file` / "
    "`edit_file` / `write_file`）。"
)


def _agent_workspace(agent: Any) -> Path | None:
    """Best-effort session workspace root from the mounted agent."""
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


def _iter_code_edit_rails(agent: Any) -> list["CodeEditNudgeRail"]:
    """Return CodeEditNudgeRail instances mounted on *agent*."""
    if agent is None:
        return []
    rails = getattr(agent, "rails", None)
    if rails is None:
        deep = getattr(agent, "deep_config", None)
        rails = getattr(deep, "rails", None) if deep else None
    if not rails:
        return []
    return [rail for rail in rails if isinstance(rail, CodeEditNudgeRail)]


def reset_stream_rails(agent: Any) -> None:
    """Reset per-stream explore counters on coding rails."""
    for rail in _iter_code_edit_rails(agent):
        rail.reset_stream_state()


def tighten_edit_rails_for_continuation(
    agent: Any,
    *,
    verify_only: bool = False,
) -> None:
    """Use a short explore budget on SessionHost continuation streams.

    After explore-without-edit the agent must patch immediately. After a
    workspace mutation without verify, force verify-only (almost no explore).
    """
    for rail in _iter_code_edit_rails(agent):
        rail.explore_budget = 0
        if verify_only or rail._workspace_mutated:
            rail.explore_abort_cap = POST_MUTATION_EXPLORE_ABORT_CAP
            rail.model_abort_cap = POST_MUTATION_MODEL_ABORT_CAP
        else:
            rail.explore_abort_cap = CONTINUATION_EXPLORE_ABORT_CAP
            rail.model_abort_cap = CONTINUATION_MODEL_ABORT_CAP
        rail.reset_stream_state()


class CodeEditNudgeRail(DeepAgentRail):
    """Inject an edit reminder after *explore_budget* explore-only tools."""

    priority = 85

    def __init__(
        self,
        explore_budget: int = 8,
        *,
        explore_abort_cap: int | None = None,
        model_abort_cap: int | None = None,
        post_mutation_explore_abort_cap: int | None = None,
        post_mutation_model_abort_cap: int | None = None,
    ) -> None:
        super().__init__()
        self.explore_budget = max(1, int(explore_budget))
        # Default abort cap is intentionally higher than the nudge budget so
        # TypeScript/Python repos can be oriented (list/read a dozen files)
        # before a hard stop. Hard abort is recovered by SessionHost as an
        # empty-worktree continuation — not TurnFailed.
        cap = explore_abort_cap
        if cap is not None:
            self.explore_abort_cap = max(1, int(cap))
        else:
            self.explore_abort_cap = max(
                self.explore_budget + 1,
                24,
            )
        if model_abort_cap is not None:
            self.model_abort_cap = max(1, int(model_abort_cap))
        else:
            self.model_abort_cap = max(
                self.explore_budget + 1,
                16,
            )
        self.post_mutation_explore_abort_cap = max(
            1,
            int(
                post_mutation_explore_abort_cap
                if post_mutation_explore_abort_cap is not None
                else POST_MUTATION_EXPLORE_ABORT_CAP
            ),
        )
        self.post_mutation_model_abort_cap = max(
            1,
            int(
                post_mutation_model_abort_cap
                if post_mutation_model_abort_cap is not None
                else POST_MUTATION_MODEL_ABORT_CAP
            ),
        )
        self._explore_count = 0
        self._workspace_mutated = False
        self._verify_succeeded = False
        self._model_rounds = 0
        self._aborted_for_explore = False
        self._user_text = ""
        self.system_prompt_builder = None
        self._agent: Any = None

    def init(self, agent: Any) -> None:
        self._agent = agent
        self.system_prompt_builder = getattr(
            agent, "system_prompt_builder", None
        )
        # Reset per agent construction (one turn / session factory).
        self._explore_count = 0
        self._workspace_mutated = False
        self._verify_succeeded = False
        self._model_rounds = 0
        self._aborted_for_explore = False
        self._user_text = ""

    def reset_stream_state(self) -> None:
        """Fresh explore/abort budget for each inner ReAct stream."""
        self._explore_count = 0
        self._model_rounds = 0
        self._aborted_for_explore = False

    def _ensure_user_text(self, ctx: AgentCallbackContext) -> None:
        if self._user_text:
            return
        text = primary_user_task_text(ctx)
        if text:
            self._user_text = text

    def _active_explore_cap(self) -> int:
        if self._workspace_mutated and not self._verify_succeeded:
            return min(
                self.explore_abort_cap, self.post_mutation_explore_abort_cap
            )
        return self.explore_abort_cap

    def _active_model_cap(self) -> int:
        if self._workspace_mutated and not self._verify_succeeded:
            return min(self.model_abort_cap, self.post_mutation_model_abort_cap)
        return self.model_abort_cap

    async def _abort_stall(self, ctx: AgentCallbackContext) -> None:
        """Soft-abort stalled implement streams so SessionHost can continue."""
        if self._aborted_for_explore or self._verify_succeeded:
            return
        self._ensure_user_text(ctx)
        if not looks_like_implement_task(self._user_text):
            return
        agent = self._agent
        abort = getattr(agent, "abort", None) if agent is not None else None
        if not callable(abort):
            return
        self._aborted_for_explore = True
        await abort()

    async def _maybe_abort_explore_only(self, ctx: AgentCallbackContext) -> None:
        if self._aborted_for_explore or self._verify_succeeded:
            return
        if (
            self._explore_count < self._active_explore_cap()
            and self._model_rounds < self._active_model_cap()
        ):
            return
        await self._abort_stall(ctx)

    async def _count_explore(self, ctx: AgentCallbackContext) -> None:
        self._explore_count += 1
        await self._maybe_abort_explore_only(ctx)

    def _inject_no_greeting(self, builder: Any) -> None:
        remove = getattr(builder, "remove_section", None)
        if callable(remove):
            remove(_NO_GREETING_SECTION)
        lang = getattr(builder, "language", "en") or "en"
        text = (
            _NO_GREETING_CN
            if str(lang).startswith("zh") or lang == "cn"
            else _NO_GREETING_EN
        )
        builder.add_section(
            PromptSection(
                name=_NO_GREETING_SECTION,
                content={
                    "en": _NO_GREETING_EN,
                    "cn": _NO_GREETING_CN,
                    lang: text,
                },
                priority=_NO_GREETING_PRIORITY,
            )
        )

    async def after_tool_call(self, ctx: AgentCallbackContext) -> None:
        self._ensure_user_text(ctx)
        inputs = ctx.inputs
        name = str(getattr(inputs, "tool_name", "") or "")
        if not name:
            return
        if name in MUTATING_TOOLS:
            tool_result = getattr(inputs, "tool_result", None)
            if tool_result is not None:
                result_payload, tool_success = tool_result_payload(tool_result)
                if mutating_tool_applied(
                    name, result_payload, tool_success=tool_success
                ):
                    ws = _agent_workspace(self._agent)
                    path = mutation_path_from_args(getattr(inputs, "tool_args", None))
                    if ws is not None and path and not path_under_workspace(path, ws):
                        await self._count_explore(ctx)
                        return
                    # Successful in-workspace edit: start a short post-mutation
                    # explore budget so git-log loops still soft-abort.
                    self._workspace_mutated = True
                    self._verify_succeeded = False
                    self._explore_count = 0
                    self._aborted_for_explore = False
                    return
                await self._count_explore(ctx)
            return
        if name in _EXPLORE_TOOLS:
            await self._count_explore(ctx)
            return
        if name == "bash":
            cmd = extract_bash_command(getattr(inputs, "tool_args", None))
            tool_result = getattr(inputs, "tool_result", None)
            # Before the first edit, even "verify-looking" bash is explore
            # (npm test / go test loops without a patch). After mutation,
            # successful verify clears the stall; failed verify is not explore.
            if self._workspace_mutated and looks_like_verify_command(cmd):
                result_payload, parsed_success = tool_result_payload(tool_result)
                tool_success = getattr(inputs, "tool_success", None)
                if tool_success is None:
                    tool_success = parsed_success
                ok = bash_result_succeeded(
                    result_payload,
                    tool_success=tool_success,
                )
                # Track the latest verify result, not whether any earlier
                # command happened to pass. A later failing broad suite must
                # re-enable the text-only soft abort so SessionHost can issue
                # its verify-failed continuation instead of accepting "done".
                self._verify_succeeded = ok is True
                return
            if not self._workspace_mutated or looks_like_explore_bash(cmd):
                await self._count_explore(ctx)

    async def before_model_call(self, ctx: AgentCallbackContext) -> None:
        self._model_rounds += 1
        self._ensure_user_text(ctx)
        if (
            not self._verify_succeeded
            and looks_like_implement_task(self._user_text)
            and self._model_rounds >= self._active_model_cap()
        ):
            await self._maybe_abort_explore_only(ctx)

        builder = self.system_prompt_builder
        if builder is None:
            return

        # On implement tasks, always forbid greeting until a workspace edit.
        if (
            not self._workspace_mutated
            and looks_like_implement_task(self._user_text)
        ):
            self._inject_no_greeting(builder)
        else:
            remove = getattr(builder, "remove_section", None)
            if callable(remove):
                remove(_NO_GREETING_SECTION)

        remove = getattr(builder, "remove_section", None)
        if callable(remove):
            remove(_SECTION)

        lang = getattr(builder, "language", "en") or "en"
        if self._verify_succeeded:
            text = (
                _POST_VERIFY_NUDGE_CN
                if str(lang).startswith("zh") or lang == "cn"
                else _POST_VERIFY_NUDGE_EN
            )
            builder.add_section(
                PromptSection(
                    name=_SECTION,
                    content={
                        "en": _POST_VERIFY_NUDGE_EN,
                        "cn": _POST_VERIFY_NUDGE_CN,
                        lang: text,
                    },
                    priority=_PRIORITY,
                )
            )
            return

        if self._workspace_mutated:
            if self._explore_count < 1:
                return
            text = (
                _VERIFY_NUDGE_CN
                if str(lang).startswith("zh") or lang == "cn"
                else _VERIFY_NUDGE_EN
            )
            builder.add_section(
                PromptSection(
                    name=_SECTION,
                    content={
                        "en": _VERIFY_NUDGE_EN,
                        "cn": _VERIFY_NUDGE_CN,
                        lang: text,
                    },
                    priority=_PRIORITY,
                )
            )
            return

        if self._explore_count < self.explore_budget:
            return

        text = _NUDGE_CN if str(lang).startswith("zh") or lang == "cn" else _NUDGE_EN
        builder.add_section(
            PromptSection(
                name=_SECTION,
                content={"en": _NUDGE_EN, "cn": _NUDGE_CN, lang: text},
                priority=_PRIORITY,
            )
        )

    @staticmethod
    def _response_has_tool_calls(ctx: AgentCallbackContext) -> bool:
        """Return True when the latest model response requested tool calls."""
        inputs = getattr(ctx, "inputs", None)
        response = getattr(inputs, "response", None) if inputs is not None else None
        if response is None:
            return False
        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            return True
        # Dict-shaped responses / OpenAI-compatible payloads.
        if isinstance(response, dict):
            if response.get("tool_calls"):
                return True
            msg = response.get("message") or response.get("choices")
            if isinstance(msg, dict) and msg.get("tool_calls"):
                return True
        return False

    @staticmethod
    def _response_text(ctx: AgentCallbackContext) -> str:
        """Best-effort assistant text from the latest model response."""
        inputs = getattr(ctx, "inputs", None)
        response = getattr(inputs, "response", None) if inputs is not None else None
        if response is None:
            return ""
        content = getattr(response, "content", None)
        if content:
            return str(content)
        if isinstance(response, dict):
            return str(response.get("content") or "")
        return ""

    async def after_model_call(self, ctx: AgentCallbackContext) -> None:
        """Soft-abort implement streams that stall without editing/verifying.

        ``after_model_call`` runs *before* tool execution, so we inspect the
        model response for tool_calls rather than post-hoc tool counters.
        """
        self._ensure_user_text(ctx)
        if self._aborted_for_explore or self._verify_succeeded:
            return
        if not looks_like_implement_task(self._user_text):
            return
        if self._response_has_tool_calls(ctx):
            return

        text = self._response_text(ctx)
        if self._workspace_mutated:
            # Post-edit text-only (git essays / greetings) → force verify continue.
            await self._abort_stall(ctx)
            return

        if self._explore_count == 0:
            await self._abort_stall(ctx)
            return
        if looks_like_greeting_response(text):
            await self._abort_stall(ctx)
            return
        if self._explore_count >= self.explore_budget:
            await self._abort_stall(ctx)


__all__ = [
    "CodeEditNudgeRail",
    "reset_stream_rails",
    "tighten_edit_rails_for_continuation",
]

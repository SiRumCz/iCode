# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Nudge coding agents to edit after a budget of explore-only tool calls."""

from __future__ import annotations

from typing import Any

from openjiuwen.core.single_agent.prompts.builder import PromptSection
from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.harness.rails.base import DeepAgentRail

from openjiuwen_icode.features.implement_gate import (
    extract_bash_command,
    looks_like_explore_bash,
    looks_like_implement_task,
    primary_user_task_text,
)
from openjiuwen_icode.features.mutations import (
    MUTATING_TOOLS,
    mutating_tool_applied,
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
    }
)

_SECTION = "code_edit_nudge"
_PRIORITY = 96

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


def reset_stream_rails(agent: Any) -> None:
    """Reset per-stream explore counters on coding rails."""
    if agent is None:
        return
    rails = getattr(agent, "rails", None)
    if rails is None:
        deep = getattr(agent, "deep_config", None)
        rails = getattr(deep, "rails", None) if deep else None
    if not rails:
        return
    for rail in rails:
        reset = getattr(rail, "reset_stream_state", None)
        if callable(reset):
            reset()


class CodeEditNudgeRail(DeepAgentRail):
    """Inject an edit reminder after *explore_budget* explore-only tools."""

    priority = 85

    def __init__(
        self,
        explore_budget: int = 3,
        *,
        explore_abort_cap: int | None = None,
        model_abort_cap: int | None = None,
    ) -> None:
        super().__init__()
        self.explore_budget = max(1, int(explore_budget))
        cap = explore_abort_cap
        self.explore_abort_cap = max(
            self.explore_budget + 1,
            int(cap if cap is not None else self.explore_budget * 4),
        )
        self.model_abort_cap = max(
            self.explore_budget + 1,
            int(model_abort_cap if model_abort_cap is not None else 18),
        )
        self._explore_count = 0
        self._workspace_mutated = False
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

    async def _maybe_abort_explore_only(self, ctx: AgentCallbackContext) -> None:
        if (
            self._workspace_mutated
            or self._aborted_for_explore
            or (
                self._explore_count < self.explore_abort_cap
                and self._model_rounds < self.model_abort_cap
            )
        ):
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

    async def _count_explore(self, ctx: AgentCallbackContext) -> None:
        self._explore_count += 1
        await self._maybe_abort_explore_only(ctx)

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
                    self._workspace_mutated = True
                    return
                await self._count_explore(ctx)
            return
        if name in _EXPLORE_TOOLS:
            await self._count_explore(ctx)
            return
        if name == "bash":
            cmd = extract_bash_command(getattr(inputs, "tool_args", None))
            if not self._workspace_mutated or looks_like_explore_bash(cmd):
                await self._count_explore(ctx)

    async def before_model_call(self, ctx: AgentCallbackContext) -> None:
        self._model_rounds += 1
        self._ensure_user_text(ctx)
        if (
            not self._workspace_mutated
            and looks_like_implement_task(self._user_text)
            and self._model_rounds >= self.model_abort_cap
        ):
            await self._maybe_abort_explore_only(ctx)

        builder = self.system_prompt_builder
        if builder is None:
            return
        remove = getattr(builder, "remove_section", None)
        if callable(remove):
            remove(_SECTION)

        if self._workspace_mutated or self._explore_count < self.explore_budget:
            return

        lang = getattr(builder, "language", "en") or "en"
        text = _NUDGE_CN if str(lang).startswith("zh") or lang == "cn" else _NUDGE_EN
        builder.add_section(
            PromptSection(
                name=_SECTION,
                content={"en": _NUDGE_EN, "cn": _NUDGE_CN, lang: text},
                priority=_PRIORITY,
            )
        )


__all__ = ["CodeEditNudgeRail", "reset_stream_rails"]

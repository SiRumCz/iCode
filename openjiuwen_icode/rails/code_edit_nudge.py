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
)
from openjiuwen_icode.features.mutations import MUTATING_TOOLS

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


class CodeEditNudgeRail(DeepAgentRail):
    """Inject an edit reminder after *explore_budget* explore-only tools."""

    priority = 85

    def __init__(self, explore_budget: int = 5) -> None:
        super().__init__()
        self.explore_budget = max(1, int(explore_budget))
        self._explore_count = 0
        self._mutated = False
        self.system_prompt_builder = None
        self._agent: Any = None

    def init(self, agent: Any) -> None:
        self._agent = agent
        self.system_prompt_builder = getattr(
            agent, "system_prompt_builder", None
        )
        # Reset per agent construction (one turn / session factory).
        self._explore_count = 0
        self._mutated = False

    async def after_tool_call(self, ctx: AgentCallbackContext) -> None:
        inputs = ctx.inputs
        name = str(getattr(inputs, "tool_name", "") or "")
        if not name:
            return
        if name in MUTATING_TOOLS:
            self._mutated = True
            return
        if name in _EXPLORE_TOOLS:
            self._explore_count += 1
            return
        # Read-only bash (git archaeology, go test/build, grep/cat) burns the
        # explore budget too — common failure mode on pruned eval checkouts.
        if name == "bash":
            cmd = extract_bash_command(getattr(inputs, "tool_args", None))
            if looks_like_explore_bash(cmd):
                self._explore_count += 1

    async def before_model_call(self, ctx: AgentCallbackContext) -> None:
        builder = self.system_prompt_builder
        if builder is None:
            return
        remove = getattr(builder, "remove_section", None)
        if callable(remove):
            remove(_SECTION)

        if self._mutated or self._explore_count < self.explore_budget:
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


__all__ = ["CodeEditNudgeRail"]

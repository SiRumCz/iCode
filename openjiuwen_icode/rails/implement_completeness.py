# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Nudge coding agents after shallow edits or missing verify/submit steps."""

from __future__ import annotations

from typing import Any

from openjiuwen.core.single_agent.prompts.builder import PromptSection
from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.harness.rails.base import DeepAgentRail

from openjiuwen_icode.features.implement_gate import (
    edit_args_look_shallow,
    extract_bash_command,
    looks_like_submit_command,
    looks_like_verify_command,
)
from openjiuwen_icode.features.mutations import MUTATING_TOOLS

_SECTION = "implement_completeness"
_PRIORITY = 97

_SHALLOW_EN = (
    "## Incomplete edit reminder\n"
    "Recent edits look signature/docs-only (type swaps without parsers, "
    "validation, or apply/resolve wiring). Keep implementing the full "
    "behavior, then verify with `bash` (`cargo check` / targeted tests)."
)

_SHALLOW_CN = (
    "## 改动不完整提醒\n"
    "最近的编辑看起来只改了类型签名/文档（例如 Option→Vec，但没有 parser、"
    "校验或 apply/resolve）。请继续实现完整行为，并用 `bash` 做编译/"
    "针对性测试验证（Rust 可用 `cargo check`）。"
)

_VERIFY_EN = (
    "## Verify reminder\n"
    "You already modified files. Before finishing, run a compile or "
    "targeted test via `bash`. Fix failures. If the user named a submit "
    "command (e.g. `lolbench-submit`), run it after verification."
)

_VERIFY_CN = (
    "## 验证提醒\n"
    "你已修改文件。结束前请用 `bash` 跑编译或针对性测试，并根据报错继续修。"
    "若用户要求提交命令（例如 `lolbench-submit`），验证通过后再执行。"
)


class ImplementCompletenessRail(DeepAgentRail):
    """Inject shallow-edit / verify reminders mid-turn after mutations."""

    priority = 86

    def __init__(self) -> None:
        super().__init__()
        self._mutated = False
        self._shallow_only = True
        self._verify_attempted = False
        self._submit_attempted = False
        self.system_prompt_builder = None
        self._agent: Any = None

    def init(self, agent: Any) -> None:
        self._agent = agent
        self.system_prompt_builder = getattr(
            agent, "system_prompt_builder", None
        )
        self._mutated = False
        self._shallow_only = True
        self._verify_attempted = False
        self._submit_attempted = False

    async def after_tool_call(self, ctx: AgentCallbackContext) -> None:
        inputs = ctx.inputs
        name = str(getattr(inputs, "tool_name", "") or "")
        args = getattr(inputs, "tool_args", None)
        if not name:
            return
        if name in MUTATING_TOOLS:
            self._mutated = True
            if not edit_args_look_shallow(args):
                self._shallow_only = False
            return
        if name == "bash":
            cmd = extract_bash_command(args)
            if looks_like_verify_command(cmd):
                self._verify_attempted = True
            if looks_like_submit_command(cmd):
                self._submit_attempted = True

    async def before_model_call(self, ctx: AgentCallbackContext) -> None:
        builder = self.system_prompt_builder
        if builder is None:
            return
        remove = getattr(builder, "remove_section", None)
        if callable(remove):
            remove(_SECTION)

        if not self._mutated:
            return
        if self._verify_attempted and not self._shallow_only:
            return

        lang = getattr(builder, "language", "en") or "en"
        zh = str(lang).startswith("zh") or lang == "cn"
        if self._shallow_only:
            text = _SHALLOW_CN if zh else _SHALLOW_EN
            content = {"en": _SHALLOW_EN, "cn": _SHALLOW_CN, lang: text}
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

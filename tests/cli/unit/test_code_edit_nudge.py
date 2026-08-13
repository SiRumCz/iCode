# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for CodeEditNudgeRail."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjiuwen_icode.rails.code_edit_nudge import CodeEditNudgeRail


class _FakeBuilder:
    def __init__(self) -> None:
        self.language = "en"
        self.sections: list[str] = []

    def remove_section(self, name: str) -> None:
        self.sections = [s for s in self.sections if s != name]

    def add_section(self, section: object) -> None:
        name = getattr(section, "name", "")
        self.sections.append(str(name))


@pytest.mark.asyncio
async def test_nudge_injects_after_explore_budget() -> None:
    rail = CodeEditNudgeRail(explore_budget=3)
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    for name in ("grep", "read_file", "glob"):
        ctx = SimpleNamespace(
            inputs=SimpleNamespace(tool_name=name, tool_args={})
        )
        await rail.after_tool_call(ctx)

    await rail.before_model_call(MagicMock())
    assert "code_edit_nudge" in builder.sections


@pytest.mark.asyncio
async def test_nudge_cleared_after_mutation() -> None:
    rail = CodeEditNudgeRail(explore_budget=2)
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(inputs=SimpleNamespace(tool_name="grep"))
    )
    await rail.after_tool_call(
        SimpleNamespace(inputs=SimpleNamespace(tool_name="grep"))
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(tool_name="edit_file", tool_args={})
        )
    )
    await rail.before_model_call(MagicMock())
    assert "code_edit_nudge" not in builder.sections

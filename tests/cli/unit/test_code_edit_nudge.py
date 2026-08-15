# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for CodeEditNudgeRail."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from openjiuwen_icode.rails.code_edit_nudge import (
    CodeEditNudgeRail,
    tighten_edit_rails_for_continuation,
)


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
async def test_nudge_counts_npm_test_bash() -> None:
    rail = CodeEditNudgeRail(explore_budget=2)
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    for cmd in ("npm test", "grep -R initializer src/"):
        await rail.after_tool_call(
            SimpleNamespace(
                inputs=SimpleNamespace(
                    tool_name="bash",
                    tool_args={"command": cmd},
                )
            )
        )
    await rail.before_model_call(MagicMock())
    assert "code_edit_nudge" in builder.sections


@pytest.mark.asyncio
async def test_nudge_counts_go_test_bash() -> None:
    rail = CodeEditNudgeRail(explore_budget=2)
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    for cmd in ("go test ./... -count=1", "grep -R default parser/"):
        await rail.after_tool_call(
            SimpleNamespace(
                inputs=SimpleNamespace(
                    tool_name="bash",
                    tool_args={"command": cmd},
                )
            )
        )
    await rail.before_model_call(MagicMock())
    assert "code_edit_nudge" in builder.sections


@pytest.mark.asyncio
async def test_nudge_counts_git_archaeology_bash() -> None:
    rail = CodeEditNudgeRail(explore_budget=2)
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    for _ in range(2):
        await rail.after_tool_call(
            SimpleNamespace(
                inputs=SimpleNamespace(
                    tool_name="bash",
                    tool_args={
                        "command": "git log --all --oneline | head -20"
                    },
                )
            )
        )
    await rail.before_model_call(MagicMock())
    assert "code_edit_nudge" in builder.sections


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
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={},
                tool_result=SimpleNamespace(
                    success=True,
                    content="Applied patch to parser.go",
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "code_edit_nudge" not in builder.sections


@pytest.mark.asyncio
async def test_abort_after_explore_cap_on_implement_task() -> None:
    rail = CodeEditNudgeRail(explore_budget=2, explore_abort_cap=4)
    agent = MagicMock()
    agent.abort = AsyncMock()
    rail.init(agent)
    ctx = SimpleNamespace(
        inputs=SimpleNamespace(
            tool_name="grep",
            tool_args={},
            messages=[
                SimpleNamespace(
                    role="user",
                    content="Implement typed variable bindings in parser/vm",
                )
            ],
        )
    )
    for _ in range(4):
        await rail.after_tool_call(ctx)
    agent.abort.assert_called_once()


@pytest.mark.asyncio
async def test_failed_edit_still_counts_as_explore() -> None:
    rail = CodeEditNudgeRail(explore_budget=2, explore_abort_cap=3)
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={"path": "missing.go"},
                tool_result=SimpleNamespace(
                    success=False,
                    content="old_string not found in file",
                ),
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(inputs=SimpleNamespace(tool_name="grep"))
    )
    await rail.before_model_call(MagicMock())
    assert "code_edit_nudge" in builder.sections


@pytest.mark.asyncio
async def test_reset_stream_state_fresh_abort_budget() -> None:
    rail = CodeEditNudgeRail(explore_budget=2, explore_abort_cap=3)
    agent = MagicMock()
    agent.abort = AsyncMock()
    rail.init(agent)
    rail._model_rounds = 18
    rail._explore_count = 10
    rail._aborted_for_explore = True
    rail.reset_stream_state()
    assert rail._model_rounds == 0
    assert rail._explore_count == 0
    assert rail._aborted_for_explore is False


@pytest.mark.asyncio
async def test_all_bash_counts_as_explore_before_mutation() -> None:
    rail = CodeEditNudgeRail(explore_budget=2)
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    for cmd in ("make -j2", "go run ./cmd"):
        await rail.after_tool_call(
            SimpleNamespace(
                inputs=SimpleNamespace(
                    tool_name="bash",
                    tool_args={"command": cmd},
                )
            )
        )
    await rail.before_model_call(MagicMock())
    assert "code_edit_nudge" in builder.sections


def test_tighten_edit_rails_for_continuation() -> None:
    rail = CodeEditNudgeRail(explore_budget=3, explore_abort_cap=12)
    agent = MagicMock()
    agent.rails = [rail]
    rail._explore_count = 9
    tighten_edit_rails_for_continuation(agent)
    assert rail.explore_budget == 1
    assert rail.explore_abort_cap <= 5
    assert rail._explore_count == 0

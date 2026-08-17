# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for ImplementCompletenessRail."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjiuwen_icode.rails.implement_completeness import (
    ImplementCompletenessRail,
)


class _FakeBuilder:
    def __init__(self) -> None:
        self.language = "en"
        self.sections: list[str] = []
        self.last_content: dict[str, str] | None = None

    def remove_section(self, name: str) -> None:
        self.sections = [s for s in self.sections if s != name]

    def add_section(self, section: object) -> None:
        name = getattr(section, "name", "")
        self.sections.append(str(name))
        content = getattr(section, "content", None)
        if isinstance(content, dict):
            self.last_content = {
                str(k): str(v) for k, v in content.items()
            }


@pytest.mark.asyncio
async def test_shallow_edit_injects_completeness_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "old_string": "    pub config: Option<PathBuf>,\n",
                    "new_string": "    pub config: Vec<String>,\n",
                },
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections


@pytest.mark.asyncio
async def test_verify_clears_nudge_after_real_edit() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "old_string": "x",
                    "new_string": (
                        "fn parse_ref(value: &str) -> Result<()> {\n"
                        "    if value.contains('=') {\n"
                        "        return Ok(());\n"
                        "    }\n"
                        "    Err(anyhow::anyhow!(\"bad\"))\n"
                        "}\n"
                    ),
                },
                tool_result=None,
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "cargo check -p ruff"},
                tool_result=SimpleNamespace(
                    success=True,
                    data=(
                        "Command: cargo check -p ruff\n"
                        "Stdout: ok\nExit Code: 0"
                    ),
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" not in builder.sections


@pytest.mark.asyncio
async def test_failed_verify_keeps_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="write_file",
                tool_args={
                    "file_path": "/tmp/x.rs",
                    "content": "fn main() {}\n",
                },
                tool_result=None,
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "CCACHE_DISABLE=1 make -j2 python"},
                tool_result=SimpleNamespace(
                    success=False,
                    data=(
                        "Command: CCACHE_DISABLE=1 make -j2 python\n"
                        "Stdout: gcc error\nExit Code: 2"
                    ),
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections


@pytest.mark.asyncio
async def test_write_only_keeps_integration_nudge_even_after_verify() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="write_file",
                tool_args={
                    "file_path": "/tmp/modules.go",
                    "content": "package evaluator\nfunc helper() {}\n",
                },
                tool_result=None,
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "go build ./..."},
                tool_result=SimpleNamespace(
                    success=True,
                    data="Command: go build ./...\nExit Code: 0",
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections


@pytest.mark.asyncio
async def test_python_edit_requires_pytest_before_clearing_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "aiomonitor/monitor.py",
                    "old_string": "old",
                    "new_string": "new helper logic\n",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "python -m compileall aiomonitor"},
                tool_result=SimpleNamespace(
                    success=True,
                    data=(
                        "Command: python -m compileall aiomonitor\n"
                        "Exit Code: 0"
                    ),
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections


@pytest.mark.asyncio
async def test_python_pytest_clears_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder
    task = (
        "Add snapshot support with capture_snapshot. "
        "Snapshots snapshots snapshots."
    )
    rail._user_text = task

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "aiomonitor/monitor.py",
                    "old_string": "old",
                    "new_string": "new helper logic\n",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "pytest -q tests/test_snapshot.py"},
                tool_result=SimpleNamespace(
                    success=True,
                    data=(
                        "Command: pytest -q tests/test_snapshot.py\n"
                        "Exit Code: 0"
                    ),
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" not in builder.sections


@pytest.mark.asyncio
async def test_unrelated_pytest_keeps_python_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder
    task = (
        "Add snapshot support with capture_snapshot. "
        "Snapshots snapshots snapshots."
    )
    rail._user_text = task

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "aiomonitor/monitor.py",
                    "old_string": "old",
                    "new_string": "new helper logic\n",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "pytest -q tests/test_monitor.py"},
                tool_result=SimpleNamespace(
                    success=True,
                    data=(
                        "Command: pytest -q tests/test_monitor.py\n"
                        "Exit Code: 0"
                    ),
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections
    text = (builder.last_content or {}).get("en", "")
    assert "test_<feature>.py" in text or "test_<feature>" in text
    assert "compile errors" not in text.lower()


@pytest.mark.asyncio
async def test_native_edit_requires_build_before_clearing_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "Objects/typevarobject.c",
                    "old_string": "old_fn();",
                    "new_string": "new_fn();",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "./python -m test test_typing"},
                tool_result=SimpleNamespace(success=True),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections


@pytest.mark.asyncio
async def test_native_build_clears_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "Objects/typevarobject.c",
                    "old_string": "old_fn();",
                    "new_string": "new_fn();",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "make -j2 Objects/typevarobject.o"},
                tool_result=SimpleNamespace(success=True),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" not in builder.sections


@pytest.mark.asyncio
async def test_go_edit_requires_go_test_before_clearing_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "evaluator/evaluator.go",
                    "old_string": "old",
                    "new_string": "func evalStepped() {}\n",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "go build ./..."},
                tool_result=SimpleNamespace(
                    success=True,
                    data="Command: go build ./...\nExit Code: 0",
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections


@pytest.mark.asyncio
async def test_go_test_clears_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "evaluator/evaluator.go",
                    "old_string": "old",
                    "new_string": "func evalStepped() {}\n",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "go test ./evaluator -count=1"},
                tool_result=SimpleNamespace(
                    success=True,
                    data=(
                        "Command: go test ./evaluator -count=1\n"
                        "Exit Code: 0"
                    ),
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" not in builder.sections


@pytest.mark.asyncio
async def test_typescript_edit_requires_suite_before_clearing_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "src/container.ts",
                    "old_string": "old",
                    "new_string": "async initialize() {}\n",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={"command": "tsc --noEmit"},
                tool_result=SimpleNamespace(
                    success=True,
                    data="Command: tsc --noEmit\nExit Code: 0",
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections


@pytest.mark.asyncio
async def test_typescript_suite_clears_nudge() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder
    rail._user_text = (
        "Add async container initialization with initializer initialize initialize."
    )

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="edit_file",
                tool_args={
                    "file_path": "src/container.ts",
                    "old_string": "old",
                    "new_string": "async initialize() {}\n",
                },
            )
        )
    )
    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="bash",
                tool_args={
                    "command": "npm test -- async-initialization"
                },
                tool_result=SimpleNamespace(
                    success=True,
                    data=(
                        "Command: npm test -- async-initialization\n"
                        "Exit Code: 0"
                    ),
                ),
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" not in builder.sections


@pytest.mark.asyncio
async def test_real_edit_without_verify_still_nudges() -> None:
    rail = ImplementCompletenessRail()
    builder = _FakeBuilder()
    rail.system_prompt_builder = builder

    await rail.after_tool_call(
        SimpleNamespace(
            inputs=SimpleNamespace(
                tool_name="write_file",
                tool_args={
                    "file_path": "/tmp/x.rs",
                    "content": "fn main() {}\n",
                },
            )
        )
    )
    await rail.before_model_call(MagicMock())
    assert "implement_completeness" in builder.sections

"""Unit tests for CodeTaskPlanningRail."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjiuwen.harness.prompts import SystemPromptBuilder
from openjiuwen.harness.prompts.sections import SectionName

from openjiuwen_icode.rails.code_task_planning import CodeTaskPlanningRail


@pytest.mark.asyncio
async def test_code_task_planning_rail_injects_coding_todo() -> None:
    """before_model_call installs coding todo overrides on the builder."""
    rail = CodeTaskPlanningRail()
    builder = SystemPromptBuilder(language="en")
    rail.system_prompt_builder = builder

    ctx = SimpleNamespace(agent=MagicMock())
    # Avoid parent model-switch path needing a real agent LLM.
    rail._model_selection = {}
    rail._default_llm = None

    await rail.before_model_call(ctx)

    section = builder.get_section(SectionName.TODO)
    assert section is not None
    text = section.render("en")
    assert "Coding-agent task planning overrides" in text
    assert "edit_file" in text

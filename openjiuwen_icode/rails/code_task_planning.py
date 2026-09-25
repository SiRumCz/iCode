# coding: utf-8
"""TaskPlanningRail variant that injects coding-oriented todo guidance."""

from __future__ import annotations

from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.harness.rails.task_planning_rail import TaskPlanningRail

from openjiuwen_icode.prompts.code_profile import build_code_todo_section


class CodeTaskPlanningRail(TaskPlanningRail):
    """Like :class:`TaskPlanningRail`, but TODO prompt prefers implement/edit.

    Registers the same todo tools. On each model call, replaces the generic
    todo system section with the coding-agent addendum so Inspect-first
    planning does not dominate implementation tasks.
    """

    async def before_model_call(self, ctx: AgentCallbackContext) -> None:
        """Run parent model-switch path, then inject coding todo guidance."""
        if self.system_prompt_builder is None:
            return

        # Parent with inject_prompt=False clears generic TODO and still
        # performs selected_model_id switching.
        saved = self.inject_prompt
        self.inject_prompt = False
        try:
            await super().before_model_call(ctx)
        finally:
            self.inject_prompt = saved

        if not saved:
            return

        section = build_code_todo_section(
            language=self.system_prompt_builder.language,
            model_selection=(
                self._model_selection if self._model_selection else None
            ),
        )
        self.system_prompt_builder.add_section(section)


__all__ = ["CodeTaskPlanningRail"]

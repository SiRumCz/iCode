# coding: utf-8
"""Pilot coverage for SubAgentCard widget."""

from __future__ import annotations

import pytest
from textual.app import App
from textual.containers import VerticalScroll

from openjiuwen_icode.tui.widgets.subagent_card import (
    SubAgentActionPressed,
    SubAgentCard,
    _fmt_args,
)


def test_fmt_args_non_dict() -> None:
    assert "hello" in _fmt_args("hello\nworld")
    assert _fmt_args(None) == ""
    long = _fmt_args({"path": "x" * 80})
    assert "…" in long


@pytest.mark.asyncio
async def test_card_lifecycle_and_actions() -> None:
    pressed: list[tuple[str, str]] = []

    class T(App):
        def compose(self):
            yield VerticalScroll(
                SubAgentCard(
                    "inv-abcdefghijklmnopqrstuvwxyz",
                    "code_agent",
                    task="do work",
                    transport="acp",
                ),
                id="root",
            )

        def on_sub_agent_action_pressed(
            self, event: SubAgentActionPressed
        ) -> None:
            pressed.append((event.invocation_id, event.action))

    async with T().run_test() as pilot:
        card = pilot.app.query_one(SubAgentCard)
        card.set_running(task="updated")
        cid = card.add_tool_start("read_file", {"path": "a.py"})
        card.add_tool_start("bash", {"command": "ls"}, call_id=cid)
        card.complete_tool(result="ok", call_id=cid)
        card.complete_tool(tool_name="orphan", result="solo")
        for i in range(10):
            card.add_tool_start(f"t{i}", {"i": i})
            card.complete_tool(call_id=f"t{i+1}" if False else None)
        # complete by open / name paths
        open_id = card.add_tool_start("grep", {"pattern": "x"})
        card.complete_tool()
        card.add_tool_start("grep", {"pattern": "y"})
        card.complete_tool(tool_name="grep", result="1 match")
        card.set_retry_attempt("fail", 1, 3, 2)
        card.clear_retry_banner()
        card.set_paused(reason="awaiting", last_error="err")
        await pilot.click("#retry")
        card.set_failed(error="boom", allow_retry=True)
        await pilot.click("#abort")
        card.set_done(preview="done text")
        card.set_aborted(reason="user abort")
        card.clear_tools()
        card.set_running(clear_tools=True)
        assert "code_agent" in card._header_text()
        assert pressed

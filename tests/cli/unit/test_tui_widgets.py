# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for Chrys-aligned TUI widgets."""

from __future__ import annotations

import pytest

from openjiuwen_icode.tui.markup import md_to_markup
from openjiuwen_icode.tui.widgets.suggestion_list import (
    SLASH_COMMANDS,
    SuggestionList,
)
from openjiuwen_icode.tui.widgets.tool_card import ToolCard, _truncate


class TestMarkup:
    def test_md_to_markup(self) -> None:
        assert "[bold]" in md_to_markup("**hi**")
        assert "\\[" in md_to_markup("a[b]")

    def test_ampersand_not_html_escaped(self) -> None:
        assert md_to_markup("Kod & utveckling") == "Kod & utveckling"
        assert "&amp;" not in md_to_markup("a & b")

    def test_unescapes_model_entities(self) -> None:
        assert md_to_markup("Kod **&amp;** x") == "Kod [bold]&[/bold] x"


class TestToolCardLogic:
    def test_truncate(self) -> None:
        assert _truncate("short") == "short"
        assert _truncate("x" * 200, 10).endswith("…")

    @pytest.mark.asyncio
    async def test_expand_collapse(self) -> None:
        from textual.app import App
        from textual.containers import VerticalScroll

        class T(App):
            def compose(self):
                yield VerticalScroll(ToolCard("bash", {"cmd": "ls"}), id="root")

        async with T().run_test() as pilot:
            card = pilot.app.query_one(ToolCard)
            assert card._expanded is False
            card.set_result("hello\nworld")
            card.set_expanded(True)
            assert card._expanded is True
            assert "hello" in card.result
            card.collapse()
            assert card._expanded is False


class TestSuggestionList:
    @pytest.mark.asyncio
    async def test_filters_commands(self) -> None:
        from textual.app import App

        class T(App):
            def compose(self):
                yield SuggestionList(id="suggest")

        async with T().run_test() as pilot:
            sug = pilot.app.query_one(SuggestionList)
            sug.show_for("/wo")
            assert sug.is_open
            assert sug.selected_command() is not None
            assert any(c.startswith("/workdirs") for c, _ in SLASH_COMMANDS)
            sug.hide()
            assert not sug.is_open

    def test_slash_catalog_nonempty(self) -> None:
        assert len(SLASH_COMMANDS) >= 8


class TestBubbles:
    @pytest.mark.asyncio
    async def test_agent_append(self) -> None:
        from textual.app import App
        from textual.containers import VerticalScroll

        from openjiuwen_icode.tui.widgets.messages import (
            AgentBubble,
            UserBubble,
        )

        class T(App):
            def compose(self):
                yield VerticalScroll(
                    UserBubble("hi"),
                    AgentBubble("Hello"),
                    id="root",
                )

        async with T().run_test() as pilot:
            agent = pilot.app.query_one(AgentBubble)
            agent.append_text(" world")
            assert agent.text == "Hello world"

    @pytest.mark.asyncio
    async def test_await_remove_children_allows_reuse_turn_id(self) -> None:
        """SessionRestored remounts turn-* bubbles; prune must be awaited."""
        from textual.app import App
        from textual.containers import VerticalScroll

        from openjiuwen_icode.tui.widgets.messages import UserBubble

        class T(App):
            def compose(self):
                yield VerticalScroll(id="root")

        async with T().run_test() as pilot:
            scroll = pilot.app.query_one("#root", VerticalScroll)
            scroll.mount(UserBubble("first", id="turn-1"))
            await scroll.remove_children()
            scroll.mount(UserBubble("restored", id="turn-1"))
            bubble = pilot.app.query_one("#turn-1", UserBubble)
            assert "restored" in bubble.text

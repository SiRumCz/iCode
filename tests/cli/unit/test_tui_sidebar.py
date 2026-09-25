# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for Messages/Tasks/Context sidebar widgets."""

from __future__ import annotations

import pytest

from openjiuwen_icode.tui.widgets.sidebar.context import (
    ContextPanel,
    estimate_usage_from_messages,
    format_token_count,
)
from openjiuwen_icode.tui.widgets.sidebar.tasks import (
    TasksPanel,
    normalize_todo_items,
)
from openjiuwen_icode.tui.widgets.sidebar.toc import (
    ConversationToc,
    TocItem,
    plan_session_replay,
    summarize_prompt,
)
from openjiuwen_icode.tui.widgets.sidebar.panel import SidebarPanel


class TestFormatTokens:
    def test_compact(self) -> None:
        assert format_token_count(51) == "51"
        assert format_token_count(17200).endswith("k")


class TestEstimateUsage:
    def test_from_roles(self) -> None:
        est = estimate_usage_from_messages(
            [
                {"role": "user", "content": "hello world " * 20},
                {"role": "assistant", "content": "hi " * 10},
            ]
        )
        assert est["input_tokens"] > 0
        assert est["output_tokens"] > 0
        assert est["used_tokens"] == est["total_tokens"]

    def test_prefers_token_count(self) -> None:
        est = estimate_usage_from_messages(
            [{"role": "user", "content": "x", "token_count": 42}]
        )
        assert est["input_tokens"] == 42
        assert est["used_tokens"] == 42

    def test_empty(self) -> None:
        assert estimate_usage_from_messages([])["used_tokens"] == 0
        assert estimate_usage_from_messages(None)["total_tokens"] == 0


class TestSummarize:
    def test_first_line_and_truncate(self) -> None:
        assert summarize_prompt("hello\nworld") == "hello"
        long = "x" * 120
        out = summarize_prompt(long, max_length=20)
        assert out.endswith("…")
        assert len(out) <= 20

    def test_empty(self) -> None:
        assert summarize_prompt("  ") == "(empty)"


class TestSessionReplay:
    def test_pairs_user_assistant_with_turn_ids(self) -> None:
        msgs = [
            type("M", (), {"role": "user", "content": "下午好"})(),
            type(
                "M",
                (),
                {"role": "assistant", "content": "你好！有什么可以帮你？"},
            )(),
        ]
        toc, bubbles = plan_session_replay(msgs)
        assert len(toc) == 1
        assert toc[0].turn_id == "turn-1"
        assert toc[0].summary == "下午好"
        assert [b.role for b in bubbles] == ["user", "assistant"]
        assert bubbles[0].turn_id == "turn-1"
        assert bubbles[1].turn_id is None
        assert bubbles[1].content.startswith("你好")

    def test_dict_messages(self) -> None:
        toc, bubbles = plan_session_replay(
            [
                {"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
            ]
        )
        assert [t.turn_id for t in toc] == ["turn-1", "turn-2"]
        assert len(bubbles) == 2


class TestNormalizeTodos:
    def test_list_of_dicts(self) -> None:
        items = normalize_todo_items(
            [
                {"content": "A", "status": "completed"},
                {"content": "B", "status": "pending"},
            ]
        )
        assert len(items) == 2
        assert items[0]["status"] == "completed"

    def test_wrapped_payload(self) -> None:
        items = normalize_todo_items(
            {"items": [{"content": "X", "status": "in_progress"}]}
        )
        assert items[0]["content"] == "X"

    def test_none(self) -> None:
        assert normalize_todo_items(None) == []


class TestSidebarWidgets:
    @pytest.mark.asyncio
    async def test_toc_and_tasks_update(self) -> None:
        from textual.app import App
        from textual.containers import Horizontal

        class T(App):
            def compose(self):
                with Horizontal():
                    yield SidebarPanel(id="sidebar")

        async with T().run_test() as pilot:
            side = pilot.app.query_one("#sidebar", SidebarPanel)
            assert side.is_visible
            side.set_toc_items(
                [TocItem(turn_id="turn-1", summary="下午好")]
            )
            toc = side.toc
            assert len(toc._items) == 1
            side.set_todos(
                [
                    {"content": "Write tests", "status": "in_progress"},
                    {"content": "Ship", "status": "pending"},
                ]
            )
            assert len(side.tasks._items) == 2
            side.toggle()
            assert not side.is_visible
            side.toggle()
            assert side.is_visible
            side.clear_session()
            assert toc._items == []
            assert side.tasks._items == []
            assert side.context_panel._current_used == 0
            assert side.context_panel._block_count == 0
            side.context_panel.seed_from_messages(
                [
                    {"role": "user", "content": "hej " * 50},
                    {"role": "assistant", "content": "hej! " * 20},
                ]
            )
            assert side.context_panel._current_used > 0
            assert side.context_panel._total_session_input_tokens > 0

    @pytest.mark.asyncio
    async def test_context_usage_and_compaction(self) -> None:
        from textual.app import App

        class T(App):
            def compose(self):
                yield ContextPanel()

        async with T().run_test() as pilot:
            panel = pilot.app.query_one(ContextPanel)
            panel.update_usage(
                17249,
                1_000_000,
                total_session_tokens=17249 + 51,
                total_session_input_tokens=17249,
                total_session_output_tokens=51,
            )
            assert panel._current_used == 17249
            assert panel._current_max == 1_000_000
            assert panel._total_session_output_tokens == 51
            panel.add_compressed_block("trimmed older turns", ok=True)
            assert panel._block_count == 1
            panel.reset(128_000)
            assert panel._current_used == 0
            assert panel._current_max == 128_000
            assert panel._block_count == 0

    @pytest.mark.asyncio
    async def test_context_gauge_uses_last_input_not_cumulative(self) -> None:
        from textual.app import App

        from openjiuwen_icode.events import UsageUpdate

        class T(App):
            def compose(self):
                yield ContextPanel()

        async with T().run_test() as pilot:
            panel = pilot.app.query_one(ContextPanel)
            panel.apply_usage_event(
                UsageUpdate(
                    input_tokens=490_716,
                    output_tokens=12_000,
                    total_tokens=502_716,
                    last_input_tokens=42_000,
                    last_output_tokens=800,
                )
            )
            # Gauge = current window fill (last prompt), not session sum.
            assert panel._current_used == 42_000
            assert panel._total_session_input_tokens == 490_716
            assert panel._total_session_output_tokens == 12_000

    @pytest.mark.asyncio
    async def test_context_fill_bar_matches_percent(self) -> None:
        from textual.app import App
        from textual.widgets import ProgressBar

        class T(App):
            def compose(self):
                yield ContextPanel(max_context_tokens=100_000)

        async with T().run_test() as pilot:
            panel = pilot.app.query_one(ContextPanel)
            panel.update_usage(3_000, 100_000)
            bar = panel.query_one("#ctx-fill", ProgressBar)
            assert bar.progress == pytest.approx(3.0)
            text = panel.query_one("#ctx-usage-text").render()
            assert "3.0%" in str(text)

    @pytest.mark.asyncio
    async def test_toc_empty_state(self) -> None:
        from textual.app import App

        class T(App):
            def compose(self):
                yield ConversationToc()

        async with T().run_test() as pilot:
            toc = pilot.app.query_one(ConversationToc)
            toc.update_items([])
            empty = toc.query_one("#toc-empty")
            assert empty.display is True

    @pytest.mark.asyncio
    async def test_tasks_empty_state(self) -> None:
        from textual.app import App

        class T(App):
            def compose(self):
                yield TasksPanel()

        async with T().run_test() as pilot:
            panel = pilot.app.query_one(TasksPanel)
            panel.set_items([])
            empty = panel.query_one("#tasks-empty")
            assert empty.display is True

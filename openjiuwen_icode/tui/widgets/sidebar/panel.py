# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Toggleable tabbed sidebar (Messages + Tasks + Context)."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import TabbedContent, TabPane

from openjiuwen_icode.tui.widgets.sidebar.context import ContextPanel
from openjiuwen_icode.tui.widgets.sidebar.tasks import TasksPanel
from openjiuwen_icode.tui.widgets.sidebar.toc import (
    ConversationToc,
    TocItem,
)


class SidebarPanel(Widget, can_focus=False):
    """Right-hand sidebar with Messages TOC, Tasks, and Context tabs."""

    DEFAULT_CSS = """
    SidebarPanel {
        width: 32%;
        min-width: 28;
        max-width: 56;
        height: 1fr;
        border: solid $primary;
        padding: 0;
    }
    SidebarPanel > TabbedContent {
        height: 1fr;
    }
    SidebarPanel TabPane {
        height: 1fr;
        padding: 0;
    }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="tab-toc"):
            with TabPane("Messages", id="tab-toc"):
                yield ConversationToc()
            with TabPane("Tasks", id="tab-tasks"):
                yield TasksPanel()
            with TabPane("Context", id="tab-context"):
                yield ContextPanel()

    def toggle(self) -> None:
        self.display = not self.display

    @property
    def is_visible(self) -> bool:
        return bool(self.display)

    @property
    def toc(self) -> ConversationToc:
        return self.query_one(ConversationToc)

    @property
    def tasks(self) -> TasksPanel:
        return self.query_one(TasksPanel)

    @property
    def context_panel(self) -> ContextPanel:
        return self.query_one(ContextPanel)

    def set_toc_items(self, items: list[TocItem]) -> None:
        self.toc.update_items(items)

    def set_todos(self, items: Any) -> None:
        self.tasks.set_items(items)

    def clear_session(self) -> None:
        self.toc.clear()
        self.tasks.clear()
        self.context_panel.reset()

    def focus_messages(self) -> None:
        self.query_one(TabbedContent).active = "tab-toc"

    def focus_tasks(self) -> None:
        self.query_one(TabbedContent).active = "tab-tasks"

    def focus_context(self) -> None:
        self.query_one(TabbedContent).active = "tab-context"

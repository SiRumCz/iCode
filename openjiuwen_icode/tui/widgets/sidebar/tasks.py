# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tasks sidebar panel — live session todo checklist."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from openjiuwen_icode.ui.todo_render import (
    render_todo_item,
    render_todo_summary,
)


def normalize_todo_items(raw: Any) -> list[dict[str, Any]]:
    """Coerce TodoListUpdated payload into a list of content/status dicts."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        if "items" in raw:
            raw = raw["items"]
        elif "todos" in raw:
            raw = raw["todos"]
        elif "content" in raw or "status" in raw:
            raw = [raw]
        else:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            content = str(
                item.get("content")
                or item.get("activeForm")
                or item.get("active_form")
                or ""
            )
            status = str(item.get("status") or "pending")
            if hasattr(status, "value"):
                status = str(getattr(status, "value"))
            out.append({"content": content, "status": status})
            continue
        # Pydantic TodoItem-like objects
        content = str(
            getattr(item, "content", None)
            or getattr(item, "activeForm", None)
            or getattr(item, "active_form", None)
            or ""
        )
        status = getattr(item, "status", "pending")
        if hasattr(status, "value"):
            status = status.value
        out.append({"content": content, "status": str(status or "pending")})
    return out


class TasksPanel(Widget, can_focus=False):
    """Renders the session todo list with status markers."""

    DEFAULT_CSS = """
    TasksPanel {
        height: 1fr;
        width: 100%;
        padding: 0 1;
    }
    TasksPanel > .tasks-label {
        height: 1;
        text-style: bold;
        color: $text-muted;
        margin: 0 0 1 0;
    }
    TasksPanel > #tasks-list {
        height: 1fr;
        border: none;
        padding: 0;
    }
    TasksPanel > #tasks-empty {
        height: 1fr;
        width: 100%;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._items: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Static("Todos", classes="tasks-label")
        yield VerticalScroll(Static("", id="tasks-checklist"), id="tasks-list")
        yield Static("No tasks yet", id="tasks-empty")

    def on_mount(self) -> None:
        self.set_items(self._items)

    def set_items(self, items: list[dict[str, Any]] | Any) -> None:
        self._items = normalize_todo_items(items)
        self._sync()

    def clear(self) -> None:
        self.set_items([])

    def _sync(self) -> None:
        try:
            label = self.query_one(".tasks-label", Static)
            scroller = self.query_one("#tasks-list", VerticalScroll)
            checklist = self.query_one("#tasks-checklist", Static)
            empty = self.query_one("#tasks-empty", Static)
        except NoMatches:
            return
        if not self._items:
            label.update("Todos")
            checklist.update("")
            scroller.display = False
            empty.display = True
            return
        summary = render_todo_summary(self._items)
        label.update(f"Todos ({summary})")
        lines = [
            render_todo_item(
                str(item.get("content") or ""),
                str(item.get("status") or "pending"),
            )
            for item in self._items
        ]
        checklist.update("\n".join(lines))
        scroller.display = True
        empty.display = False

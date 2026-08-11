# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Collapsible tool call cards for the EventBus TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


def _truncate(text: str, limit: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class ToolCard(Vertical):
    """Collapsible tool invocation card (header + optional result body)."""

    DEFAULT_CSS = """
    ToolCard {
        height: auto;
        width: 100%;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #1e293b;
        border-left: heavy yellow;
    }
    ToolCard .tool-header {
        height: auto;
        width: 100%;
        color: yellow;
    }
    ToolCard .tool-body {
        height: auto;
        width: 100%;
        color: $text-muted;
        padding: 0 0 0 2;
        display: none;
    }
    ToolCard.-expanded .tool-body {
        display: block;
    }
    """

    can_focus = True

    def __init__(
        self,
        tool_name: str,
        tool_args: object = None,
        *,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self.tool_name = tool_name or "tool"
        self.tool_args = tool_args
        self.result = ""
        self._expanded = False

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), classes="tool-header", markup=False)
        yield Static("", classes="tool-body", markup=False)

    def _header_text(self) -> str:
        marker = "▼" if self._expanded else "▶"
        args = _truncate(repr(self.tool_args), 100)
        status = "done" if self.result else "running…"
        return f"{marker} ⚙ {self.tool_name}  {args}  [{status}]"

    def _refresh_header(self) -> None:
        self.query_one(".tool-header", Static).update(self._header_text())

    def set_result(self, result: str) -> None:
        self.result = result or ""
        body = self.query_one(".tool-body", Static)
        preview = self.result
        if len(preview) > 4000:
            preview = preview[:3999] + "…"
        body.update(preview)
        self._refresh_header()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.set_class(expanded, "-expanded")
        self._refresh_header()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def collapse(self) -> None:
        self.set_expanded(False)

    def on_click(self) -> None:
        if self.result:
            self.toggle()

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", "")
        if key in {"enter", "space"} and self.result:
            self.toggle()
            stop = getattr(event, "stop", None)
            if callable(stop):
                stop()

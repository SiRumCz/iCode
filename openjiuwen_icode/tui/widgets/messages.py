# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Role message bubbles for the EventBus TUI (Chrys-style)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Static

from openjiuwen_icode.tui.markup import md_to_markup


class _Bubble(Vertical):
    """Base selectable message bubble with a colored left border."""

    DEFAULT_CSS = """
    _Bubble {
        height: auto;
        width: 100%;
        margin: 0 0 1 0;
        padding: 0 1;
        border-left: heavy $primary;
    }
    _Bubble .bubble-role {
        height: 1;
        text-style: bold;
        color: $text-muted;
    }
    _Bubble .bubble-body {
        height: auto;
        width: 100%;
    }
    """

    ROLE = "msg"
    ROLE_LABEL = "Msg"
    BORDER_COLOR = "$primary"
    BODY_MARKUP = True

    def __init__(
        self,
        text: str = "",
        *,
        classes: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(classes=classes, id=id)
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(self.ROLE_LABEL, classes="bubble-role")
        yield Static(
            self._format_body(self._text),
            markup=self.BODY_MARKUP,
            classes="bubble-body",
        )

    def on_mount(self) -> None:
        # Stream tokens may arrive before compose children exist; sync once ready.
        self._sync_body()

    def _format_body(self, text: str) -> str:
        return text

    def _sync_body(self) -> None:
        try:
            body = self.query_one(".bubble-body", Static)
        except NoMatches:
            return
        body.update(self._format_body(self._text))

    def set_text(self, text: str) -> None:
        self._text = text
        self._sync_body()

    def append_text(self, chunk: str) -> None:
        self.set_text(self._text + chunk)

    @property
    def text(self) -> str:
        return self._text


class UserBubble(_Bubble):
    ROLE = "user"
    ROLE_LABEL = "You"
    BORDER_COLOR = "cyan"
    BODY_MARKUP = False

    DEFAULT_CSS = """
    UserBubble {
        border-left: heavy cyan;
    }
    UserBubble .bubble-role { color: cyan; }
    """


class AgentBubble(_Bubble):
    ROLE = "agent"
    ROLE_LABEL = "Agent"
    BORDER_COLOR = "green"

    DEFAULT_CSS = """
    AgentBubble {
        border-left: heavy green;
    }
    AgentBubble .bubble-role { color: green; }
    """

    def _format_body(self, text: str) -> str:
        return md_to_markup(text)


class SystemBubble(_Bubble):
    ROLE = "system"
    ROLE_LABEL = "System"
    BORDER_COLOR = "#888888"
    BODY_MARKUP = False

    DEFAULT_CSS = """
    SystemBubble {
        border-left: heavy #888888;
        color: #aaaaaa;
    }
    SystemBubble .bubble-role { color: #aaaaaa; }
    """


class ErrorBubble(_Bubble):
    ROLE = "error"
    ROLE_LABEL = "Error"
    BORDER_COLOR = "red"
    BODY_MARKUP = False

    DEFAULT_CSS = """
    ErrorBubble {
        border-left: heavy red;
    }
    ErrorBubble .bubble-role { color: red; }
    ErrorBubble .bubble-body { color: red; }
    """

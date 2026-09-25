# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tiny yes/no confirm modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConfirmModal(ModalScreen[bool]):
    """Return True on confirm, False on cancel."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > #confirm-root {
        width: 60;
        max-width: 80%;
        height: auto;
        border: round $error;
        background: $surface;
        padding: 1 2;
    }
    ConfirmModal #confirm-title {
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }
    ConfirmModal #confirm-message {
        height: auto;
        margin-bottom: 1;
    }
    ConfirmModal #confirm-buttons {
        height: 3;
        align: right middle;
    }
    ConfirmModal #confirm-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str = "Confirm",
        message: str = "Are you sure?",
        confirm_label: str = "Confirm",
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-root"):
            yield Label(self._title, id="confirm-title")
            yield Static(self._message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button(
                    self._confirm_label,
                    id="confirm",
                    variant="error",
                )
                yield Button("Cancel", id="cancel", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)

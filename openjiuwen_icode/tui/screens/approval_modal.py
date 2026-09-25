# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Approval / ask modals for the EventBus TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ApprovalModal(ModalScreen[tuple[bool, str]]):
    """Approve or reject a tool call.

    Dismiss result: ``(approved, feedback)``.
    """

    DEFAULT_CSS = """
    ApprovalModal {
        align: center middle;
    }
    ApprovalModal > Vertical {
        width: 70%;
        max-width: 80;
        height: auto;
        border: solid yellow;
        background: $surface;
        padding: 1 2;
    }
    ApprovalModal #approval-title {
        text-style: bold;
        color: yellow;
        margin-bottom: 1;
    }
    ApprovalModal #approval-detail {
        height: auto;
        margin-bottom: 1;
        color: $text-muted;
    }
    ApprovalModal #approval-feedback {
        margin-bottom: 1;
    }
    ApprovalModal Horizontal {
        height: auto;
        align: right middle;
    }
    ApprovalModal Button {
        margin-left: 1;
    }
    """

    def __init__(self, tool_name: str, tool_args: object = None) -> None:
        super().__init__()
        self.tool_name = tool_name or "tool"
        self.tool_args = tool_args

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"Approve {self.tool_name}?",
                id="approval-title",
            )
            yield Static(
                repr(self.tool_args),
                id="approval-detail",
                markup=False,
            )
            yield Input(
                placeholder="Optional reject feedback…",
                id="approval-feedback",
            )
            with Horizontal():
                yield Button("Reject", variant="error", id="reject")
                yield Button("Approve", variant="success", id="approve")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        feedback = self.query_one("#approval-feedback", Input).value.strip()
        if event.button.id == "approve":
            self.dismiss((True, ""))
            return
        self.dismiss((False, feedback or "rejected"))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter in feedback field = reject with that feedback.
        self.dismiss((False, event.value.strip() or "rejected"))


class AskModal(ModalScreen[str]):
    """Collect a free-text answer for QuestionToUser."""

    DEFAULT_CSS = """
    AskModal {
        align: center middle;
    }
    AskModal > Vertical {
        width: 70%;
        max-width: 80;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    AskModal #ask-title {
        text-style: bold;
        margin-bottom: 1;
    }
    AskModal #ask-body {
        height: auto;
        margin-bottom: 1;
        color: $text-muted;
    }
    AskModal Button {
        margin-top: 1;
    }
    """

    def __init__(self, questions: list[object] | None = None) -> None:
        super().__init__()
        self.questions = questions or []

    def compose(self) -> ComposeResult:
        lines: list[str] = []
        for q in self.questions:
            if isinstance(q, dict):
                lines.append(
                    f"{q.get('header', 'Q')}: {q.get('question', '')}"
                )
            else:
                lines.append(str(q))
        body = "\n".join(lines) if lines else "Agent needs your input."
        with Vertical():
            yield Label("Agent is asking", id="ask-title")
            yield Static(body, id="ask-body", markup=False)
            yield Input(placeholder="Your answer…", id="ask-answer")
            yield Button("Submit", variant="primary", id="ask-submit")

    def on_mount(self) -> None:
        self.query_one("#ask-answer", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ask-submit":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        answer = self.query_one("#ask-answer", Input).value.strip()
        self.dismiss(answer)

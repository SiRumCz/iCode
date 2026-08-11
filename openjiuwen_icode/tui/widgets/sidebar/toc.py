# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Conversation table-of-contents for the Messages sidebar tab."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

_SUMMARY_MAX = 80


@dataclass
class TocItem:
    """One conversation turn entry in the Messages TOC."""

    turn_id: str
    summary: str
    children: list[TocItem] = field(default_factory=list)


@dataclass
class ReplayBubble:
    """One bubble to mount when replaying a stored session."""

    role: str  # user | assistant | system
    content: str
    turn_id: str | None = None


def summarize_prompt(text: str, max_length: int = _SUMMARY_MAX) -> str:
    """First-line summary for TOC labels."""
    if not text or not str(text).strip():
        return "(empty)"
    first = str(text).split("\n", 1)[0].strip()
    if len(first) > max_length:
        return first[: max_length - 1] + "…"
    return first


def plan_session_replay(
    messages: list[Any],
) -> tuple[list[TocItem], list[ReplayBubble]]:
    """Build TOC + bubble plan from persisted session messages.

    User messages get ``turn-N`` ids shared by TOC entries and UserBubble
    widgets so sidebar clicks can scroll to the matching turn.
    """
    toc: list[TocItem] = []
    bubbles: list[ReplayBubble] = []
    turn_seq = 0
    for msg in messages:
        role = str(getattr(msg, "role", "") or "")
        content = str(getattr(msg, "content", "") or "")
        if isinstance(msg, dict):
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
        if role == "user":
            turn_seq += 1
            turn_id = f"turn-{turn_seq}"
            toc.append(
                TocItem(turn_id=turn_id, summary=summarize_prompt(content))
            )
            bubbles.append(
                ReplayBubble(role="user", content=content, turn_id=turn_id)
            )
        elif role == "assistant":
            text = content.rstrip("\n")
            if text:
                bubbles.append(ReplayBubble(role="assistant", content=text))
        elif content.strip():
            bubbles.append(ReplayBubble(role="system", content=content))
    return toc, bubbles


def _option_id(turn_id: str) -> str:
    """CSS-safe option id."""
    return "toc-" + turn_id.replace(" ", "-")


class ConversationToc(Widget, can_focus=False):
    """Numbered list of user turns (Messages tab)."""

    DEFAULT_CSS = """
    ConversationToc {
        height: 1fr;
        width: 100%;
        padding: 0 0 0 1;
    }
    ConversationToc > #toc-list {
        height: 1fr;
        background: transparent;
        border: none;
        padding: 0;
    }
    ConversationToc > #toc-empty {
        height: 1fr;
        width: 100%;
        content-align: center middle;
        color: $text-muted;
    }
    """

    class TurnSelected(Message):
        """User selected a TOC entry."""

        def __init__(self, turn_id: str) -> None:
            super().__init__()
            self.turn_id = turn_id

    def __init__(self) -> None:
        super().__init__()
        self._items: list[TocItem] = []
        self._id_map: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield OptionList(id="toc-list")
        yield Static(
            "Your conversation will appear here",
            id="toc-empty",
        )

    def on_mount(self) -> None:
        self.query_one("#toc-list", OptionList).can_focus = False
        self._rebuild()

    def update_items(self, items: list[TocItem]) -> None:
        self._items = list(items)
        self._rebuild()

    def clear(self) -> None:
        self.update_items([])

    def _rebuild(self) -> None:
        try:
            listing = self.query_one("#toc-list", OptionList)
            empty = self.query_one("#toc-empty", Static)
        except Exception:  # noqa: BLE001 — not mounted yet
            return
        listing.clear_options()
        self._id_map.clear()
        if not self._items:
            listing.display = False
            empty.display = True
            return
        listing.display = True
        empty.display = False
        for i, item in enumerate(self._items, start=1):
            oid = _option_id(item.turn_id)
            self._id_map[oid] = item.turn_id
            listing.add_option(
                Option(f"{i}. {item.summary}", id=oid)
            )

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        event.stop()
        oid = str(event.option.id) if event.option.id else ""
        turn_id = self._id_map.get(oid)
        if turn_id:
            self.post_message(self.TurnSelected(turn_id))

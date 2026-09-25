# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for Chrys-style right-click / selection copy helpers."""

from __future__ import annotations

from openjiuwen_icode.tui.right_click_copy import copy_screen_selection


class _FakeScreen:
    def __init__(self, text: str | None) -> None:
        self._text = text
        self.cleared = False

    def get_selected_text(self) -> str | None:
        return self._text

    def clear_selection(self) -> None:
        self.cleared = True


class _FakeApp:
    def __init__(self) -> None:
        self.focused = None
        self.copied: list[str] = []

    def copy_to_clipboard(self, text: str) -> None:
        self.copied.append(text)


def test_copy_screen_selection(monkeypatch) -> None:
    app = _FakeApp()
    screen = _FakeScreen("picked")
    monkeypatch.setattr(
        "openjiuwen_icode.tui.right_click_copy.copy_text_to_clipboards",
        lambda a, t: a.copied.append(t) or True,
    )
    assert copy_screen_selection(app, screen, clear=True)
    assert app.copied == ["picked"]
    assert screen.cleared is True


def test_copy_prefers_input_selection(monkeypatch) -> None:
    app = _FakeApp()

    class _Focused:
        selected_text = "from-input"

    app.focused = _Focused()
    screen = _FakeScreen("from-screen")
    monkeypatch.setattr(
        "openjiuwen_icode.tui.right_click_copy.copy_text_to_clipboards",
        lambda a, t: a.copied.append(t) or True,
    )
    assert copy_screen_selection(app, screen)
    assert app.copied == ["from-input"]

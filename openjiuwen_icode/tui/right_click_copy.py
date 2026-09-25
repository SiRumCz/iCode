# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Right-click copy helpers (Chrys-style) for the EventBus TUI."""

from __future__ import annotations

from typing import Any

from openjiuwen_icode.tui.clipboard import copy_text_to_clipboards


def cancel_textual_mouse_chain(screen: Any) -> None:
    """Cancel Textual's private mouse bookkeeping after right-click copy."""
    app = getattr(screen, "app", None)
    if app is not None:
        app._mouse_down_widget = None
    screen._mouse_down_offset = None
    screen._selecting = False


def copy_screen_selection(app: Any, screen: Any, *, clear: bool = False) -> bool:
    """Copy current screen/input selection via dual clipboard."""
    text = None
    focused = getattr(app, "focused", None)
    selected_text = getattr(focused, "selected_text", None)
    if isinstance(selected_text, str) and selected_text:
        text = selected_text
    else:
        getter = getattr(screen, "get_selected_text", None)
        if callable(getter):
            text = getter()
    if not text:
        return False
    if not copy_text_to_clipboards(app, text):
        return False
    if clear:
        clearer = getattr(screen, "clear_selection", None)
        if callable(clearer):
            clearer()
    return True

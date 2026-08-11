# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for TUI clipboard dual-write helpers."""

from __future__ import annotations

from openjiuwen_icode.tui.clipboard import (
    OSC52_COPY_MAX_BYTES,
    copy_text_to_clipboards,
)


class _FakeApp:
    def __init__(self) -> None:
        self.copied: list[str] = []

    def copy_to_clipboard(self, text: str) -> None:
        self.copied.append(text)


def test_copy_text_dual_write(monkeypatch) -> None:
    app = _FakeApp()
    calls: list[str] = []

    monkeypatch.setattr(
        "openjiuwen_icode.tui.clipboard.os_clipboard_copy",
        lambda text: calls.append(text) or True,
    )
    assert copy_text_to_clipboards(app, "hello")
    assert app.copied == ["hello"]
    assert calls == ["hello"]


def test_copy_skips_huge_osc52(monkeypatch) -> None:
    app = _FakeApp()
    monkeypatch.setattr(
        "openjiuwen_icode.tui.clipboard.os_clipboard_copy",
        lambda text: True,
    )
    huge = "x" * (OSC52_COPY_MAX_BYTES + 10)
    assert copy_text_to_clipboards(app, huge)
    assert app.copied == []


def test_copy_empty_fails() -> None:
    assert not copy_text_to_clipboards(_FakeApp(), "")

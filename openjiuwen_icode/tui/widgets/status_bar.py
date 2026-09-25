# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Status bar widget for turn phase + usage."""

from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """Single-line status showing phase and optional token usage."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        color: $text-muted;
        padding: 0 1;
        width: 100%;
    }
    """

    def __init__(self, text: str = "Ready", *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)
        self._phase = text
        self._usage = ""

    def set_phase(self, phase: str) -> None:
        self._phase = phase
        self._render_status()

    def set_usage(self, usage: str) -> None:
        self._usage = usage
        self._render_status()

    def flash(self, text: str) -> None:
        """Temporarily show *text* without losing the current phase."""
        suffix = f" · {self._usage}" if self._usage else ""
        self.update(text + suffix)

    def restore(self) -> None:
        self._render_status()

    def _render_status(self) -> None:
        suffix = f" · {self._usage}" if self._usage else ""
        self.update(self._phase + suffix)

    @property
    def phase(self) -> str:
        return self._phase

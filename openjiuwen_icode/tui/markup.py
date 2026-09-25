# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Shared markup helpers for TUI bubbles."""

from __future__ import annotations

import html
import re


def md_to_markup(text: str) -> str:
    """Very light markdown → Rich/Textual markup for transcript bubbles.

    Only ``[`` needs escaping for markup; do **not** HTML-escape ``&`` —
    Textual leaves ``&amp;`` literal on screen.
    """
    # Models sometimes emit entities (&amp;); show the real character.
    out = html.unescape(text or "")
    out = out.replace("[", "\\[")
    out = re.sub(r"\*\*(.+?)\*\*", r"[bold]\1[/bold]", out)
    out = re.sub(r"`([^`]+)`", r"[cyan]\1[/cyan]", out)
    return out

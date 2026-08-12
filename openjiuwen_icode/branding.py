# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Product branding for the agentic coding assistant."""

from __future__ import annotations

# Display name of the coding-assistant product (TUI / REPL / prompts).
# User-facing CLI / release binary is ``icode``; pip package remains
# ``openjiuwen-icode`` and the import path is ``openjiuwen_icode``.
PRODUCT_NAME = "iCode"
PRODUCT_SHORT = "iCode"
PRODUCT_TAGLINE = "iCode — agentic coding assistant"


def window_title(model: str | None = None, *, workspace: str | None = None) -> str:
    """Build the Textual / terminal window title."""
    parts = [PRODUCT_NAME]
    if model:
        parts[0] = f"{PRODUCT_NAME} ({model})"
    if workspace:
        parts.append(workspace)
    return " · ".join(parts)

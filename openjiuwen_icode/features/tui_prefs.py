# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""TUI theme + notification preference helpers (E5)."""

from __future__ import annotations

from typing import Any

from openjiuwen_icode.agent.config import (
    SETTINGS_PATH,
    load_settings_json,
    save_settings_json,
)

BUILTIN_THEMES = (
    "default",
    "dark",
    "light",
    "solarized",
    "monokai",
)


def get_theme() -> str:
    data = load_settings_json()
    theme = str(data.get("theme") or data.get("tui_theme") or "default").strip()
    return theme or "default"


def set_theme(theme: str, path: Any = None) -> str:
    cleaned = (theme or "").strip() or "default"
    save_settings_json(
        {"theme": cleaned},
        path=path or SETTINGS_PATH,
    )
    return cleaned


def notifications_enabled() -> bool:
    data = load_settings_json()
    if "notifications" in data:
        return bool(data.get("notifications"))
    if "tui_notifications" in data:
        return bool(data.get("tui_notifications"))
    return True


def set_notifications(enabled: bool, path: Any = None) -> bool:
    save_settings_json(
        {"notifications": bool(enabled)},
        path=path or SETTINGS_PATH,
    )
    return bool(enabled)


__all__ = [
    "BUILTIN_THEMES",
    "get_theme",
    "notifications_enabled",
    "set_notifications",
    "set_theme",
]

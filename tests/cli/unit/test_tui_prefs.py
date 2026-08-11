# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Unit tests for TUI theme / notification preferences."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjiuwen_icode.features import tui_prefs
from openjiuwen_icode.features.tui_prefs import (
    BUILTIN_THEMES,
    get_theme,
    notifications_enabled,
    set_notifications,
    set_theme,
)


class TestBuiltinThemes:
    def test_contains_expected_names(self) -> None:
        assert "default" in BUILTIN_THEMES
        assert "dark" in BUILTIN_THEMES
        assert "light" in BUILTIN_THEMES
        assert "solarized" in BUILTIN_THEMES
        assert "monokai" in BUILTIN_THEMES


class TestGetTheme:
    def test_defaults_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs, "load_settings_json", lambda: {}
        )
        assert get_theme() == "default"

    def test_reads_theme_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs,
            "load_settings_json",
            lambda: {"theme": "dark"},
        )
        assert get_theme() == "dark"

    def test_falls_back_to_tui_theme(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs,
            "load_settings_json",
            lambda: {"tui_theme": "solarized"},
        )
        assert get_theme() == "solarized"

    def test_blank_theme_becomes_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs,
            "load_settings_json",
            lambda: {"theme": "   "},
        )
        assert get_theme() == "default"

    def test_strips_whitespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs,
            "load_settings_json",
            lambda: {"theme": "  monokai  "},
        )
        assert get_theme() == "monokai"


class TestSetTheme:
    def test_persists_and_returns(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "settings.json"
        assert set_theme("dark", path=path) == "dark"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["theme"] == "dark"

    def test_blank_becomes_default(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "settings.json"
        assert set_theme("  ", path=path) == "default"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["theme"] == "default"

    def test_none_like_empty_becomes_default(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "settings.json"
        assert set_theme("", path=path) == "default"

    def test_uses_settings_path_when_path_omitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "settings.json"
        monkeypatch.setattr(tui_prefs, "SETTINGS_PATH", path)
        assert set_theme("light") == "light"
        assert json.loads(path.read_text())["theme"] == "light"


class TestNotificationsEnabled:
    def test_defaults_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs, "load_settings_json", lambda: {}
        )
        assert notifications_enabled() is True

    def test_reads_notifications_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs,
            "load_settings_json",
            lambda: {"notifications": False},
        )
        assert notifications_enabled() is False

    def test_falls_back_to_tui_notifications(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs,
            "load_settings_json",
            lambda: {"tui_notifications": False},
        )
        assert notifications_enabled() is False

    def test_notifications_key_wins_over_tui(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tui_prefs,
            "load_settings_json",
            lambda: {
                "notifications": True,
                "tui_notifications": False,
            },
        )
        assert notifications_enabled() is True


class TestSetNotifications:
    def test_persists_and_returns(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "settings.json"
        assert set_notifications(False, path=path) is False
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["notifications"] is False

    def test_uses_settings_path_when_path_omitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "settings.json"
        monkeypatch.setattr(tui_prefs, "SETTINGS_PATH", path)
        assert set_notifications(True) is True
        assert json.loads(path.read_text())["notifications"] is True

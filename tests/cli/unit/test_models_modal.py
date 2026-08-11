# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for model profiles CRUD and Models modal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjiuwen_icode.host.profiles import (
    delete_model_profile,
    get_model_profile,
    list_model_profiles,
    save_model_profile,
    switch_model_in_settings,
)


class TestModelProfileCRUD:
    def test_save_list_get_delete(self, tmp_path: Path) -> None:
        models_dir = tmp_path / "models"
        path = save_model_profile(
            {
                "id": "yunwu-kimi",
                "label": "Kimi via Yunwu",
                "provider": "OpenAI",
                "apiBase": "https://example.com/v1",
            },
            models_dir=models_dir,
        )
        assert path.is_file()
        rows = list_model_profiles(models_dir=models_dir)
        assert any(r["id"] == "yunwu-kimi" and not r.get("builtin") for r in rows)
        got = get_model_profile("yunwu-kimi", models_dir=models_dir)
        assert got is not None
        assert got["apiBase"] == "https://example.com/v1"
        assert delete_model_profile("yunwu-kimi", models_dir=models_dir)
        assert get_model_profile("yunwu-kimi", models_dir=models_dir) is None

    def test_no_builtin_profiles(self, tmp_path: Path) -> None:
        rows = list_model_profiles(models_dir=tmp_path / "empty")
        assert rows == []

    def test_unique_copy_id(self, tmp_path: Path) -> None:
        from openjiuwen_icode.host.profiles import unique_model_profile_id

        models_dir = tmp_path / "models"
        save_model_profile(
            {"id": "base", "provider": "OpenAI"},
            models_dir=models_dir,
        )
        assert unique_model_profile_id("base", models_dir=models_dir) == "base-copy"
        save_model_profile(
            {"id": "base-copy", "provider": "OpenAI"},
            models_dir=models_dir,
        )
        assert (
            unique_model_profile_id("base", models_dir=models_dir)
            == "base-copy-2"
        )

    def test_delete_missing(self, tmp_path: Path) -> None:
        assert not delete_model_profile("nope", models_dir=tmp_path / "empty")

    def test_switch_writes_settings(self, tmp_path: Path) -> None:
        models_dir = tmp_path / "models"
        settings = tmp_path / "settings.json"
        settings.write_text("{}", encoding="utf-8")
        save_model_profile(
            {
                "id": "my-model",
                "provider": "OpenAI",
                "apiBase": "https://x/v1",
            },
            models_dir=models_dir,
        )
        updated = switch_model_in_settings(
            "my-model",
            path=settings,
            models_dir=models_dir,
        )
        assert updated["model"] == "my-model"
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["model"] == "my-model"
        assert data["apiBase"] == "https://x/v1"


class TestModelsModal:
    @pytest.mark.asyncio
    async def test_lists_and_use(self, tmp_path: Path) -> None:
        from textual.app import App

        from openjiuwen_icode.tui.screens.models_modal import ModelsModal

        models_dir = tmp_path / "models"
        save_model_profile(
            {
                "id": "demo-model",
                "label": "Demo",
                "provider": "OpenAI",
            },
            models_dir=models_dir,
        )

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ModelsModal(
                        models_dir=models_dir,
                        current_model="demo-model",
                    )
                )

        async with T().run_test() as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, ModelsModal)
            assert any(r["id"] == "demo-model" for r in modal._profiles)
            # Select demo-model and press Use
            modal._load_profile(
                get_model_profile("demo-model", models_dir=models_dir)  # type: ignore[arg-type]
            )
            modal._use_selected()
            # Dismiss result is consumed by push_screen; verify form id
            assert modal.query_one("#field-id").value == "demo-model"

    @pytest.mark.asyncio
    async def test_duplicate_copies_form(self, tmp_path: Path) -> None:
        from textual.app import App

        from openjiuwen_icode.tui.screens.models_modal import ModelsModal

        models_dir = tmp_path / "models"
        save_model_profile(
            {
                "id": "src-model",
                "label": "Source",
                "provider": "OpenAI",
                "apiBase": "https://example.com/v1",
            },
            models_dir=models_dir,
        )

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ModelsModal(
                        models_dir=models_dir,
                        current_model="src-model",
                    )
                )

        async with T().run_test() as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, ModelsModal)
            modal._load_profile(
                get_model_profile("src-model", models_dir=models_dir)  # type: ignore[arg-type]
            )
            modal._duplicate_selected()
            assert modal.query_one("#field-id").value == "src-model-copy"
            assert "copy" in modal.query_one("#field-label").value.lower()
            assert (
                modal.query_one("#field-api-base").value
                == "https://example.com/v1"
            )
            assert modal._creating is True

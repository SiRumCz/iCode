# coding: utf-8
"""Pilot tests for TUI modal screens and status bar."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App

from openjiuwen_icode.host.profiles import save_model_profile
from openjiuwen_icode.tui.screens.approval_modal import AskModal, ApprovalModal
from openjiuwen_icode.tui.screens.confirm_modal import ConfirmModal
from openjiuwen_icode.tui.screens.directory_picker_modal import (
    DirectoryPickerModal,
    default_browse_root,
    path_from_tree_node,
)
from openjiuwen_icode.tui.screens.models_modal import ModelsModal
from openjiuwen_icode.tui.screens.sessions_modal import SessionsModal
from openjiuwen_icode.tui.widgets.status_bar import StatusBar


class TestApprovalAskModals:
    @pytest.mark.asyncio
    async def test_approve_and_reject(self) -> None:
        results: list[object] = []

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ApprovalModal("write_file", {"path": "a.py"}),
                    callback=results.append,
                )

        async with T().run_test() as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, ApprovalModal)
            await pilot.click("#approve")
        assert results and results[0] == (True, "")

        results.clear()

        class T2(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ApprovalModal("bash", {"command": "rm"}),
                    callback=results.append,
                )

        async with T2().run_test() as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, ApprovalModal)
            modal.query_one("#approval-feedback").value = "nope"
            await pilot.click("#reject")
        assert results and results[0] == (False, "nope")

    @pytest.mark.asyncio
    async def test_ask_modal_submit(self) -> None:
        results: list[object] = []

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    AskModal(
                        questions=[
                            {"header": "Q1", "question": "Name?"},
                            "plain",
                        ]
                    ),
                    callback=results.append,
                )

        async with T().run_test() as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, AskModal)
            modal.query_one("#ask-answer").value = "Ada"
            await pilot.click("#ask-submit")
        assert results == ["Ada"]


class TestConfirmModal:
    @pytest.mark.asyncio
    async def test_confirm_and_cancel(self) -> None:
        results: list[object] = []

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ConfirmModal(title="T", message="M", confirm_label="Yes"),
                    callback=results.append,
                )

        async with T().run_test() as pilot:
            await pilot.click("#confirm")
        assert results == [True]

        results.clear()

        class T2(App):
            def on_mount(self) -> None:
                self.push_screen(ConfirmModal(), callback=results.append)

        async with T2().run_test() as pilot:
            await pilot.click("#cancel")
        assert results == [False]


class TestDirectoryPicker:
    def test_default_browse_root(self, tmp_path: Path) -> None:
        d = tmp_path / "dir"
        d.mkdir()
        assert default_browse_root(d) == d.resolve()
        f = d / "file.txt"
        f.write_text("x", encoding="utf-8")
        assert default_browse_root(f) == d.resolve()
        assert default_browse_root(None).is_dir()

    def test_path_from_tree_node(self) -> None:
        assert path_from_tree_node(None) is None

    @pytest.mark.asyncio
    async def test_cancel_and_confirm(self, tmp_path: Path) -> None:
        results: list[object] = []

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    DirectoryPickerModal(
                        start_path=tmp_path,
                        existing_dirs=[str(tmp_path)],
                    ),
                    callback=results.append,
                )

        async with T().run_test(size=(120, 40)) as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, DirectoryPickerModal)
            assert "(already registered)" in str(
                modal.query_one("#selected-path").render()
            )
            modal.action_cancel()
        assert results == [None]

        results.clear()

        class T2(App):
            def on_mount(self) -> None:
                self.push_screen(
                    DirectoryPickerModal(start_path=tmp_path),
                    callback=results.append,
                )

        async with T2().run_test(size=(120, 40)) as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, DirectoryPickerModal)
            modal.action_confirm()
        assert results and results[0]["action"] == "select"
        assert Path(results[0]["path"]).is_dir()


class TestSessionsModalPilot:
    @pytest.mark.asyncio
    async def test_lists_resume_and_close(self) -> None:
        sessions = [
            {
                "id": "cli-aaaa1111",
                "title": "Alpha",
                "updated_at": "2026-08-06T01:00:00+00:00",
                "turns": 2,
                "size_bytes": 100,
                "directory": "/tmp/a",
                "model": "m1",
                "preview": "hello",
            }
        ]
        results: list[object] = []

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    SessionsModal(
                        sessions=sessions,
                        current_session_id="cli-aaaa1111",
                    ),
                    callback=results.append,
                )

        async with T().run_test() as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, SessionsModal)
            assert len(modal._rows) == 1
            await pilot.click("#resume")
        assert results and results[0]["action"] == "resume"

        results.clear()

        class T2(App):
            def on_mount(self) -> None:
                self.push_screen(
                    SessionsModal(sessions=sessions),
                    callback=results.append,
                )

        async with T2().run_test() as pilot:
            await pilot.click("#cancel")
        assert results == [None]

    @pytest.mark.asyncio
    async def test_empty_and_delete(self) -> None:
        deleted: list[str] = []
        sessions = [
            {
                "id": "cli-bbbb2222",
                "title": "Beta",
                "updated_at": "2026-08-06T02:00:00+00:00",
                "turns": 1,
                "size_bytes": 10,
                "directory": "/tmp/b",
                "model": "m",
                "preview": "x",
            }
        ]

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    SessionsModal(
                        sessions=list(sessions),
                        current_session_id="cli-bbbb2222",
                        on_delete=deleted.append,
                    )
                )

        async with T().run_test() as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, SessionsModal)
            modal._on_delete_confirmed(True)
            assert deleted == ["cli-bbbb2222"]
            assert modal._deleted_current is True


class TestModelsModalButtons:
    @pytest.mark.asyncio
    async def test_new_save_use_close(self, tmp_path: Path) -> None:
        models_dir = tmp_path / "models"
        save_model_profile(
            {"id": "demo", "label": "Demo", "provider": "OpenAI"},
            models_dir=models_dir,
        )
        results: list[object] = []

        class T(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ModelsModal(
                        models_dir=models_dir,
                        current_model="demo",
                    ),
                    callback=results.append,
                )

        async with T().run_test(size=(140, 50)) as pilot:
            modal = pilot.app.screen
            assert isinstance(modal, ModelsModal)
            modal._blank_form()
            assert modal._creating is True
            modal.query_one("#field-id").value = "fresh-model"
            modal.query_one("#field-label").value = "Fresh"
            modal._save_form()
            assert any(
                "fresh-model" in p.name for p in models_dir.glob("*.json")
            )
            modal._use_selected()
        assert results and results[0]["action"] == "use"


class TestStatusBar:
    @pytest.mark.asyncio
    async def test_phase_usage_flash(self) -> None:
        class T(App):
            def compose(self):
                yield StatusBar("Ready", id="status")

        async with T().run_test() as pilot:
            bar = pilot.app.query_one(StatusBar)
            bar.set_phase("Thinking")
            bar.set_usage("1.2k")
            assert "Thinking" in str(bar.render())
            bar.flash("Copied")
            bar.restore()
            assert bar.phase == "Thinking"

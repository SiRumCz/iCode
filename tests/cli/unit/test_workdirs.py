# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for multi-workdir registry and slash commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjiuwen_icode.events import EventBus, SystemNotice, UserCommand
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.session_host import SessionHost
from openjiuwen_icode.host.workdirs import (
    WorkdirRegistry,
    format_directories_command_args,
    parse_directories_slash,
)
from openjiuwen_icode.tui.screens.directory_picker_modal import (
    default_browse_root,
)


class TestWorkdirRegistry:
    def test_add_list_use_rm(self, tmp_path: Path) -> None:
        a = tmp_path / "proj-a"
        b = tmp_path / "proj-b"
        a.mkdir()
        b.mkdir()
        store = tmp_path / "workdirs.json"
        reg = WorkdirRegistry(store_path=store)

        reg.add(str(a))
        assert reg.primary == str(a.resolve())
        reg.add(str(b))
        assert len(reg.dirs) == 2

        text = reg.format_list()
        assert "*" in text
        assert str(a.resolve()) in text

        reg.use("2")
        assert reg.primary == str(b.resolve())

        with pytest.raises(ValueError, match="primary"):
            reg.remove("2")

        reg.use("1")
        removed = reg.remove("2")
        assert removed == str(b.resolve())
        assert len(reg.dirs) == 1

        # reload
        other = WorkdirRegistry.load(store)
        assert other.primary == str(a.resolve())
        assert other.dirs == [str(a.resolve())]

    def test_ensure_seed(self, tmp_path: Path) -> None:
        proj = tmp_path / "seed"
        proj.mkdir()
        reg = WorkdirRegistry(store_path=tmp_path / "w.json")
        assert reg.ensure_seed(str(proj))
        assert reg.primary == str(proj.resolve())
        assert not reg.ensure_seed(str(proj))


class TestWorkdirsSlash:
    @pytest.mark.asyncio
    async def test_workdirs_add_use_aliases(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        bus = EventBus()
        backend = DemoBackend()
        reg = WorkdirRegistry(store_path=tmp_path / "w.json")
        host = SessionHost(
            bus, backend, session_id="wd", workdirs=reg
        )
        notices: list[SystemNotice] = []

        async def on_notice(event: SystemNotice) -> None:
            notices.append(event)

        await bus.subscribe(SystemNotice, on_notice)
        await host.start()

        await bus.publish(
            UserCommand(name="workdirs-add", args=str(a), session_id="wd")
        )
        assert any(str(a.resolve()) in n.text for n in notices)

        await bus.publish(
            UserCommand(
                name="workdirs",
                args=f"add {b}",
                session_id="wd",
            )
        )
        assert host.workdirs.dirs == [
            str(a.resolve()),
            str(b.resolve()),
        ]

        await bus.publish(
            UserCommand(name="workdirs-use", args="2", session_id="wd")
        )
        assert host.workdirs.primary == str(b.resolve())

        await bus.publish(UserCommand(name="workdirs", session_id="wd"))
        assert any("Directories" in n.text for n in notices)

        await bus.publish(
            UserCommand(name="directories-add", args=str(a), session_id="wd")
        )
        assert any("directories" in n.text.lower() for n in notices[-1:])

        await host.stop()


class TestParseDirectoriesSlash:
    def test_list_and_add(self) -> None:
        assert parse_directories_slash("/directories") == ("", "")
        assert parse_directories_slash("/workdirs add") == ("add", "")
        assert parse_directories_slash("/directories add ~/src") == (
            "add",
            "~/src",
        )
        assert parse_directories_slash("/directories-add /tmp") == (
            "add",
            "/tmp",
        )
        assert parse_directories_slash("/help") is None

    def test_format_args(self) -> None:
        assert format_directories_command_args("", "") == ""
        assert format_directories_command_args("add", "/tmp/x") == "add /tmp/x"
        assert format_directories_command_args("use", "2") == "use 2"


class TestDefaultBrowseRoot:
    def test_prefers_existing_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "repo"
        d.mkdir()
        assert default_browse_root(d) == d.resolve()

    def test_falls_back_to_parent(self, tmp_path: Path) -> None:
        d = tmp_path / "repo" / "file.txt"
        d.parent.mkdir(parents=True)
        d.write_text("x")
        assert default_browse_root(d) == d.parent.resolve()

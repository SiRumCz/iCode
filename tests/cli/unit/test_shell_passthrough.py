# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for local shell passthrough helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjiuwen_icode.shell_passthrough import (
    is_shell_toggle,
    run_shell_command,
    shell_command_from_bang_line,
)


class TestShellToggleParse:
    def test_ascii_and_fullwidth_toggle(self) -> None:
        assert is_shell_toggle("!")
        assert is_shell_toggle("！")
        assert is_shell_toggle("  !  ")
        assert not is_shell_toggle("!ls")
        assert not is_shell_toggle("")
        assert not is_shell_toggle("hello")

    def test_bang_line_one_shot(self) -> None:
        assert shell_command_from_bang_line("!ls -la") == "ls -la"
        assert shell_command_from_bang_line("！pwd") == "pwd"
        assert shell_command_from_bang_line("!") == ""
        assert shell_command_from_bang_line("！") == ""
        assert shell_command_from_bang_line("ls") is None
        assert shell_command_from_bang_line("") is None


class TestRunShellCommand:
    @pytest.mark.asyncio
    async def test_echo_ok(self) -> None:
        result = await run_shell_command("echo hello-shell")
        assert result.returncode == 0
        assert "hello-shell" in result.stdout
        assert result.stderr == ""

    @pytest.mark.asyncio
    async def test_nonzero_exit(self) -> None:
        result = await run_shell_command("exit 42")
        assert result.returncode == 42


class TestPersistShellTurn:
    def test_formats_and_persists(self, tmp_path: Path) -> None:
        from openjiuwen_icode.shell_passthrough import (
            ShellResult,
            format_shell_result_message,
            format_shell_user_message,
            persist_shell_turn,
        )
        from openjiuwen_icode.storage.session_store import SessionStore

        store = SessionStore(store_dir=tmp_path)
        store.new_session("shell-hist", "test")
        result = ShellResult(
            command="echo hi",
            returncode=0,
            stdout="hi\n",
            stderr="",
        )
        assert format_shell_user_message("echo hi") == "$ echo hi"
        assert "[shell]" in format_shell_result_message(result)
        persist_shell_turn(store, result)
        assert store.current is not None
        assert len(store.current.messages) == 2
        assert store.current.messages[0].role == "user"
        assert store.current.messages[0].content == "$ echo hi"
        assert store.current.messages[1].role == "assistant"
        assert "hi" in store.current.messages[1].content

    def test_persist_noop_without_store(self) -> None:
        from openjiuwen_icode.shell_passthrough import (
            ShellResult,
            persist_shell_turn,
        )

        persist_shell_turn(
            None,
            ShellResult(command="x", returncode=0, stdout="", stderr=""),
        )

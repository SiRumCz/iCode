# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""CLI interactive routing (P0 T-02)."""

from __future__ import annotations

from click.testing import CliRunner

from openjiuwen_icode.cli import (
    CLIOptions,
    _run_interactive,
    cli,
)


class TestInteractiveRouting:
    def test_chat_help_exposes_repl_escape_hatch(self) -> None:
        result = CliRunner().invoke(cli, ["chat", "--help"])
        assert result.exit_code == 0
        assert "--repl" in result.output
        assert "EventBus" in result.output or "TUI" in result.output

    def test_tui_help_is_default_shell(self) -> None:
        result = CliRunner().invoke(cli, ["tui", "--help"])
        assert result.exit_code == 0
        assert "demo" in result.output.lower()

    def test_force_repl_rejects_demo(self) -> None:
        import asyncio
        import pytest

        opts = CLIOptions()
        with pytest.raises(ValueError, match="--demo"):
            asyncio.run(
                _run_interactive(opts, demo=True, force_repl=True)
            )

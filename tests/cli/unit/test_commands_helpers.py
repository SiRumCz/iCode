# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Helpers for SessionHost slash commands (_format_mcp_tools, theme, notifications)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openjiuwen_icode.events import SystemNotice
from openjiuwen_icode.host import commands as cmd_mod


def test_format_mcp_tools_empty() -> None:
    with patch("openjiuwen.core.runner.Runner") as runner:
        runner.resource_mgr = None
        text = cmd_mod._format_mcp_tools()
    assert "No live MCP tools" in text


def test_format_mcp_tools_lists_and_filters() -> None:
    tool_ids = [f"srv.tool_{i}" for i in range(42)]
    resource = SimpleNamespace(
        config=SimpleNamespace(server_name="demo"),
        tool_ids=tool_ids,
    )
    resources = {"sid-1": resource}

    with patch("openjiuwen.core.runner.Runner") as runner:
        runner.resource_mgr = SimpleNamespace(
            tool_mgr=SimpleNamespace(_mcp_server_resources=resources)
        )
        text = cmd_mod._format_mcp_tools()
        filtered = cmd_mod._format_mcp_tools(filter_name="other")
        matched = cmd_mod._format_mcp_tools(filter_name="demo")

    assert "MCP tools (live):" in text
    assert "demo" in text
    assert "+2 more" in text
    assert "No live MCP server matching" in filtered
    assert "tool_0" in matched


def test_format_mcp_tools_exception() -> None:
    class _Boom:
        @property
        def resource_mgr(self):  # noqa: ANN201
            raise RuntimeError("boom")

    with patch("openjiuwen.core.runner.Runner", _Boom()):
        text = cmd_mod._format_mcp_tools()
    assert "Failed to list MCP tools" in text
    assert "boom" in text


@pytest.mark.asyncio
async def test_cmd_theme_show_and_set(tmp_path, monkeypatch) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "openjiuwen_icode.features.tui_prefs.SETTINGS_PATH",
        settings,
    )
    monkeypatch.setattr(
        "openjiuwen_icode.agent.config.SETTINGS_PATH",
        settings,
    )
    host = MagicMock()
    host._bus = MagicMock()
    host._bus.publish = AsyncMock()

    await cmd_mod._cmd_theme(host, "", "s1")
    notice = host._bus.publish.await_args.args[0]
    assert isinstance(notice, SystemNotice)
    assert "Theme:" in notice.text

    await cmd_mod._cmd_theme(host, "dark", "s1")
    notice2 = host._bus.publish.await_args.args[0]
    assert "dark" in notice2.text


@pytest.mark.asyncio
async def test_cmd_notifications_toggle(tmp_path, monkeypatch) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "openjiuwen_icode.features.tui_prefs.SETTINGS_PATH",
        settings,
    )
    monkeypatch.setattr(
        "openjiuwen_icode.agent.config.SETTINGS_PATH",
        settings,
    )
    host = MagicMock()
    host._bus = MagicMock()
    host._bus.publish = AsyncMock()

    await cmd_mod._cmd_notifications(host, "", "s1")
    assert "Notifications:" in host._bus.publish.await_args.args[0].text

    await cmd_mod._cmd_notifications(host, "off", "s1")
    assert "disabled" in host._bus.publish.await_args.args[0].text

    await cmd_mod._cmd_notifications(host, "on", "s1")
    assert "enabled" in host._bus.publish.await_args.args[0].text

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for /agents use profile switching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openjiuwen_icode.host.profiles import (
    get_agent_profile,
    switch_agent_profile_in_settings,
)


def test_get_agent_profile_code() -> None:
    row = get_agent_profile("code")
    assert row is not None
    assert row["id"] == "code"


def test_switch_agent_profile_persists_settings(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text('{"model":"gpt-4o"}\n', encoding="utf-8")
    pid = switch_agent_profile_in_settings("code", path=settings)
    assert pid == "code"
    import json

    data = json.loads(settings.read_text())
    assert data["agent_profile"] == "code"


@pytest.mark.asyncio
async def test_cmd_agents_use_rebuilds(monkeypatch: pytest.MonkeyPatch) -> None:
    from openjiuwen_icode.host import commands as cmd_mod
    from openjiuwen_icode.host.commands import _cmd_agents

    monkeypatch.setattr(
        cmd_mod,
        "switch_agent_profile_in_settings",
        lambda pid, path=None: pid,
    )
    rebuild = AsyncMock(return_value=True)
    monkeypatch.setattr(cmd_mod, "rebuild_backend_agent", rebuild)

    host = MagicMock()
    host.turn_active = False
    host._backend = MagicMock()
    host.session_store = None
    host.workdirs = MagicMock(primary="")
    bus = MagicMock()
    bus.publish = AsyncMock()
    host._bus = bus

    await _cmd_agents(host, "use code", "cli-test")

    rebuild.assert_awaited_once()
    assert bus.publish.await_count >= 2

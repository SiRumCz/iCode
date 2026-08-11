# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""TUI /quit and /exit must exit the app (same as Ctrl+Q)."""

from __future__ import annotations

import pytest

from openjiuwen_icode.events import EventBus
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.session_host import SessionHost
from openjiuwen_icode.tui.app import CodingAssistantApp, _parse_slash


def test_parse_quit_aliases() -> None:
    assert _parse_slash("/quit") == ("quit", "")
    assert _parse_slash("/exit") == ("exit", "")
    assert _parse_slash("/QUIT now") == ("quit", "now")


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", ["/quit", "/exit"])
async def test_slash_quit_exits_app(cmd: str) -> None:
    bus = EventBus()
    host = SessionHost(bus, DemoBackend(), session_id="quit-test")
    app = CodingAssistantApp.create(bus=bus, host=host)

    async with app.run_test() as pilot:
        await pilot.app._submit_text(cmd)
        assert pilot.app._exit is True

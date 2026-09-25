# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""TUI smoke via Textual Pilot + DemoBackend (no LLM)."""

from __future__ import annotations

import pytest

from openjiuwen_icode.events import EventBus, SystemNotice
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.session_host import SessionHost
from openjiuwen_icode.tui.app import CodingAssistantApp


pytestmark = pytest.mark.smoke


@pytest.mark.asyncio
async def test_tui_demo_help_and_quit() -> None:
    bus = EventBus()
    host = SessionHost(bus, DemoBackend(), session_id="tui-smoke")
    await host.start()
    notices: list[SystemNotice] = []

    async def _on_notice(event: SystemNotice) -> None:
        notices.append(event)

    await bus.subscribe(SystemNotice, _on_notice)
    app = CodingAssistantApp.create(bus=bus, host=host)
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.app._submit_text("/help")
            await pilot.pause()
            help_notices = [n for n in notices if n.kind == "help"]
            assert help_notices
            assert "/quit" in help_notices[-1].text

            await pilot.app._submit_text("/quit")
            assert pilot.app._exit is True
    finally:
        await host.stop()

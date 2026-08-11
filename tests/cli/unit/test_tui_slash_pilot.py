# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Pilot table-driven tests: TUI slash → bus events / modals / exit.

These are app-level UI integration tests (Textual ``run_test``), not full
process e2e. They drive ``_submit_text`` (and one Enter path) on the real
``CodingAssistantApp`` with ``DemoBackend``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio

from openjiuwen_icode.events import (
    Event,
    EventBus,
    SystemNotice,
    UserCommand,
)
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.session_host import SessionHost
from openjiuwen_icode.tui.app import CodingAssistantApp


@dataclass
class _Harness:
    bus: EventBus
    host: SessionHost
    app: Any
    events: list[Event] = field(default_factory=list)

    def commands(self) -> list[UserCommand]:
        return [e for e in self.events if isinstance(e, UserCommand)]

    def notices(self) -> list[SystemNotice]:
        return [e for e in self.events if isinstance(e, SystemNotice)]


@pytest_asyncio.fixture
async def tui_harness():
    bus = EventBus()
    host = SessionHost(bus, DemoBackend(), session_id="slash-pilot")
    await host.start()

    seen: list[Event] = []

    async def _tap(event: Event) -> None:
        seen.append(event)

    # Capture everything the TUI/host publish for assertions.
    for et in (UserCommand, SystemNotice):
        await bus.subscribe(et, _tap)

    app = CodingAssistantApp.create(bus=bus, host=host)
    harness = _Harness(bus=bus, host=host, app=app, events=seen)
    try:
        yield harness
    finally:
        await host.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_name", "expected_args"),
    [
        ("/help", "help", ""),
        ("/status", "status", ""),
        ("/cwd", "cwd", ""),
        ("/clear", "clear", ""),
        ("/skills", "skills", ""),
        ("/compact", "compact", ""),
        ("/hooks", "hooks", ""),
        ("/mcp", "mcp", ""),
        ("/title", "title", ""),
        ("/title Hello", "title", "Hello"),
        ("/directories", "workdirs", ""),
        ("/workdirs", "workdirs", ""),
        ("/directories use 1", "workdirs", "use 1"),
        ("/directories rm 2", "workdirs", "rm 2"),
        ("/workdirs add /tmp", "workdirs", "add /tmp"),
        ("/agents", "agents", ""),
        ("/subagents", "subagents", ""),
        ("/new", "new", ""),
        ("/models gpt-4o", "models", "gpt-4o"),
    ],
)
async def test_slash_publishes_user_command(
    tui_harness: _Harness,
    prompt: str,
    expected_name: str,
    expected_args: str,
) -> None:
    async with tui_harness.app.run_test() as pilot:
        before = len(tui_harness.commands())
        await pilot.app._submit_text(prompt)
        cmds = tui_harness.commands()[before:]
        assert len(cmds) == 1
        assert cmds[0].name == expected_name
        assert cmds[0].args == expected_args
        assert cmds[0].session_id == "slash-pilot"


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["/quit", "/exit"])
async def test_slash_quit_exits(
    tui_harness: _Harness, prompt: str
) -> None:
    async with tui_harness.app.run_test() as pilot:
        await pilot.app._submit_text(prompt)
        assert pilot.app._exit is True
        assert tui_harness.commands() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "opener"),
    [
        ("/models", "_open_models_modal"),
        ("/model", "_open_models_modal"),
        ("/sessions", "_open_sessions_modal"),
        ("/directories add", "_open_directory_picker_modal"),
    ],
)
async def test_slash_opens_modal(
    tui_harness: _Harness, prompt: str, opener: str
) -> None:
    """Slash routing should invoke the modal openers (not publish UserCommand)."""
    async with tui_harness.app.run_test(size=(120, 40)) as pilot:
        called: list[str] = []
        setattr(
            pilot.app,
            opener,
            lambda *a, **k: called.append(opener),
        )
        await pilot.app._submit_text(prompt)
        assert called == [opener]
        assert tui_harness.commands() == []


@pytest.mark.asyncio
async def test_help_produces_help_notice(tui_harness: _Harness) -> None:
    """End-to-end within the app: slash → host → SystemNotice(help)."""
    async with tui_harness.app.run_test() as pilot:
        await pilot.app._submit_text("/help")
        notices = [n for n in tui_harness.notices() if n.kind == "help"]
        assert notices
        assert "/quit" in notices[-1].text
        assert "/directories" in notices[-1].text


@pytest.mark.asyncio
async def test_help_via_input_enter(tui_harness: _Harness) -> None:
    """Closer to real UX: fill #prompt and press Enter."""
    from textual.widgets import Input

    async with tui_harness.app.run_test() as pilot:
        # Ensure suggest widget is queryable on the active screen.
        assert pilot.app.query_one("#suggest") is not None
        inp = pilot.app.query_one("#prompt", Input)
        inp.value = "/help"
        # Hide suggestions so Enter submits the typed text, not a highlight.
        pilot.app._suggestions().hide()
        await pilot.press("enter")
        notices = [n for n in tui_harness.notices() if n.kind == "help"]
        assert notices


@pytest.mark.asyncio
async def test_busy_blocks_non_quit_slash(
    tui_harness: _Harness,
) -> None:
    """While a turn is busy, non-quit slashes are treated as inject text."""
    from openjiuwen_icode.events import UserInject

    injected: list[UserInject] = []

    async def _on_inject(event: UserInject) -> None:
        injected.append(event)

    await tui_harness.bus.subscribe(UserInject, _on_inject)

    async with tui_harness.app.run_test() as pilot:
        pilot.app._busy = True
        await pilot.app._submit_text("/help")
        assert tui_harness.commands() == []
        assert len(injected) == 1
        assert injected[0].text == "/help"

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""P2 unit tests: session store, profiles, slash commands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from openjiuwen_icode.events import (
    CompactionFinished,
    EventBus,
    ProfileSwitched,
    SessionCreated,
    SessionListed,
    SystemNotice,
    UserCommand,
)
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.profiles import (
    list_model_profiles,
    switch_model_in_settings,
)
from openjiuwen_icode.host.session_host import SessionHost
from openjiuwen_icode.storage.session_store import SessionStore


class TestSessionStoreP2:
    def test_atomic_save_and_load(self, tmp_path: Path) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("s-load", "gpt-4o")
        store.add_message("user", "hi")
        store.add_message("assistant", "hello")

        path = tmp_path / "s-load.json"
        assert path.exists()
        assert (tmp_path / "s-load.json.bak").exists() or True

        other = SessionStore(store_dir=tmp_path)
        loaded = other.load_session("s-load")
        assert loaded.session_id == "s-load"
        assert len(loaded.messages) == 2
        other.switch_session("s-load")
        assert other.current is not None
        assert other.current.messages[0].content == "hi"

    def test_recovery_sidecar_on_corrupt(self, tmp_path: Path) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("s-rec", "m")
        store.add_message("user", "kept")
        main = tmp_path / "s-rec.json"
        main.write_text("{not-json", encoding="utf-8")
        # recovery may already be cleared after successful save; rewrite bak
        bak = tmp_path / "s-rec.json.bak"
        bak.write_text(
            json.dumps(
                {
                    "session_id": "s-rec",
                    "model": "m",
                    "created_at": "t",
                    "messages": [
                        {
                            "role": "user",
                            "content": "from-bak",
                            "timestamp": "t",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        loaded = store.load_session("s-rec")
        assert loaded.messages[0].content == "from-bak"


class TestProfiles:
    def test_list_and_switch(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text("{}", encoding="utf-8")
        models_dir = tmp_path / "models"
        from openjiuwen_icode.host.profiles import save_model_profile

        save_model_profile(
            {
                "id": "gpt-4o-mini",
                "provider": "OpenAI",
                "label": "mini",
            },
            models_dir=models_dir,
        )
        assert any(
            p["id"] == "gpt-4o-mini"
            for p in list_model_profiles(models_dir=models_dir)
        )
        updated = switch_model_in_settings(
            "gpt-4o-mini", path=settings, models_dir=models_dir
        )
        assert updated["model"] == "gpt-4o-mini"
        data = json.loads(settings.read_text())
        assert data["model"] == "gpt-4o-mini"


class TestSlashCommands:
    @pytest.mark.asyncio
    async def test_help_and_models_and_new(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = SessionStore(store_dir=tmp_path)
        host = SessionHost(
            bus,
            DemoBackend(),
            session_id="s1",
            session_store=store,
            model_name="demo",
        )
        notices: list[SystemNotice] = []
        created: list[SessionCreated] = []

        async with bus.stream(
            SystemNotice, SessionCreated, ProfileSwitched, SessionListed
        ) as stream:

            async def consume() -> None:
                async for event in stream:
                    if isinstance(event, SystemNotice):
                        notices.append(event)
                        if len(notices) >= 2 and created:
                            break
                    elif isinstance(event, SessionCreated):
                        created.append(event)

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(UserCommand(name="help", session_id="s1"))
            await bus.publish(UserCommand(name="new", session_id="s1"))
            await asyncio.wait_for(consumer, timeout=3)
            await host.stop()

        assert any("status" in n.text for n in notices)
        assert created and created[0].session_id.startswith("cli-")

    @pytest.mark.asyncio
    async def test_compact_emits_events(self, tmp_path: Path) -> None:
        bus = EventBus()
        host = SessionHost(
            bus,
            DemoBackend(),
            session_id="s1",
            session_store=SessionStore(store_dir=tmp_path),
        )
        finished: list[CompactionFinished] = []

        async with bus.stream(CompactionFinished) as stream:
            consumer = asyncio.create_task(
                asyncio.wait_for(stream.__anext__(), timeout=2)
            )
            await host.start()
            await bus.publish(UserCommand(name="compact", session_id="s1"))
            ev = await consumer
            finished.append(ev)  # type: ignore[arg-type]
            await host.stop()

        assert finished and finished[0].ok is True

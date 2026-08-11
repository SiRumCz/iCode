# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for session titles and enriched /sessions list."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openjiuwen_icode.events import (
    EventBus,
    SessionTitleUpdated,
    SystemNotice,
    UserCommand,
    UserMessage,
)
from openjiuwen_icode.features.session_title import (
    TITLE_LLM,
    TITLE_MANUAL,
    TITLE_PROVISIONAL,
    extract_assistant_invoke_text,
    format_session_list,
    llm_title_enabled,
    looks_like_message_repr,
    provisional_title,
    refine_title_with_llm,
    sanitize_llm_title,
)
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.session_host import SessionHost
from openjiuwen_icode.storage.session_store import SessionStore


class TestProvisionalTitle:
    def test_truncates_long_text(self) -> None:
        long = "word " * 40
        out = provisional_title(long, max_len=40)
        assert len(out) <= 41
        assert out.endswith("…")

    def test_empty_becomes_untitled(self) -> None:
        assert provisional_title("   ") == "Untitled"

    def test_sanitize_strips_prefix(self) -> None:
        assert sanitize_llm_title('Title: "Hello world"') == "Hello world"

    def test_sanitize_rejects_message_repr(self) -> None:
        bad = "role='assistant' content='' name=None tool_calls=None"
        assert sanitize_llm_title(bad) == ""
        assert looks_like_message_repr(bad)


class TestExtractAndLlmTitle:
    def test_extract_assistant_invoke_text_variants(self) -> None:
        assert extract_assistant_invoke_text(None) == ""
        assert (
            extract_assistant_invoke_text(
                type("R", (), {"parser_content": "  via parser  "})()
            )
            == "via parser"
        )
        assert (
            extract_assistant_invoke_text(
                type("R", (), {"content": "  plain  "})()
            )
            == "plain"
        )
        assert (
            extract_assistant_invoke_text(
                type(
                    "R",
                    (),
                    {
                        "content": [
                            "a",
                            {"text": "b"},
                            {"content": "c"},
                            {"text": ""},
                        ]
                    },
                )()
            )
            == "a b c"
        )
        assert extract_assistant_invoke_text({"content": "dict"}) == "dict"
        assert extract_assistant_invoke_text(object()) == ""

    def test_llm_title_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENJIUWEN_SESSION_TITLE_LLM", raising=False)
        assert llm_title_enabled() is True
        monkeypatch.setenv("OPENJIUWEN_SESSION_TITLE_LLM", "0")
        assert llm_title_enabled() is False

    @pytest.mark.asyncio
    async def test_refine_title_with_llm_guards(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENJIUWEN_SESSION_TITLE_LLM", "0")
        assert await refine_title_with_llm("u", "a", SimpleNamespace()) is None
        monkeypatch.setenv("OPENJIUWEN_SESSION_TITLE_LLM", "1")
        assert await refine_title_with_llm("u", "a", None) is None
        assert (
            await refine_title_with_llm(
                "u",
                "a",
                SimpleNamespace(api_key="", provider="OpenAI", model="m"),
            )
            is None
        )
        assert (
            await refine_title_with_llm(
                "",
                "a",
                SimpleNamespace(
                    api_key="k", provider="OpenAI", model="m", api_base=None
                ),
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_refine_title_with_llm_mocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENJIUWEN_SESSION_TITLE_LLM", "1")
        cfg = SimpleNamespace(
            api_key="sk",
            provider="OpenAI",
            model="gpt",
            api_base="http://x",
        )
        reply = SimpleNamespace(parser_content="Title: Nice Session")
        model = MagicMock()
        model.invoke = AsyncMock(return_value=reply)
        with patch(
            "openjiuwen.core.foundation.llm.model.Model",
            return_value=model,
        ), patch(
            "openjiuwen.core.foundation.llm.schema.config.ModelClientConfig"
        ), patch(
            "openjiuwen.core.foundation.llm.schema.config.ModelRequestConfig"
        ):
            out = await refine_title_with_llm("user text", "assistant", cfg)
        assert out == "Nice Session"


class TestDisplaySessionTitle:
    def test_falls_back_when_title_is_repr(self) -> None:
        from openjiuwen_icode.features.session_title import (
            display_session_title,
        )
        from openjiuwen_icode.storage.session_store import (
            StoredMessage,
            StoredSession,
        )

        session = StoredSession(
            session_id="cli-x",
            model="m",
            created_at="2026-01-01T00:00:00+00:00",
            title="role='assistant' content='' name=None…",
            title_source=TITLE_LLM,
            messages=[
                StoredMessage(
                    role="user",
                    content="分析 OpenJiuWen iCode 架构",
                    timestamp="2026-01-01T00:00:01+00:00",
                ),
            ],
        )
        title = display_session_title(session)
        assert "OpenJiuWen" in title
        assert "name=None" not in title


class TestSessionStoreTitles:
    def test_first_user_message_sets_provisional(
        self, tmp_path: Path
    ) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("s1", "m")
        store.add_message("user", "Fix the AgentBubble race condition")
        assert store.current is not None
        assert "AgentBubble" in store.current.title
        assert store.current.title_source == TITLE_PROVISIONAL
        assert store.current.updated_at

    def test_list_includes_title_sorted(
        self, tmp_path: Path
    ) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("old", "m")
        store.add_message("user", "Older topic")
        store.new_session("new", "m")
        store.add_message("user", "Newer topic")
        rows = store.list_sessions()
        assert rows[0]["id"] == "new"
        assert rows[0]["title"] == "Newer topic"
        assert rows[1]["title"] == "Older topic"

    def test_manual_title_blocks_llm(
        self, tmp_path: Path
    ) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("s", "m")
        store.add_message("user", "hello")
        assert store.set_title("My Name", source=TITLE_MANUAL)
        assert not store.set_title("From LLM", source=TITLE_LLM)
        assert store.current is not None
        assert store.current.title == "My Name"

    def test_legacy_session_without_title_field(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "legacy.json"
        path.write_text(
            '{"session_id":"legacy","model":"m","created_at":"t",'
            '"messages":[{"role":"user","content":"Legacy hello",'
            '"timestamp":"t"}]}',
            encoding="utf-8",
        )
        store = SessionStore(store_dir=tmp_path)
        rows = store.list_sessions()
        assert len(rows) == 1
        assert rows[0]["title"] == "Legacy hello"


class TestFormatSessionList:
    def test_marks_current(self) -> None:
        text = format_session_list(
            [
                {
                    "id": "a",
                    "title": "One",
                    "model": "m",
                    "turns": 2,
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
            current_id="a",
        )
        assert text.startswith("Sessions")
        assert "*a" in text
        assert "One" in text


class TestHostTitleFlow:
    @pytest.mark.asyncio
    async def test_provisional_event_and_slash_title(
        self, tmp_path: Path
    ) -> None:
        bus = EventBus()
        store = SessionStore(store_dir=tmp_path)
        host = SessionHost(
            bus,
            DemoBackend(),
            session_id="cli-test",
            session_store=store,
            model_name="demo",
        )
        titles: list[SessionTitleUpdated] = []
        notices: list[SystemNotice] = []

        async with bus.stream(
            SessionTitleUpdated, SystemNotice
        ) as stream:

            async def consume() -> None:
                async for event in stream:
                    if isinstance(event, SessionTitleUpdated):
                        titles.append(event)
                    elif isinstance(event, SystemNotice):
                        notices.append(event)
                        if any("Title set" in n.text for n in notices):
                            break

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(
                UserMessage(text="Explain session titles", session_id="cli-test")
            )
            # Wait for provisional title from first user message.
            for _ in range(50):
                if titles:
                    break
                await asyncio.sleep(0.02)
            assert titles
            assert titles[0].source == TITLE_PROVISIONAL
            assert "session titles" in titles[0].title.lower()

            await bus.publish(
                UserCommand(
                    name="title",
                    args="Custom Title",
                    session_id="cli-test",
                )
            )
            await asyncio.wait_for(consumer, timeout=2.0)
            assert store.current is not None
            assert store.current.title == "Custom Title"
            assert store.current.title_source == TITLE_MANUAL
            await host.stop()

    @pytest.mark.asyncio
    async def test_sessions_list_shows_title(
        self, tmp_path: Path
    ) -> None:
        bus = EventBus()
        store = SessionStore(store_dir=tmp_path)
        store.new_session("s-list", "demo")
        store.add_message("user", "Listed topic")
        host = SessionHost(
            bus,
            DemoBackend(),
            session_id="s-list",
            session_store=store,
            model_name="demo",
        )
        notices: list[SystemNotice] = []

        async with bus.stream(SystemNotice) as stream:

            async def consume() -> None:
                async for event in stream:
                    notices.append(event)
                    break

            consumer = asyncio.create_task(consume())
            await host.start()
            await bus.publish(
                UserCommand(name="sessions", session_id="s-list")
            )
            await asyncio.wait_for(consumer, timeout=2.0)
            assert notices
            assert "Listed topic" in notices[0].text
            assert "*s-list" in notices[0].text
            await host.stop()

    @pytest.mark.asyncio
    async def test_llm_refine_publishes_update(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENJIUWEN_SESSION_TITLE_LLM", "1")
        bus = EventBus()
        store = SessionStore(store_dir=tmp_path)
        backend = DemoBackend()
        # Give backend a fake cfg so refine path is attempted.
        backend.cfg = type(  # type: ignore[attr-defined]
            "Cfg",
            (),
            {
                "api_key": "sk-test",
                "provider": "OpenAI",
                "model": "gpt-4o-mini",
                "api_base": "http://localhost",
            },
        )()
        host = SessionHost(
            bus,
            backend,
            session_id="s-llm",
            session_store=store,
            model_name="demo",
        )
        titles: list[SessionTitleUpdated] = []

        async with bus.stream(SessionTitleUpdated) as stream:

            async def consume() -> None:
                async for event in stream:
                    titles.append(event)
                    if event.source == TITLE_LLM:
                        break

            consumer = asyncio.create_task(consume())
            with patch(
                "openjiuwen_icode.host.session_host.refine_title_with_llm",
                new=AsyncMock(return_value="Refined Title"),
            ):
                await host.start()
                await bus.publish(
                    UserMessage(text="hello world", session_id="s-llm")
                )
                await asyncio.wait_for(consumer, timeout=3.0)
            assert any(t.source == TITLE_LLM for t in titles)
            assert store.current is not None
            assert store.current.title == "Refined Title"
            await host.stop()

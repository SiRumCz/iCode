# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Unit tests for non-interactive UI runner helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from openjiuwen_icode.agent.config import CLIConfig
from openjiuwen_icode.ui import runner as runner_mod
from openjiuwen_icode.ui.renderer import CHUNK_ANSWER, CHUNK_LLM_OUTPUT
from openjiuwen_icode.ui.runner import (
    _output_json,
    _output_stream_json,
    _print_error,
    run_once,
)


async def _aiter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


class TestOutputJson:
    @pytest.mark.asyncio
    async def test_collects_llm_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        written: list[str] = []
        monkeypatch.setattr(
            runner_mod, "_write_terminal", lambda t: written.append(t)
        )
        chunks = [
            SimpleNamespace(
                type=CHUNK_LLM_OUTPUT,
                payload={"content": "Hello"},
            ),
            SimpleNamespace(
                type=CHUNK_LLM_OUTPUT,
                payload={"content": " world"},
            ),
            SimpleNamespace(
                type=CHUNK_ANSWER,
                payload={"content": "ignored"},
            ),
        ]
        cfg = CLIConfig(api_key="k", model="gpt-test")
        code = await _output_json(_aiter(chunks), cfg)
        assert code == 0
        payload = json.loads("".join(written).strip())
        assert payload["result"] == "Hello world"
        assert payload["chunks"] == 3
        assert payload["model"] == "gpt-test"

    @pytest.mark.asyncio
    async def test_falls_back_to_answer_without_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        written: list[str] = []
        monkeypatch.setattr(
            runner_mod, "_write_terminal", lambda t: written.append(t)
        )
        chunks = [
            SimpleNamespace(
                type=CHUNK_ANSWER,
                payload={"content": "final"},
            ),
        ]
        cfg = CLIConfig(api_key="k", model="m")
        code = await _output_json(_aiter(chunks), cfg)
        assert code == 0
        payload = json.loads("".join(written).strip())
        assert payload["result"] == "final"
        assert payload["chunks"] == 1


class TestOutputStreamJson:
    @pytest.mark.asyncio
    async def test_writes_jsonl_lines(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        written: list[str] = []
        monkeypatch.setattr(
            runner_mod, "_write_terminal", lambda t: written.append(t)
        )
        chunks = [
            SimpleNamespace(
                type="llm_output",
                index=0,
                payload={"content": "a"},
            ),
            SimpleNamespace(
                type="message",
                index=1,
                payload=123,
            ),
        ]
        code = await _output_stream_json(_aiter(chunks))
        assert code == 0
        lines = [
            json.loads(part)
            for part in "".join(written).splitlines()
            if part.strip()
        ]
        assert lines[0] == {
            "type": "llm_output",
            "index": 0,
            "payload": {"content": "a"},
        }
        assert lines[1]["payload"] == "123"


class TestPrintError:
    def test_rate_limit_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed: list[str] = []

        class FakeConsole:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def print(self, msg: str) -> None:
                printed.append(msg)

        monkeypatch.setattr(runner_mod, "Console", FakeConsole)
        _print_error(RuntimeError("rate_limit exceeded"))
        assert "Rate limited" in printed[0]

    def test_auth_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed: list[str] = []

        class FakeConsole:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def print(self, msg: str) -> None:
                printed.append(msg)

        monkeypatch.setattr(runner_mod, "Console", FakeConsole)
        _print_error(RuntimeError("authentication failed 401"))
        assert "API Key invalid" in printed[0]

    def test_context_length_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed: list[str] = []

        class FakeConsole:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def print(self, msg: str) -> None:
                printed.append(msg)

        monkeypatch.setattr(runner_mod, "Console", FakeConsole)
        _print_error(RuntimeError("context_length exceeded"))
        assert "Context too long" in printed[0]

    def test_timeout_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed: list[str] = []

        class FakeConsole:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def print(self, msg: str) -> None:
                printed.append(msg)

        monkeypatch.setattr(runner_mod, "Console", FakeConsole)
        _print_error(RuntimeError("timeout waiting"))
        assert "timed out" in printed[0].lower()

    def test_generic_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed: list[str] = []

        class FakeConsole:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def print(self, msg: str) -> None:
                printed.append(msg)

        monkeypatch.setattr(runner_mod, "Console", FakeConsole)
        _print_error(ValueError("weird boom"))
        assert "Error: weird boom" in printed[0]


class TestRunOnce:
    @pytest.mark.asyncio
    async def test_json_format_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = MagicMock()
        backend.start = AsyncMock()
        backend.stop = AsyncMock()
        backend.run_streaming = MagicMock(
            return_value=_aiter(
                [
                    SimpleNamespace(
                        type=CHUNK_LLM_OUTPUT,
                        payload={"content": "hi"},
                    )
                ]
            )
        )
        monkeypatch.setattr(runner_mod, "create_backend", lambda cfg: backend)
        written: list[str] = []
        monkeypatch.setattr(
            runner_mod, "_write_terminal", lambda t: written.append(t)
        )

        code = await run_once(
            CLIConfig(api_key="k", model="m1"),
            "hello",
            output_format="json",
        )
        assert code == 0
        backend.start.assert_awaited_once()
        backend.stop.assert_awaited_once()
        payload = json.loads("".join(written).strip())
        assert payload["result"] == "hi"

    @pytest.mark.asyncio
    async def test_stream_json_format(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = MagicMock()
        backend.start = AsyncMock()
        backend.stop = AsyncMock()
        backend.run_streaming = MagicMock(
            return_value=_aiter(
                [
                    SimpleNamespace(
                        type="llm_output",
                        index=0,
                        payload="x",
                    )
                ]
            )
        )
        monkeypatch.setattr(runner_mod, "create_backend", lambda cfg: backend)
        written: list[str] = []
        monkeypatch.setattr(
            runner_mod, "_write_terminal", lambda t: written.append(t)
        )
        code = await run_once(
            CLIConfig(api_key="k"), "p", output_format="stream-json"
        )
        assert code == 0
        assert '"type": "llm_output"' in "".join(written) or (
            '"type":"llm_output"' in "".join(written).replace(" ", "")
        )

    @pytest.mark.asyncio
    async def test_text_format_uses_render(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = MagicMock()
        backend.start = AsyncMock()
        backend.stop = AsyncMock()
        backend.run_streaming = MagicMock(return_value=_aiter([]))
        monkeypatch.setattr(runner_mod, "create_backend", lambda cfg: backend)
        render = AsyncMock()
        monkeypatch.setattr(runner_mod, "render_stream", render)
        code = await run_once(
            CLIConfig(api_key="k"), "p", output_format="text"
        )
        assert code == 0
        render.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_format_returns_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = MagicMock()
        backend.start = AsyncMock()
        backend.stop = AsyncMock()
        backend.run_streaming = MagicMock(return_value=_aiter([]))
        monkeypatch.setattr(runner_mod, "create_backend", lambda cfg: backend)
        errors: list[Exception] = []
        monkeypatch.setattr(
            runner_mod, "_print_error", lambda exc: errors.append(exc)
        )
        code = await run_once(
            CLIConfig(api_key="k"), "p", output_format="xml"
        )
        assert code == 1
        assert errors and "Unknown output format" in str(errors[0])

    @pytest.mark.asyncio
    async def test_exception_returns_1_and_stops(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = MagicMock()
        backend.start = AsyncMock(side_effect=RuntimeError("boom"))
        backend.stop = AsyncMock()
        monkeypatch.setattr(runner_mod, "create_backend", lambda cfg: backend)
        errors: list[Exception] = []
        monkeypatch.setattr(
            runner_mod, "_print_error", lambda exc: errors.append(exc)
        )
        code = await run_once(CLIConfig(api_key="k"), "p")
        assert code == 1
        assert isinstance(errors[0], RuntimeError)
        backend.stop.assert_awaited_once()

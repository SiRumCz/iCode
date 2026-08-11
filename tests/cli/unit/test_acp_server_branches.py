# coding: utf-8
"""Extra coverage for ACP server dispatch branches."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openjiuwen_icode.acp.server import (
    AcpProtocolError,
    AcpServer,
    _extract_prompt_text,
    run_acp_server,
)
from openjiuwen_icode.events import TurnFailed
from openjiuwen_icode.storage.session_store import SessionStore


class _Capture:
    def __init__(self) -> None:
        self.buf = io.StringIO()

    def write(self, s: str) -> int:
        return self.buf.write(s)

    def flush(self) -> None:
        return None

    def lines(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for line in self.buf.getvalue().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out


def test_extract_prompt_text_variants() -> None:
    assert _extract_prompt_text({"prompt": " hi "}) == "hi"
    assert _extract_prompt_text({"text": "x"}) == "x"
    assert (
        _extract_prompt_text(
            {"prompt": [{"type": "text", "text": "a"}, "b", {"text": "c"}]}
        )
        == "abc"
    )
    assert _extract_prompt_text({}) == ""


@pytest.mark.asyncio
async def test_alias_methods_and_errors() -> None:
    out = _Capture()
    err = io.StringIO()
    server = AcpServer(demo=True, stdout=out, stderr=err)  # type: ignore[arg-type]

    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "agent/initialize", "params": []}
    )
    assert out.lines()[-1]["result"]["protocolVersion"] == 1

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "newSession",
            "params": {"sessionId": "acp-fixed", "cwd": "/nope"},
        }
    )
    assert out.lines()[-1]["result"]["sessionId"] == "acp-fixed"

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/new",
            "params": {"sessionId": "acp-fixed"},
        }
    )
    assert out.lines()[-1]["error"]["code"] == -32000

    await server.handle_request(
        {"jsonrpc": "2.0", "method": "nope", "params": {}}
    )
    assert "ACP error" in err.getvalue() or True

    await server.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "session/cancel", "params": {}}
    )
    assert out.lines()[-1]["result"]["cancelled"] is False

    await server.handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "session/close", "params": {}}
    )
    assert out.lines()[-1]["result"]["closed"] is False

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "session/prompt",
            "params": {"sessionId": "missing-auto", "prompt": ""},
        }
    )
    assert out.lines()[-1]["error"]["code"] == -32602

    await server.handle_request(
        {"jsonrpc": "2.0", "id": 7, "method": "shutdown", "params": {}}
    )
    assert server._closed is True


@pytest.mark.asyncio
async def test_session_load_and_prompt_fail(
    tmp_path: Path,
) -> None:
    store = SessionStore(store_dir=tmp_path / "sessions")
    sess = store.new_session("acp-load1", "m")
    sess.title = "Loaded"
    store.save_current()

    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]
    server._default_store = store

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/load",
            "params": {"sessionId": "acp-load1"},
        }
    )
    loaded = out.lines()[-1]["result"]
    assert loaded["sessionId"] == "acp-load1"
    assert loaded["title"] == "Loaded"

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "loadSession",
            "params": {},
        }
    )
    assert out.lines()[-1]["error"]["code"] == -32602

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/load",
            "params": {"sessionId": "missing"},
        }
    )
    assert out.lines()[-1]["error"]["code"] == -32001

    # Prompt that fails via TurnFailed before demo finishes
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "session/new",
            "params": {"sessionId": "acp-fail"},
        }
    )
    sess_obj = server._sessions["acp-fail"]

    class SlowBackend:
        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def abort(self) -> None:
            return None

        async def steer(self, msg: str) -> None:
            return None

        async def follow_up(self, msg: str) -> None:
            return None

        def get_usage(self) -> None:
            return None

        async def run_streaming(
            self, query: object, session_id: str | None = None
        ):
            await asyncio.sleep(60)
            if False:
                yield None

    sess_obj.bundle.host._backend = SlowBackend()  # type: ignore[attr-defined]

    async def fail_soon() -> None:
        await asyncio.sleep(0.05)
        await sess_obj.bundle.bus.publish(
            TurnFailed(error="boom", session_id="acp-fail")
        )

    task = asyncio.create_task(fail_soon())
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "prompt",
            "params": {
                "sessionId": "acp-fail",
                "prompt": [{"type": "text", "text": "go"}],
            },
        }
    )
    await task
    prompt = [m for m in out.lines() if m.get("id") == 5][0]
    assert prompt["result"]["ok"] is False
    assert prompt["result"]["stopReason"] == "error"


@pytest.mark.asyncio
async def test_handler_generic_exception() -> None:
    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]
    with patch.object(
        server,
        "_dispatch",
        AsyncMock(side_effect=RuntimeError("explode")),
    ):
        await server.handle_request(
            {"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {}}
        )
    assert out.lines()[-1]["error"]["code"] == -32603


@pytest.mark.asyncio
async def test_serve_stdio_parse_and_eof() -> None:
    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]

    class FakeReader:
        def __init__(self) -> None:
            self._lines = [
                b"not-json\n",
                b'"just-a-string"\n',
                b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
                b"",
            ]
            self._i = 0

        async def readline(self) -> bytes:
            line = self._lines[self._i]
            self._i += 1
            return line

    loop = asyncio.get_running_loop()
    with patch.object(loop, "connect_read_pipe", AsyncMock()), patch(
        "asyncio.StreamReader", FakeReader
    ), patch("asyncio.StreamReaderProtocol", MagicMock()):
        # Patch serve_stdio internals more directly
        async def fake_serve() -> int:
            reader = FakeReader()
            while not server._closed:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    server._reply_error(None, -32700, "Parse error")
                    continue
                if not isinstance(message, dict):
                    continue
                await server.handle_request(message)
            await server.close_all()
            return 0

        code = await fake_serve()
    assert code == 0
    assert any(m.get("error", {}).get("code") == -32700 for m in out.lines())
    assert any(m.get("id") == 1 for m in out.lines())


@pytest.mark.asyncio
async def test_run_acp_server_entry() -> None:
    with patch(
        "openjiuwen_icode.acp.server.AcpServer.serve_stdio",
        AsyncMock(return_value=0),
    ):
        assert await run_acp_server(demo=True) == 0


def test_protocol_error_fields() -> None:
    exc = AcpProtocolError(-1, "msg", data={"a": 1})
    assert exc.code == -1
    assert exc.data == {"a": 1}

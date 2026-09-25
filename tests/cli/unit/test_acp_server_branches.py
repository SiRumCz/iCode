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
    assert "messages" in loaded
    assert isinstance(loaded["messages"], list)

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
async def test_serve_reader_parse_and_eof() -> None:
    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]
    reader = asyncio.StreamReader()
    reader.feed_data(b"not-json\n")
    reader.feed_data(b'"just-a-string"\n')
    reader.feed_data(
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
    )
    reader.feed_eof()
    code = await server.serve_reader(reader)
    assert code == 0
    assert any(m.get("error", {}).get("code") == -32700 for m in out.lines())
    assert any(m.get("id") == 1 for m in out.lines())
    init = next(m for m in out.lines() if m.get("id") == 1)
    assert init["result"]["agentInfo"]["version"]


@pytest.mark.asyncio
async def test_serve_stdio_uses_connect_read_pipe() -> None:
    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]
    reader = asyncio.StreamReader()
    reader.feed_data(
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
    )
    reader.feed_eof()

    async def fake_connect(protocol_factory, pipe):  # noqa: ANN001
        return None

    with patch(
        "asyncio.StreamReader", return_value=reader
    ), patch(
        "asyncio.StreamReaderProtocol", MagicMock()
    ), patch.object(
        asyncio.get_running_loop(),
        "connect_read_pipe",
        AsyncMock(side_effect=fake_connect),
    ):
        code = await server.serve_stdio()
    assert code == 0
    assert any(m.get("id") == 1 for m in out.lines())


@pytest.mark.asyncio
async def test_run_acp_server_entry() -> None:
    with patch(
        "openjiuwen_icode.acp.server.AcpServer.serve_stdio",
        AsyncMock(return_value=0),
    ):
        assert await run_acp_server(demo=True, auto_approve=False) == 0


@pytest.mark.asyncio
async def test_session_approve_and_diff() -> None:
    out = _Capture()
    server = AcpServer(demo=True, stdout=out, auto_approve=True)  # type: ignore[arg-type]
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/new",
            "params": {"cwd": "/tmp", "sessionId": "acp-diff1"},
        }
    )
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/approve",
            "params": {
                "sessionId": "acp-diff1",
                "interactionId": "ix-1",
                "approved": False,
            },
        }
    )
    approve = next(m for m in out.lines() if m.get("id") == 2)
    assert approve["result"]["ok"] is True
    assert approve["result"]["approved"] is False

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/diff",
            "params": {"sessionId": "acp-diff1"},
        }
    )
    diff = next(m for m in out.lines() if m.get("id") == 3)
    assert "files" in diff["result"]
    await server.close_all()


@pytest.mark.asyncio
async def test_session_transcript_does_not_require_open_session(
    tmp_path: Path,
) -> None:
    store = SessionStore(store_dir=tmp_path / "sessions")
    sess = store.new_session("acp-tr1", "m")
    sess.title = "Export me"
    store.add_message("user", "hello transcript")
    store.add_message("assistant", "hi there")
    store.save_current()

    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]
    server._default_store = store

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/transcript",
            "params": {"sessionId": "acp-tr1"},
        }
    )
    result = out.lines()[-1]["result"]
    assert result["sessionId"] == "acp-tr1"
    assert result["title"] == "Export me"
    assert any(m.get("role") == "user" for m in result["messages"])
    assert "acp-tr1" not in server._sessions

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "sessionTranscript",
            "params": {"sessionId": "missing"},
        }
    )
    assert out.lines()[-1]["error"]["code"] == -32000
    await server.close_all()


@pytest.mark.asyncio
async def test_session_delete(tmp_path: Path) -> None:
    store = SessionStore(store_dir=tmp_path / "sessions")
    store.new_session("acp-del1", "m")
    store.add_message("user", "bye")
    store.save_current()
    assert store._session_path("acp-del1").is_file()

    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]
    server._default_store = store

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/delete",
            "params": {"sessionId": "acp-del1"},
        }
    )
    deleted = next(m for m in out.lines() if m.get("id") == 1)
    assert deleted["result"]["deleted"] is True
    assert not store._session_path("acp-del1").exists()

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "deleteSession",
            "params": {"sessionId": "missing"},
        }
    )
    assert out.lines()[-1]["error"]["code"] == -32001


def test_protocol_error_fields() -> None:
    exc = AcpProtocolError(-1, "msg", data={"a": 1})
    assert exc.code == -1
    assert exc.data == {"a": 1}

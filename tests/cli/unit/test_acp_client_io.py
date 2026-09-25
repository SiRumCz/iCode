# coding: utf-8
"""Unit tests for AcpClient request/response loop (mocked subprocess)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openjiuwen_icode.acp.client import (
    AcpClient,
    AcpClientConfig,
)


class _FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)
        self._i = 0

    async def readline(self) -> bytes:
        if self._i >= len(self._lines):
            return b""
        line = self._lines[self._i]
        self._i += 1
        return line


def _response(req_id: int, result: dict[str, Any]) -> bytes:
    return (
        json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n"
    ).encode()


def _error(req_id: int, code: int, message: str) -> bytes:
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": code, "message": message},
            }
        )
        + "\n"
    ).encode()


@pytest.mark.asyncio
async def test_client_start_prompt_cancel_close() -> None:
    lines = [
        # skip notification
        (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {},
                }
            )
            + "\n"
        ).encode(),
        _response(1, {"protocolVersion": 1}),
        _response(2, {"sessionId": "s-1"}),
        (
            json.dumps({"jsonrpc": "2.0", "id": 99}) + "\n"
        ).encode(),  # non-dict skip via wrong id
        b"not-a-dict\n".replace(b"not-a-dict", b"123"),  # int json → continue
        _response(3, {"ok": True, "text": "hi", "stopReason": "end_turn"}),
        _response(4, {"cancelled": True}),
        _response(5, {"closed": True}),
    ]
    # Fix: line that is valid JSON but not a dict
    lines[4] = b"123\n"

    proc = MagicMock()
    proc.stdin = _FakeStdin()
    proc.stdout = _FakeStdout(lines)
    proc.returncode = 0
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)

    cfg = AcpClientConfig(
        command="icode",
        args=["acp", "--demo"],
        env={"FOO": "1"},
        cwd="/tmp",
        profile_id="ext",
    )
    client = AcpClient(cfg)

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        sid = await client.start()
        assert sid == "s-1"
        result = await client.prompt("hello")
        assert result.ok is True
        assert result.text == "hi"
        await client.cancel()
        await client.close()

    assert proc.stdin.writes


@pytest.mark.asyncio
async def test_client_prompt_starts_when_needed() -> None:
    lines = [
        _response(1, {}),
        _response(2, {"sessionId": "auto"}),
        _response(3, {"ok": False, "error": "bad", "text": ""}),
    ]
    proc = MagicMock()
    proc.stdin = _FakeStdin()
    proc.stdout = _FakeStdout(lines)
    proc.returncode = 0
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(return_value=0)

    client = AcpClient(AcpClientConfig(command="x"))
    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        result = await client.prompt("q")
        await client.close()
    assert result.session_id == "auto"
    assert result.ok is False


@pytest.mark.asyncio
async def test_client_errors_and_cancel_swallow() -> None:
    client = AcpClient(AcpClientConfig(command="x"))
    with pytest.raises(RuntimeError, match="not started"):
        await client._request("initialize", {})

    proc = MagicMock()
    proc.stdin = _FakeStdin()
    proc.stdout = _FakeStdout(
        [
            _error(1, -32000, "nope"),
        ]
    )
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())

    client._proc = proc
    client._reader = proc.stdout
    client._session_id = "s"
    with pytest.raises(RuntimeError, match="ACP error"):
        await client._request("session/new", {})

    # cancel swallows failures
    client._reader = _FakeStdout([b""])
    await client.cancel()

    # close with hang → kill
    client._proc = proc
    client._reader = _FakeStdout([_response(2, {})])
    client._req_id = 1
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
        await client.close()
    proc.kill.assert_called()


@pytest.mark.asyncio
async def test_client_child_closed_stdout() -> None:
    proc = MagicMock()
    proc.stdin = _FakeStdin()
    proc.stdout = _FakeStdout([b""])
    client = AcpClient(AcpClientConfig(command="x"))
    client._proc = proc
    client._reader = proc.stdout
    with pytest.raises(RuntimeError, match="closed stdout"):
        await client._request("initialize", {})

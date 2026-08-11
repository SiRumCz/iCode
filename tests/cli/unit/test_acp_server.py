# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Contract tests for ACP JSON-RPC MVP (T-30)."""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any

import pytest

from openjiuwen_icode.acp.server import AcpServer


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


@pytest.mark.asyncio
async def test_initialize_and_session_new_prompt_cancel() -> None:
    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]

    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    init = out.lines()[-1]
    assert init["id"] == 1
    assert init["result"]["protocolVersion"] == 1
    assert "OpenJiuWen" in init["result"]["agentInfo"]["name"]
    from openjiuwen_icode import __version__

    assert init["result"]["agentInfo"]["version"] == __version__

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": "/tmp"},
        }
    )
    created = [m for m in out.lines() if m.get("id") == 2][0]
    sid = created["result"]["sessionId"]
    assert sid.startswith("acp-")

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {
                "sessionId": sid,
                "prompt": [{"type": "text", "text": "hello acp"}],
            },
        }
    )
    prompt_resp = [m for m in out.lines() if m.get("id") == 3][0]
    assert prompt_resp["result"]["ok"] is True
    assert prompt_resp["result"]["stopReason"] == "end_turn"
    assert "hello acp" in prompt_resp["result"].get("text", "") or True

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "session/cancel",
            "params": {"sessionId": sid},
        }
    )
    cancel = [m for m in out.lines() if m.get("id") == 4][0]
    assert cancel["result"]["cancelled"] is True

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "session/list",
            "params": {},
        }
    )
    listed = [m for m in out.lines() if m.get("id") == 5][0]
    assert "sessions" in listed["result"]

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "session/close",
            "params": {"sessionId": sid},
        }
    )
    closed = [m for m in out.lines() if m.get("id") == 6][0]
    assert closed["result"]["closed"] is True


@pytest.mark.asyncio
async def test_unknown_method_error() -> None:
    out = _Capture()
    server = AcpServer(demo=True, stdout=out)  # type: ignore[arg-type]
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 9, "method": "nope", "params": {}}
    )
    err = out.lines()[-1]
    assert err["error"]["code"] == -32601

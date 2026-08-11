# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for ACP subagent transport helpers (T-31)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openjiuwen_icode.acp.client import (
    AcpClientConfig,
    AcpClientResult,
    parse_acp_transport,
    run_acp_subagent_prompt,
)
from openjiuwen_icode.agent.profile_loader import parse_profile_subagents


def test_parse_acp_transport_from_profile() -> None:
    cfg = parse_acp_transport(
        {
            "id": "ext",
            "transport": "acp",
            "acp": {
                "command": "openjiuwen",
                "args": ["acp", "--demo"],
                "env": {"FOO": "1"},
            },
        }
    )
    assert cfg is not None
    assert cfg.command == "openjiuwen"
    assert cfg.args == ["acp", "--demo"]
    assert cfg.env["FOO"] == "1"
    assert cfg.profile_id == "ext"


def test_parse_acp_transport_defaults_and_none() -> None:
    assert parse_acp_transport(None) is None
    assert parse_acp_transport({"id": "x"}) is None
    assert parse_acp_transport({"transport": "local"}) is None

    # transport=acp without acp block → defaults
    cfg = parse_acp_transport({"id": "d", "transport": "acp"})
    assert cfg is not None
    assert cfg.command == "icode"
    assert cfg.args == ["acp", "--demo"]
    assert cfg.env == {}
    assert cfg.cwd is None

    # acp block alone (no transport field) still works
    cfg2 = parse_acp_transport(
        {"id": "y", "acp": {"command": "bin", "args": "not-a-list", "cwd": "/tmp"}}
    )
    assert cfg2 is not None
    assert cfg2.command == "bin"
    assert cfg2.args == ["acp", "--demo"]
    assert cfg2.cwd == "/tmp"


def test_parse_profile_subagents_includes_transport() -> None:
    opts = parse_profile_subagents(
        {
            "transport": "acp",
            "sub_agents": {"roster": ["code_agent"], "acp": {"command": "x"}},
        }
    )
    assert opts["transport"] == "acp"
    assert opts["acp"]["command"] == "x"


@pytest.mark.asyncio
async def test_run_acp_subagent_prompt_success_publishes() -> None:
    bus = MagicMock()
    bus.publish = AsyncMock()
    cfg = AcpClientConfig(command="x", profile_id="ext")
    result = AcpClientResult(session_id="s1", text="hello", ok=True)

    client = MagicMock()
    client.start = AsyncMock(return_value="s1")
    client.prompt = AsyncMock(return_value=result)
    client.close = AsyncMock()

    with patch(
        "openjiuwen_icode.acp.client.AcpClient",
        return_value=client,
    ):
        out = await run_acp_subagent_prompt(
            cfg, "do work", bus=bus, session_id="parent", invocation_id="inv-1"
        )
    assert out.text == "hello"
    assert bus.publish.await_count == 2
    client.close.assert_awaited()


@pytest.mark.asyncio
async def test_run_acp_subagent_prompt_failure_and_exception() -> None:
    bus = MagicMock()
    bus.publish = AsyncMock()
    cfg = AcpClientConfig(command="x", profile_id="ext")

    client = MagicMock()
    client.start = AsyncMock(return_value="s1")
    client.prompt = AsyncMock(
        return_value=AcpClientResult(
            session_id="s1", text="", ok=False, error="nope"
        )
    )
    client.close = AsyncMock()

    with patch(
        "openjiuwen_icode.acp.client.AcpClient",
        return_value=client,
    ):
        out = await run_acp_subagent_prompt(cfg, "x", bus=bus)
    assert out.ok is False
    assert bus.publish.await_count == 2

    client2 = MagicMock()
    client2.start = AsyncMock(side_effect=RuntimeError("spawn failed"))
    client2.close = AsyncMock()
    bus2 = MagicMock()
    bus2.publish = AsyncMock()
    with patch(
        "openjiuwen_icode.acp.client.AcpClient",
        return_value=client2,
    ):
        with pytest.raises(RuntimeError, match="spawn failed"):
            await run_acp_subagent_prompt(cfg, "x", bus=bus2)
    client2.close.assert_awaited()
    assert bus2.publish.await_count == 2

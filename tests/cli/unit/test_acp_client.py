# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for ACP subagent transport helpers (T-31)."""

from __future__ import annotations

from openjiuwen_icode.acp.client import parse_acp_transport
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


def test_parse_profile_subagents_includes_transport() -> None:
    opts = parse_profile_subagents(
        {
            "transport": "acp",
            "sub_agents": {"roster": ["code_agent"], "acp": {"command": "x"}},
        }
    )
    assert opts["transport"] == "acp"
    assert opts["acp"]["command"] == "x"

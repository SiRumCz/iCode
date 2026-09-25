# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for MCP cwd+hash connection cache keys."""

from __future__ import annotations

from openjiuwen.core.foundation.tool import McpServerConfig
from openjiuwen_icode.features.mcp_cache import (
    assign_stable_server_id,
    format_mcp_status,
    mcp_config_cache_key,
    collect_mcp_status,
)


def test_same_config_same_cwd_same_key() -> None:
    a = mcp_config_cache_key(
        server_name="fs",
        client_type="stdio",
        params={"command": "npx", "args": ["-y", "x"], "env": {"A": "1"}},
        cwd="/proj",
    )
    b = mcp_config_cache_key(
        server_name="fs",
        client_type="stdio",
        params={"command": "npx", "args": ["-y", "x"], "env": {"A": "1"}},
        cwd="/proj",
    )
    assert a == b


def test_cwd_change_changes_key() -> None:
    a = mcp_config_cache_key(
        server_name="fs",
        client_type="stdio",
        params={"command": "npx"},
        cwd="/a",
    )
    b = mcp_config_cache_key(
        server_name="fs",
        client_type="stdio",
        params={"command": "npx"},
        cwd="/b",
    )
    assert a != b


def test_assign_stable_server_id_deterministic() -> None:
    cfg = McpServerConfig(
        server_name="demo",
        server_path="",
        client_type="stdio",
        params={"command": "echo"},
    )
    key1 = assign_stable_server_id(cfg, cwd="/ws")
    sid1 = cfg.server_id
    key2 = assign_stable_server_id(cfg, cwd="/ws")
    assert key1 == key2
    assert sid1 == cfg.server_id
    assert cfg.server_id.startswith("demo:")
    assert len(cfg.server_id.split(":")[1]) == 12


def test_format_mcp_status_includes_cache_hint() -> None:
    status = collect_mcp_status(configs=[], cwd="/x", config_path="/tmp/mcp.json")
    text = format_mcp_status(status)
    assert "sha256" in text
    assert "/tmp/mcp.json" in text

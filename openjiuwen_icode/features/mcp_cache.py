# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""MCP connection cache keys (cwd + config hash) and CLI status helpers.

ToolMgr already reuses live clients by ``server_id``.  Assigning a stable
``server_id`` from ``sha256(cwd + config)`` makes rebuilds / profile switches
hit the same connection instead of spawning a new stdio handshake.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any


def _stable_mapping(mapping: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not mapping:
        return []
    return sorted((str(k), str(v)) for k, v in mapping.items())


def mcp_config_cache_key(
    *,
    server_name: str,
    client_type: str,
    server_path: str = "",
    params: dict[str, Any] | None = None,
    auth_headers: dict[str, Any] | None = None,
    cwd: str | None = None,
) -> str:
    """Return a hex fingerprint for effective MCP config + stdio cwd."""
    params = dict(params or {})
    effective_cwd = (
        str(params.get("cwd") or "").strip()
        or (cwd or "").strip()
        or os.getcwd()
    )
    payload: dict[str, Any] = {
        "name": server_name,
        "transport": client_type,
        "path": server_path or "",
        "params": {
            "command": params.get("command"),
            "args": list(params.get("args") or []),
            "env": _stable_mapping(params.get("env") if isinstance(params.get("env"), dict) else None),
            "cwd": effective_cwd,
            "url": params.get("url"),
        },
        "auth_headers": _stable_mapping(
            auth_headers if isinstance(auth_headers, dict) else None
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def assign_stable_server_id(
    config: Any,
    *,
    cwd: str | None = None,
) -> str:
    """Set ``config.server_id`` to ``{name}:{hash12}`` and return the key."""
    params = getattr(config, "params", None) or {}
    if not isinstance(params, dict):
        params = {}
    key = mcp_config_cache_key(
        server_name=str(getattr(config, "server_name", "") or ""),
        client_type=str(getattr(config, "client_type", "") or "stdio"),
        server_path=str(getattr(config, "server_path", "") or ""),
        params=params,
        auth_headers=getattr(config, "auth_headers", None) or {},
        cwd=cwd,
    )
    name = str(getattr(config, "server_name", "") or "mcp")
    config.server_id = f"{name}:{key[:12]}"
    # Ensure stdio child cwd is part of the effective config for connect.
    if not params.get("cwd"):
        params = dict(params)
        params["cwd"] = (cwd or "").strip() or os.getcwd()
        try:
            config.params = params
        except Exception:  # noqa: BLE001
            pass
    return key


@dataclass
class McpCacheStatus:
    """Snapshot for ``/mcp`` display."""

    config_path: str = ""
    configured: list[dict[str, str]] = field(default_factory=list)
    live: list[dict[str, str]] = field(default_factory=list)
    note: str = ""


def format_mcp_status(status: McpCacheStatus) -> str:
    """Human-readable MCP cache / config status."""
    lines = [
        f"MCP config: {status.config_path or '(none)'}",
        "Cache key: sha256(cwd + transport + command/args/env/url + headers)",
        "Reuse: ToolMgr keeps one live client per stable server_id.",
    ]
    if status.configured:
        lines.append("Configured servers:")
        for row in status.configured:
            lines.append(
                f"  - {row.get('name', '?')} "
                f"[{row.get('transport', '?')}] "
                f"id={row.get('server_id', '?')} "
                f"key={row.get('key_short', '?')}"
            )
    else:
        lines.append("Configured servers: (none)")
    if status.live:
        lines.append("Live connections (process ToolMgr):")
        for row in status.live:
            tools = row.get("tools", "0")
            lines.append(
                f"  * {row.get('name', '?')} id={row.get('server_id', '?')} "
                f"tools={tools}"
            )
    else:
        lines.append("Live connections: (none yet — connect on first agent turn)")
    if status.note:
        lines.append(status.note)
    return "\n".join(lines)


def collect_mcp_status(
    *,
    configs: list[Any] | None = None,
    cwd: str | None = None,
    config_path: str = "",
) -> McpCacheStatus:
    """Build status from loaded configs + optional Runner ToolMgr."""
    status = McpCacheStatus(config_path=config_path)
    for cfg in configs or []:
        name = str(getattr(cfg, "server_name", "") or "")
        key = mcp_config_cache_key(
            server_name=name,
            client_type=str(getattr(cfg, "client_type", "") or ""),
            server_path=str(getattr(cfg, "server_path", "") or ""),
            params=getattr(cfg, "params", None) or {},
            auth_headers=getattr(cfg, "auth_headers", None) or {},
            cwd=cwd,
        )
        status.configured.append(
            {
                "name": name,
                "transport": str(getattr(cfg, "client_type", "") or ""),
                "server_id": str(getattr(cfg, "server_id", "") or ""),
                "key_short": key[:12],
            }
        )
    try:
        from openjiuwen.core.runner import Runner

        mgr = getattr(Runner, "resource_mgr", None)
        tool_mgr = getattr(mgr, "tool_mgr", None) if mgr is not None else None
        resources = getattr(tool_mgr, "_mcp_server_resources", None)
        if isinstance(resources, dict):
            for sid, resource in resources.items():
                cfg = getattr(resource, "config", None)
                tool_ids = getattr(resource, "tool_ids", None) or []
                status.live.append(
                    {
                        "server_id": str(sid),
                        "name": str(getattr(cfg, "server_name", "") or sid),
                        "tools": str(len(tool_ids)),
                    }
                )
    except Exception:  # noqa: BLE001
        status.note = "Live ToolMgr unavailable (Runner not started)."
    return status


__all__ = [
    "McpCacheStatus",
    "assign_stable_server_id",
    "collect_mcp_status",
    "format_mcp_status",
    "mcp_config_cache_key",
]

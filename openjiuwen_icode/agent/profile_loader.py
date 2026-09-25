# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Load Chrys-style agent profiles from ~/.icode/agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from openjiuwen_icode.agent.config import load_settings_json
from openjiuwen_icode.host.profiles import AGENTS_DIR


def active_agent_profile_id() -> str:
    """Profile id from settings (``agent_profile`` / ``agentProfile``)."""
    data = load_settings_json()
    raw = data.get("agent_profile") or data.get("agentProfile") or ""
    return str(raw).strip()


def _read_profile_file(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            return None
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def resolve_agent_profile_path(profile_id: str) -> Path | None:
    """Find ``profile_id`` under ``AGENTS_DIR`` (yaml/json, id or stem)."""
    if not profile_id:
        return None
    root = AGENTS_DIR
    if not root.is_dir():
        return None
    candidates = [
        root / f"{profile_id}.yaml",
        root / f"{profile_id}.yml",
        root / f"{profile_id}.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    for path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        data = _read_profile_file(path)
        if data and str(data.get("id") or path.stem) == profile_id:
            return path
    for path in sorted(root.glob("*.json")):
        data = _read_profile_file(path)
        if data and str(data.get("id") or path.stem) == profile_id:
            return path
    return None


def load_agent_profile(profile_id: str | None = None) -> dict[str, Any] | None:
    """Load one agent profile document."""
    pid = (profile_id or active_agent_profile_id()).strip()
    if not pid:
        return None
    path = resolve_agent_profile_path(pid)
    if path is None:
        return None
    data = _read_profile_file(path)
    if data is None:
        return None
    data.setdefault("id", pid)
    data["_path"] = str(path)
    return data


def parse_profile_subagents(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Extract CLI sub-agent options from a profile ``sub_agents`` block."""
    if not profile:
        return {}
    block = profile.get("sub_agents") or profile.get("subagents")
    if not isinstance(block, dict):
        return {}
    out: dict[str, Any] = {}
    max_total = block.get("max_total_concurrency") or block.get("max_total")
    max_per = block.get("max_per_type_concurrency") or block.get("max_per_type")
    if max_total is not None:
        try:
            out["max_total"] = max(1, int(max_total))
        except (TypeError, ValueError):
            pass
    if max_per is not None:
        try:
            out["max_per_type"] = max(1, int(max_per))
        except (TypeError, ValueError):
            pass
    roster = block.get("roster")
    if isinstance(roster, list) and roster:
        out["roster_names"] = [str(x).strip() for x in roster if str(x).strip()]
    agents = block.get("agents")
    if isinstance(agents, list):
        names: list[str] = []
        for entry in agents:
            if isinstance(entry, str) and entry.strip():
                names.append(entry.strip())
            elif isinstance(entry, dict):
                tn = entry.get("tool_name") or entry.get("name") or entry.get("id")
                if tn:
                    names.append(str(tn).strip())
        if names:
            out["roster_names"] = names
    if block.get("include_browser") is not None:
        out["include_browser"] = bool(block.get("include_browser"))
    if block.get("include_research") is not None:
        out["include_research"] = bool(block.get("include_research"))
    # ACP external sub-agent transport (T-31)
    transport = str(block.get("transport") or profile.get("transport") or "").strip()
    if transport:
        out["transport"] = transport.lower()
    acp = block.get("acp") or profile.get("acp")
    if isinstance(acp, dict):
        out["acp"] = acp
    return out


def merged_cli_subagent_options() -> dict[str, Any]:
    """Settings ``subagents`` merged with active agent profile."""
    from openjiuwen_icode.subagents import load_cli_subagent_options

    opts = load_cli_subagent_options()
    profile_opts = parse_profile_subagents(load_agent_profile())
    for key, val in profile_opts.items():
        opts[key] = val
    return opts


__all__ = [
    "active_agent_profile_id",
    "load_agent_profile",
    "merged_cli_subagent_options",
    "parse_profile_subagents",
    "resolve_agent_profile_path",
]

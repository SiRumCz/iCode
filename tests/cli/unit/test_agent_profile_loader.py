# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Agent profile YAML sub_agents parsing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml

from openjiuwen_icode.agent.profile_loader import (
    active_agent_profile_id,
    load_agent_profile,
    merged_cli_subagent_options,
    parse_profile_subagents,
    resolve_agent_profile_path,
)


def test_parse_chrys_style_sub_agents(tmp_path: Path) -> None:
    path = tmp_path / "Code.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "id": "code-custom",
                "label": "Custom Code",
                "sub_agents": {
                    "max_total_concurrency": 3,
                    "agents": [
                        {"tool_name": "explore_agent"},
                        {"tool_name": "plan_agent"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    opts = parse_profile_subagents(data)
    assert opts["max_total"] == 3
    assert opts["roster_names"] == ["explore_agent", "plan_agent"]
    assert resolve_agent_profile_path("missing") is None


def test_parse_profile_subagents_branches() -> None:
    assert parse_profile_subagents(None) == {}
    assert parse_profile_subagents({"sub_agents": "x"}) == {}
    opts = parse_profile_subagents(
        {
            "subagents": {
                "max_total": "bad",
                "max_per_type": 2,
                "roster": [" a ", "", "b"],
                "include_browser": False,
                "include_research": True,
                "transport": "ACP",
                "agents": ["plain", {"name": "named"}, {"id": "ided"}, {}],
            }
        }
    )
    assert "max_total" not in opts
    assert opts["max_per_type"] == 2
    assert opts["roster_names"] == ["plain", "named", "ided"]
    assert opts["include_browser"] is False
    assert opts["include_research"] is True
    assert opts["transport"] == "acp"


def test_resolve_and_load_profile(tmp_path: Path, monkeypatch) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "explore.yaml").write_text(
        yaml.safe_dump({"id": "explore", "label": "E"}),
        encoding="utf-8",
    )
    (agents / "by-stem.yml").write_text(
        "label: Stem\n",
        encoding="utf-8",
    )
    (agents / "json-one.json").write_text(
        json.dumps({"id": "json-one", "label": "J"}),
        encoding="utf-8",
    )
    (agents / "bad.yaml").write_text(": not: valid: [", encoding="utf-8")

    monkeypatch.setattr(
        "openjiuwen_icode.agent.profile_loader.AGENTS_DIR",
        agents,
    )
    assert resolve_agent_profile_path("") is None
    assert resolve_agent_profile_path("explore") == agents / "explore.yaml"
    assert resolve_agent_profile_path("by-stem") == agents / "by-stem.yml"
    assert resolve_agent_profile_path("json-one") == agents / "json-one.json"

    loaded = load_agent_profile("explore")
    assert loaded is not None
    assert loaded["id"] == "explore"
    assert "_path" in loaded

    with patch(
        "openjiuwen_icode.agent.profile_loader.active_agent_profile_id",
        return_value="",
    ):
        assert load_agent_profile() is None


def test_active_and_merged(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjiuwen_icode.agent.profile_loader.load_settings_json",
        lambda: {"agent_profile": "code"},
    )
    assert active_agent_profile_id() == "code"

    with patch(
        "openjiuwen_icode.subagents.load_cli_subagent_options",
        return_value={"include_browser": True},
    ), patch(
        "openjiuwen_icode.agent.profile_loader.load_agent_profile",
        return_value={"sub_agents": {"include_research": True, "roster": ["x"]}},
    ):
        opts = merged_cli_subagent_options()
    assert opts["include_browser"] is True
    assert opts["include_research"] is True
    assert opts["roster_names"] == ["x"]

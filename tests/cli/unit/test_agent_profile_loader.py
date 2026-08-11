# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Agent profile YAML sub_agents parsing."""

from __future__ import annotations

from pathlib import Path

import yaml

from openjiuwen_icode.agent.profile_loader import (
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

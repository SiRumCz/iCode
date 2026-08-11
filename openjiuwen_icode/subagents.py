# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""CLI sub-agent roster aligned with Chrys Code profile defaults."""

from __future__ import annotations

import os
from typing import Any

from openjiuwen.core.single_agent.schema.agent_card import AgentCard
from openjiuwen.core.common.logging import logger
from openjiuwen.harness.rails.sys_operation_rail import SysOperationRail
from openjiuwen.harness.schema.config import SubAgentConfig
from openjiuwen.harness.subagents.concurrency import SubagentConcurrencyConfig


def load_subagent_concurrency_config() -> SubagentConcurrencyConfig:
    """Read limits from profile, settings.json, env, or defaults."""
    from openjiuwen_icode.agent.config import load_settings_json
    from openjiuwen_icode.agent.profile_loader import (
        load_agent_profile,
        parse_profile_subagents,
    )

    def _int(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return max(1, int(raw))
        except ValueError:
            return default

    settings = load_settings_json()
    block = settings.get("subagents")
    if not isinstance(block, dict):
        block = {}

    def _setting_int(key: str, default: int) -> int:
        val = block.get(key)
        if val is None:
            return default
        try:
            return max(1, int(val))
        except (TypeError, ValueError):
            return default

    per_agent: dict[str, int] = {}
    raw_per = block.get("per_agent")
    if isinstance(raw_per, dict):
        for name, limit in raw_per.items():
            try:
                per_agent[str(name)] = max(1, int(limit))
            except (TypeError, ValueError):
                continue

    base_total = _setting_int("max_total", 2)
    base_per = _setting_int("max_per_type", 2)
    profile_opts = parse_profile_subagents(load_agent_profile())
    if "max_total" in profile_opts:
        base_total = int(profile_opts["max_total"])
    if "max_per_type" in profile_opts:
        base_per = int(profile_opts["max_per_type"])

    return SubagentConcurrencyConfig(
        max_total=_int("OPENJIUWEN_SUBAGENT_MAX_TOTAL", base_total),
        per_agent_default=_int("OPENJIUWEN_SUBAGENT_MAX_PER_TYPE", base_per),
        per_agent=per_agent,
    )


def load_cli_subagent_options() -> dict[str, Any]:
    """Optional roster / feature flags from ``settings.json`` → ``subagents``."""
    from openjiuwen_icode.agent.config import load_settings_json

    settings = load_settings_json()
    block = settings.get("subagents")
    if not isinstance(block, dict):
        block = {}
    opts: dict[str, Any] = {}
    roster = block.get("roster")
    if isinstance(roster, list) and roster:
        opts["roster_names"] = [str(x).strip() for x in roster if str(x).strip()]
    if "include_browser" in block:
        opts["include_browser"] = bool(block.get("include_browser"))
    if "include_research" in block:
        opts["include_research"] = bool(block.get("include_research"))
    return opts


def build_cli_subagents(
    model: Any,
    *,
    language: str = "en",
    include_browser: bool = True,
    include_research: bool = False,
    roster_names: list[str] | None = None,
) -> list[SubAgentConfig]:
    """Build Chrys-style sub-agents for OpenJiuWen iCode CLI.

    Default roster (like Chrys ``Code.yaml``): ``explore_agent``, ``plan_agent``,
    plus ``general-purpose`` via ``add_general_purpose_agent=True`` on
    ``create_deep_agent``. Optional ``research_agent`` / ``browser_agent``.
    """
    from openjiuwen.harness.subagents.explore_agent import (
        build_explore_agent_config,
    )
    from openjiuwen.harness.subagents.plan_agent import build_plan_agent_config

    subagents: list[SubAgentConfig] = []

    subagents.append(
        build_explore_agent_config(model=model, language=language)
    )
    subagents.append(build_plan_agent_config(model=model, language=language))

    if include_research:
        from openjiuwen.core.single_agent.schema.agent_card import AgentCard
        from openjiuwen.harness.rails.sys_operation_rail import SysOperationRail
        from openjiuwen.harness.subagents.research_agent import (
            DEFAULT_RESEARCH_AGENT_DESCRIPTION,
            DEFAULT_RESEARCH_AGENT_SYSTEM_PROMPT,
        )

        subagents.append(
            SubAgentConfig(
                agent_card=AgentCard(
                    name="research_agent",
                    description=DEFAULT_RESEARCH_AGENT_DESCRIPTION.get(
                        language,
                        DEFAULT_RESEARCH_AGENT_DESCRIPTION["en"],
                    ),
                ),
                system_prompt=DEFAULT_RESEARCH_AGENT_SYSTEM_PROMPT.get(
                    language,
                    DEFAULT_RESEARCH_AGENT_SYSTEM_PROMPT["en"],
                ),
                model=model,
                rails=[SysOperationRail()],
                language=language,
            )
        )

    if include_browser:
        try:
            from openjiuwen.harness.subagents.browser_agent import (
                build_browser_agent_config,
            )

            subagents.append(
                build_browser_agent_config(model, language=language)
            )
        except Exception:  # noqa: BLE001
            logger.debug("Browser subagent not available", exc_info=True)

    if roster_names:
        allowed = {n.strip() for n in roster_names if n.strip()}
        filtered: list[SubAgentConfig] = []
        for spec in subagents:
            name = getattr(getattr(spec, "agent_card", None), "name", "") or ""
            if name in allowed:
                filtered.append(spec)
        subagents = filtered

    return subagents


__all__ = [
    "SubagentConcurrencyConfig",
    "build_cli_subagents",
    "load_cli_subagent_options",
    "load_subagent_concurrency_config",
]

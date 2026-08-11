# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Resolve skill slash commands for EventBus TUI / host."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openjiuwen_icode.skills.config import load_skills_config
from openjiuwen_icode.skills.paths import collect_default_skill_dirs
from openjiuwen_icode.skills.query import (
    build_inline_skill_query,
    build_skill_query,
)
from openjiuwen_icode.skills.scan import (
    discover_skills,
    format_skills_list,
)


def _cwd_hint(host: Any = None) -> str | None:
    if host is not None:
        primary = getattr(getattr(host, "workdirs", None), "primary", None)
        if primary:
            return str(primary)
        cfg = getattr(getattr(host, "_backend", None), "cfg", None)
        if cfg is not None:
            return getattr(cfg, "cwd", None) or getattr(cfg, "workspace", None)
    try:
        from openjiuwen.core.sys_operation.cwd import get_cwd

        return get_cwd() or str(Path.cwd())
    except Exception:  # noqa: BLE001
        return str(Path.cwd())


def scan_cli_skills(host: Any = None) -> dict[str, Any]:
    """Return ``{name: DiscoveredSkill|InlineSkillConfig}`` for slash UX."""
    cfg = load_skills_config()
    roots = collect_default_skill_dirs(
        cwd=_cwd_hint(host),
        extra_paths=cfg.paths,
        include_chrys=cfg.auto_load_chrys_skills,
        include_user_agents=cfg.auto_load_user_agents_skills,
        include_cwd_agents=cfg.auto_load_cwd_agents_skills,
    )
    discovered = discover_skills(roots)
    result: dict[str, Any] = dict(discovered)
    for inline in cfg.inline:
        if inline.name not in result:
            result[inline.name] = inline
    return result


def skill_slash_entries(host: Any = None) -> list[tuple[str, str]]:
    """``( /name, description )`` pairs for SuggestionList."""
    entries: list[tuple[str, str]] = [("/skills", "List loaded skills")]
    for name, skill in scan_cli_skills(host).items():
        desc = getattr(skill, "description", "") or "Skill"
        if len(desc) > 48:
            desc = desc[:45] + "..."
        entries.append((f"/{name}", desc))
    return entries


def resolve_skill_user_text(
    name: str,
    args: str = "",
    *,
    host: Any = None,
) -> str | None:
    """Build a user-turn payload for ``/<skill>`` or return None."""
    skills = scan_cli_skills(host)
    skill = skills.get(name)
    if skill is None:
        return None
    skill_md = getattr(skill, "skill_md", None)
    if skill_md is not None:
        return build_skill_query(Path(skill_md), args)
    instructions = getattr(skill, "instructions", None)
    if instructions is not None:
        return build_inline_skill_query(
            name=getattr(skill, "name", name),
            instructions=instructions,
            args=args,
        )
    return None


def skills_status_text(host: Any = None) -> str:
    cfg = load_skills_config()
    roots = collect_default_skill_dirs(
        cwd=_cwd_hint(host),
        extra_paths=cfg.paths,
        include_chrys=cfg.auto_load_chrys_skills,
        include_user_agents=cfg.auto_load_user_agents_skills,
        include_cwd_agents=cfg.auto_load_cwd_agents_skills,
    )
    discovered = discover_skills(roots)
    return format_skills_list(
        discovered.values(),
        inline_names=[s.name for s in cfg.inline],
    )


__all__ = [
    "resolve_skill_user_text",
    "scan_cli_skills",
    "skill_slash_entries",
    "skills_status_text",
]

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""User skills configuration (``~/.icode/skills.json`` + settings)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from openjiuwen_icode.agent.config import load_settings_json
from openjiuwen_icode.paths import skills_config_path

SKILLS_CONFIG_PATH = skills_config_path()


@dataclass(frozen=True)
class InlineSkillConfig:
    """Inline skill declared in config (Chrys ``skills.inline`` shape)."""

    name: str
    description: str = ""
    instructions: str = ""
    resources: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SkillsUserConfig:
    """Merged skills config for the CLI / SkillUseRail."""

    paths: tuple[str, ...] = ()
    inline: tuple[InlineSkillConfig, ...] = ()
    script_timeout: int = 300
    auto_load_chrys_skills: bool = True
    auto_load_user_agents_skills: bool = True
    auto_load_cwd_agents_skills: bool = True


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_inline(raw: Any) -> tuple[InlineSkillConfig, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[InlineSkillConfig] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        resources_raw = item.get("resources") or []
        resources: list[tuple[str, str]] = []
        if isinstance(resources_raw, list):
            for res in resources_raw:
                if not isinstance(res, Mapping):
                    continue
                rname = str(res.get("name") or "").strip()
                content = res.get("content")
                if not rname or content is None:
                    continue
                resources.append((rname, str(content)))
        out.append(
            InlineSkillConfig(
                name=name,
                description=str(item.get("description") or ""),
                instructions=str(
                    item.get("instructions") or item.get("content") or ""
                ),
                resources=tuple(resources),
            )
        )
    return tuple(out)


def _parse_paths(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        text = raw.strip()
        return (text,) if text else ()
    if isinstance(raw, Sequence):
        return tuple(str(p).strip() for p in raw if str(p).strip())
    return ()


def _from_mapping(data: Mapping[str, Any]) -> SkillsUserConfig:
    timeout_raw = data.get("script_timeout", 300)
    try:
        timeout = int(timeout_raw)
    except (TypeError, ValueError):
        timeout = 300
    return SkillsUserConfig(
        paths=_parse_paths(data.get("paths")),
        inline=_parse_inline(data.get("inline")),
        script_timeout=max(1, timeout),
        auto_load_chrys_skills=_as_bool(
            data.get("auto_load_chrys_skills"), True
        ),
        auto_load_user_agents_skills=_as_bool(
            data.get("auto_load_user_agents_skills"), True
        ),
        auto_load_cwd_agents_skills=_as_bool(
            data.get("auto_load_cwd_agents_skills"), True
        ),
    )


def load_skills_config(
    *,
    skills_path: Path | None = None,
    settings: Mapping[str, Any] | None = None,
) -> SkillsUserConfig:
    """Load skills config from ``skills.json``, then overlay ``settings["skills"]``."""
    path = skills_path if skills_path is not None else SKILLS_CONFIG_PATH
    base = SkillsUserConfig()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            base = _from_mapping(payload)

    settings_data = (
        dict(settings) if settings is not None else load_settings_json()
    )
    overlay = settings_data.get("skills")
    if isinstance(overlay, dict):
        overlay_cfg = _from_mapping(overlay)
        # Overlay replaces scalar flags; paths/inline are concatenated
        # with overlay first so settings can pin higher-priority paths.
        merged_paths = tuple(
            dict.fromkeys([*overlay_cfg.paths, *base.paths])
        )
        # Overlay inline wins on name collision.
        by_name = {s.name: s for s in base.inline}
        by_name.update({s.name: s for s in overlay_cfg.inline})
        return SkillsUserConfig(
            paths=merged_paths,
            inline=tuple(by_name.values()),
            script_timeout=overlay_cfg.script_timeout
            if "script_timeout" in overlay
            else base.script_timeout,
            auto_load_chrys_skills=overlay_cfg.auto_load_chrys_skills
            if "auto_load_chrys_skills" in overlay
            else base.auto_load_chrys_skills,
            auto_load_user_agents_skills=(
                overlay_cfg.auto_load_user_agents_skills
                if "auto_load_user_agents_skills" in overlay
                else base.auto_load_user_agents_skills
            ),
            auto_load_cwd_agents_skills=(
                overlay_cfg.auto_load_cwd_agents_skills
                if "auto_load_cwd_agents_skills" in overlay
                else base.auto_load_cwd_agents_skills
            ),
        )
    return base


__all__ = [
    "InlineSkillConfig",
    "SKILLS_CONFIG_PATH",
    "SkillsUserConfig",
    "load_skills_config",
]

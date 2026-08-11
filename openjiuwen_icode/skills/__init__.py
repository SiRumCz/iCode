# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""CLI skills helpers: paths, config, discovery, slash query builders."""

from openjiuwen_icode.skills.config import (
    InlineSkillConfig,
    SKILLS_CONFIG_PATH,
    SkillsUserConfig,
    load_skills_config,
)
from openjiuwen_icode.skills.paths import (
    CHRYS_SKILLS_DIR,
    CWD_AGENTS_SKILLS,
    USER_AGENTS_SKILLS_DIR,
    collect_default_skill_dirs,
)
from openjiuwen_icode.skills.query import (
    build_inline_skill_query,
    build_skill_query,
)
from openjiuwen_icode.skills.scan import (
    DiscoveredSkill,
    discover_skills,
    format_skills_list,
    iter_skill_directories,
)
from openjiuwen_icode.skills.slash import (
    resolve_skill_user_text,
    scan_cli_skills,
    skill_slash_entries,
    skills_status_text,
)

__all__ = [
    "CHRYS_SKILLS_DIR",
    "CWD_AGENTS_SKILLS",
    "DiscoveredSkill",
    "InlineSkillConfig",
    "SKILLS_CONFIG_PATH",
    "SkillsUserConfig",
    "USER_AGENTS_SKILLS_DIR",
    "build_inline_skill_query",
    "build_skill_query",
    "collect_default_skill_dirs",
    "discover_skills",
    "format_skills_list",
    "iter_skill_directories",
    "load_skills_config",
    "resolve_skill_user_text",
    "scan_cli_skills",
    "skill_slash_entries",
    "skills_status_text",
]

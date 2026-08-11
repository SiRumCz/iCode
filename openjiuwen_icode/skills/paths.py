# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Default skill-root discovery for OpenJiuWen iCode (Chrys-compatible paths)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

#: Sentinel expanded by :class:`~openjiuwen.harness.rails.skills.SkillUseRail`
#: against the agent cwd on every refresh (survives ``/directories use``).
CWD_AGENTS_SKILLS: str = "<cwd>/.agents/skills"

#: Product / third-party roots (priority high → low among these).
#: Project workspace skills are injected at collect time (current iCode project).
_PRODUCT_SKILL_DIRS: tuple[str, ...] = (
    "~/.claude/skills",
    "~/.codex/skills",
    "~/.jiuwenclaw/workspace/skills",
)

#: Chrys user skills root (always considered when enabled).
CHRYS_SKILLS_DIR: str = "~/.chrys/skills"

#: Shared Agents Skills user root.
USER_AGENTS_SKILLS_DIR: str = "~/.agents/skills"


def _current_project_skills_dir() -> str:
    try:
        from openjiuwen_icode.paths import IcodeProject

        return str(IcodeProject.open().workspace_dir / "skills")
    except Exception:  # noqa: BLE001
        from openjiuwen_icode.paths import default_project_path

        return str(default_project_path() / "workspace" / "skills")


def collect_default_skill_dirs(
    *,
    cwd: str | Path | None = None,
    extra_paths: Sequence[str] | None = None,
    include_chrys: bool = True,
    include_user_agents: bool = True,
    include_cwd_agents: bool = True,
) -> list[str]:
    """Return skill root paths in descending priority.

    Non-existent directories are kept in the list; :class:`SkillUseRail`
    skips them at scan time. ``<cwd>/.agents/skills`` stays as a sentinel
    so the rail can re-resolve against :func:`get_cwd` each refresh.
    """
    dirs: list[str] = [_current_project_skills_dir(), *_PRODUCT_SKILL_DIRS]
    if include_chrys:
        dirs.append(CHRYS_SKILLS_DIR)
    if include_user_agents:
        dirs.append(USER_AGENTS_SKILLS_DIR)
    if include_cwd_agents:
        dirs.append(CWD_AGENTS_SKILLS)
        if cwd is not None:
            try:
                abs_cwd = Path(cwd).expanduser().resolve()
                dirs.append(str(abs_cwd / ".agents" / "skills"))
            except OSError:
                pass
    if extra_paths:
        for raw in extra_paths:
            text = str(raw or "").strip()
            if text and text not in dirs:
                dirs.append(text)
    return _dedupe_preserve(dirs)


def _dedupe_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item if item.startswith("<") else str(Path(item).expanduser())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


__all__ = [
    "CHRYS_SKILLS_DIR",
    "CWD_AGENTS_SKILLS",
    "USER_AGENTS_SKILLS_DIR",
    "collect_default_skill_dirs",
]

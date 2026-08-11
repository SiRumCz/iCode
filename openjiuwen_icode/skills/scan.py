# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Filesystem skill discovery (Agent Skills depth-2 semantics)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

_FRONTMATTER_RE = re.compile(
    r"\A\uFEFF?---\s*\n(.*?\n)---\s*\n?",
    re.DOTALL,
)


@dataclass(frozen=True)
class DiscoveredSkill:
    """A skill found on disk for slash / catalog UX."""

    name: str
    description: str
    skill_md: Path
    directory: Path


def iter_skill_directories(
    root: Path,
    *,
    max_depth: int = 2,
) -> list[Path]:
    """Find skill dirs under *root* (each contains ``SKILL.md``).

    Depth 1 = immediate children; depth 2 = one nesting level
    (e.g. ``root/category/skill-name``). The first ``SKILL.md`` on a
    branch owns that subtree — nested skills are not discovered.
    """
    if max_depth < 1:
        raise ValueError(f"max_depth must be >= 1, got {max_depth}")
    root = root.expanduser()
    if not root.is_dir():
        return []
    found: list[Path] = []

    def walk(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        if depth >= 1 and (current / "SKILL.md").is_file():
            found.append(current)
            return
        if depth == max_depth:
            return
        try:
            children = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for child in children:
            if child.is_dir():
                walk(child, depth + 1)

    walk(root, 0)
    return found


def _read_frontmatter_fields(skill_md: Path) -> dict[str, str]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return {}
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            fields[key] = value
    return fields


def discover_skills(
    roots: Sequence[str | Path],
    *,
    max_depth: int = 2,
) -> dict[str, DiscoveredSkill]:
    """Scan *roots* and return ``name → DiscoveredSkill`` (first wins)."""
    found: dict[str, DiscoveredSkill] = {}
    for raw in roots:
        text = str(raw or "").strip()
        if not text or text.startswith("<"):
            # Sentinels need runtime cwd; skip in static scans.
            continue
        root = Path(text).expanduser()
        try:
            root = root.resolve()
        except OSError:
            continue
        for skill_dir in iter_skill_directories(root, max_depth=max_depth):
            skill_md = skill_dir / "SKILL.md"
            fields = _read_frontmatter_fields(skill_md)
            name = (fields.get("name") or skill_dir.name).strip()
            if not name or name in found:
                continue
            desc = (fields.get("description") or "").strip()
            found[name] = DiscoveredSkill(
                name=name,
                description=desc or f"Skill located in {skill_dir}",
                skill_md=skill_md,
                directory=skill_dir,
            )
    return found


def format_skills_list(
    skills: Iterable[DiscoveredSkill],
    *,
    inline_names: Sequence[str] = (),
) -> str:
    """Human-readable skills listing for ``/skills``."""
    rows = list(skills)
    lines = [f"Skills ({len(rows)} file + {len(inline_names)} inline):"]
    for skill in rows:
        lines.append(f"  /{skill.name}  — {skill.description[:80]}")
        lines.append(f"    {skill.directory}")
    for name in inline_names:
        lines.append(f"  /{name}  — (inline)")
    if len(rows) == 0 and not inline_names:
        lines.append("  (none found)")
    return "\n".join(lines)


__all__ = [
    "DiscoveredSkill",
    "discover_skills",
    "format_skills_list",
    "iter_skill_directories",
]

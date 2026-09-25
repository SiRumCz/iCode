# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Build user-turn payloads for ``/<skill-name>`` slash invocation."""

from __future__ import annotations

from pathlib import Path


def build_skill_query(skill_md: Path, args: str = "") -> str:
    """Wrap SKILL.md content as a structured user message."""
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return (
            f"Error reading skill file: {skill_md}. {exc}. "
            "Please check the skill directory."
        )
    parts = [
        "<skill-instructions>",
        content,
        "</skill-instructions>",
    ]
    args = (args or "").strip()
    if args:
        parts.append(f"\nUser arguments: {args}")
    parts.append("\nPlease follow the skill instructions above.")
    return "\n".join(parts)


def build_inline_skill_query(
    *,
    name: str,
    instructions: str,
    args: str = "",
) -> str:
    """Wrap an inline skill body as a structured user message."""
    parts = [
        "<skill-instructions>",
        f"# {name}",
        instructions or "",
        "</skill-instructions>",
    ]
    args = (args or "").strip()
    if args:
        parts.append(f"\nUser arguments: {args}")
    parts.append("\nPlease follow the skill instructions above.")
    return "\n".join(parts)


__all__ = [
    "build_inline_skill_query",
    "build_skill_query",
]

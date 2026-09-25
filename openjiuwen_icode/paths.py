# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""iCode four-layer path roots (see ``docs/design/icode-path-layout-rfc.md``).

Layers:

1. **Agents home** — ``~/.agents/`` (cross-harness, read-only by default)
2. **iCode home** — ``~/.icode/`` (machine-local product config)
3. **iCode project** — user path with ``directories.json``, ``workspace/``, ``sessions/``
4. **iCode session** — ``<project>/sessions/<id>/``
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_SCHEMA = 1


def agents_home() -> Path:
    """Layer 1: shared Agents ecosystem home."""
    raw = os.environ.get("AGENTS_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".agents").resolve()


def icode_home() -> Path:
    """Layer 2: machine-local iCode product home."""
    raw = os.environ.get("ICODE_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".icode").resolve()


def default_project_path() -> Path:
    """Default iCode project when ``-p`` / ``ICODE_PROJECT`` is unset."""
    return icode_home() / "projects" / "default"


def resolve_project_path(explicit: str | Path | None = None) -> Path:
    """Resolve project root from arg, ``ICODE_PROJECT``, or default."""
    if explicit is not None and str(explicit).strip():
        return Path(str(explicit)).expanduser().resolve()
    env = os.environ.get("ICODE_PROJECT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return default_project_path()


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class IcodeProject:
    """Layer 3: one iCode work setup (directories + agent workspace + sessions)."""

    root: Path

    @classmethod
    def open(
        cls,
        path: str | Path | None = None,
        *,
        create: bool = True,
    ) -> IcodeProject:
        root = resolve_project_path(path)
        proj = cls(root=root)
        if create:
            proj.ensure_layout()
        return proj

    @property
    def project_json(self) -> Path:
        return self.root / "project.json"

    @property
    def directories_json(self) -> Path:
        return self.root / "directories.json"

    @property
    def workspace_dir(self) -> Path:
        """Agent workspace (IDENTITY, memory, todo, …)."""
        return self.root / "workspace"

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self.project_json.exists():
            payload = {
                "schema": _PROJECT_SCHEMA,
                "name": self.root.name,
                "created_at": _utc_now(),
            }
            self.project_json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if not self.directories_json.exists():
            self.directories_json.write_text(
                json.dumps(
                    {"primary": "", "dirs": []},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    def read_meta(self) -> dict[str, Any]:
        if not self.project_json.exists():
            return {}
        try:
            data = json.loads(self.project_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


# Convenience aliases used by settings / MCP / profiles
def settings_path() -> Path:
    return icode_home() / "settings.json"


def mcp_path() -> Path:
    return icode_home() / "mcp.json"


def models_dir() -> Path:
    return icode_home() / "models"


def agents_dir() -> Path:
    return icode_home() / "agents"


def skills_config_path() -> Path:
    return icode_home() / "skills.json"


def preference_md_path() -> Path:
    return icode_home() / "OPENJIUWEN.md"


__all__ = [
    "IcodeProject",
    "agents_dir",
    "agents_home",
    "default_project_path",
    "icode_home",
    "mcp_path",
    "models_dir",
    "preference_md_path",
    "resolve_project_path",
    "settings_path",
    "skills_config_path",
]

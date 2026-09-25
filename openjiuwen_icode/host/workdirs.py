# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Project ``directories.json`` registry (external code/doc roots).

Product language: **directories** (one **primary**).
Persisted under the active iCode project, not iCode home.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def resolve_workdir(path: str) -> Path:
    """Expand ``~`` and resolve to an absolute path."""
    return Path(path).expanduser().resolve()


def parse_directories_slash(text: str) -> tuple[str, str] | None:
    """Parse ``/workdirs`` / ``/directories`` slash lines.

    Returns ``(action, rest)`` when the line is a directories command
    (*action* may be ``""`` for list). Returns ``None`` otherwise.
    """
    stripped = text.strip()
    if not stripped.startswith("/") or "\n" in stripped:
        return None
    body = stripped[1:]
    parts = body.split(maxsplit=2)
    if not parts:
        return None
    head = parts[0].lower()
    tail = parts[1] if len(parts) > 1 else ""

    alias_actions: dict[str, str] = {
        "workdirs-add": "add",
        "workdir-add": "add",
        "directories-add": "add",
        "directory-add": "add",
        "workdirs-rm": "rm",
        "workdir-rm": "rm",
        "workdirs-remove": "rm",
        "directories-rm": "rm",
        "directory-rm": "rm",
        "directories-remove": "rm",
        "workdirs-use": "use",
        "workdir-use": "use",
        "directories-use": "use",
        "directory-use": "use",
    }
    if head in alias_actions:
        return alias_actions[head], tail

    if head not in {"workdirs", "workdir", "directories", "directory"}:
        return None
    if len(parts) == 1:
        return "", ""
    action = parts[1].lower()
    rest = parts[2] if len(parts) > 2 else ""
    return action, rest


def format_directories_command_args(action: str, rest: str) -> str:
    """Build ``UserCommand`` args for :func:`parse_directories_slash` output."""
    act = (action or "").strip().lower()
    if not act or act in {"list", "ls"}:
        return rest.strip()
    return f"{act} {rest}".strip()


@dataclass
class WorkdirRegistry:
    """Ordered list of external project directories + one primary.

    File format (``directories.json``)::

        {"primary": "/abs/path", "dirs": ["/abs/path", ...]}
    """

    dirs: list[str] = field(default_factory=list)
    primary: str = ""
    store_path: Path = field(default_factory=lambda: Path("directories.json"))

    @classmethod
    def load(cls, store_path: Path | None = None) -> WorkdirRegistry:
        if store_path is None:
            raise ValueError(
                "WorkdirRegistry.load requires store_path "
                "(iCode project directories.json)"
            )
        path = store_path
        reg = cls(store_path=path)
        if not path.is_file():
            return reg
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return reg
        if not isinstance(data, dict):
            return reg
        dirs_raw = data.get("dirs") or []
        dirs: list[str] = []
        for item in dirs_raw:
            try:
                dirs.append(str(resolve_workdir(str(item))))
            except OSError:
                continue
        seen: set[str] = set()
        unique: list[str] = []
        for d in dirs:
            if d not in seen:
                seen.add(d)
                unique.append(d)
        primary = str(data.get("primary") or "")
        if primary:
            try:
                primary = str(resolve_workdir(primary))
            except OSError:
                primary = ""
        if primary and primary not in unique:
            unique.insert(0, primary)
        if not primary and unique:
            primary = unique[0]
        reg.dirs = unique
        reg.primary = primary
        return reg

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"primary": self.primary, "dirs": list(self.dirs)}
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def ensure_seed(self, path: str | None) -> bool:
        """If empty, seed with *path*. Returns True when primary changed."""
        if not path:
            return False
        try:
            resolved = str(resolve_workdir(path))
        except OSError:
            return False
        changed = False
        if resolved not in self.dirs:
            self.dirs.append(resolved)
            changed = True
        if not self.primary:
            self.primary = resolved
            changed = True
        if changed:
            self.save()
        return changed

    def format_list(self) -> str:
        if not self.dirs:
            return (
                "No directories configured.\n"
                "Add one: /directories add  (TUI: folder picker)\n"
                "Or: /directories add <path>\n"
                "Or: openjiuwen -p <icode-project>  (then add directories)"
            )
        lines = ["Directories (* = primary):"]
        for i, path in enumerate(self.dirs, start=1):
            mark = "*" if path == self.primary else " "
            lines.append(f"  {mark} {i}. {path}")
        lines.append("")
        lines.append(
            "Commands: /directories add|rm|use <path|#>  (alias: /workdirs)"
        )
        return "\n".join(lines)

    def resolve_ref(self, ref: str) -> str:
        """Resolve a path or 1-based index to an absolute dir string."""
        raw = (ref or "").strip()
        if not raw:
            raise ValueError("missing path or index")
        if raw.isdigit():
            idx = int(raw)
            if idx < 1 or idx > len(self.dirs):
                raise ValueError(
                    f"index {idx} out of range (1..{len(self.dirs) or 0})"
                )
            return self.dirs[idx - 1]
        return str(resolve_workdir(raw))

    def add(self, path: str) -> str:
        resolved = str(resolve_workdir(path))
        if not Path(resolved).is_dir():
            raise ValueError(f"not a directory: {resolved}")
        if resolved in self.dirs:
            return resolved
        self.dirs.append(resolved)
        if not self.primary:
            self.primary = resolved
        self.save()
        return resolved

    def remove(self, ref: str) -> str:
        target = self.resolve_ref(ref)
        if target not in self.dirs:
            raise ValueError(f"not in directories: {target}")
        if target == self.primary:
            raise ValueError(
                "cannot remove primary directory; "
                "/directories use <other> first"
            )
        self.dirs = [d for d in self.dirs if d != target]
        self.save()
        return target

    def use(self, ref: str) -> str:
        """Set primary. Adds path if it is a new existing directory."""
        raw = (ref or "").strip()
        if not raw:
            raise ValueError("missing path or index")
        if raw.isdigit():
            target = self.resolve_ref(raw)
        else:
            target = str(resolve_workdir(raw))
            if target not in self.dirs:
                if not Path(target).is_dir():
                    raise ValueError(f"not a directory: {target}")
                self.dirs.append(target)
        if target not in self.dirs:
            raise ValueError(f"not in directories: {target}")
        self.primary = target
        self.save()
        return target


def apply_workdir_to_backend(backend: Any, path: str) -> list[str]:
    """Hot-apply primary **directory** onto backend (tool cwd), not agent workspace.

    Agent workspace (``cfg.workspace`` / IDENTITY tree) stays on the iCode
    project and must not be overwritten when switching directories.
    """
    notes: list[str] = []
    resolved = str(resolve_workdir(path))
    cfg = getattr(backend, "cfg", None)
    if cfg is not None:
        if hasattr(cfg, "cwd"):
            cfg.cwd = resolved
            notes.append("cfg.cwd")

    agent = getattr(backend, "agent", None)
    deep = getattr(agent, "deep_config", None) if agent is not None else None
    # Do not rewrite deep_config.workspace.root_path — that is the agent workspace.

    if hasattr(backend, "_pending_workdir"):
        backend._pending_workdir = resolved
        notes.append("pending agent cwd")
    elif cfg is not None:
        try:
            backend._pending_workdir = resolved
            notes.append("pending agent cwd")
        except Exception:  # noqa: BLE001
            pass

    return notes


def apply_pending_workdir_cwd(backend: Any) -> None:
    """Apply ``backend._pending_workdir`` into sys_operation cwd ContextVar."""
    pending = getattr(backend, "_pending_workdir", None)
    if not pending:
        return
    try:
        from openjiuwen.core.sys_operation.cwd import (
            set_cwd,
            set_original_cwd,
            set_project_root,
        )

        set_cwd(pending)
        set_original_cwd(pending)
        set_project_root(pending)
    except Exception:  # noqa: BLE001
        return
    backend._pending_workdir = None

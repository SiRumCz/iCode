# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Per-turn filesystem mutation tracking for /diff and /rollback (T-40)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

MUTATING_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "Write",
        "Edit",
        "write",
        "edit",
    }
)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class FileMutation:
    """One file change within a turn."""

    path: str
    kind: str = "modify"  # create | modify | delete
    before_hash: str = ""
    after_hash: str = ""
    snapshot_before: str = ""  # relative path under mutations dir
    snapshot_after: str = ""


@dataclass
class TurnMutations:
    """Mutations attributed to one user turn."""

    turn_id: str
    session_id: str
    created_at: str = field(default_factory=_utc_now)
    files: list[FileMutation] = field(default_factory=list)
    note: str = ""


class MutationTracker:
    """Track workspace file changes per turn with optional snapshots."""

    def __init__(
        self,
        root: Path,
        *,
        workspace: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self._current: TurnMutations | None = None
        self._turns: list[TurnMutations] = []
        self._load_index()

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _load_index(self) -> None:
        path = self._index_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        turns = data.get("turns") or []
        loaded: list[TurnMutations] = []
        for row in turns:
            if not isinstance(row, dict):
                continue
            files = [
                FileMutation(**f)
                for f in row.get("files") or []
                if isinstance(f, dict)
            ]
            loaded.append(
                TurnMutations(
                    turn_id=str(row.get("turn_id") or ""),
                    session_id=str(row.get("session_id") or ""),
                    created_at=str(row.get("created_at") or ""),
                    files=files,
                    note=str(row.get("note") or ""),
                )
            )
        self._turns = loaded

    def _save_index(self) -> None:
        payload = {
            "turns": [
                {
                    **asdict(t),
                    "files": [asdict(f) for f in t.files],
                }
                for t in self._turns
            ]
        }
        self._index_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def begin_turn(self, session_id: str, turn_id: str | None = None) -> str:
        tid = turn_id or f"turn-{uuid4().hex[:8]}"
        self._current = TurnMutations(turn_id=tid, session_id=session_id)
        return tid

    def end_turn(self) -> TurnMutations | None:
        cur = self._current
        self._current = None
        if cur is None:
            return None
        if cur.files:
            self._turns.append(cur)
            self._save_index()
        return cur

    def record_tool_mutation(
        self,
        tool_name: str,
        tool_args: Any,
        *,
        result: str = "",
    ) -> FileMutation | None:
        """Record a mutating tool call against the open turn."""
        if self._current is None:
            return None
        if tool_name not in MUTATING_TOOLS:
            return None
        path = _extract_path(tool_args)
        if not path:
            return None
        abs_path = self._resolve(path)
        before = ""
        before_hash = ""
        kind = "modify"
        if abs_path.is_file():
            before_hash = _file_hash(abs_path)
            snap = self._snapshot_file(abs_path, "before")
            before = snap
        else:
            kind = "create"
        # After content may not exist yet if tool hasn't flushed; try read.
        after_hash = ""
        after_snap = ""
        if abs_path.is_file():
            after_hash = _file_hash(abs_path)
            if after_hash != before_hash:
                after_snap = self._snapshot_file(abs_path, "after")
            elif kind == "create":
                after_snap = self._snapshot_file(abs_path, "after")
        mut = FileMutation(
            path=str(abs_path),
            kind=kind,
            before_hash=before_hash,
            after_hash=after_hash,
            snapshot_before=before,
            snapshot_after=after_snap,
        )
        self._current.files.append(mut)
        if result:
            self._current.note = (self._current.note + " " + result[:200]).strip()
        return mut

    def refresh_after_hashes(self) -> None:
        """Re-hash files after a tool completed (post-write)."""
        if self._current is None:
            return
        for mut in self._current.files:
            path = Path(mut.path)
            if path.is_file():
                mut.after_hash = _file_hash(path)
                if not mut.snapshot_after:
                    mut.snapshot_after = self._snapshot_file(path, "after")

    def list_turns(self) -> list[TurnMutations]:
        return list(self._turns)

    def format_diff(self, turn_id: str | None = None) -> str:
        """Human-readable diff summary (git prefer, else snapshot compare)."""
        turns = self._turns
        if turn_id:
            turns = [t for t in turns if t.turn_id == turn_id]
        if not turns:
            return "No recorded mutations."
        lines: list[str] = []
        for turn in turns[-10:]:
            lines.append(f"Turn {turn.turn_id} @ {turn.created_at}")
            for mut in turn.files:
                lines.append(
                    f"  [{mut.kind}] {mut.path} "
                    f"({mut.before_hash[:8] or '-'} → {mut.after_hash[:8] or '-'})"
                )
                git_diff = _git_diff_file(self.workspace, mut.path)
                if git_diff:
                    lines.append(git_diff[:2000])
                elif mut.snapshot_before and mut.snapshot_after:
                    lines.append(
                        f"    snapshots: {mut.snapshot_before} → {mut.snapshot_after}"
                    )
        return "\n".join(lines) if lines else "No recorded mutations."

    def rollback_turn(self, turn_id: str | None = None) -> str:
        """Restore files from before-snapshots for one turn (default: last)."""
        if not self._turns:
            return "Nothing to rollback."
        if turn_id:
            turn = next((t for t in self._turns if t.turn_id == turn_id), None)
            if turn is None:
                return f"Unknown turn: {turn_id}"
        else:
            turn = self._turns[-1]
        restored: list[str] = []
        for mut in turn.files:
            target = Path(mut.path)
            if mut.kind == "create":
                if target.is_file():
                    target.unlink()
                    restored.append(f"deleted created {target}")
                continue
            if not mut.snapshot_before:
                # Prefer git checkout when available.
                if _git_checkout_file(self.workspace, mut.path):
                    restored.append(f"git restored {mut.path}")
                continue
            snap = self.root / mut.snapshot_before
            if snap.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snap, target)
                restored.append(f"restored {target}")
        # Drop rolled-back turn and any newer turns (linear).
        idx = self._turns.index(turn)
        self._turns = self._turns[:idx]
        self._save_index()
        if not restored:
            return f"Rollback {turn.turn_id}: no snapshots available."
        return f"Rollback {turn.turn_id}:\n" + "\n".join(f"  - {r}" for r in restored)

    def _resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = (self.workspace / p).resolve()
        return p

    def _snapshot_file(self, path: Path, phase: str) -> str:
        rel = f"snaps/{uuid4().hex[:10]}_{phase}{path.suffix or '.bin'}"
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, dest)
        except OSError:
            return ""
        return rel


def _extract_path(tool_args: Any) -> str:
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except json.JSONDecodeError:
            return tool_args.strip()
    if not isinstance(tool_args, dict):
        return ""
    for key in ("path", "file_path", "file", "filename", "target"):
        val = tool_args.get(key)
        if val:
            return str(val).strip()
    return ""


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _git_diff_file(workspace: Path, path: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "diff", "--", path],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip()


def _git_checkout_file(workspace: Path, path: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "checkout", "--", path],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


__all__ = [
    "FileMutation",
    "MUTATING_TOOLS",
    "MutationTracker",
    "TurnMutations",
]

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Structured session storage (JSON files) with atomic write / recovery."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjiuwen_icode.features.session_title import (
    TITLE_MANUAL,
    TITLE_PROVISIONAL,
    display_session_title,
    looks_like_message_repr,
    provisional_title,
)


@dataclass
class StoredMessage:
    """A single message in a conversation."""

    role: str
    content: str
    timestamp: str
    token_count: Optional[int] = None


@dataclass
class StoredSession:
    """Complete record of one conversation session."""

    session_id: str
    model: str
    created_at: str
    messages: List[StoredMessage] = field(default_factory=list)
    title: str = ""
    updated_at: str = ""
    title_source: str = ""  # provisional | llm | manual | ""
    agent_profile: str = ""  # main DeepAgent profile id (e.g. code)
    forked_from: str = ""  # source session_id when created via /fork
    workdir: str = ""  # primary project directory at last persist


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically and keep a ``.bak`` of the previous file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            bak.write_bytes(path.read_bytes())
        except OSError:
            pass

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class SessionStore:
    """JSON file-based session storage under ``<icode-project>/sessions/``.

    Features (P2 / T-21):
    * atomic writes via temp + ``os.replace``
    * ``.bak`` sidecar of previous good file
    * ``session.recovery.json`` written before replace; cleared after success
    * ``load_session`` / ``switch_session`` restore API
    * session ``title`` / ``updated_at`` for list UX (T-44)
    """

    def __init__(self, store_dir: Optional[Path] = None) -> None:
        if store_dir is None:
            from openjiuwen_icode.paths import IcodeProject

            store_dir = IcodeProject.open().sessions_dir
        self.store_dir = store_dir
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._current: Optional[StoredSession] = None

    @property
    def current(self) -> Optional[StoredSession]:
        return self._current

    def new_session(
        self,
        session_id: str,
        model: str,
        *,
        agent_profile: str | None = None,
        workdir: str | None = None,
    ) -> StoredSession:
        """Start tracking a new session (in memory; persisted on first message)."""
        from openjiuwen_icode.agent.profile_loader import (
            active_agent_profile_id,
        )

        profile = (agent_profile or active_agent_profile_id() or "code").strip()
        wd = (workdir or "").strip()
        now = _utc_now()
        self._current = StoredSession(
            session_id=session_id,
            model=model,
            created_at=now,
            updated_at=now,
            title="",
            title_source="",
            agent_profile=profile,
            workdir=wd,
        )
        return self._current

    def add_message(self, role: str, content: str) -> None:
        """Append a message to the current session and persist."""
        if self._current is None:
            return
        self._current.messages.append(
            StoredMessage(
                role=role,
                content=content,
                timestamp=_utc_now(),
            )
        )
        if (
            role == "user"
            and not self._current.title
            and not self._current.title_source
        ):
            self._current.title = provisional_title(content)
            self._current.title_source = TITLE_PROVISIONAL
        self._current.updated_at = _utc_now()
        self._save()

    def set_title(
        self,
        title: str,
        *,
        source: str = TITLE_MANUAL,
        force: bool = False,
    ) -> bool:
        """Update the current session title.

        Returns ``True`` if the title was changed. LLM/provisional updates are
        skipped when the title was set manually unless *force* is True.
        """
        if self._current is None:
            return False
        cleaned = (title or "").strip()
        if not cleaned or looks_like_message_repr(cleaned):
            return False
        if (
            not force
            and self._current.title_source == TITLE_MANUAL
            and source != TITLE_MANUAL
        ):
            return False
        if (
            cleaned == self._current.title
            and source == self._current.title_source
        ):
            return False
        self._current.title = cleaned
        self._current.title_source = source
        self._current.updated_at = _utc_now()
        self._save()
        return True

    def update_metadata(
        self,
        *,
        model: str | None = None,
        workdir: str | None = None,
        agent_profile: str | None = None,
    ) -> bool:
        """Patch session fields and persist when anything changed."""
        if self._current is None:
            return False
        changed = False
        if model is not None:
            cleaned = model.strip()
            if cleaned and cleaned != self._current.model:
                self._current.model = cleaned
                changed = True
        if workdir is not None:
            cleaned = workdir.strip()
            if cleaned != (self._current.workdir or ""):
                self._current.workdir = cleaned
                changed = True
        if agent_profile is not None:
            cleaned = agent_profile.strip()
            if cleaned and cleaned != (self._current.agent_profile or ""):
                self._current.agent_profile = cleaned
                changed = True
        if not changed:
            return False
        self._current.updated_at = _utc_now()
        self._save()
        return True

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Return summaries of all persisted sessions (newest first)."""
        sessions: list[dict[str, Any]] = []
        for path in self.store_dir.glob("*.json"):
            if path.name.endswith(".recovery.json") or path.name.startswith(
                "."
            ):
                continue
            if path.suffix == ".bak" or path.name.endswith(".json.bak"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                messages = data.get("messages") or []
                stub = StoredSession(
                    session_id=str(data.get("session_id") or ""),
                    model=str(data.get("model") or ""),
                    created_at=str(data.get("created_at") or ""),
                    title=str(data.get("title") or ""),
                    agent_profile=str(data.get("agent_profile") or ""),
                    messages=[
                        StoredMessage(
                            role=str(m.get("role", "")),
                            content=str(m.get("content", "")),
                            timestamp=str(m.get("timestamp", "")),
                        )
                        for m in messages
                        if isinstance(m, dict)
                    ],
                )
                title = display_session_title(stub)
                preview = ""
                for msg in messages:
                    if (
                        isinstance(msg, dict)
                        and msg.get("role") == "user"
                        and msg.get("content")
                    ):
                        preview = str(msg["content"]).strip()
                        break
                if not title:
                    title = "Untitled"
                updated = str(
                    data.get("updated_at")
                    or data.get("created_at")
                    or ""
                )
                try:
                    size_bytes = path.stat().st_size
                except OSError:
                    size_bytes = 0
                directory = str(
                    data.get("workdir")
                    or data.get("workspace")
                    or data.get("cwd")
                    or ""
                )
                sessions.append(
                    {
                        "id": data["session_id"],
                        "model": data.get("model", ""),
                        "created_at": data.get("created_at", ""),
                        "updated_at": updated,
                        "turns": len(messages),
                        "title": title,
                        "title_source": str(data.get("title_source") or ""),
                        "agent_profile": str(data.get("agent_profile") or ""),
                        "size_bytes": size_bytes,
                        "directory": directory,
                        "preview": preview,
                        "path": str(path),
                    }
                )
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        sessions.sort(
            key=lambda row: str(row.get("updated_at") or ""),
            reverse=True,
        )
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a persisted session file (and bak/recovery sidecars).

        Returns True if the primary JSON was removed.
        """
        path = self._session_path(session_id)
        removed = False
        for candidate in (
            path,
            path.with_suffix(path.suffix + ".bak"),
            self._recovery_path(session_id),
        ):
            try:
                if candidate.exists():
                    candidate.unlink()
                    if candidate == path:
                        removed = True
            except OSError:
                continue
        if (
            self._current is not None
            and self._current.session_id == session_id
        ):
            self._current = None
        return removed

    def load_session(self, session_id: str) -> StoredSession:
        """Load a persisted session into memory (does not switch current)."""
        path = self._session_path(session_id)
        data = self._read_session_file(path, session_id)
        messages = [
            StoredMessage(
                role=str(item.get("role", "")),
                content=str(item.get("content", "")),
                timestamp=str(item.get("timestamp", "")),
                token_count=item.get("token_count"),
            )
            for item in data.get("messages", [])
            if isinstance(item, dict)
        ]
        title = str(data.get("title") or "")
        title_source = str(data.get("title_source") or "")
        if not title:
            for msg in messages:
                if msg.role == "user" and msg.content:
                    title = provisional_title(msg.content)
                    title_source = title_source or TITLE_PROVISIONAL
                    break
        return StoredSession(
            session_id=str(data["session_id"]),
            model=str(data.get("model", "")),
            created_at=str(data.get("created_at", "")),
            messages=messages,
            title=title,
            updated_at=str(
                data.get("updated_at") or data.get("created_at") or ""
            ),
            title_source=title_source,
            agent_profile=str(data.get("agent_profile") or ""),
            forked_from=str(data.get("forked_from") or ""),
            workdir=str(data.get("workdir") or ""),
        )

    def switch_session(self, session_id: str) -> StoredSession:
        """Load *session_id* and make it the current session."""
        session = self.load_session(session_id)
        self._current = session
        return session

    def fork_session(
        self,
        source_id: str,
        new_id: str,
        *,
        title_suffix: str = " (fork)",
    ) -> StoredSession:
        """Clone persisted transcript + metadata into *new_id* (must not exist)."""
        if self._session_path(new_id).exists():
            raise FileExistsError(f"session already exists: {new_id}")
        source = self.load_session(source_id)
        now = _utc_now()
        title = (source.title or "").strip()
        if title and title_suffix and not title.endswith(title_suffix):
            title = f"{title}{title_suffix}"
        elif not title:
            title = f"Fork of {source_id[:16]}"
        forked = StoredSession(
            session_id=new_id,
            model=source.model,
            created_at=now,
            updated_at=now,
            messages=[
                StoredMessage(
                    role=m.role,
                    content=m.content,
                    timestamp=m.timestamp,
                    token_count=m.token_count,
                )
                for m in source.messages
            ],
            title=title,
            title_source=source.title_source,
            agent_profile=source.agent_profile,
            forked_from=source_id,
            workdir=source.workdir,
        )
        self._current = forked
        self._save()
        from openjiuwen_icode.storage.event_log import (
            copy_session_event_log,
        )

        copy_session_event_log(self.store_dir, source_id, new_id)
        return forked

    def save_current(self) -> None:
        """Force-persist the current session."""
        self._save()

    def _session_path(self, session_id: str) -> Path:
        return self.store_dir / f"{session_id}.json"

    def _recovery_path(self, session_id: str) -> Path:
        return self.store_dir / f"{session_id}.recovery.json"

    def _read_session_file(
        self, path: Path, session_id: str
    ) -> dict[str, Any]:
        candidates = [
            path,
            path.with_suffix(path.suffix + ".bak"),
            self._recovery_path(session_id),
        ]
        last_error: Exception | None = None
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "session_id" in data:
                    return data
            except (json.JSONDecodeError, OSError) as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise FileNotFoundError(
                f"session {session_id!r} unreadable: {last_error}"
            ) from last_error
        raise FileNotFoundError(f"session not found: {session_id}")

    def _save(self) -> None:
        if self._current is None:
            return
        if not self._current.updated_at:
            self._current.updated_at = self._current.created_at or _utc_now()
        path = self._session_path(self._current.session_id)
        recovery = self._recovery_path(self._current.session_id)
        payload = asdict(self._current)
        recovery.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            _atomic_write_json(path, payload)
        except Exception:
            # Leave recovery sidecar for next load attempt.
            raise
        try:
            recovery.unlink(missing_ok=True)
        except OSError:
            pass

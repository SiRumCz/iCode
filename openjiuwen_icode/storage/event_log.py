# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Append-only session event log for OpenCode-compatible export."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from openjiuwen_icode.events.types import Event

logger = logging.getLogger(__name__)

# Events that matter for trajectory / OpenCode parts reconstruction.
_RECORDED_TYPES = frozenset(
    {
        "UserMessage",
        "TurnStarted",
        "TurnFinished",
        "TurnFailed",
        "AgentMessage",
        "AgentThinking",
        "ToolCallStart",
        "ToolCallResult",
        "UsageUpdate",
        "ModelUsage",
        "CompactionStarted",
        "CompactionFinished",
        "SubAgentStarted",
        "SubAgentFinished",
        "SubAgentFailed",
        "SubAgentToolCallStart",
        "SubAgentToolCallResult",
        "TodoListUpdated",
    }
)


def event_log_path(store_dir: Path, session_id: str) -> Path:
    """Return ``<icode-project>/sessions/<id>/events.jsonl``."""
    return store_dir / session_id / "events.jsonl"


def serialize_event(event: Event) -> dict[str, Any]:
    """JSON-serializable record for one EventBus event."""
    data: dict[str, Any] = {
        "type": type(event).__name__,
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "session_id": event.session_id,
    }
    # Prefer explicit fields over a full ``asdict`` dump so we stay
    # stable across event schema additions.
    for key, value in vars(event).items():
        if key in data:
            continue
        data[key] = _json_safe(value)
    return data


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except Exception:
            dumped = None
        if isinstance(dumped, dict):
            return _json_safe(dumped)
    return str(value)


class SessionEventLog:
    """Append-only JSONL log of transcript-relevant EventBus events."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_session(cls, store_dir: Path, session_id: str) -> SessionEventLog:
        return cls(event_log_path(store_dir, session_id))

    def should_record(self, event: Event) -> bool:
        return type(event).__name__ in _RECORDED_TYPES

    def append(self, record: dict[str, Any]) -> None:
        """Append one already-serialized record."""
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")
        except OSError:
            logger.exception("Failed to append session event log %s", self.path)

    def record_event(self, event: Event) -> None:
        """Serialize and append *event* when it is transcript-relevant."""
        if not self.should_record(event):
            return
        self.append(serialize_event(event))

    def read_all(self) -> list[dict[str, Any]]:
        """Load all JSONL records (skips corrupt lines)."""
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed to read session event log %s", self.path)
            return []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def clear(self) -> None:
        """Truncate the log file if present."""
        try:
            if self.path.exists():
                self.path.write_text("", encoding="utf-8")
        except OSError:
            logger.exception("Failed to clear session event log %s", self.path)


def load_session_events(
    store_dir: Path,
    session_id: str,
) -> list[dict[str, Any]]:
    """Convenience loader for ``events.jsonl``."""
    return SessionEventLog.for_session(store_dir, session_id).read_all()


def copy_session_event_log(
    store_dir: Path,
    source_id: str,
    dest_id: str,
) -> bool:
    """Copy ``events.jsonl`` from *source_id* to *dest_id*, rewriting ``session_id``."""
    src = event_log_path(store_dir, source_id)
    if not src.is_file():
        return False
    dest = event_log_path(store_dir, dest_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []
    try:
        raw = src.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read event log %s", src)
        return False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            out_lines.append(line)
            continue
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["session_id"] = dest_id
            out_lines.append(json.dumps(payload, ensure_ascii=False))
        else:
            out_lines.append(line)
    try:
        dest.write_text(
            "\n".join(out_lines) + ("\n" if out_lines else ""),
            encoding="utf-8",
        )
    except OSError:
        logger.exception("Failed to write event log %s", dest)
        return False
    return True


def iter_recorded_types() -> Iterable[str]:
    """Return the event type whitelist (for tests / docs)."""
    return sorted(_RECORDED_TYPES)


__all__ = [
    "SessionEventLog",
    "copy_session_event_log",
    "event_log_path",
    "iter_recorded_types",
    "load_session_events",
    "serialize_event",
]

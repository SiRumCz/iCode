# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Pure presentation helpers for the Sessions modal (sortable / searchable)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kib = size_bytes / 1024
    if kib < 1024:
        return f"{kib:.1f} KB"
    mib = kib / 1024
    if mib < 1024:
        return f"{mib:.1f} MB"
    return f"{mib / 1024:.1f} GB"


def _parse_iso(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def time_ago(value: str, *, now: datetime | None = None) -> str:
    dt = _parse_iso(value)
    if dt is None:
        return value[:16].replace("T", " ") if value else "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    current = now or datetime.now(tz=timezone.utc)
    seconds = int((current - dt).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days == 1:
        return "1 day ago"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    if months == 1:
        return "1 month ago"
    if months < 12:
        return f"{months} months ago"
    years = days // 365
    if years == 1:
        return "1 year ago"
    return f"{years} years ago"


def absolute_time(value: str) -> str:
    dt = _parse_iso(value)
    if dt is None:
        return value or "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y/%m/%d %H:%M")


def short_id(session_id: str, *, length: int = 12) -> str:
    text = (session_id or "").strip()
    if len(text) <= length:
        return text
    return text[:length]


def directory_display(raw: str, *, max_width: int = 24) -> str:
    text = (raw or "").strip()
    if not text:
        return "-"
    name = Path(text).name or text
    if len(name) <= max_width:
        return name
    keep = max(4, (max_width - 1) // 2)
    return f"{name[:keep]}…{name[-keep:]}"


def title_display(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "").strip()
    if title:
        return title
    return f"{short_id(str(row.get('id') or ''), length=8)}.."


@dataclass(frozen=True)
class SessionColumn:
    key: str
    label: str
    width: int | None = None
    numeric: bool = False
    default_reverse: bool = False


COLUMNS: tuple[SessionColumn, ...] = (
    SessionColumn("id", "Session ID", width=14),
    SessionColumn("title", "Title", width=28),
    SessionColumn("directory", "Directory", width=16),
    SessionColumn(
        "updated", "Last Active", width=14, default_reverse=True
    ),
    SessionColumn("turns", "Turns", width=7, numeric=True, default_reverse=True),
    SessionColumn("size", "Size", width=9, numeric=True, default_reverse=True),
)


def column_by_key(key: str) -> SessionColumn:
    for column in COLUMNS:
        if column.key == key:
            return column
    return COLUMNS[3]  # Last Active


@dataclass
class SessionRow:
    meta: dict[str, Any]
    cells: dict[str, str]
    search_blob: str
    prompt_snippet: str = ""


def _cell_values(meta: dict[str, Any]) -> dict[str, str]:
    return {
        "id": short_id(str(meta.get("id") or "")),
        "title": title_display(meta),
        "directory": directory_display(str(meta.get("directory") or "")),
        "updated": time_ago(str(meta.get("updated_at") or "")),
        "turns": str(int(meta.get("turns") or 0)),
        "size": format_size(int(meta.get("size_bytes") or 0)),
    }


def _search_blob(meta: dict[str, Any], cells: dict[str, str]) -> str:
    parts = [
        str(meta.get("id") or ""),
        str(meta.get("title") or ""),
        str(meta.get("model") or ""),
        str(meta.get("directory") or ""),
        str(meta.get("preview") or ""),
        *cells.values(),
    ]
    return " ".join(parts).lower()


def build_session_rows(
    sessions: list[dict[str, Any]],
    *,
    sort_column: str = "updated",
    sort_reverse: bool = True,
    query: str = "",
) -> list[SessionRow]:
    rows = [
        SessionRow(
            meta=meta,
            cells=_cell_values(meta),
            search_blob=_search_blob(meta, _cell_values(meta)),
            prompt_snippet=_snippet(str(meta.get("preview") or "")),
        )
        for meta in sessions
    ]
    needle = (query or "").strip().lower()
    if needle:
        filtered: list[SessionRow] = []
        for row in rows:
            if needle in row.search_blob:
                filtered.append(row)
                continue
            preview = str(row.meta.get("preview") or "")
            if needle in preview.lower():
                # Mark prompt-only match via snippet.
                row.prompt_snippet = _snippet(preview, needle=needle)
                filtered.append(row)
        rows = filtered

    key = sort_column or "updated"
    reverse = sort_reverse

    def sort_key(row: SessionRow) -> Any:
        meta = row.meta
        if key == "id":
            return str(meta.get("id") or "")
        if key == "title":
            return title_display(meta).lower()
        if key == "directory":
            return str(meta.get("directory") or "").lower()
        if key == "updated":
            return str(meta.get("updated_at") or "")
        if key == "turns":
            return int(meta.get("turns") or 0)
        if key == "size":
            return int(meta.get("size_bytes") or 0)
        return str(meta.get("updated_at") or "")

    rows.sort(key=sort_key, reverse=reverse)
    return rows


def _snippet(text: str, *, needle: str = "", limit: int = 80) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    if needle:
        idx = cleaned.lower().find(needle.lower())
        if idx >= 0:
            start = max(0, idx - 20)
            chunk = cleaned[start : start + limit]
            return ("…" if start else "") + chunk
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def row_tooltip_lines(row: SessionRow) -> list[str]:
    meta = row.meta
    lines = [
        f"Title: {title_display(meta)}",
        f"Model: {meta.get('model') or '-'}",
    ]
    if row.prompt_snippet:
        lines.insert(1, f"Prompt: {row.prompt_snippet}")
    directory = str(meta.get("directory") or "").strip()
    if directory:
        lines.append(f"Directory: {directory}")
    lines.append(f"Turns: {int(meta.get('turns') or 0)}")
    lines.append(f"Size: {format_size(int(meta.get('size_bytes') or 0))}")
    lines.append(
        f"Last interaction: {absolute_time(str(meta.get('updated_at') or ''))}"
    )
    lines.append(f"Session ID: {meta.get('id') or '-'}")
    return lines


__all__ = [
    "COLUMNS",
    "SessionColumn",
    "SessionRow",
    "absolute_time",
    "build_session_rows",
    "column_by_key",
    "directory_display",
    "format_size",
    "row_tooltip_lines",
    "short_id",
    "time_ago",
    "title_display",
]

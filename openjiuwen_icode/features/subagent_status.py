# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Sub-agent activity listing for CLI slash commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _audit_entries(session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    from openjiuwen_icode.paths import IcodeProject

    path = IcodeProject.open().sessions_dir / session_id / "sub_agents.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def collect_subagent_items(
    agent: Any | None,
    session_id: str,
) -> list[dict[str, Any]]:
    """Merge async toolkit rows with recent audit log entries."""
    items: list[dict[str, Any]] = []
    toolkit = getattr(agent, "_session_toolkit", None) if agent is not None else None
    if toolkit is not None:
        for row in toolkit.list_all():
            items.append(
                {
                    "source": "async",
                    "task_id": row.task_id,
                    "subagent_type": getattr(row, "subagent_type", "") or "",
                    "status": row.status,
                    "description": (row.description or "")[:120],
                    "sub_session_id": row.sub_session_id,
                    "result": (row.result or "")[:80],
                    "error": (row.error or "")[:80],
                }
            )
    for entry in _audit_entries(session_id):
        items.append(
            {
                "source": "audit",
                "phase": entry.get("phase", ""),
                "subagent_type": entry.get("agent_name", ""),
                "invocation_id": entry.get("invocation_id", ""),
                "sub_session_id": entry.get("sub_session_id", ""),
                "transport": entry.get("transport", ""),
                "ok": entry.get("ok"),
            }
        )
    return items


def format_subagent_status_text(
    agent: Any | None,
    session_id: str,
) -> str:
    """Human-readable report for ``/subagents``."""
    items = collect_subagent_items(agent, session_id)
    if not items:
        return "No sub-agent activity for this session yet."

    lines = [f"Sub-agents (session {session_id or '-'}):"]
    async_rows = [i for i in items if i.get("source") == "async"]
    if async_rows:
        lines.append("")
        lines.append("Background tasks:")
        for row in async_rows:
            st = row.get("subagent_type") or "subagent"
            lines.append(
                f"  {row.get('task_id', '?')[:12]}… | {st} | "
                f"{row.get('status', '?')} | {row.get('description', '')}"
            )
    audit_rows = [i for i in items if i.get("source") == "audit"]
    if audit_rows:
        lines.append("")
        lines.append("Recent lifecycle (audit tail):")
        for row in audit_rows[-8:]:
            inv = row.get("invocation_id") or "-"
            phase = row.get("phase") or "?"
            st = row.get("subagent_type") or "subagent"
            transport = row.get("transport") or ""
            extra = f" [{transport}]" if transport else ""
            lines.append(f"  {inv} | {phase} | {st}{extra}")
    return "\n".join(lines)


__all__ = [
    "collect_subagent_items",
    "format_subagent_status_text",
]

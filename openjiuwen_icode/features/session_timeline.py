# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Rebuild a chat-facing timeline from session ``events.jsonl``.

Rows mirror what the VS Code extension shows during a live ACP turn
(``user`` / ``thought`` / ``tool`` / ``assistant`` / ``system``).
"""

from __future__ import annotations

import json
from typing import Any

from openjiuwen_icode.storage.event_log import load_session_events

_MAX_TOOL_DETAIL = 2_000


def _clip(text: str, limit: int = _MAX_TOOL_DETAIL) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _fmt_json(value: Any) -> str:
    """Match extension live tool detail: JSON.stringify-style args/result."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _clip(value)
    try:
        return _clip(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return _clip(str(value))


def timeline_from_events(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Collapse EventBus JSONL into UI transcript rows.

    Formatting matches ``handleSessionUpdate`` in the VS Code extension:
    - thinking → one ``thought`` bubble (merged chunks)
    - tool start → ``▶ {name}`` + JSON args
    - tool result → ``■ {name} {status}`` + clipped result
    - usage → ``Tokens in=… out=…``
    - assistant → merged text (markdown-rendered in the client)
    """
    timeline: list[dict[str, str]] = []
    thinking: list[str] = []
    assistant: list[str] = []

    def flush_thinking() -> None:
        text = "".join(thinking)
        thinking.clear()
        if text:
            timeline.append({"role": "thought", "content": text})

    def flush_assistant() -> None:
        text = "".join(assistant)
        assistant.clear()
        if text:
            timeline.append({"role": "assistant", "content": text})

    for ev in events:
        kind = str(ev.get("type") or "")
        if kind == "UserMessage":
            flush_thinking()
            flush_assistant()
            text = str(ev.get("text") or "")
            if text:
                timeline.append({"role": "user", "content": text})
        elif kind == "AgentThinking":
            flush_assistant()
            chunk = str(ev.get("text") or "")
            if chunk:
                thinking.append(chunk)
        elif kind == "AgentMessage":
            flush_thinking()
            chunk = str(ev.get("text") or "")
            if chunk:
                assistant.append(chunk)
        elif kind == "ToolCallStart":
            flush_thinking()
            flush_assistant()
            name = str(ev.get("tool_name") or "tool")
            # Live path: JSON.stringify(rawInput ?? {})
            args = ev.get("tool_args")
            detail = _fmt_json({} if args is None else args)
            timeline.append(
                {
                    "role": "tool",
                    "title": f"▶ {name}",
                    "content": detail,
                }
            )
        elif kind == "ToolCallResult":
            flush_thinking()
            flush_assistant()
            name = str(ev.get("tool_name") or "tool")
            ok = ev.get("tool_success")
            status = "failed" if ok is False else "completed"
            detail = _fmt_json(ev.get("result"))
            timeline.append(
                {
                    "role": "tool",
                    "title": f"■ {name} {status}",
                    "content": detail,
                }
            )
        elif kind == "UsageUpdate":
            flush_thinking()
            flush_assistant()
            timeline.append(
                {
                    "role": "system",
                    "content": (
                        f"Tokens in={int(ev.get('input_tokens') or 0)} "
                        f"out={int(ev.get('output_tokens') or 0)}"
                    ),
                }
            )
        elif kind == "TurnFailed":
            flush_thinking()
            flush_assistant()
            err = str(ev.get("error") or "turn failed")
            timeline.append({"role": "system", "content": f"Error: {err}"})
        elif kind in {"TurnFinished", "TurnStarted"}:
            flush_thinking()
            flush_assistant()

    flush_thinking()
    flush_assistant()
    return timeline


def session_timeline(
    store_dir: Any,
    session_id: str,
    *,
    fallback_messages: list[Any] | None = None,
) -> list[dict[str, str]]:
    """Prefer ``events.jsonl`` timeline; else map stored user/assistant messages."""
    from pathlib import Path

    events = load_session_events(Path(store_dir), session_id)
    if events:
        rows = timeline_from_events(events)
        if rows:
            return rows
    out: list[dict[str, str]] = []
    for msg in fallback_messages or []:
        role = str(getattr(msg, "role", None) or "")
        content = str(getattr(msg, "content", None) or "")
        if isinstance(msg, dict):
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
        if not content:
            continue
        out.append({"role": role or "system", "content": content})
    return out


__all__ = ["session_timeline", "timeline_from_events"]

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Materialize OpenCode-compatible ``{info, messages[{info, parts}]}`` exports."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from openjiuwen_icode.agent.profile_loader import active_agent_profile_id
from openjiuwen_icode.branding import PRODUCT_NAME
from openjiuwen_icode.features.session_title import display_session_title
from openjiuwen_icode.storage.event_log import load_session_events
from openjiuwen_icode.storage.session_store import (
    SessionStore,
    StoredMessage,
    StoredSession,
)

_EXPORT_SCHEMA = "opencode-export-compat"
_HARNESS_VERSION = "openjiuwen-harness"
_DEFAULT_AGENT_PROFILE = "code"


def resolve_export_agent_profile(
    session: StoredSession | None = None,
    *,
    agent_profile: str | None = None,
) -> str:
    """OpenCode ``agent`` / ``mode`` label for the main (profile) agent."""
    pid = (agent_profile or "").strip()
    if not pid and session is not None:
        pid = str(getattr(session, "agent_profile", "") or "").strip()
    if not pid:
        pid = active_agent_profile_id().strip()
    return pid or _DEFAULT_AGENT_PROFILE


def _oc_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def _ms(ts: float | str | None) -> int:
    if ts is None:
        return int(time.time() * 1000)
    if isinstance(ts, (int, float)):
        # Heuristic: values < 1e12 are seconds.
        if ts < 1_000_000_000_000:
            return int(ts * 1000)
        return int(ts)
    text = str(ts).strip()
    if not text:
        return int(time.time() * 1000)
    try:
        # ISO-8601
        from datetime import datetime

        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        try:
            return int(float(text) * 1000)
        except ValueError:
            return int(time.time() * 1000)


def _empty_tokens() -> dict[str, Any]:
    return {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache": {"read": 0, "write": 0},
    }


def _parse_model(model: str) -> tuple[str, str]:
    raw = (model or "unknown").strip() or "unknown"
    if "/" in raw:
        provider, name = raw.split("/", 1)
        return provider or "unknown", name or raw
    return "unknown", raw


def _sanitize_text(text: str, *, enabled: bool) -> str:
    if not enabled or not text:
        return text
    home = str(Path.home())
    out = text.replace(home, "~")
    # Redact obvious absolute POSIX paths while keeping basename cues.
    out = re.sub(r"(?<!\w)/[\w./-]+", "[redacted:path]", out)
    return out


def _sanitize_obj(value: Any, *, enabled: bool) -> Any:
    if not enabled:
        return value
    if isinstance(value, str):
        return _sanitize_text(value, enabled=True)
    if isinstance(value, dict):
        return {k: _sanitize_obj(v, enabled=True) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_obj(v, enabled=True) for v in value]
    return value


def _tool_title(tool_name: str, tool_args: Any) -> str:
    if isinstance(tool_args, dict):
        for key in ("path", "file_path", "command", "query", "url"):
            val = tool_args.get(key)
            if val:
                return f"{tool_name} {val}"
    return tool_name or "tool"


class _ExportBuilder:
    """Incremental OpenCode transcript builder from event records."""

    def __init__(
        self,
        *,
        session_id: str,
        model: str,
        directory: str,
        title: str,
        created_ms: int,
        agent: str = "build",
        agent_profile: str = "",
        product: str = "",
        sanitize: bool = False,
    ) -> None:
        self.session_id = session_id
        self.model = model
        self.provider_id, self.model_id = _parse_model(model)
        self.directory = directory
        self.title = title
        self.created_ms = created_ms
        self.updated_ms = created_ms
        self.agent_profile = agent_profile or agent
        self.agent = self.agent_profile
        self.product = product or PRODUCT_NAME
        self.sanitize = sanitize
        self.messages: list[dict[str, Any]] = []
        self._user_msg: dict[str, Any] | None = None
        self._assistant_msg: dict[str, Any] | None = None
        self._open_tools: dict[str, dict[str, Any]] = {}
        self._tool_queue: list[str] = []
        self._step_open = False
        self._text_buf: list[str] = []
        self._reasoning_buf: list[str] = []
        self._saw_tool = False
        self._last_tokens = _empty_tokens()
        self.fidelity = "text"

    def _touch(self, ts: Any) -> int:
        ms = _ms(ts)
        self.updated_ms = max(self.updated_ms, ms)
        return ms

    def _ensure_assistant(self, ts: Any) -> dict[str, Any]:
        if self._assistant_msg is not None:
            return self._assistant_msg
        ms = self._touch(ts)
        parent_id = ""
        if self._user_msg is not None:
            parent_id = str(self._user_msg["info"]["id"])
        msg = {
            "info": {
                "id": _oc_id("msg"),
                "sessionID": self.session_id,
                "role": "assistant",
                "time": {"created": ms},
                "parentID": parent_id,
                "modelID": self.model_id,
                "providerID": self.provider_id,
                "mode": self.agent,
                "agent": self.agent,
                "path": {"cwd": self.directory, "root": self.directory},
                "cost": 0,
                "tokens": _empty_tokens(),
                "finish": "unknown",
            },
            "parts": [],
        }
        self.messages.append(msg)
        self._assistant_msg = msg
        self._step_open = False
        self._text_buf = []
        self._reasoning_buf = []
        self._saw_tool = False
        self._open_tools.clear()
        self._tool_queue.clear()
        return msg

    def _ensure_step_start(self, ts: Any) -> None:
        msg = self._ensure_assistant(ts)
        if self._step_open:
            return
        ms = self._touch(ts)
        msg["parts"].append(
            {
                "id": _oc_id("prt"),
                "sessionID": self.session_id,
                "messageID": msg["info"]["id"],
                "type": "step-start",
            }
        )
        self._step_open = True
        _ = ms

    def _flush_text(self, ts: Any) -> None:
        if not self._text_buf or self._assistant_msg is None:
            return
        text = "".join(self._text_buf)
        self._text_buf = []
        if not text:
            return
        ms = self._touch(ts)
        msg = self._assistant_msg
        msg["parts"].append(
            {
                "id": _oc_id("prt"),
                "sessionID": self.session_id,
                "messageID": msg["info"]["id"],
                "type": "text",
                "text": _sanitize_text(text, enabled=self.sanitize),
                "time": {"start": ms, "end": ms},
            }
        )

    def _flush_reasoning(self, ts: Any) -> None:
        if not self._reasoning_buf or self._assistant_msg is None:
            return
        text = "".join(self._reasoning_buf)
        self._reasoning_buf = []
        if not text:
            return
        ms = self._touch(ts)
        msg = self._assistant_msg
        msg["parts"].append(
            {
                "id": _oc_id("prt"),
                "sessionID": self.session_id,
                "messageID": msg["info"]["id"],
                "type": "reasoning",
                "text": _sanitize_text(text, enabled=self.sanitize),
                "time": {"start": ms, "end": ms},
            }
        )
        self.fidelity = "full"

    def _close_step(self, ts: Any, *, reason: str) -> None:
        if self._assistant_msg is None or not self._step_open:
            return
        self._flush_reasoning(ts)
        self._flush_text(ts)
        ms = self._touch(ts)
        msg = self._assistant_msg
        tokens = dict(self._last_tokens)
        msg["parts"].append(
            {
                "id": _oc_id("prt"),
                "sessionID": self.session_id,
                "messageID": msg["info"]["id"],
                "type": "step-finish",
                "reason": reason,
                "cost": 0,
                "tokens": tokens,
            }
        )
        msg["info"]["finish"] = reason
        msg["info"]["tokens"] = tokens
        msg["info"]["time"]["completed"] = ms
        self._step_open = False

    def on_user_turn(self, text: str, ts: Any) -> None:
        self._close_step(ts, reason="stop" if not self._saw_tool else "tool-calls")
        self._assistant_msg = None
        ms = self._touch(ts)
        msg_id = _oc_id("msg")
        part_id = _oc_id("prt")
        body = _sanitize_text(text or "", enabled=self.sanitize)
        msg = {
            "info": {
                "id": msg_id,
                "sessionID": self.session_id,
                "role": "user",
                "time": {"created": ms},
                "agent": self.agent,
                "model": {
                    "providerID": self.provider_id,
                    "modelID": self.model_id,
                },
            },
            "parts": [
                {
                    "id": part_id,
                    "sessionID": self.session_id,
                    "messageID": msg_id,
                    "type": "text",
                    "text": body,
                }
            ],
        }
        self.messages.append(msg)
        self._user_msg = msg

    def on_agent_text(self, text: str, ts: Any) -> None:
        if not text:
            return
        self._ensure_step_start(ts)
        self._text_buf.append(text)

    def on_thinking(self, text: str, ts: Any) -> None:
        if not text:
            return
        self._ensure_step_start(ts)
        self._reasoning_buf.append(text)

    def on_tool_start(
        self,
        *,
        tool_name: str,
        tool_args: Any,
        tool_call_id: str,
        ts: Any,
    ) -> None:
        self._ensure_step_start(ts)
        self._flush_reasoning(ts)
        self._flush_text(ts)
        self._saw_tool = True
        self.fidelity = "full"
        ms = self._touch(ts)
        msg = self._ensure_assistant(ts)
        call_id = tool_call_id or _oc_id("call")
        part = {
            "id": _oc_id("prt"),
            "sessionID": self.session_id,
            "messageID": msg["info"]["id"],
            "type": "tool",
            "callID": call_id,
            "tool": tool_name or "unknown",
            "state": {
                "status": "running",
                "input": _sanitize_obj(tool_args if tool_args is not None else {}, enabled=self.sanitize),
                "time": {"start": ms},
            },
        }
        msg["parts"].append(part)
        self._open_tools[call_id] = part
        self._tool_queue.append(call_id)

    def on_tool_result(
        self,
        *,
        tool_name: str,
        result: str,
        tool_call_id: str,
        ok: bool | None,
        ts: Any,
    ) -> None:
        self._ensure_step_start(ts)
        ms = self._touch(ts)
        call_id = tool_call_id
        part = self._open_tools.get(call_id) if call_id else None
        if part is None and self._tool_queue:
            # Match FIFO when call ids were missing on start/result.
            call_id = self._tool_queue.pop(0)
            part = self._open_tools.pop(call_id, None)
        elif call_id and call_id in self._open_tools:
            part = self._open_tools.pop(call_id)
            if call_id in self._tool_queue:
                self._tool_queue.remove(call_id)
        if part is None:
            # Result without start — synthesize a completed tool part.
            self.on_tool_start(
                tool_name=tool_name,
                tool_args={},
                tool_call_id=call_id or "",
                ts=ts,
            )
            return self.on_tool_result(
                tool_name=tool_name,
                result=result,
                tool_call_id=call_id or (self._tool_queue[-1] if self._tool_queue else ""),
                ok=ok,
                ts=ts,
            )
        status = "completed" if ok is not False else "error"
        state = part.setdefault("state", {})
        state["status"] = status
        state["output"] = _sanitize_text(result or "", enabled=self.sanitize)
        state["title"] = _sanitize_text(
            _tool_title(tool_name or part.get("tool", ""), state.get("input")),
            enabled=self.sanitize,
        )
        state.setdefault("metadata", {})
        time_info = state.setdefault("time", {})
        time_info["end"] = ms
        self.fidelity = "full"

    def on_model_usage(self, *, input_tokens: int, output_tokens: int, ts: Any) -> None:
        self._last_tokens = {
            "input": int(input_tokens or 0),
            "output": int(output_tokens or 0),
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        }
        self._touch(ts)
        if self._assistant_msg is not None:
            self._assistant_msg["info"]["tokens"] = dict(self._last_tokens)
        self.fidelity = "full"

    def on_usage_totals(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        ts: Any,
    ) -> None:
        # Prefer per-call ModelUsage; totals fill gaps for text-only runs.
        if self._last_tokens["input"] or self._last_tokens["output"]:
            self._touch(ts)
            return
        self.on_model_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            ts=ts,
        )

    def on_subagent(
        self,
        *,
        agent_name: str,
        task: str,
        result: str,
        ok: bool,
        ts: Any,
    ) -> None:
        self._ensure_step_start(ts)
        self._flush_text(ts)
        ms = self._touch(ts)
        msg = self._ensure_assistant(ts)
        msg["parts"].append(
            {
                "id": _oc_id("prt"),
                "sessionID": self.session_id,
                "messageID": msg["info"]["id"],
                "type": "subtask",
                "prompt": _sanitize_text(task or "", enabled=self.sanitize),
                "description": _sanitize_text(
                    (result or "")[:500],
                    enabled=self.sanitize,
                ),
                "agent": agent_name or "subagent",
                "time": {"start": ms, "end": ms},
                "metadata": {"ok": ok},
            }
        )
        self.fidelity = "full"

    def on_turn_finished(self, ts: Any) -> None:
        reason = "tool-calls" if self._saw_tool else "stop"
        self._close_step(ts, reason=reason)
        self._assistant_msg = None

    def on_turn_failed(self, error: str, ts: Any) -> None:
        self._ensure_assistant(ts)
        self._close_step(ts, reason="error")
        if self._assistant_msg is not None:
            self._assistant_msg["info"]["error"] = _sanitize_text(
                error or "error",
                enabled=self.sanitize,
            )
        self._assistant_msg = None

    def build(self) -> dict[str, Any]:
        # Close any dangling step.
        self._close_step(self.updated_ms, reason="stop" if not self._saw_tool else "tool-calls")
        title = _sanitize_text(self.title or self.session_id, enabled=self.sanitize)
        directory = _sanitize_text(self.directory or "", enabled=self.sanitize)
        return {
            "info": {
                "id": self.session_id,
                "projectID": "global",
                "directory": directory,
                "title": title,
                "version": _HARNESS_VERSION,
                "time": {
                    "created": self.created_ms,
                    "updated": self.updated_ms,
                },
                "slug": "",
            },
            "messages": self.messages,
            "harness": {
                "schema": _EXPORT_SCHEMA,
                "fidelity": self.fidelity,
                "product": self.product,
                "agent_profile": self.agent_profile,
            },
        }


def _feed_events(builder: _ExportBuilder, events: list[dict[str, Any]]) -> None:
    for row in events:
        etype = str(row.get("type") or "")
        ts = row.get("timestamp")
        if etype in {"UserMessage", "TurnStarted"}:
            text = str(row.get("text") or "")
            # Prefer TurnStarted; skip UserMessage when both exist for same turn
            # by only handling TurnStarted + orphan UserMessage without following
            # TurnStarted is enough in SessionHost path.
            if etype == "UserMessage":
                # Still record if no TurnStarted will follow in this log slice;
                # duplicate user turns are rare. Prefer TurnStarted exclusively.
                continue
            builder.on_user_turn(text, ts)
        elif etype == "AgentMessage":
            builder.on_agent_text(str(row.get("text") or ""), ts)
        elif etype == "AgentThinking":
            builder.on_thinking(str(row.get("text") or ""), ts)
        elif etype == "ToolCallStart":
            builder.on_tool_start(
                tool_name=str(row.get("tool_name") or ""),
                tool_args=row.get("tool_args"),
                tool_call_id=str(row.get("tool_call_id") or ""),
                ts=ts,
            )
        elif etype == "ToolCallResult":
            ok = row.get("tool_success")
            if ok is None and "ok" in row:
                ok = row.get("ok")
            builder.on_tool_result(
                tool_name=str(row.get("tool_name") or ""),
                result=str(row.get("result") or ""),
                tool_call_id=str(row.get("tool_call_id") or ""),
                ok=None if ok is None else bool(ok),
                ts=ts,
            )
        elif etype == "ModelUsage":
            builder.on_model_usage(
                input_tokens=int(row.get("input_tokens") or 0),
                output_tokens=int(row.get("output_tokens") or 0),
                ts=ts,
            )
        elif etype == "UsageUpdate":
            builder.on_usage_totals(
                input_tokens=int(row.get("input_tokens") or 0),
                output_tokens=int(row.get("output_tokens") or 0),
                ts=ts,
            )
        elif etype == "SubAgentStarted":
            builder.on_subagent(
                agent_name=str(row.get("agent_name") or ""),
                task=str(row.get("task") or ""),
                result="",
                ok=True,
                ts=ts,
            )
        elif etype == "SubAgentFinished":
            builder.on_subagent(
                agent_name=str(row.get("agent_name") or ""),
                task="",
                result=str(row.get("result") or ""),
                ok=bool(row.get("ok", True)),
                ts=ts,
            )
        elif etype == "SubAgentFailed":
            builder.on_subagent(
                agent_name=str(row.get("agent_name") or ""),
                task="",
                result=str(row.get("error") or ""),
                ok=False,
                ts=ts,
            )
        elif etype == "TurnFinished":
            builder.on_turn_finished(ts)
        elif etype == "TurnFailed":
            builder.on_turn_failed(str(row.get("error") or "error"), ts)


def _from_stored_messages(
    builder: _ExportBuilder,
    messages: list[StoredMessage],
) -> None:
    for msg in messages:
        ts = msg.timestamp
        if msg.role == "user":
            builder.on_user_turn(msg.content, ts)
        elif msg.role == "assistant":
            builder.on_agent_text(msg.content, ts)
            builder.on_turn_finished(ts)


def build_opencode_export(
    *,
    session: StoredSession,
    events: list[dict[str, Any]] | None = None,
    directory: str = "",
    sanitize: bool = False,
    agent_profile: str | None = None,
    product: str | None = None,
) -> dict[str, Any]:
    """Build an OpenCode-shaped export document for *session*."""
    profile = resolve_export_agent_profile(
        session, agent_profile=agent_profile
    )
    created_ms = _ms(session.created_at)
    builder = _ExportBuilder(
        session_id=session.session_id,
        model=session.model,
        directory=directory,
        title=display_session_title(session),
        created_ms=created_ms,
        agent=profile,
        agent_profile=profile,
        product=product or PRODUCT_NAME,
        sanitize=sanitize,
    )
    if events:
        _feed_events(builder, events)
    else:
        _from_stored_messages(builder, list(session.messages))
        builder.fidelity = "text"
    return builder.build()


def export_session_opencode(
    store: SessionStore,
    session_id: str,
    *,
    directory: str = "",
    sanitize: bool = False,
    agent_profile: str | None = None,
    product: str | None = None,
) -> dict[str, Any]:
    """Load session + events.jsonl and return OpenCode-compatible JSON."""
    path = store.store_dir / f"{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")
    # Prefer in-memory current when it matches.
    session = store.current
    if session is None or session.session_id != session_id:
        session = store.load_session(session_id)
    events = load_session_events(store.store_dir, session_id)
    dir_field = (directory or "").strip() or (session.workdir or "").strip()
    return build_opencode_export(
        session=session,
        events=events or None,
        directory=dir_field,
        sanitize=sanitize,
        agent_profile=agent_profile,
        product=product,
    )


def write_opencode_export(
    document: dict[str, Any],
    dest: Path,
) -> Path:
    """Write *document* as pretty JSON and return *dest*."""
    import json

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


__all__ = [
    "build_opencode_export",
    "export_session_opencode",
    "resolve_export_agent_profile",
    "write_opencode_export",
]

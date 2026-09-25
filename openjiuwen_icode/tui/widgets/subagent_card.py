# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Sub-agent invocation cards with Chrys-style Retry/Abort when paused."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static

_MAX_VISIBLE_TOOLS = 7
_ARGS_BRIEF_MAX = 60


class SubAgentActionPressed(Message):
    """Bubble from a card when the user picks Retry or Abort."""

    def __init__(self, invocation_id: str, action: str) -> None:
        super().__init__()
        self.invocation_id = invocation_id
        self.action = action


def _truncate(text: str, limit: int = 160) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _fmt_args(tool_args: Any) -> str:
    if tool_args is None:
        return ""
    if isinstance(tool_args, dict):
        parts: list[str] = []
        for key, val in tool_args.items():
            raw = val if isinstance(val, str) else str(val)
            raw = raw.replace("\n", " ").strip()
            if len(raw) > 40:
                raw = raw[:39] + "…"
            parts.append(f"{key}={raw!r}" if isinstance(val, str) else f"{key}={raw}")
        text = " ".join(parts)
    else:
        text = str(tool_args).replace("\n", " ").strip()
    return _truncate(text, _ARGS_BRIEF_MAX)


@dataclass
class _InnerToolEntry:
    call_id: str
    tool_name: str
    args_brief: str = ""
    result_brief: str = ""
    done: bool = False


class SubAgentCard(Vertical):
    """One sub-agent run: status, live inner-tool feed, optional Retry/Abort."""

    DEFAULT_CSS = """
    SubAgentCard {
        height: auto;
        width: 100%;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #1a2332;
        border-left: heavy cyan;
    }
    SubAgentCard.-paused {
        border-left: heavy orange;
    }
    SubAgentCard.-done {
        border-left: heavy green;
    }
    SubAgentCard.-aborted {
        border-left: heavy red;
    }
    SubAgentCard .subagent-header {
        height: auto;
        width: 100%;
        color: cyan;
    }
    SubAgentCard .subagent-detail {
        height: auto;
        width: 100%;
        color: $text-muted;
        padding: 0 0 0 2;
    }
    SubAgentCard .subagent-tools {
        height: auto;
        width: 100%;
        color: $text-muted;
        padding: 0 0 0 2;
    }
    SubAgentCard .subagent-retry {
        height: auto;
        width: 100%;
        color: orange;
        text-style: italic;
        padding: 0 0 0 2;
        display: none;
    }
    SubAgentCard.-retrying .subagent-retry {
        display: block;
    }
    SubAgentCard #subagent-actions {
        height: 3;
        display: none;
    }
    SubAgentCard.-show-actions #subagent-actions {
        display: block;
    }
    SubAgentCard #subagent-actions Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        invocation_id: str,
        agent_name: str,
        task: str = "",
        *,
        transport: str = "",
    ) -> None:
        super().__init__()
        self.invocation_id = invocation_id
        self.agent_name = agent_name or "subagent"
        # Avoid clobbering Textual MessagePump.task (read-only property).
        self.task_brief = task or ""
        self.transport = transport or ""
        self._state = "running"
        self._detail = ""
        self._inner_tools: OrderedDict[str, _InnerToolEntry] = OrderedDict()
        self._tool_seq = 0
        self._total_tool_calls = 0
        self._open_call_id: str | None = None
        self._retry_banner = ""

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), classes="subagent-header", markup=False)
        yield Static("", classes="subagent-detail", markup=False)
        yield Static("", classes="subagent-retry", markup=False)
        yield Static("", classes="subagent-tools", markup=False)
        with Horizontal(id="subagent-actions"):
            yield Button("Retry", id="retry", variant="primary")
            yield Button("Abort", id="abort", variant="error")

    def _header_text(self) -> str:
        tid = (
            self.invocation_id[:12] + "…"
            if len(self.invocation_id) > 12
            else self.invocation_id
        )
        transport = f" [{self.transport}]" if self.transport else ""
        tools = (
            f" · tools×{self._total_tool_calls}"
            if self._total_tool_calls
            else ""
        )
        return (
            f"↳ {self.agent_name}{transport} · {tid} · "
            f"[{self._state}]{tools}"
        )

    def _tools_text(self) -> str:
        if not self._inner_tools:
            return ""
        lines: list[str] = []
        for entry in self._inner_tools.values():
            if entry.done:
                preview = entry.result_brief or "ok"
                lines.append(f"  ⎿ {entry.tool_name} {preview}")
            else:
                args = f" {entry.args_brief}" if entry.args_brief else ""
                lines.append(f"  ● {entry.tool_name}{args}")
        return "\n".join(lines)

    def _refresh(self) -> None:
        self.query_one(".subagent-header", Static).update(self._header_text())
        self.query_one(".subagent-detail", Static).update(self._detail)
        self.query_one(".subagent-retry", Static).update(self._retry_banner)
        self.query_one(".subagent-tools", Static).update(self._tools_text())

    def set_retry_attempt(
        self,
        message: str,
        attempt: int,
        max_attempts: int,
        delay_seconds: int,
    ) -> None:
        """Show Chrys-style inline auto-retry banner."""
        self._state = "retrying"
        self._retry_banner = (
            f"↻ Retrying in {delay_seconds}s "
            f"({attempt}/{max_attempts}): {_truncate(message, 100)}"
        )
        self.set_class(True, "-retrying")
        self.set_class(False, "-paused", "-done", "-aborted", "-show-actions")
        self._refresh()

    def clear_retry_banner(self) -> None:
        self._retry_banner = ""
        self.set_class(False, "-retrying")
        self._refresh()

    def _evict_over_cap(self) -> None:
        while len(self._inner_tools) > _MAX_VISIBLE_TOOLS:
            # Prefer dropping oldest completed entries.
            drop_id = None
            for cid, entry in self._inner_tools.items():
                if entry.done:
                    drop_id = cid
                    break
            if drop_id is None:
                drop_id = next(iter(self._inner_tools))
            del self._inner_tools[drop_id]

    def add_tool_start(
        self,
        tool_name: str,
        tool_args: Any = None,
        *,
        call_id: str | None = None,
    ) -> str:
        """Record an inner tool call start. Returns the call id used."""
        self._tool_seq += 1
        self._total_tool_calls += 1
        cid = call_id or f"t{self._tool_seq}"
        entry = self._inner_tools.get(cid)
        if entry is None:
            entry = _InnerToolEntry(
                call_id=cid,
                tool_name=tool_name or "tool",
                args_brief=_fmt_args(tool_args),
            )
            self._inner_tools[cid] = entry
        else:
            entry.tool_name = tool_name or entry.tool_name
            entry.args_brief = _fmt_args(tool_args) or entry.args_brief
            entry.done = False
            entry.result_brief = ""
        self._open_call_id = cid
        self._evict_over_cap()
        self._refresh()
        return cid

    def complete_tool(
        self,
        tool_name: str = "",
        result: str = "",
        *,
        call_id: str | None = None,
    ) -> None:
        """Mark an inner tool call complete (by id, name, or last open)."""
        entry: _InnerToolEntry | None = None
        if call_id and call_id in self._inner_tools:
            entry = self._inner_tools[call_id]
        elif self._open_call_id and self._open_call_id in self._inner_tools:
            entry = self._inner_tools[self._open_call_id]
        elif tool_name:
            for candidate in reversed(list(self._inner_tools.values())):
                if not candidate.done and candidate.tool_name == tool_name:
                    entry = candidate
                    break
        if entry is None and tool_name:
            # Result arrived without a matching start — still show a line.
            self._tool_seq += 1
            self._total_tool_calls += 1
            cid = f"t{self._tool_seq}"
            entry = _InnerToolEntry(
                call_id=cid,
                tool_name=tool_name,
                done=True,
            )
            self._inner_tools[cid] = entry
            self._evict_over_cap()
        if entry is None:
            return
        entry.done = True
        entry.result_brief = _truncate(result or "", 80)
        if self._open_call_id == entry.call_id:
            self._open_call_id = None
        self._refresh()

    def clear_tools(self) -> None:
        """Drop the live feed (e.g. on resume after pause)."""
        self._inner_tools.clear()
        self._open_call_id = None
        self._refresh()

    def set_running(self, *, task: str = "", clear_tools: bool = False) -> None:
        if task:
            self.task_brief = task
        self._state = "running"
        self._detail = _truncate(self.task_brief) if self.task_brief else ""
        self._retry_banner = ""
        if clear_tools:
            self._inner_tools.clear()
            self._open_call_id = None
        self.set_class(
            False, "-paused", "-done", "-aborted", "-show-actions", "-retrying"
        )
        self._refresh()

    def set_paused(self, *, reason: str = "", last_error: str = "") -> None:
        self._state = "paused"
        bits = [reason, last_error]
        self._detail = _truncate(" — ".join(b for b in bits if b))
        self._retry_banner = ""
        self.set_class(True, "-paused", "-show-actions")
        self.set_class(False, "-done", "-aborted", "-retrying")
        self._refresh()

    def set_failed(self, *, error: str = "", allow_retry: bool = False) -> None:
        self._state = "failed"
        self._detail = _truncate(error)
        self._retry_banner = ""
        if allow_retry:
            self.set_class(True, "-paused", "-show-actions")
        else:
            self.set_class(False, "-show-actions")
        self.set_class(False, "-done", "-aborted", "-retrying")
        self._refresh()

    def set_done(self, *, preview: str = "") -> None:
        self._state = "done"
        self._detail = _truncate(preview)
        self._retry_banner = ""
        self.set_class(True, "-done")
        self.set_class(False, "-paused", "-aborted", "-show-actions", "-retrying")
        self._refresh()

    def set_aborted(self, *, reason: str = "") -> None:
        self._state = "aborted"
        self._detail = _truncate(reason or "aborted")
        self._retry_banner = ""
        self.set_class(True, "-aborted")
        self.set_class(False, "-paused", "-done", "-show-actions", "-retrying")
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid not in {"retry", "abort"}:
            return
        self.post_message(
            SubAgentActionPressed(self.invocation_id, bid)
        )


__all__ = ["SubAgentActionPressed", "SubAgentCard"]

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Context sidebar tab — usage gauge, token totals, compressed blocks."""

from __future__ import annotations

import os
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import ProgressBar, RichLog, Static

_DEFAULT_MAX_CONTEXT = 128_000


def resolve_max_context_tokens() -> int:
    """Max context window size from env / settings / default."""
    raw = os.environ.get("OPENJIUWEN_MAX_CONTEXT_TOKENS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    try:
        from openjiuwen_icode.agent.config import load_settings_json

        data = load_settings_json()
        for key in ("max_context_tokens", "maxContextTokens", "context_window"):
            if data.get(key) is not None:
                return max(1, int(data[key]))
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_MAX_CONTEXT


def estimate_tokens_from_text(text: str) -> int:
    """Rough token estimate (~4 chars/token) when no provider count exists."""
    if not text:
        return 0
    # Prefer ceiling so short messages still contribute.
    return max(1, (len(text) + 3) // 4)


def estimate_usage_from_messages(messages: Any) -> dict[str, int]:
    """Estimate context fill + session totals from stored transcript messages.

    Used after ``/resume`` so the Context tab is not stuck at 0/max.
    Prefers per-message ``token_count`` when present; otherwise char/4.
    """
    if messages is None:
        return {
            "used_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
    input_tokens = 0
    output_tokens = 0
    for msg in messages:
        if isinstance(msg, dict):
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
            counted = msg.get("token_count")
        else:
            role = str(getattr(msg, "role", "") or "")
            content = str(getattr(msg, "content", "") or "")
            counted = getattr(msg, "token_count", None)
        try:
            n = int(counted) if counted is not None else estimate_tokens_from_text(content)
        except (TypeError, ValueError):
            n = estimate_tokens_from_text(content)
        if role == "assistant":
            output_tokens += n
        else:
            # user / system / tool / unknown all count toward context window
            input_tokens += n
    total = input_tokens + output_tokens
    # Window fill ≈ full transcript size (input+output already in context).
    used = total
    return {
        "used_tokens": used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
    }


def format_token_count(value: int) -> str:
    """Compact token display (e.g. ``17.2k``)."""
    n = int(value or 0)
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if abs(n) >= 10_000:
        return f"{n / 1000:.1f}k".rstrip("0").rstrip(".")
    if abs(n) >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _format_optional(value: int | None) -> str:
    if value is None:
        return "-"
    return format_token_count(value)


class ContextPanel(Widget, can_focus=False):
    """Chrys-style Context tab: usage bar, session tokens, compaction log."""

    DEFAULT_CSS = """
    ContextPanel {
        height: 1fr;
        width: 100%;
        padding: 0 1;
    }
    ContextPanel > Static {
        height: auto;
    }
    ContextPanel > .ctx-label {
        text-style: bold;
        color: $text-muted;
        margin-top: 0;
    }
    ContextPanel > #ctx-usage-hint {
        color: $text-muted;
        text-style: italic;
        margin: 0 0 0 0;
    }
    ContextPanel > #ctx-fill {
        height: 1;
        margin: 0 0 1 0;
        width: 100%;
    }
    ContextPanel > #ctx-session-total {
        margin: 0 0 1 0;
    }
    ContextPanel > #ctx-snapshots {
        height: 1fr;
        border: round $primary;
        scrollbar-size: 1 1;
        overflow-x: hidden;
        margin-top: 0;
    }
    """

    def __init__(self, *, max_context_tokens: int | None = None) -> None:
        super().__init__()
        self._current_used = 0
        self._current_max = (
            max_context_tokens
            if max_context_tokens and max_context_tokens > 0
            else resolve_max_context_tokens()
        )
        self._total_session_tokens = 0
        self._total_session_input_tokens = 0
        self._total_session_output_tokens = 0
        self._total_session_cache_hit_tokens: int | None = None
        self._block_count = 0

    def compose(self) -> ComposeResult:
        yield Static("Context Usage", classes="ctx-label")
        yield Static(
            f"0 / {self._current_max:,} (0.0%)",
            id="ctx-usage-text",
            markup=False,
        )
        yield Static(
            "current window fill (vs max context)",
            id="ctx-usage-hint",
            markup=False,
        )
        yield ProgressBar(
            total=100,
            show_eta=False,
            show_percentage=False,
            id="ctx-fill",
        )
        yield Static("Token Usage", classes="ctx-label")
        yield Static(
            f"✓ {'Cached':<7}{'-':>8}",
            id="ctx-session-cache-hit",
            markup=False,
        )
        yield Static(
            f"↑ {'Input':<7}{'0':>8}",
            id="ctx-session-input",
            markup=False,
        )
        yield Static(
            f"↓ {'Output':<7}{'0':>8}",
            id="ctx-session-output",
            markup=False,
        )
        yield Static(
            f"Σ {'Total':<7}{'0':>8}",
            id="ctx-session-total",
            markup=False,
        )
        yield Static("Compressed Messages", classes="ctx-label")
        yield RichLog(id="ctx-snapshots", max_lines=200, wrap=True, markup=False)

    def reset(self, max_context_tokens: int = 0) -> None:
        """Reset usage state for a new / resumed session."""
        self._current_used = 0
        self._total_session_tokens = 0
        self._total_session_input_tokens = 0
        self._total_session_output_tokens = 0
        self._total_session_cache_hit_tokens = None
        self._block_count = 0
        if max_context_tokens > 0:
            self._current_max = max_context_tokens
        try:
            self.query_one("#ctx-usage-text", Static).update(
                f"0 / {self._current_max:,} (0.0%)"
            )
            self.query_one("#ctx-fill", ProgressBar).update(progress=0)
            self.query_one("#ctx-session-input", Static).update(
                f"↑ {'Input':<7}{'0':>8}"
            )
            self.query_one("#ctx-session-output", Static).update(
                f"↓ {'Output':<7}{'0':>8}"
            )
            self.query_one("#ctx-session-total", Static).update(
                f"Σ {'Total':<7}{'0':>8}"
            )
            self.query_one("#ctx-session-cache-hit", Static).update(
                f"✓ {'Cached':<7}{'-':>8}"
            )
            self.query_one("#ctx-snapshots", RichLog).clear()
        except Exception:  # noqa: BLE001
            pass

    def update_usage(
        self,
        used: int,
        max_tokens: int = 0,
        *,
        total_session_tokens: int = 0,
        total_session_input_tokens: int = 0,
        total_session_output_tokens: int = 0,
        total_session_cache_hit_tokens: int | None = None,
    ) -> None:
        """Record current window fill for the context gauge + session totals."""
        self._current_used = max(0, int(used or 0))
        if max_tokens > 0:
            self._current_max = max_tokens
        pct = (
            self._current_used / self._current_max * 100
            if self._current_max > 0
            else 0.0
        )
        self.update_session_totals(
            total_session_tokens=total_session_tokens,
            total_session_input_tokens=total_session_input_tokens,
            total_session_output_tokens=total_session_output_tokens,
            total_session_cache_hit_tokens=total_session_cache_hit_tokens,
        )
        try:
            self.query_one("#ctx-usage-text", Static).update(
                f"{self._current_used:,} / {self._current_max:,} ({pct:.1f}%)"
            )
            # Cap at 100 so over-limit still reads as a full bar.
            self.query_one("#ctx-fill", ProgressBar).update(
                progress=min(100.0, pct)
            )
        except Exception:  # noqa: BLE001
            pass

    def update_session_totals(
        self,
        *,
        total_session_tokens: int = 0,
        total_session_input_tokens: int = 0,
        total_session_output_tokens: int = 0,
        total_session_cache_hit_tokens: int | None = None,
    ) -> None:
        """Update Token Usage rows."""
        self._total_session_tokens = int(total_session_tokens or 0)
        self._total_session_input_tokens = int(total_session_input_tokens or 0)
        self._total_session_output_tokens = int(total_session_output_tokens or 0)
        self._total_session_cache_hit_tokens = total_session_cache_hit_tokens
        try:
            self.query_one("#ctx-session-input", Static).update(
                f"↑ {'Input':<7}"
                f"{format_token_count(self._total_session_input_tokens):>8}"
            )
            self.query_one("#ctx-session-output", Static).update(
                f"↓ {'Output':<7}"
                f"{format_token_count(self._total_session_output_tokens):>8}"
            )
            self.query_one("#ctx-session-total", Static).update(
                f"Σ {'Total':<7}"
                f"{format_token_count(self._total_session_tokens):>8}"
            )
            self.query_one("#ctx-session-cache-hit", Static).update(
                f"✓ {'Cached':<7}"
                f"{_format_optional(self._total_session_cache_hit_tokens):>8}"
            )
        except Exception:  # noqa: BLE001
            pass

    def seed_from_messages(self, messages: Any) -> None:
        """Populate gauge/totals from a restored transcript."""
        est = estimate_usage_from_messages(messages)
        self.update_usage(
            est["used_tokens"],
            self._current_max,
            total_session_tokens=est["total_tokens"],
            total_session_input_tokens=est["input_tokens"],
            total_session_output_tokens=est["output_tokens"],
            total_session_cache_hit_tokens=None,
        )

    def apply_usage_event(self, event: Any) -> None:
        """Apply a :class:`UsageUpdate`-like event.

        Context Usage gauge uses *last* prompt tokens (current window
        fill). Token Usage rows use session-cumulative totals.
        """
        input_tokens = int(getattr(event, "input_tokens", 0) or 0)
        output_tokens = int(getattr(event, "output_tokens", 0) or 0)
        total_tokens = int(getattr(event, "total_tokens", 0) or 0)
        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens
        last_input = int(getattr(event, "last_input_tokens", 0) or 0)
        cache = getattr(event, "cache_hit_tokens", None)
        if cache is not None:
            try:
                cache = int(cache)
            except (TypeError, ValueError):
                cache = None
        # Window fill ≈ latest prompt size, not cumulative session input
        # (which re-counts the growing transcript on every model call).
        if last_input > 0:
            used = last_input
        elif input_tokens > 0:
            # Legacy events without last_*: treat input as fill proxy.
            used = input_tokens
        else:
            used = total_tokens
        self.update_usage(
            used,
            self._current_max,
            total_session_tokens=total_tokens,
            total_session_input_tokens=input_tokens,
            total_session_output_tokens=output_tokens,
            total_session_cache_hit_tokens=cache,
        )

    def clear_blocks(self) -> None:
        """Clear the compressed blocks log."""
        self._block_count = 0
        try:
            self.query_one("#ctx-snapshots", RichLog).clear()
        except Exception:  # noqa: BLE001
            pass

    def add_compressed_block(
        self,
        summary: str,
        *,
        context_id: str = "",
        freed_messages: int = 0,
        ok: bool = True,
    ) -> None:
        """Append one compaction entry to Compressed Messages."""
        self._block_count += 1
        cid = context_id or f"compact-{self._block_count}"
        try:
            log = self.query_one("#ctx-snapshots", RichLog)
        except Exception:  # noqa: BLE001
            return
        t = Text()
        style = "green" if ok else "red"
        t.append(f"• {cid}", style=style)
        if freed_messages:
            t.append(f"  {freed_messages:,} messages", style="dim")
        body = (summary or "").strip() or ("ok" if ok else "failed")
        t.append(f"\n{body}", style="dim italic")
        log.write(t)


__all__ = [
    "ContextPanel",
    "estimate_tokens_from_text",
    "estimate_usage_from_messages",
    "format_token_count",
    "resolve_max_context_tokens",
]

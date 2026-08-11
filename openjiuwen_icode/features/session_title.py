# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Session title helpers: provisional truncate + optional LLM refine."""

from __future__ import annotations

import os
import re
from typing import Any, Optional

# Sources stored on SessionStore.title_source
TITLE_PROVISIONAL = "provisional"
TITLE_LLM = "llm"
TITLE_MANUAL = "manual"

_WS_RE = re.compile(r"\s+")
_REPR_TITLE_RE = re.compile(
    r"^role\s*=\s*['\"]assistant['\"]|AssistantMessage\(",
    re.IGNORECASE,
)


def looks_like_message_repr(text: str) -> bool:
    """True when *text* looks like a serialized message object, not a title."""
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if _REPR_TITLE_RE.search(cleaned):
        return True
    lowered = cleaned.lower()
    if "content=''" in lowered or 'content=""' in lowered:
        if "name=none" in lowered or "role=" in lowered:
            return True
    return False


def extract_assistant_invoke_text(reply: Any) -> str:
    """Pull plain text from a foundation ``Model.invoke`` reply."""
    if reply is None:
        return ""
    parser = getattr(reply, "parser_content", None)
    if parser is not None:
        text = str(parser).strip()
        if text:
            return text
    content = getattr(reply, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                bit = item.get("text") or item.get("content")
                if bit is not None and str(bit).strip():
                    parts.append(str(bit).strip())
        if parts:
            return " ".join(parts)
    if isinstance(reply, dict):
        nested = reply.get("content")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return ""


def display_session_title(
    session: Any,
    *,
    max_len: int = 48,
) -> str:
    """Human title for sessions UI / OpenCode ``info.title``."""
    title = str(getattr(session, "title", "") or "").strip()
    if title and not looks_like_message_repr(title):
        if len(title) <= max_len:
            return title
        return provisional_title(title, max_len=max_len)
    messages = getattr(session, "messages", None) or []
    for msg in messages:
        role = getattr(msg, "role", None) if not isinstance(msg, dict) else msg.get("role")
        content = (
            getattr(msg, "content", None)
            if not isinstance(msg, dict)
            else msg.get("content")
        )
        if role == "user" and str(content or "").strip():
            return provisional_title(str(content), max_len=max_len)
    sid = str(getattr(session, "session_id", "") or "").strip()
    return sid or "Untitled"


def provisional_title(text: str, *, max_len: int = 48) -> str:
    """Derive a short display title from the first user message."""
    cleaned = _WS_RE.sub(" ", (text or "").strip())
    if not cleaned:
        return "Untitled"
    if len(cleaned) <= max_len:
        return cleaned
    # Prefer a word boundary near the limit.
    cut = cleaned[: max_len - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;:!?") + "…"


def llm_title_enabled() -> bool:
    """Whether async LLM refine is allowed (default on; set env to ``0``)."""
    return os.environ.get("OPENJIUWEN_SESSION_TITLE_LLM", "1") != "0"


def sanitize_llm_title(raw: str, *, max_len: int = 48) -> str:
    """Normalize model output into a single-line title."""
    text = (raw or "").strip()
    text = text.strip("\"'`")
    text = _WS_RE.sub(" ", text)
    # Drop common prefixes the model may add.
    lowered = text.lower()
    for prefix in ("标题：", "标题:", "title:", "title："):
        if lowered.startswith(prefix.lower()):
            text = text[len(prefix) :].strip().strip("\"'`")
            break
    if not text:
        return ""
    if looks_like_message_repr(text):
        return ""
    if len(text) > max_len:
        text = provisional_title(text, max_len=max_len)
    return text


async def refine_title_with_llm(
    user_text: str,
    assistant_text: str,
    cfg: Any,
) -> Optional[str]:
    """Best-effort one-shot title via the same provider as the coding agent.

    Returns ``None`` on any failure (caller keeps provisional title).
    """
    if cfg is None or not llm_title_enabled():
        return None
    api_key = getattr(cfg, "api_key", None) or ""
    if not api_key:
        return None
    provider = getattr(cfg, "provider", None)
    model_name = getattr(cfg, "model", None)
    api_base = getattr(cfg, "api_base", None)
    if not provider or not model_name:
        return None

    user_snip = (user_text or "").strip()[:800]
    asst_snip = (assistant_text or "").strip()[:800]
    if not user_snip:
        return None

    prompt = (
        "Generate a concise session title (max ~8 words) for this chat.\n"
        "Output only the title — no quotes, no explanation.\n\n"
        f"User:\n{user_snip}\n\n"
        f"Assistant:\n{asst_snip or '(no reply yet)'}\n"
    )
    try:
        from openjiuwen.core.foundation.llm.model import Model
        from openjiuwen.core.foundation.llm.schema.config import (
            ModelClientConfig,
            ModelRequestConfig,
        )

        model = Model(
            model_client_config=ModelClientConfig(
                client_provider=provider,
                api_key=api_key,
                api_base=api_base,
                timeout=20.0,
                verify_ssl=False,
            ),
            model_config=ModelRequestConfig(
                model=model_name,
                temperature=0.2,
                top_p=0.9,
            ),
        )
        reply = await model.invoke(
            prompt,
            max_tokens=64,
            temperature=0.2,
        )
        content = extract_assistant_invoke_text(reply)
        return sanitize_llm_title(content) or None
    except Exception:  # noqa: BLE001 — never block the main turn
        return None


def format_session_list(
    sessions: list[dict[str, Any]],
    *,
    current_id: str | None = None,
) -> str:
    """Human-readable session list for SystemNotice / REPL.

    TUI prefers the Sessions modal (F1 / bare ``/sessions``); this remains
    for headless and legacy REPL output.
    """
    if not sessions:
        return "No saved sessions."

    def _size(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n / (1024 * 1024):.1f} MB"

    lines = [
        "Sessions (newest first):",
        f"{'':1}{'ID':14}  {'Title':28}  {'Updated':16}  {'Turns':>5}  Size",
        f"{'':1}{'-' * 14}  {'-' * 28}  {'-' * 16}  {'-' * 5}  {'-' * 8}",
    ]
    for item in sessions:
        sid = str(item.get("id", ""))
        mark = "*" if current_id and sid == current_id else " "
        title = str(item.get("title") or "Untitled")
        if len(title) > 28:
            title = title[:25] + "..."
        when = str(item.get("updated_at") or item.get("created_at") or "")
        when = when[:16].replace("T", " ") if when else ""
        turns = int(item.get("turns") or 0)
        size = _size(int(item.get("size_bytes") or 0))
        short = sid if len(sid) <= 14 else sid[:14]
        lines.append(
            f"{mark}{short:14}  {title:28}  {when:16}  {turns:5d}  {size}"
        )
    lines.append("")
    lines.append("TUI: F1 or bare /sessions opens the Sessions modal.")
    return "\n".join(lines)

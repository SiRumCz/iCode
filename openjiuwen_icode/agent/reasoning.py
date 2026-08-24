"""Map semantic reasoning effort onto gateway-specific request fields.

Eval / settings store a single semantic value (``none`` / ``low`` / ``medium``
/ ``high`` / ``max``). At model-init time we translate it for:

* DeepSeek official API — top-level ``reasoning_effort`` +
  ``extra_body.thinking.type``
* OpenLux — top-level ``reasoning_effort`` + ``enable_thinking``
* Other OpenAI-compatible bases — DeepSeek-shaped body (widely accepted)
"""

from __future__ import annotations

from typing import Any, Literal, Optional

Gateway = Literal["deepseek", "openlux", "openai_compat"]

_VALID_EFFORTS = frozenset({"none", "low", "medium", "high", "max"})
_ALIASES = {
    "off": "none",
    "disabled": "none",
    "false": "none",
    "0": "none",
    "minimal": "low",
    "xhigh": "max",
}


def normalize_reasoning_effort(raw: Optional[str]) -> Optional[str]:
    """Normalize user/config effort to a canonical token, or ``None`` if unset."""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    text = _ALIASES.get(text, text)
    if text not in _VALID_EFFORTS:
        raise ValueError(
            f"unsupported reasoning_effort={raw!r}; "
            f"expected one of {sorted(_VALID_EFFORTS)}"
        )
    return text


def detect_gateway(api_base: str) -> Gateway:
    """Classify API base URL into a request-shape family."""
    base = (api_base or "").lower()
    if "deepseek.com" in base:
        return "deepseek"
    if "openlux" in base:
        return "openlux"
    return "openai_compat"


def preferred_provider_for_api_base(
    api_base: str,
    *,
    current: Optional[str] = None,
) -> Optional[str]:
    """Suggest provider when pointing at DeepSeek official (reasoning_content).

    Returns ``None`` when no change is recommended.
    """
    if detect_gateway(api_base) != "deepseek":
        return None
    cur = (current or "").strip()
    if cur.lower() in ("", "openai"):
        return "DeepSeek"
    return None


def map_reasoning_for_request(
    api_base: str,
    effort: Optional[str],
) -> dict[str, Any]:
    """Translate semantic effort into ``init_model`` / ``ModelRequestConfig`` kwargs.

    Returns an empty dict when *effort* is unset (leave gateway defaults).
    Keys may include ``reasoning_effort``, ``enable_thinking``, ``extra_body``.
    """
    normalized = normalize_reasoning_effort(effort)
    if normalized is None:
        return {}

    gateway = detect_gateway(api_base)
    thinking_on = normalized != "none"

    if gateway == "openlux":
        # OpenLux docs: low/medium/high + enable_thinking.
        openlux_effort = {
            "none": None,
            "low": "low",
            "medium": "medium",
            "high": "high",
            "max": "high",  # OpenLux table has no max; keep high unless passthrough needed
        }[normalized]
        out: dict[str, Any] = {}
        if thinking_on:
            out["enable_thinking"] = True
            if openlux_effort is not None:
                out["reasoning_effort"] = openlux_effort
        # Explicit off: omit enable_thinking (only true is documented to take effect).
        return out

    # DeepSeek official + generic OpenAI-compat proxies.
    # Official: reasoning_effort low/high/max; medium→high, xhigh→max at API.
    deepseek_effort = {
        "none": None,
        "low": "low",
        "medium": "high",
        "high": "high",
        "max": "max",
    }[normalized]
    body = {"thinking": {"type": "enabled" if thinking_on else "disabled"}}
    out = {"extra_body": body}
    if thinking_on and deepseek_effort is not None:
        out["reasoning_effort"] = deepseek_effort
    return out


def merge_request_kwargs(
    *,
    api_base: str,
    reasoning_effort: Optional[str] = None,
    extra_body: Optional[dict[str, Any]] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Build kwargs for :func:`openjiuwen.core.foundation.llm.init_model`.

    Mapped thinking fields come first; caller ``extra_body`` / headers merge on top.
    """
    mapped = map_reasoning_for_request(api_base, reasoning_effort)
    kwargs: dict[str, Any] = {}

    if "reasoning_effort" in mapped:
        kwargs["reasoning_effort"] = mapped["reasoning_effort"]
    if "enable_thinking" in mapped:
        kwargs["enable_thinking"] = mapped["enable_thinking"]

    merged_body: dict[str, Any] = {}
    if isinstance(mapped.get("extra_body"), dict):
        merged_body.update(mapped["extra_body"])
    if extra_body:
        merged_body.update(extra_body)
    if merged_body:
        kwargs["extra_body"] = merged_body

    if extra_headers:
        kwargs["custom_headers"] = {
            str(k): str(v) for k, v in extra_headers.items()
        }
    return kwargs

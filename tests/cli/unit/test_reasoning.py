"""Unit tests for reasoning-effort gateway mapping."""

from __future__ import annotations

import pytest

from openjiuwen_icode.agent.reasoning import (
    detect_gateway,
    map_reasoning_for_request,
    merge_request_kwargs,
    normalize_reasoning_effort,
    preferred_provider_for_api_base,
)


def test_normalize_aliases() -> None:
    assert normalize_reasoning_effort(None) is None
    assert normalize_reasoning_effort("") is None
    assert normalize_reasoning_effort("OFF") == "none"
    assert normalize_reasoning_effort("xhigh") == "max"
    with pytest.raises(ValueError):
        normalize_reasoning_effort("ultra")


def test_detect_gateway() -> None:
    assert detect_gateway("https://api.deepseek.com") == "deepseek"
    assert detect_gateway("https://api.openlux.ai/v1") == "openlux"
    assert detect_gateway("https://proxy.example/v1") == "openai_compat"


def test_map_openlux_high() -> None:
    assert map_reasoning_for_request(
        "https://api.openlux.ai/v1", "high"
    ) == {
        "extra_body": {"enable_thinking": True},
        "reasoning_effort": "high",
    }


def test_map_openlux_max_becomes_high() -> None:
    assert map_reasoning_for_request(
        "https://api.openlux.ai/v1", "max"
    ) == {
        "extra_body": {"enable_thinking": True},
        "reasoning_effort": "high",
    }


def test_map_openlux_none() -> None:
    assert map_reasoning_for_request(
        "https://api.openlux.ai/v1", "none"
    ) == {}


def test_map_deepseek_max() -> None:
    assert map_reasoning_for_request(
        "https://api.deepseek.com", "max"
    ) == {
        "reasoning_effort": "max",
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def test_map_deepseek_none() -> None:
    assert map_reasoning_for_request(
        "https://api.deepseek.com", "none"
    ) == {"extra_body": {"thinking": {"type": "disabled"}}}


def test_merge_caller_extra_body_wins() -> None:
    kwargs = merge_request_kwargs(
        api_base="https://api.deepseek.com",
        reasoning_effort="high",
        extra_body={"thinking": {"type": "disabled"}, "foo": 1},
    )
    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["extra_body"] == {
        "thinking": {"type": "disabled"},
        "foo": 1,
    }


def test_merge_openlux_does_not_emit_top_level_enable_thinking() -> None:
    kwargs = merge_request_kwargs(
        api_base="https://api.openlux.ai/v1",
        reasoning_effort="max",
    )
    assert "enable_thinking" not in kwargs
    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["extra_body"] == {"enable_thinking": True}


def test_preferred_provider_deepseek() -> None:
    assert (
        preferred_provider_for_api_base(
            "https://api.deepseek.com", current="OpenAI"
        )
        == "DeepSeek"
    )
    assert (
        preferred_provider_for_api_base(
            "https://api.openlux.ai/v1", current="OpenAI"
        )
        is None
    )

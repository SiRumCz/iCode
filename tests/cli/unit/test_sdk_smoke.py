# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Smoke: openjiuwen SDK + openjiuwen_icode import surface."""

from __future__ import annotations


def test_sdk_deep_agent_importable() -> None:
    from openjiuwen.harness import create_deep_agent

    assert callable(create_deep_agent)


def test_icode_event_bus_importable() -> None:
    from openjiuwen_icode import __version__
    from openjiuwen_icode.events import EventBus

    assert __version__
    assert EventBus is not None


def test_icode_paths_available() -> None:
    from openjiuwen_icode.paths import icode_home

    assert callable(icode_home)


def test_sdk_compat_filters_skill_rail_kwargs() -> None:
    from openjiuwen.harness.rails import SkillUseRail
    from openjiuwen_icode.sdk_compat import call_with_supported_kwargs

    rail = call_with_supported_kwargs(
        SkillUseRail,
        skills_dir=["/tmp"],
        skill_mode="all",
        include_tools=False,
        inline_skills=[{"name": "x"}],
        script_timeout=30,
    )
    assert rail is not None


def test_call_with_supported_kwargs_filters_and_var_keyword() -> None:
    from openjiuwen_icode.sdk_compat import call_with_supported_kwargs

    def fixed(a: int, b: int = 0) -> tuple[int, int]:
        return a, b

    assert call_with_supported_kwargs(fixed, 1, b=2, dropped=9) == (1, 2)

    def swallow(a: int, **kwargs: object) -> tuple[int, dict]:
        return a, dict(kwargs)

    assert call_with_supported_kwargs(swallow, 1, extra=True) == (1, {"extra": True})

    # builtins / C callables without inspectable signature
    assert call_with_supported_kwargs(list, (1, 2)) == [1, 2]


def test_load_concurrency_types() -> None:
    from openjiuwen_icode.sdk_compat import (
        LocalSubagentConcurrencyConfig,
        load_concurrency_types,
    )

    cfg_t, lim_t = load_concurrency_types()
    assert cfg_t is not None
    # Either SDK types or local fallback
    if lim_t is None:
        assert cfg_t is LocalSubagentConcurrencyConfig
        assert LocalSubagentConcurrencyConfig().max_total == 2
    else:
        assert callable(lim_t)

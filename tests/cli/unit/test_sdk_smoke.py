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

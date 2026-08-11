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


def test_compat_shim_aliases_paths() -> None:
    """Deprecated harness.cli.paths should resolve via shim when installed."""
    from openjiuwen.harness.cli.paths import icode_home
    from openjiuwen_icode.paths import icode_home as direct

    assert icode_home is direct

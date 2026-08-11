# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for OpenJiuWen iCode product branding."""

from __future__ import annotations

from openjiuwen_icode.branding import (
    PRODUCT_NAME,
    PRODUCT_SHORT,
    window_title,
)


def test_product_name() -> None:
    assert PRODUCT_NAME == "OpenJiuWen iCode"
    assert PRODUCT_SHORT == "iCode"


def test_window_title() -> None:
    assert window_title() == "OpenJiuWen iCode"
    assert window_title("demo") == "OpenJiuWen iCode (demo)"
    assert (
        window_title("m", workspace="agent-core")
        == "OpenJiuWen iCode (m) · agent-core"
    )

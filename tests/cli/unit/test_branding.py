# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for iCode product branding."""

from openjiuwen_icode.branding import (
    PRODUCT_NAME,
    PRODUCT_SHORT,
    window_title,
)


def test_product_constants() -> None:
    assert PRODUCT_NAME == "iCode"
    assert PRODUCT_SHORT == "iCode"


def test_window_title() -> None:
    assert window_title() == "iCode"
    assert window_title("demo") == "iCode (demo)"
    assert (
        window_title("m", workspace="agent-core")
        == "iCode (m) · agent-core"
    )

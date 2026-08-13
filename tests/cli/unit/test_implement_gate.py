# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for implement-task detection helpers."""

from __future__ import annotations

from openjiuwen_icode.features.implement_gate import (
    looks_like_implement_task,
)


def test_looks_like_implement_task_positive() -> None:
    assert looks_like_implement_task(
        "Implement CLI --config overrides then run lolbench-submit"
    )
    assert looks_like_implement_task("Please fix the bug in args.rs")
    assert looks_like_implement_task("Add support for inline TOML")


def test_looks_like_implement_task_negative() -> None:
    assert not looks_like_implement_task("What is Ruff?")
    assert not looks_like_implement_task("")
    assert not looks_like_implement_task("Explain how --config works")

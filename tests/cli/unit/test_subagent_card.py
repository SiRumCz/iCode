# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Unit tests for SubAgentCard state helpers and inner tool feed."""

from __future__ import annotations

from openjiuwen_icode.tui.widgets.subagent_card import (
    _MAX_VISIBLE_TOOLS,
    _fmt_args,
    _truncate,
)


def test_truncate_short_unchanged() -> None:
    assert _truncate("hello") == "hello"


def test_truncate_long() -> None:
    assert len(_truncate("x" * 200)) <= 160


def test_fmt_args_dict() -> None:
    text = _fmt_args({"path": "a.py", "limit": 10})
    assert "path=" in text
    assert "limit=" in text


def test_inner_tool_feed_lifecycle() -> None:
    """Exercise OrderedDict feed without mounting Textual widgets."""
    from collections import OrderedDict

    from openjiuwen_icode.tui.widgets.subagent_card import (
        _InnerToolEntry,
    )

    tools: OrderedDict[str, _InnerToolEntry] = OrderedDict()
    tools["t1"] = _InnerToolEntry("t1", "read_file", args_brief="path='x'")
    assert not tools["t1"].done
    tools["t1"].done = True
    tools["t1"].result_brief = "ok"
    assert tools["t1"].done
    assert len(tools) == 1


def test_evict_prefers_completed() -> None:
    from collections import OrderedDict

    from openjiuwen_icode.tui.widgets.subagent_card import (
        _InnerToolEntry,
    )

    tools: OrderedDict[str, _InnerToolEntry] = OrderedDict()
    for i in range(_MAX_VISIBLE_TOOLS + 2):
        tools[f"t{i}"] = _InnerToolEntry(
            f"t{i}",
            f"tool_{i}",
            done=(i < 3),
        )
    # Mimic SubAgentCard._evict_over_cap
    while len(tools) > _MAX_VISIBLE_TOOLS:
        drop_id = None
        for cid, entry in tools.items():
            if entry.done:
                drop_id = cid
                break
        if drop_id is None:
            drop_id = next(iter(tools))
        del tools[drop_id]
    assert len(tools) == _MAX_VISIBLE_TOOLS
    assert "t0" not in tools
    assert "t1" not in tools

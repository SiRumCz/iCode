# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for Sessions modal presentation helpers."""

from __future__ import annotations

from openjiuwen_icode.tui.screens.sessions_presenter import (
    build_session_rows,
    format_size,
    row_tooltip_lines,
    time_ago,
)


def test_format_size() -> None:
    assert format_size(500) == "500 B"
    assert format_size(2048).endswith("KB")
    assert format_size(3_000_000).endswith("MB")


def test_time_ago_parses_iso() -> None:
    assert time_ago("") == "-"
    # Non-empty garbage falls back to truncated display.
    assert "not-a-date" in time_ago("not-a-date")


def test_build_session_rows_sort_and_filter() -> None:
    sessions = [
        {
            "id": "cli-aaaa",
            "title": "Alpha chat",
            "updated_at": "2026-08-06T01:00:00+00:00",
            "turns": 3,
            "size_bytes": 100,
            "directory": "/tmp/a",
            "model": "m1",
            "preview": "hello world",
        },
        {
            "id": "cli-bbbb",
            "title": "Beta notes",
            "updated_at": "2026-08-06T02:00:00+00:00",
            "turns": 10,
            "size_bytes": 9999,
            "directory": "/tmp/b",
            "model": "m2",
            "preview": "need approval",
        },
    ]
    rows = build_session_rows(sessions, sort_column="updated", sort_reverse=True)
    assert rows[0].meta["id"] == "cli-bbbb"

    filtered = build_session_rows(sessions, query="approval")
    assert len(filtered) == 1
    assert filtered[0].meta["id"] == "cli-bbbb"

    tip = "\n".join(row_tooltip_lines(filtered[0]))
    assert "Title:" in tip
    assert "Model:" in tip
    assert "cli-bbbb" in tip

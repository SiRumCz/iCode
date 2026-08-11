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


def test_presenter_helpers_coverage() -> None:
    from datetime import datetime, timezone, timedelta

    from openjiuwen_icode.tui.screens.sessions_presenter import (
        absolute_time,
        column_by_key,
        directory_display,
        format_size,
        short_id,
        time_ago,
        title_display,
        _snippet,
    )

    assert format_size(2_000_000_000).endswith("GB")
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    assert time_ago(
        (now - timedelta(seconds=10)).isoformat(), now=now
    ) == "just now"
    assert "m ago" in time_ago(
        (now - timedelta(minutes=5)).isoformat(), now=now
    )
    assert "h ago" in time_ago(
        (now - timedelta(hours=3)).isoformat(), now=now
    )
    assert time_ago(
        (now - timedelta(days=1)).isoformat(), now=now
    ) == "1 day ago"
    assert "days ago" in time_ago(
        (now - timedelta(days=5)).isoformat(), now=now
    )
    assert time_ago(
        (now - timedelta(days=40)).isoformat(), now=now
    ) == "1 month ago"
    assert "months ago" in time_ago(
        (now - timedelta(days=90)).isoformat(), now=now
    )
    assert time_ago(
        (now - timedelta(days=400)).isoformat(), now=now
    ) == "1 year ago"
    assert "years ago" in time_ago(
        (now - timedelta(days=900)).isoformat(), now=now
    )
    assert absolute_time("2026-08-06T01:00:00+00:00")
    assert absolute_time("") == "-"
    assert short_id("abcdefghijklmnop") == "abcdefghijkl"
    assert directory_display("") == "-"
    assert "…" in directory_display("x" * 40, max_width=10)
    assert title_display({"id": "cli-12345678", "title": ""}).endswith("..")
    assert column_by_key("missing").key == "updated"
    assert column_by_key("title").key == "title"
    assert _snippet("") == ""
    assert "…" in _snippet("word " * 40)
    snip = _snippet("aaa NEEDLE bbb ccc", needle="NEEDLE")
    assert "NEEDLE" in snip

    rows = build_session_rows(
        [
            {
                "id": "z",
                "title": "",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "turns": 1,
                "size_bytes": 1,
                "directory": "/d",
                "preview": "only in preview UNIQUE",
            }
        ],
        sort_column="title",
        query="UNIQUE",
    )
    assert len(rows) == 1
    for key in ("id", "directory", "turns", "size", "nope"):
        build_session_rows(
            [
                {
                    "id": "a",
                    "title": "T",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "turns": 2,
                    "size_bytes": 3,
                    "directory": "/x",
                }
            ],
            sort_column=key,
        )

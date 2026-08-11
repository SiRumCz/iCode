# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for MutationTracker /diff /rollback."""

from __future__ import annotations

from pathlib import Path

from openjiuwen_icode.features.mutations import MutationTracker


def test_record_and_rollback(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "a.txt"
    target.write_text("v1\n", encoding="utf-8")

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("sess-1", turn_id="turn-1")
    tracker.record_tool_mutation("write_file", {"path": str(target)})
    target.write_text("v2\n", encoding="utf-8")
    tracker.refresh_after_hashes()
    tracker.end_turn()

    assert len(tracker.list_turns()) == 1
    diff = tracker.format_diff()
    assert "turn-1" in diff
    assert "a.txt" in diff

    msg = tracker.rollback_turn("turn-1")
    assert "restored" in msg or "Rollback" in msg
    assert target.read_text(encoding="utf-8") == "v1\n"
    assert tracker.list_turns() == []


def test_ignores_non_mutating_tools(tmp_path: Path) -> None:
    tracker = MutationTracker(tmp_path / "mut", workspace=tmp_path)
    tracker.begin_turn("s")
    assert tracker.record_tool_mutation("read_file", {"path": "x"}) is None

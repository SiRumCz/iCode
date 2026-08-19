# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for MutationTracker /diff /rollback."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from openjiuwen_icode.features.mutations import (
    MutationTracker,
    _extract_path,
    _file_hash,
    _git_checkout_file,
    _git_diff_file,
    mutating_tool_applied,
    path_under_workspace,
)


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


def test_has_workspace_changes(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "a.txt"
    target.write_text("v1\n", encoding="utf-8")

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("sess-1")
    tracker.record_tool_mutation("edit_file", {"path": str(target)})
    assert tracker.has_workspace_changes() is False
    target.write_text("v2\n", encoding="utf-8")
    tracker.refresh_after_hashes()
    assert tracker.has_workspace_changes() is True


def test_has_workspace_changes_ignores_outside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("v1\n", encoding="utf-8")

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("sess-1")
    tracker.record_tool_mutation("edit_file", {"path": str(outside)})
    outside.write_text("v2\n", encoding="utf-8")
    tracker.refresh_after_hashes()
    assert tracker.has_workspace_changes() is False


def test_has_deliverable_workspace_changes_requires_git_dirty(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    target = ws / "a.txt"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=icode@local", "-c", "user.name=icode", "commit", "-m", "base"],
        cwd=ws,
        check=True,
        capture_output=True,
    )

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("sess-1")
    tracker.record_tool_mutation("edit_file", {"path": str(target)})
    target.write_text("v2\n", encoding="utf-8")
    tracker.refresh_after_hashes()
    assert tracker.has_workspace_changes() is True
    assert tracker.git_worktree_dirty() is True
    assert tracker.has_deliverable_workspace_changes() is True


def test_has_deliverable_workspace_changes_counts_committed_edits(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    target = ws / "a.txt"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=icode@local", "-c", "user.name=icode", "commit", "-m", "base"],
        cwd=ws,
        check=True,
        capture_output=True,
    )

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("sess-1")
    tracker.record_tool_mutation("edit_file", {"path": str(target)})
    target.write_text("v2\n", encoding="utf-8")
    tracker.refresh_after_hashes()
    subprocess.run(["git", "add", "a.txt"], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=icode@local", "-c", "user.name=icode", "commit", "-m", "fix"],
        cwd=ws,
        check=True,
        capture_output=True,
    )

    assert tracker.has_workspace_changes() is True
    assert tracker.git_worktree_dirty() is False
    assert tracker.has_deliverable_workspace_changes() is True


def test_agent_created_test_names_tracks_new_test_files(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    test_file = ws / "src" / "__tests__" / "container.initialize.test.ts"
    test_file.parent.mkdir(parents=True)

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("s")
    tracker.record_tool_mutation(
        "write_file",
        {
            "file_path": str(test_file),
            "content": "test('x', () => {})\n",
        },
    )
    test_file.write_text("test('x', () => {})\n", encoding="utf-8")
    tracker.refresh_after_hashes()

    names = tracker.agent_created_test_names()
    assert "container.initialize.test.ts" in names
    assert "container.initialize" in names


def test_agent_created_test_names_tracks_python_test_files(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    test_file = ws / "tests" / "unit" / "core" / "test_cache.py"
    test_file.parent.mkdir(parents=True)

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("s")
    tracker.record_tool_mutation(
        "write_file",
        {
            "file_path": str(test_file),
            "content": "def test_x():\n    assert True\n",
        },
    )
    test_file.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    tracker.refresh_after_hashes()

    names = tracker.agent_created_test_names()
    assert "test_cache.py" in names
    assert "cache" in names


def test_agent_created_test_names_tracks_go_test_files(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    test_file = ws / "parsing" / "html" / "html_test.go"
    test_file.parent.mkdir(parents=True)

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("s")
    tracker.record_tool_mutation(
        "write_file",
        {
            "file_path": str(test_file),
            "content": "package html\n\nfunc TestX(t *testing.T) {}\n",
        },
    )
    test_file.write_text(
        "package html\n\nfunc TestX(t *testing.T) {}\n", encoding="utf-8"
    )
    tracker.refresh_after_hashes()

    names = tracker.agent_created_test_names()
    assert "html_test.go" in names
    assert "html" in names
    assert "parsing/html" in names


def test_bash_created_test_paths_are_tracked(tmp_path: Path) -> None:
    from openjiuwen_icode.features.mutations import test_paths_from_bash_command

    ws = tmp_path / "ws"
    ws.mkdir()
    test_file = ws / "tests" / "unit" / "core" / "test_nosec_directives.py"
    test_file.parent.mkdir(parents=True)

    cmd = (
        "cat > /app/tests/unit/core/test_nosec_directives.py << 'PYEOF'\n"
        "import testtools\nPYEOF"
    )
    assert test_paths_from_bash_command(cmd) == (
        "/app/tests/unit/core/test_nosec_directives.py",
    )

    tracker = MutationTracker(tmp_path / "mut", workspace=ws)
    tracker.begin_turn("s")
    tracker.record_bash_created_path(str(test_file))
    test_file.write_text("pass\n", encoding="utf-8")
    tracker.refresh_after_hashes()

    names = tracker.agent_created_test_names()
    assert "test_nosec_directives.py" in names
    assert "nosec_directives" in names


def test_path_under_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    inside = ws / "src" / "container.ts"
    inside.parent.mkdir(parents=True)
    outside = tmp_path / "other.ts"

    assert path_under_workspace(str(inside), ws)
    assert path_under_workspace("src/container.ts", ws)
    assert not path_under_workspace(str(outside), ws)
    assert not path_under_workspace("/tmp/nope.ts", ws)


def test_mutating_tool_applied() -> None:
    assert mutating_tool_applied(
        "edit_file",
        "Applied patch",
        tool_success=True,
    )
    assert not mutating_tool_applied(
        "edit_file",
        "old_string not found",
        tool_success=False,
    )
    assert not mutating_tool_applied("grep", "matches")


def test_ignores_non_mutating_tools(tmp_path: Path) -> None:
    tracker = MutationTracker(tmp_path / "mut", workspace=tmp_path)
    tracker.begin_turn("s")
    assert tracker.record_tool_mutation("read_file", {"path": "x"}) is None


def test_extract_path_from_dict_and_json() -> None:
    assert _extract_path({"file_path": " a.py "}) == "a.py"
    assert _extract_path('{"filename": "b.py"}') == "b.py"
    assert _extract_path("plain/path.txt") == "plain/path.txt"
    assert _extract_path({"other": 1}) == ""
    assert _extract_path(123) == ""


def test_file_hash_ok_and_missing(tmp_path: Path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    digest = _file_hash(f)
    assert len(digest) == 64
    assert _file_hash(tmp_path / "missing.bin") == ""


def test_git_diff_file_mocked(tmp_path: Path) -> None:
    proc = MagicMock(stdout="diff --git a/x\n")
    with patch(
        "openjiuwen_icode.features.mutations.subprocess.run",
        return_value=proc,
    ) as run:
        out = _git_diff_file(tmp_path, "x")
    assert out.startswith("diff --git")
    run.assert_called_once()


def test_git_diff_file_timeout(tmp_path: Path) -> None:
    with patch(
        "openjiuwen_icode.features.mutations.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
    ):
        assert _git_diff_file(tmp_path, "x") == ""


def test_git_checkout_file_mocked(tmp_path: Path) -> None:
    with patch(
        "openjiuwen_icode.features.mutations.subprocess.run",
        return_value=MagicMock(returncode=0),
    ):
        assert _git_checkout_file(tmp_path, "x") is True
    with patch(
        "openjiuwen_icode.features.mutations.subprocess.run",
        return_value=MagicMock(returncode=1),
    ):
        assert _git_checkout_file(tmp_path, "x") is False
    with patch(
        "openjiuwen_icode.features.mutations.subprocess.run",
        side_effect=OSError("no git"),
    ):
        assert _git_checkout_file(tmp_path, "x") is False

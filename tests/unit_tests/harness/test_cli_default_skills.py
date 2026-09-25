# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for CLI default skill directory configuration."""

from __future__ import annotations

from openjiuwen_icode.agent.factory import _default_skill_dirs
from openjiuwen_icode.skills import CWD_AGENTS_SKILLS


def test_default_skill_dirs_returns_expected_paths(tmp_path, monkeypatch):
    """_default_skill_dirs should include iCode project + Chrys/Agents roots."""
    monkeypatch.setenv("ICODE_PROJECT", str(tmp_path / "proj"))
    dirs = _default_skill_dirs()
    assert dirs[0] == str((tmp_path / "proj" / "workspace" / "skills").resolve())
    assert dirs[1] == "~/.claude/skills"
    assert dirs[2] == "~/.codex/skills"
    assert dirs[3] == "~/.jiuwenclaw/workspace/skills"
    assert "~/.chrys/skills" in dirs
    assert "~/.agents/skills" in dirs
    assert CWD_AGENTS_SKILLS in dirs


def test_default_skill_dirs_returns_copy():
    """_default_skill_dirs should return a fresh list each call."""
    dirs = _default_skill_dirs()
    dirs.append("extra")
    assert "extra" not in _default_skill_dirs()

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for iCode four-layer path helpers."""

from __future__ import annotations

from pathlib import Path

from openjiuwen_icode.host.workdirs import (
    WorkdirRegistry,
    apply_workdir_to_backend,
)
from openjiuwen_icode.paths import (
    IcodeProject,
    agents_home,
    icode_home,
)


def test_homes_respect_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ICODE_HOME", str(tmp_path / "icode"))
    monkeypatch.setenv("AGENTS_HOME", str(tmp_path / "agents"))
    assert icode_home() == (tmp_path / "icode").resolve()
    assert agents_home() == (tmp_path / "agents").resolve()


def test_icode_project_layout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ICODE_HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    proj = IcodeProject.open(root)
    assert proj.workspace_dir.is_dir()
    assert proj.sessions_dir.is_dir()
    assert proj.directories_json.is_file()
    assert proj.project_json.is_file()


def test_apply_workdir_does_not_overwrite_agent_workspace(
    tmp_path: Path,
) -> None:
    class Cfg:
        cwd = "/old"
        workspace = str(tmp_path / "agent-ws")

    class Backend:
        cfg = Cfg()

    code = tmp_path / "repo"
    code.mkdir()
    backend = Backend()
    notes = apply_workdir_to_backend(backend, str(code))
    assert backend.cfg.cwd == str(code.resolve())
    assert backend.cfg.workspace == str(tmp_path / "agent-ws")
    assert "cfg.cwd" in notes
    assert "cfg.workspace" not in notes


def test_directories_json_under_project(tmp_path: Path) -> None:
    store = tmp_path / "directories.json"
    a = tmp_path / "a"
    a.mkdir()
    reg = WorkdirRegistry(store_path=store)
    reg.add(str(a))
    loaded = WorkdirRegistry.load(store)
    assert loaded.primary == str(a.resolve())

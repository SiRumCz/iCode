# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Unit tests for skill slash command helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openjiuwen_icode.skills import slash as slash_mod
from openjiuwen_icode.skills.config import (
    InlineSkillConfig,
    SkillsUserConfig,
)
from openjiuwen_icode.skills.slash import (
    _cwd_hint,
    resolve_skill_user_text,
    scan_cli_skills,
    skill_slash_entries,
    skills_status_text,
)


def _write_skill(root: Path, name: str, description: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {name}\n\n"
        "Do the thing.\n",
        encoding="utf-8",
    )
    return skill_md


class TestCwdHint:
    def test_uses_host_workdirs_primary(self) -> None:
        host = SimpleNamespace(
            workdirs=SimpleNamespace(primary="/ws/project"),
            _backend=None,
        )
        assert _cwd_hint(host) == "/ws/project"

    def test_falls_back_to_backend_cfg_cwd(self) -> None:
        host = SimpleNamespace(
            workdirs=SimpleNamespace(primary=None),
            _backend=SimpleNamespace(
                cfg=SimpleNamespace(cwd="/from-cfg", workspace=None)
            ),
        )
        assert _cwd_hint(host) == "/from-cfg"

    def test_falls_back_to_backend_cfg_workspace(self) -> None:
        host = SimpleNamespace(
            workdirs=SimpleNamespace(primary=""),
            _backend=SimpleNamespace(
                cfg=SimpleNamespace(cwd=None, workspace="/ws")
            ),
        )
        assert _cwd_hint(host) == "/ws"

    def test_no_host_returns_cwd_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        hint = _cwd_hint(None)
        assert hint is not None
        assert Path(hint).resolve() == tmp_path.resolve()


class TestScanCliSkills:
    def test_merges_discovered_and_inline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill_md = _write_skill(tmp_path, "disk-skill", "From disk")
        inline = InlineSkillConfig(
            name="inline-skill",
            description="Inline one",
            instructions="Be helpful.",
        )
        cfg = SkillsUserConfig(
            paths=(),
            inline=(inline,),
            auto_load_chrys_skills=False,
            auto_load_user_agents_skills=False,
            auto_load_cwd_agents_skills=False,
        )
        monkeypatch.setattr(slash_mod, "load_skills_config", lambda: cfg)
        monkeypatch.setattr(
            slash_mod,
            "collect_default_skill_dirs",
            lambda **_kwargs: [str(tmp_path)],
        )

        result = scan_cli_skills()
        assert "disk-skill" in result
        assert Path(result["disk-skill"].skill_md) == skill_md
        assert result["inline-skill"] is inline

    def test_discovered_wins_over_same_name_inline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_skill(tmp_path, "shared", "Disk wins")
        inline = InlineSkillConfig(
            name="shared",
            description="Inline loser",
            instructions="Nope.",
        )
        cfg = SkillsUserConfig(inline=(inline,))
        monkeypatch.setattr(slash_mod, "load_skills_config", lambda: cfg)
        monkeypatch.setattr(
            slash_mod,
            "collect_default_skill_dirs",
            lambda **_kwargs: [str(tmp_path)],
        )
        result = scan_cli_skills()
        assert getattr(result["shared"], "skill_md", None) is not None


class TestSkillSlashEntries:
    def test_includes_skills_list_and_discovered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        discovered = {
            "alpha": SimpleNamespace(description="Alpha skill"),
            "beta": SimpleNamespace(
                description="x" * 60  # truncated
            ),
        }
        monkeypatch.setattr(
            slash_mod, "scan_cli_skills", lambda host=None: discovered
        )
        entries = skill_slash_entries()
        assert entries[0] == ("/skills", "List loaded skills")
        by_name = dict(entries)
        assert by_name["/alpha"] == "Alpha skill"
        assert by_name["/beta"].endswith("...")
        assert len(by_name["/beta"]) == 48

    def test_missing_description_uses_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            slash_mod,
            "scan_cli_skills",
            lambda host=None: {"plain": SimpleNamespace()},
        )
        entries = dict(skill_slash_entries())
        assert entries["/plain"] == "Skill"


class TestResolveSkillUserText:
    def test_unknown_skill_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            slash_mod, "scan_cli_skills", lambda host=None: {}
        )
        assert resolve_skill_user_text("missing") is None

    def test_file_skill_builds_query(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill_md = _write_skill(tmp_path, "file-sk", "File skill")
        monkeypatch.setattr(
            slash_mod,
            "scan_cli_skills",
            lambda host=None: {
                "file-sk": SimpleNamespace(skill_md=skill_md)
            },
        )
        text = resolve_skill_user_text("file-sk", "do it")
        assert text is not None
        assert "<skill-instructions>" in text
        assert "User arguments: do it" in text
        assert "Do the thing." in text

    def test_inline_skill_builds_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inline = InlineSkillConfig(
            name="in-sk",
            description="Inline",
            instructions="Follow carefully.",
        )
        monkeypatch.setattr(
            slash_mod,
            "scan_cli_skills",
            lambda host=None: {"in-sk": inline},
        )
        text = resolve_skill_user_text("in-sk", "arg1")
        assert text is not None
        assert "# in-sk" in text
        assert "Follow carefully." in text
        assert "User arguments: arg1" in text

    def test_skill_without_md_or_instructions_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            slash_mod,
            "scan_cli_skills",
            lambda host=None: {"odd": SimpleNamespace()},
        )
        assert resolve_skill_user_text("odd") is None


class TestSkillsStatusText:
    def test_formats_discovered_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_skill(tmp_path, "status-sk", "Status skill")
        cfg = SkillsUserConfig(
            inline=(),
            auto_load_chrys_skills=False,
            auto_load_user_agents_skills=False,
            auto_load_cwd_agents_skills=False,
        )
        monkeypatch.setattr(slash_mod, "load_skills_config", lambda: cfg)
        monkeypatch.setattr(
            slash_mod,
            "collect_default_skill_dirs",
            lambda **_kwargs: [str(tmp_path)],
        )
        text = skills_status_text()
        assert "status-sk" in text

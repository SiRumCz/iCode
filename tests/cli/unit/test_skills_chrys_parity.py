# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for Chrys-aligned CLI skills paths / discovery / runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjiuwen_icode.skills import (
    CWD_AGENTS_SKILLS,
    collect_default_skill_dirs,
    discover_skills,
    iter_skill_directories,
    load_skills_config,
)
from openjiuwen_icode.skills.query import (
    build_inline_skill_query,
    build_skill_query,
)


def test_collect_default_skill_dirs_includes_chrys_agents(tmp_path: Path) -> None:
    dirs = collect_default_skill_dirs(cwd=tmp_path)
    assert any(d.endswith(".chrys/skills") or "/.chrys/skills" in d for d in dirs)
    assert any(".agents/skills" in d for d in dirs)
    assert CWD_AGENTS_SKILLS in dirs
    assert str(tmp_path / ".agents" / "skills") in dirs


def test_collect_can_disable_agents_roots() -> None:
    dirs = collect_default_skill_dirs(
        include_chrys=False,
        include_user_agents=False,
        include_cwd_agents=False,
    )
    assert all(".chrys/skills" not in d for d in dirs)
    assert all(".agents/skills" not in d for d in dirs)
    assert CWD_AGENTS_SKILLS not in dirs


def test_iter_skill_directories_depth_two(tmp_path: Path) -> None:
    shallow = tmp_path / "alpha"
    shallow.mkdir()
    (shallow / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: A\n---\nbody\n",
        encoding="utf-8",
    )
    nested = tmp_path / "cat" / "beta"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(
        "---\nname: beta\ndescription: B\n---\nbody\n",
        encoding="utf-8",
    )
    # Nested under an existing skill should not be a separate skill.
    nested_under = shallow / "ignored"
    nested_under.mkdir()
    (nested_under / "SKILL.md").write_text(
        "---\nname: ignored\ndescription: X\n---\n",
        encoding="utf-8",
    )

    found = {p.name for p in iter_skill_directories(tmp_path, max_depth=2)}
    assert found == {"alpha", "beta"}


def test_discover_skills_first_wins(tmp_path: Path) -> None:
    high = tmp_path / "high"
    low = tmp_path / "low"
    for root, desc in ((high, "high"), (low, "low")):
        skill = root / "dup"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: dup\ndescription: {desc}\n---\n",
            encoding="utf-8",
        )
    found = discover_skills([high, low])
    assert found["dup"].description == "high"


def test_load_skills_config_inline(tmp_path: Path) -> None:
    path = tmp_path / "skills.json"
    path.write_text(
        json.dumps(
            {
                "paths": ["~/extra"],
                "inline": [
                    {
                        "name": "note",
                        "description": "d",
                        "instructions": "do it",
                        "resources": [{"name": "r.md", "content": "R"}],
                    }
                ],
                "script_timeout": 12,
            }
        ),
        encoding="utf-8",
    )
    cfg = load_skills_config(skills_path=path, settings={})
    assert cfg.paths == ("~/extra",)
    assert cfg.inline[0].name == "note"
    assert cfg.inline[0].resources == (("r.md", "R"),)
    assert cfg.script_timeout == 12


def test_build_skill_query(tmp_path: Path) -> None:
    md = tmp_path / "SKILL.md"
    md.write_text("hello skill", encoding="utf-8")
    text = build_skill_query(md, "arg1")
    assert "<skill-instructions>" in text
    assert "hello skill" in text
    assert "arg1" in text


def test_build_inline_skill_query() -> None:
    text = build_inline_skill_query(
        name="n", instructions="body", args="x"
    )
    assert "body" in text and "x" in text


@pytest.mark.asyncio
async def test_script_runner_path_escape_and_run(tmp_path: Path) -> None:
    script_runner = pytest.importorskip(
        "openjiuwen.harness.tools.skills.script_runner",
        reason="script_runner absent on agent-core icode",
    )
    skill = tmp_path / "skill"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "hi.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    assert script_runner.resolve_under_skill_dir(skill, "../outside.py") is None
    resolved = script_runner.resolve_under_skill_dir(skill, "scripts/hi.py")
    assert resolved == script.resolve()

    runner = script_runner.SubprocessScriptRunner(timeout=30)
    out = await runner.run(
        skill_dir=skill,
        script_rel="scripts/hi.py",
        arguments=[],
    )
    assert "ok" in out
    assert not out.startswith("Error:")


@pytest.mark.asyncio
async def test_skill_use_rail_inline_and_script_tool(tmp_path: Path) -> None:
    pytest.importorskip(
        "openjiuwen.harness.tools.skills.run_skill_script",
        reason="RunSkillScriptTool / inline_skills absent on agent-core icode",
    )
    from openjiuwen.core.runner import Runner
    from openjiuwen.core.sys_operation import (
        LocalWorkConfig,
        OperationMode,
        SysOperationCard,
    )
    from openjiuwen.harness.rails.skills.skill_use_rail import SkillUseRail
    from openjiuwen.harness.tools.skills.skill_tool import SkillTool
    from openjiuwen.harness.tools.skills.run_skill_script import (
        RunSkillScriptTool,
    )

    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "pack"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: pack\ndescription: packed\n---\n# Pack\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "echo.py").write_text(
        "import sys\nprint(sys.argv[1])\n",
        encoding="utf-8",
    )

    await Runner.start()
    card_id = "test_skills_gap_op"
    try:
        card = SysOperationCard(
            id=card_id,
            mode=OperationMode.LOCAL,
            work_config=LocalWorkConfig(shell_allowlist=[]),
        )
        Runner.resource_mgr.add_sys_operation(card)
        rail = SkillUseRail(
            skills_dir=str(skills_root),
            skill_mode="all",
            include_tools=False,
            inline_skills=[
                {
                    "name": "inline-one",
                    "description": "inline",
                    "instructions": "Be brief.",
                    "resources": [{"name": "a.md", "content": "AAA"}],
                }
            ],
        )
        rail.sys_operation = Runner.resource_mgr.get_sys_operation(card_id)
        await rail.reload_skills()
        names = {s.name for s in rail.skills}
        assert "pack" in names
        assert "inline-one" in names

        skill_tool = SkillTool(
            rail.sys_operation, lambda: rail.skills
        )
        inline_res = await skill_tool.invoke(
            {"skill_name": "inline-one", "relative_file_path": "a.md"}
        )
        assert inline_res.success
        assert "AAA" in inline_res.data["skill_content"]

        run_tool = RunSkillScriptTool(lambda: rail.skills)
        run_res = await run_tool.invoke(
            {
                "skill_name": "pack",
                "script_name": "scripts/echo.py",
                "arguments": ["hello"],
            }
        )
        assert run_res.success
        assert "hello" in run_res.data["output"]
    finally:
        Runner.resource_mgr.remove_sys_operation(sys_operation_id=card_id)
        await Runner.stop()

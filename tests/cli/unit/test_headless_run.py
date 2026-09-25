# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for Chrys-aligned headless run helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjiuwen_icode.features.headless_run import (
    TaskFileError,
    apply_workdir,
    read_task_file,
    resolve_prompt,
)


def test_read_task_file(tmp_path: Path) -> None:
    f = tmp_path / "task.md"
    f.write_text("do the thing\n", encoding="utf-8")
    assert read_task_file(str(f)).strip() == "do the thing"


def test_read_task_relative_to_workdir(tmp_path: Path) -> None:
    (tmp_path / "t.txt").write_text("hello", encoding="utf-8")
    assert read_task_file("t.txt", relative_to=str(tmp_path)) == "hello"


def test_read_task_missing() -> None:
    with pytest.raises(TaskFileError) as ei:
        read_task_file("/no/such/file-xyz")
    assert ei.value.code == "task_file_not_found"


def test_resolve_prompt_exclusive() -> None:
    with pytest.raises(ValueError):
        resolve_prompt(prompt="a", task="b")
    with pytest.raises(ValueError):
        resolve_prompt(prompt=None, task=None)


def test_resolve_prompt_envelopes_implement_task_file(tmp_path: Path) -> None:
    from openjiuwen_icode.features.implement_gate import (
        HEADLESS_TASK_ENVELOPE_MARKER,
    )

    f = tmp_path / "deepswe_task.md"
    body = (
        "Add a **Content** rule **Link Style** (alias: `link-style`).\n\n"
        "## Configuration\n\n"
        "- `linkStyle`: `markdown` | `wiki`\n\n"
        "---\n"
        "Execution rules for this DeepSWE eval:\n"
        "1. The repository under evaluation is `/app`.\n"
    )
    f.write_text(body, encoding="utf-8")
    text = resolve_prompt(prompt=None, task=str(f))
    assert text.lstrip().startswith(HEADLESS_TASK_ENVELOPE_MARKER)
    assert "## Configuration" in text
    assert "Execution rules for this DeepSWE eval" in text
    # Idempotent.
    assert resolve_prompt(prompt=text, task=None) == text


def test_resolve_prompt_skips_envelope_for_non_implement() -> None:
    text = resolve_prompt(prompt="What is 2+2?", task=None)
    assert text == "What is 2+2?"


def test_apply_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    nested = tmp_path / "ws"
    nested.mkdir()
    resolved = apply_workdir(str(nested))
    assert resolved == str(nested.resolve())
    assert Path.cwd() == nested.resolve()


@pytest.mark.asyncio
async def test_run_via_bus_result_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from openjiuwen_icode.host.bus_runner import run_via_bus

    monkeypatch.setenv("ICODE_PROJECT", str(tmp_path / "proj"))
    (tmp_path / "proj").mkdir()
    code = await run_via_bus(
        None, "hello", demo=True, result_json=True
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out.strip())
    assert "session_id" in data
    assert "result" in data
    assert "duration" in data

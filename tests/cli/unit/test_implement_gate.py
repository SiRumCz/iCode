# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for implement-task detection helpers."""

from __future__ import annotations

from openjiuwen_icode.features.implement_gate import (
    SHALLOW_EDIT_NUDGE,
    SUBMIT_NUDGE,
    VERIFY_NUDGE,
    ZERO_MUTATION_NUDGE,
    edit_args_look_shallow,
    extract_bash_command,
    is_shallow_signature_edit,
    looks_like_implement_task,
    looks_like_submit_command,
    looks_like_verify_command,
    next_implement_continuation,
    task_requires_submit,
)


def test_looks_like_implement_task_positive() -> None:
    assert looks_like_implement_task(
        "Implement CLI --config overrides then run lolbench-submit"
    )
    assert looks_like_implement_task("Please fix the bug in args.rs")
    assert looks_like_implement_task("Add support for inline TOML")


def test_looks_like_implement_task_negative() -> None:
    assert not looks_like_implement_task("What is Ruff?")
    assert not looks_like_implement_task("")
    assert not looks_like_implement_task("Explain how --config works")


def test_verify_and_submit_command_detection() -> None:
    assert looks_like_verify_command("cargo check -p ruff")
    assert looks_like_verify_command("cd /workspace/ruff && cargo test --test x")
    assert looks_like_verify_command("pytest -q")
    assert not looks_like_verify_command("ls crates")
    assert looks_like_submit_command("lolbench-submit")
    assert looks_like_submit_command("cat /logs/artifacts/solution.patch")
    assert not looks_like_submit_command("cargo check")
    assert extract_bash_command({"command": "cargo check"}) == "cargo check"
    assert task_requires_submit("run lolbench-submit when done")
    assert not task_requires_submit("implement the feature")


def test_shallow_signature_edit_option_to_vec() -> None:
    old = "    pub config: Option<PathBuf>,\n"
    new = "    pub config: Vec<String>,\n"
    assert is_shallow_signature_edit(old, new)
    assert edit_args_look_shallow(
        {"old_string": old, "new_string": new, "replace_all": True}
    )


def test_shallow_signature_edit_docs_and_type() -> None:
    old = (
        "    /// Path to the configuration.\n"
        "    #[arg(long, conflicts_with = \"isolated\")]\n"
        "    pub config: Option<PathBuf>,\n"
    )
    new = (
        "    /// Path or inline TOML override.\n"
        "    #[arg(long, value_name = \"CONFIG\")]\n"
        "    pub config: Vec<String>,\n"
    )
    assert is_shallow_signature_edit(old, new)


def test_non_shallow_when_parser_added() -> None:
    old = "    pub config: Option<PathBuf>,\n"
    new = (
        "    #[arg(long, value_parser = ConfigArgumentParser)]\n"
        "    pub config: Vec<SingleConfigArgument>,\n"
        "\n"
        "fn parse_ref(value: &str) -> Result<SingleConfigArgument> {\n"
        "    if value.contains('=') {\n"
        "        return Ok(SingleConfigArgument::SettingsOverride(...));\n"
        "    }\n"
        "    Ok(SingleConfigArgument::FilePath(PathBuf::from(value)))\n"
        "}\n"
    )
    assert not is_shallow_signature_edit(old, new)


def test_next_implement_continuation_chain() -> None:
    text = "Implement --config overrides then run lolbench-submit"
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=False,
            verify_attempted=False,
            submit_attempted=False,
            shallow_only=True,
        )
        == ZERO_MUTATION_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=False,
            submit_attempted=False,
            shallow_only=True,
        )
        == SHALLOW_EDIT_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=False,
            submit_attempted=False,
            shallow_only=False,
        )
        == VERIFY_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            submit_attempted=False,
            shallow_only=False,
        )
        == SUBMIT_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            submit_attempted=True,
            shallow_only=False,
        )
        is None
    )

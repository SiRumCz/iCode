# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for implement-task detection helpers."""

from __future__ import annotations

from openjiuwen_icode.features.implement_gate import (
    NATIVE_BUILD_NUDGE,
    SHALLOW_EDIT_NUDGE,
    SUBMIT_NUDGE,
    VERIFY_FAILED_NUDGE,
    VERIFY_NUDGE,
    ZERO_MUTATION_NUDGE,
    bash_result_succeeded,
    edit_args_look_shallow,
    extract_bash_command,
    extract_bash_command_from_result,
    extract_required_prompt_symbols,
    is_headless_continuation_nudge,
    is_wrapped_implement_continuation_query,
    is_native_source_path,
    is_shallow_signature_edit,
    looks_like_implement_task,
    looks_like_native_build_command,
    looks_like_submit_command,
    looks_like_verify_command,
    mutation_args_touch_native,
    next_implement_continuation,
    original_task_from_query,
    primary_user_task_text,
    pytest_command_matches_task_scope,
    task_requires_submit,
    verify_command_qualifies_for_completion,
    wrap_implement_continuation_query,
)


def test_looks_like_implement_task_positive() -> None:
    assert looks_like_implement_task(
        "Implement CLI --config overrides then run lolbench-submit"
    )
    assert looks_like_implement_task("Please fix the bug in args.rs")
    assert looks_like_implement_task("Add support for inline TOML")
    assert looks_like_implement_task(
        "Add `var x: type = value` syntax to Anko for typed variable declarations."
    )


def test_looks_like_implement_task_negative() -> None:
    assert not looks_like_implement_task("What is Ruff?")
    assert not looks_like_implement_task("")
    assert not looks_like_implement_task("Explain how --config works")


def test_looks_like_implement_task_harbor_spec() -> None:
    assert looks_like_implement_task(
        "Expected Feature:\nSupport $ref resolution in dependentSchemas."
    )
    assert looks_like_implement_task(
        "Ensure enum deep equality with object/array values"
    )
    assert looks_like_implement_task(
        "IMPORTANT: Please work on this in a new branch from main."
    )


def test_original_task_from_query() -> None:
    original = "Add typed bindings to Anko."
    wrapped = wrap_implement_continuation_query(original, ZERO_MUTATION_NUDGE)
    assert original_task_from_query(original) == original
    assert original_task_from_query(wrapped) == original
    assert original_task_from_query("") == ""


def test_primary_user_task_text_skips_continuation_nudges() -> None:
    original = (
        "Add typed variable bindings to Anko parser and vm with type error messages."
    )
    messages = [
        {"role": "user", "content": original},
        {"role": "assistant", "content": "I'll inspect the repo."},
        {"role": "user", "content": ZERO_MUTATION_NUDGE},
    ]
    assert primary_user_task_text(messages) == original
    assert is_headless_continuation_nudge(ZERO_MUTATION_NUDGE)
    assert not is_headless_continuation_nudge(original)


def test_wrap_implement_continuation_query_includes_original_task() -> None:
    original = "Add typed bindings to Anko."
    wrapped = wrap_implement_continuation_query(original, ZERO_MUTATION_NUDGE)
    assert ZERO_MUTATION_NUDGE in wrapped
    assert original in wrapped
    assert wrap_implement_continuation_query(original, original) == original
    assert is_wrapped_implement_continuation_query(wrapped)
    assert not is_wrapped_implement_continuation_query(original)


def test_verify_and_submit_command_detection() -> None:
    assert looks_like_verify_command("cargo check -p ruff")
    assert looks_like_verify_command("cd /workspace/ruff && cargo test --test x")
    assert looks_like_verify_command("pytest -q")
    assert looks_like_verify_command("CCACHE_DISABLE=1 make -j2 python")
    assert looks_like_verify_command("make regen-pegen regen-ast")
    assert looks_like_verify_command("make -j4 Objects/typevarobject.o")
    assert looks_like_verify_command("./python -c \"import ast; assert True\"")
    assert looks_like_verify_command("python -m pytest -q")
    assert looks_like_verify_command("python3 -m compileall Lib/typing.py")
    assert looks_like_native_build_command("make -j2")
    assert looks_like_native_build_command("make -j4 Objects/typevarobject.o")
    assert looks_like_native_build_command("cargo check -p foo")
    assert not looks_like_native_build_command("./python -m test test_typing")
    assert not looks_like_verify_command("ls crates")
    assert looks_like_submit_command("lolbench-submit")
    assert looks_like_submit_command("cat /logs/artifacts/solution.patch")
    assert not looks_like_submit_command("cargo check")
    assert extract_bash_command({"command": "cargo check"}) == "cargo check"
    assert task_requires_submit("run lolbench-submit when done")
    assert not task_requires_submit("implement the feature")


def test_native_source_detection() -> None:
    assert is_native_source_path("Objects/typevarobject.c")
    assert is_native_source_path("/workspace/cpython/Include/foo.h")
    assert not is_native_source_path("Lib/typing.py")
    assert mutation_args_touch_native(
        {
            "file_path": "Objects/typevarobject.c",
            "old_string": "x",
            "new_string": "y",
        }
    )


def test_native_build_required_for_completion() -> None:
    assert (
        verify_command_qualifies_for_completion(
            "./python -m test test_typing",
            native_mutated=True,
            success=True,
        )
        is False
    )
    assert (
        verify_command_qualifies_for_completion(
            "make -j2 Objects/typevarobject.o",
            native_mutated=True,
            success=True,
        )
        is True
    )
    assert (
        verify_command_qualifies_for_completion(
            "./python -m test test_typing",
            native_mutated=False,
            success=True,
        )
        is True
    )


def test_python_suite_required_for_pure_python_edits() -> None:
    from openjiuwen_icode.features.implement_gate import (
        PYTHON_SUITE_NUDGE,
        is_python_source_path,
        looks_like_python_suite_command,
        mutation_args_touch_python,
    )

    assert is_python_source_path("aiomonitor/monitor.py")
    assert not is_python_source_path("Objects/foo.c")
    assert mutation_args_touch_python(
        {"file_path": "aiomonitor/types.py", "content": "x = 1\n"}
    )
    assert looks_like_python_suite_command("pytest -q tests/test_snapshot.py")
    assert looks_like_python_suite_command("python -m pytest -q")
    assert looks_like_python_suite_command("python3 -m unittest discover")
    assert not looks_like_python_suite_command("python -m compileall aiomonitor")
    assert not looks_like_python_suite_command('python -c "import aiomonitor"')

    assert (
        verify_command_qualifies_for_completion(
            "python -m compileall aiomonitor",
            native_mutated=False,
            python_mutated=True,
            success=True,
        )
        is False
    )
    assert (
        verify_command_qualifies_for_completion(
            "pytest -q tests/test_snapshot.py",
            native_mutated=False,
            python_mutated=True,
            success=True,
        )
        is True
    )
    # Native+Python: native build still qualifies completion.
    assert (
        verify_command_qualifies_for_completion(
            "make -j2",
            native_mutated=True,
            python_mutated=True,
            success=True,
        )
        is True
    )

    text = "Implement snapshot CLI then run lolbench-submit"
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=False,
            submit_attempted=False,
            shallow_only=False,
            python_mutated=True,
            python_suite_verified=False,
        )
        == PYTHON_SUITE_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=True,
            submit_attempted=False,
            shallow_only=False,
            python_mutated=True,
            python_suite_verified=True,
        )
        == SUBMIT_NUDGE
    )


def test_go_suite_required_for_pure_go_edits() -> None:
    from openjiuwen_icode.features.implement_gate import (
        GO_SUITE_NUDGE,
        is_go_source_path,
        looks_like_go_suite_command,
        mutation_args_touch_go,
    )

    assert is_go_source_path("evaluator/evaluator.go")
    assert is_go_source_path("evaluator/evaluator_test.go")
    assert mutation_args_touch_go(
        {"file_path": "parser/parser.go", "content": "package parser\n"}
    )
    assert looks_like_go_suite_command("go test ./evaluator ./parser -count=1")
    assert looks_like_go_suite_command("go test ./...")
    assert not looks_like_go_suite_command("go build ./...")
    assert not looks_like_go_suite_command("go vet ./...")

    assert (
        verify_command_qualifies_for_completion(
            "go build ./...",
            native_mutated=False,
            go_mutated=True,
            success=True,
        )
        is False
    )
    assert (
        verify_command_qualifies_for_completion(
            "go test ./evaluator -count=1",
            native_mutated=False,
            go_mutated=True,
            success=True,
        )
        is True
    )

    text = "Implement stepped slice indexing in the ABS evaluator."
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=False,
            submit_attempted=False,
            shallow_only=False,
            go_mutated=True,
            go_suite_verified=False,
        )
        == GO_SUITE_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=True,
            submit_attempted=False,
            shallow_only=False,
            go_mutated=True,
            go_suite_verified=True,
        )
        is None
    )


def test_typescript_suite_required_for_pure_ts_edits() -> None:
    from openjiuwen_icode.features.implement_gate import (
        TS_SUITE_NUDGE,
        is_typescript_source_path,
        looks_like_typescript_suite_command,
        mutation_args_touch_typescript,
        typescript_command_matches_task_scope,
    )

    assert is_typescript_source_path("src/container.ts")
    assert is_typescript_source_path("src/__tests__/async-initialization.test.ts")
    assert not is_typescript_source_path("package.json")
    assert mutation_args_touch_typescript(
        {"file_path": "src/container.ts", "content": "export {}\n"}
    )
    assert looks_like_typescript_suite_command("npm test -- async-initialization")
    assert looks_like_typescript_suite_command("npx jest async-initialization")
    assert looks_like_typescript_suite_command("yarn test src/__tests__/foo.test.ts")
    assert not looks_like_typescript_suite_command("tsc --noEmit")
    assert not looks_like_typescript_suite_command("npm run build")

    assert (
        verify_command_qualifies_for_completion(
            "tsc --noEmit",
            native_mutated=False,
            typescript_mutated=True,
            success=True,
        )
        is False
    )
    assert (
        verify_command_qualifies_for_completion(
            "npm test -- async-initialization",
            native_mutated=False,
            typescript_mutated=True,
            success=True,
        )
        is True
    )

    task = (
        "Add support for asynchronous container initialization with "
        "initializer() and initialize(). initializer initializer initialize."
    )
    assert not typescript_command_matches_task_scope(task, "npm test")
    assert typescript_command_matches_task_scope(
        task, "npm test -- async-initialization"
    )
    assert (
        next_implement_continuation(
            user_text=task,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=False,
            submit_attempted=False,
            shallow_only=False,
            typescript_mutated=True,
            typescript_suite_verified=False,
        )
        == TS_SUITE_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=task,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=True,
            submit_attempted=False,
            shallow_only=False,
            typescript_mutated=True,
            typescript_suite_verified=True,
        )
        is None
    )


def test_native_build_nudge_before_submit() -> None:
    text = "Implement PEP 696 then run lolbench-submit"
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=True,
            submit_attempted=False,
            shallow_only=False,
            native_mutated=True,
            native_build_verified=False,
        )
        == NATIVE_BUILD_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=True,
            submit_attempted=False,
            shallow_only=False,
            native_mutated=True,
            native_build_verified=True,
        )
        == SUBMIT_NUDGE
    )


def test_bash_result_success_detection() -> None:
    ok = (
        "Command: make -j2 python\nStdout: built\nStderr: (empty)\n"
        "Exit Code: 0"
    )
    fail = (
        "Command: make -j2 python\nStdout: gcc error\nStderr: err\n"
        "Exit Code: 2"
    )
    assert bash_result_succeeded(ok) is True
    assert bash_result_succeeded(fail) is False
    assert bash_result_succeeded("no exit info") is None
    assert bash_result_succeeded("", tool_success=True) is True
    assert extract_bash_command_from_result(ok) == "make -j2 python"


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


def test_looks_like_git_archaeology() -> None:
    from openjiuwen_icode.features.implement_gate import (
        looks_like_git_archaeology,
    )

    assert looks_like_git_archaeology(
        "git log --all --oneline --grep=comprehension | head"
    )
    assert looks_like_git_archaeology("git for-each-ref --format=...")
    assert not looks_like_git_archaeology("cargo check -p ruff")
    assert not looks_like_git_archaeology("git status")


def test_looks_like_explore_bash() -> None:
    from openjiuwen_icode.features.implement_gate import (
        looks_like_explore_bash,
    )

    assert looks_like_explore_bash("go test ./... -count=1")
    assert looks_like_explore_bash("go build ./...")
    assert looks_like_explore_bash("npm test")
    assert looks_like_explore_bash("npx jest --runInBand")
    assert looks_like_explore_bash("grep -R 'default' parser/")
    assert looks_like_explore_bash("cat vm/vm.go | head")
    assert not looks_like_explore_bash("cargo check -p ruff")
    assert not looks_like_explore_bash("git status")


def test_go_command_matches_task_scope() -> None:
    from openjiuwen_icode.features.implement_gate import (
        go_command_matches_task_scope,
    )

    task = (
        "Add support for default argument values written as `name = expression`. "
        "When a call omits trailing arguments, assign default values. "
        "Invalid declarations should use `invalid default argument declaration`."
    )
    assert not go_command_matches_task_scope(task, "go test ./... -count=1")
    assert go_command_matches_task_scope(
        task, "go test ./vm -run TestDefaultArguments -count=1"
    )
    assert go_command_matches_task_scope(
        task, "go test -run DefaultArgument -count=1 ./..."
    )
    assert go_command_matches_task_scope(
        task, "go test ./parser ./vm -count=1"
    )
    assert not go_command_matches_task_scope(task, "go test -count=1")


def test_go_verify_requires_task_scoped_go_test() -> None:
    from openjiuwen_icode.features.implement_gate import (
        go_command_matches_task_scope,
    )

    task = (
        "Add default argument values. Default default default arguments "
        "arguments arguments arguments."
    )
    assert not go_command_matches_task_scope(task, "go test ./...")
    assert (
        verify_command_qualifies_for_completion(
            "go test ./...",
            native_mutated=False,
            go_mutated=True,
            success=True,
            user_text=task,
        )
        is False
    )
    assert (
        verify_command_qualifies_for_completion(
            "go test ./vm -run Default -count=1",
            native_mutated=False,
            go_mutated=True,
            success=True,
            user_text=task,
        )
        is True
    )


def test_next_implement_continuation_chain() -> None:
    text = "Implement --config overrides then run lolbench-submit"
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=False,
            verify_attempted=False,
            verify_succeeded=False,
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
            verify_succeeded=False,
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
            verify_succeeded=False,
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
            verify_succeeded=False,
            submit_attempted=False,
            shallow_only=False,
        )
        == VERIFY_FAILED_NUDGE
    )
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=True,
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
            verify_succeeded=True,
            submit_attempted=True,
            shallow_only=False,
        )
        is None
    )


def test_submit_before_verify_does_not_complete() -> None:
    text = "Implement --config overrides then run lolbench-submit"
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=False,
            submit_attempted=True,
            shallow_only=False,
        )
        == VERIFY_FAILED_NUDGE
    )


def test_go_verify_command_detection() -> None:
    assert looks_like_verify_command("go test ./evaluator ./repl -count=1")
    assert looks_like_verify_command("go build ./...")
    assert looks_like_verify_command("go vet ./...")


def test_integration_and_prompt_symbol_continuation() -> None:
    from openjiuwen_icode.features.implement_gate import (
        INTEGRATION_NUDGE,
        extract_required_prompt_symbols,
        missing_prompt_symbols,
        prompt_symbol_nudge,
    )

    text = (
        "Implement require_cache_info() and reset_require_cache(), "
        "preserve BeginRepl(args []string, version string), and support "
        "`--module-debug` plus `--module-path` in script mode."
    )
    symbols = extract_required_prompt_symbols(text)
    assert "require_cache_info" in symbols
    assert "reset_require_cache" in symbols
    assert "BeginRepl" in symbols
    assert "--module-debug" in symbols

    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=False,
            verify_succeeded=False,
            submit_attempted=False,
            shallow_only=False,
            integration_attempted=False,
        )
        == INTEGRATION_NUDGE
    )

    missing = missing_prompt_symbols(
        user_text=text,
        mutation_blob="func requireCacheInfoFn() {}",
    )
    assert missing
    nudge = next_implement_continuation(
        user_text=text,
        mutate_attempted=True,
        verify_attempted=True,
        verify_succeeded=True,
        submit_attempted=False,
        shallow_only=False,
        integration_attempted=True,
        missing_symbols=missing,
    )
    assert nudge == prompt_symbol_nudge(missing)
    assert "BeginRepl" in (nudge or "")

    covered = missing_prompt_symbols(
        user_text=text,
        mutation_blob=(
            "require_cache_info reset_require_cache BeginRepl "
            "--module-debug --module-path"
        ),
    )
    assert covered == ()
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=True,
            submit_attempted=False,
            shallow_only=False,
            integration_attempted=True,
            missing_symbols=(),
        )
        is None
    )


def test_mutation_text_and_edit_tool_helpers() -> None:
    from openjiuwen_icode.features.implement_gate import (
        mutation_text_from_args,
        tool_is_edit_existing,
        tool_is_write_file,
    )

    assert tool_is_edit_existing("edit_file")
    assert tool_is_write_file("write_file")
    assert not tool_is_edit_existing("write_file")
    blob = mutation_text_from_args(
        {
            "file_path": "evaluator/functions.go",
            "old_string": "old",
            "new_string": ' "require_cache_info": &object.Builtin{',
        }
    )
    assert "require_cache_info" in blob
    assert "functions.go" in blob


def test_snapshot_task_symbol_extraction_and_missing() -> None:
    from openjiuwen_icode.features.implement_gate import (
        missing_prompt_symbols,
        pytest_command_matches_task_scope,
    )

    task = (
        "Add snapshots to Monitor. Monitor/start_monitor accept max_snapshots. "
        "Monitor methods: capture_snapshot, list_snapshots (returns summaries "
        "with id, name, running_count, and terminated_count), get_snapshot, "
        "format_snapshot_diff(snapshot_id_1, snapshot_id_2). "
        "Web API returns {id} and {added, removed, common}."
    )
    symbols = extract_required_prompt_symbols(task)
    assert "capture_snapshot" in symbols
    assert "start_monitor" in symbols
    assert "max_snapshots" in symbols
    assert "format_snapshot_diff" in symbols
    assert "id" in symbols
    assert "running_count" in symbols

    patch_blob = (
        "def capture_snapshot(self): ... snapshot_id: int running_count "
        "terminated_count format_snapshot_diff"
    )
    missing = missing_prompt_symbols(user_text=task, mutation_blob=patch_blob)
    assert "start_monitor" in missing
    assert "id" in missing

    assert not pytest_command_matches_task_scope(task, "pytest -q")
    assert not pytest_command_matches_task_scope(task, "pytest -q tests/test_monitor.py")
    assert pytest_command_matches_task_scope(
        task, "pytest -q tests/test_snapshot.py"
    )


def test_python_verify_requires_task_scoped_pytest() -> None:
    task = (
        "Add snapshot support with capture_snapshot and format_snapshot_diff. "
        "Snapshots snapshots snapshots."
    )
    assert not pytest_command_matches_task_scope(task, "pytest -q")
    assert (
        verify_command_qualifies_for_completion(
            "pytest -q",
            native_mutated=False,
            python_mutated=True,
            success=True,
            user_text=task,
        )
        is False
    )
    assert (
        verify_command_qualifies_for_completion(
            "pytest -q tests/test_monitor.py",
            native_mutated=False,
            python_mutated=True,
            success=True,
            user_text=task,
        )
        is False
    )
    assert (
        verify_command_qualifies_for_completion(
            "pytest -q tests/test_snapshot.py",
            native_mutated=False,
            python_mutated=True,
            success=True,
            user_text=task,
        )
        is True
    )


def test_bare_pytest_rejected_when_task_has_feature_keywords() -> None:
    task = (
        "`name_mapping` gains `aliases` and `alias_style`. "
        "Loading resolves aliases with ordered alias fallback. "
        "Aliases are literal under `name_style`."
    )
    assert not pytest_command_matches_task_scope(task, "pytest -q")
    assert pytest_command_matches_task_scope(
        task, "pytest -q tests/integration/morphing/test_aliases.py"
    )


def test_worktree_nudge_when_edits_do_not_change_files() -> None:
    from openjiuwen_icode.features.implement_gate import WORKTREE_NUDGE

    text = "Implement alias support in name_mapping."
    assert (
        next_implement_continuation(
            user_text=text,
            mutate_attempted=True,
            verify_attempted=True,
            verify_succeeded=True,
            submit_attempted=False,
            shallow_only=False,
            workspace_mutated=False,
        )
        == WORKTREE_NUDGE
    )

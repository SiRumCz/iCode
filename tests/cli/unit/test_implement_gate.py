# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for implement-task detection helpers."""

from __future__ import annotations

from openjiuwen_icode.features.implement_gate import (
    NATIVE_BUILD_NUDGE,
    SHALLOW_EDIT_NUDGE,
    SUBMIT_NUDGE,
    TOOL_RUNTIME_NUDGE,
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
    tool_runtime_continuation_nudge,
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
    from openjiuwen_icode.features.implement_gate import (
        wrap_headless_implement_prompt,
    )

    original = "Add typed bindings to Anko."
    wrapped = wrap_implement_continuation_query(original, ZERO_MUTATION_NUDGE)
    enveloped = wrap_headless_implement_prompt(original)
    assert original_task_from_query(original) == original
    assert original_task_from_query(wrapped) == original
    assert original_task_from_query(enveloped) == original
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


def test_primary_user_task_text_extracts_wrapped_continuation() -> None:
    from openjiuwen_icode.features.implement_gate import (
        wrap_headless_implement_prompt,
    )

    original = (
        "Add support for asynchronous initialization of container registrations."
    )
    wrapped = wrap_implement_continuation_query(original, ZERO_MUTATION_NUDGE)
    assert not is_headless_continuation_nudge(wrapped)
    assert primary_user_task_text([{"role": "user", "content": wrapped}]) == original
    assert (
        primary_user_task_text(
            [{"role": "user", "content": wrap_headless_implement_prompt(original)}]
        )
        == original
    )


def test_wrap_implement_continuation_query_includes_original_task() -> None:
    original = "Add typed bindings to Anko."
    wrapped = wrap_implement_continuation_query(original, ZERO_MUTATION_NUDGE)
    assert ZERO_MUTATION_NUDGE in wrapped
    assert original in wrapped
    assert wrap_implement_continuation_query(original, original) == original
    assert is_wrapped_implement_continuation_query(wrapped)
    assert not is_wrapped_implement_continuation_query(original)


def test_tool_runtime_nudge_is_headless_continuation() -> None:
    assert is_headless_continuation_nudge(TOOL_RUNTIME_NUDGE)
    wrapped = wrap_implement_continuation_query(
        "Implement AutoToc in src/rules/auto-toc.ts",
        tool_runtime_continuation_nudge(OSError(36, "File name too long")),
    )
    assert is_wrapped_implement_continuation_query(wrapped)
    assert "plain path" in wrapped
    assert "File name too long" in wrapped


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
    assert looks_like_verify_command("npx jest --runInBand")
    assert looks_like_verify_command("npx jest container.initialize")
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
            user_text=(
                "Add snapshot support with capture_snapshot. "
                "Snapshots snapshots snapshots."
            ),
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


def test_typescript_insufficient_verify_nudge_after_passing_unqualified_run() -> None:
    from openjiuwen_icode.features.implement_gate import (
        TS_INSUFFICIENT_VERIFY_NUDGE_TEMPLATE,
        TS_SUITE_NUDGE,
        extract_chainable_method_names,
        next_implement_continuation,
        typescript_insufficient_verify_nudge,
        verify_command_qualifies_for_completion,
    )

    task = (
        "Add window function helpers with .over() on builders. "
        "The chainable .window(name, spec) method must be available on "
        "select builders across all supported dialects."
    )
    agent_tests = frozenset({"window-functions.test.ts", "window-functions"})
    cmd = "cd /app/drizzle-orm && npx vitest run 2>&1 | tail -30"

    assert extract_chainable_method_names(task) == ("over", "window")
    assert not verify_command_qualifies_for_completion(
        cmd,
        native_mutated=False,
        typescript_mutated=True,
        success=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    nudge = typescript_insufficient_verify_nudge(task)
    assert TS_INSUFFICIENT_VERIFY_NUDGE_TEMPLATE in nudge
    assert "`.over()`" in nudge
    assert "`.window()`" in nudge
    assert "touch commits" in nudge
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
            typescript_suite_passed_unqualified=True,
        )
        == nudge
    )
    assert (
        next_implement_continuation(
            user_text=task,
            mutate_attempted=True,
            verify_attempted=False,
            verify_succeeded=False,
            submit_attempted=False,
            shallow_only=False,
            typescript_mutated=True,
            typescript_suite_verified=False,
            typescript_suite_passed_unqualified=False,
        )
        == TS_SUITE_NUDGE
    )


def test_chainable_methods_count_as_wiring_symbols() -> None:
    from openjiuwen_icode.features.implement_gate import missing_prompt_symbols

    task = (
        "Implement ranking helpers rowNumber and denseRank. "
        "Each helper returns a builder with a .over() method. "
        "The .window() method on query builders must reject empty names."
    )
    assert missing_prompt_symbols(
        user_text=task,
        mutation_blob="export function rowNumber() {}",
    ) == ("over", "window")


def test_typescript_suite_required_for_js_and_ts_edits() -> None:
    from openjiuwen_icode.features.implement_gate import (
        TS_SUITE_NUDGE,
        is_typescript_source_path,
        looks_like_typescript_suite_command,
        mutation_args_touch_typescript,
        typescript_command_matches_task_scope,
    )

    assert is_typescript_source_path("src/container.ts")
    assert is_typescript_source_path("src/__tests__/async-initialization.test.ts")
    assert is_typescript_source_path("src/container.js")
    assert is_typescript_source_path("src/container.jsx")
    assert is_typescript_source_path("src/container.mjs")
    assert is_typescript_source_path("src/container.cjs")
    assert not is_typescript_source_path("package.json")
    assert mutation_args_touch_typescript(
        {"file_path": "src/container.ts", "content": "export {}\n"}
    )
    assert mutation_args_touch_typescript(
        {"file_path": "lib/lexer/shorthand.js", "content": "export {}\n"}
    )
    assert looks_like_typescript_suite_command("npm test -- async-initialization")
    assert looks_like_typescript_suite_command("npx jest async-initialization")
    assert looks_like_typescript_suite_command("yarn test src/__tests__/foo.test.ts")
    assert not looks_like_typescript_suite_command("tsc --noEmit")
    assert not looks_like_typescript_suite_command("npm run build")
    assert looks_like_typescript_suite_command(
        "deno test --allow-env --allow-read command/test/"
    )
    assert looks_like_typescript_suite_command("deno task test:deno-v2")

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
    assert typescript_command_matches_task_scope(task, "npm test")
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


def test_ava_commands_count_as_typescript_verification() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_typescript_suite_command,
        looks_like_typescript_suite_command,
        verify_command_targets_agent_authored_tests,
    )

    task = "Implement grid layout support with grid_template_rows()."
    agent_tests = frozenset({"grid.tsx", "grid"})

    assert looks_like_verify_command("npx ava")
    assert looks_like_typescript_suite_command("npx ava")
    assert is_full_typescript_suite_command("npx ava")
    assert not is_full_typescript_suite_command("npx ava test/grid.tsx")
    assert not verify_command_targets_agent_authored_tests("npx ava", agent_tests)
    assert verify_command_targets_agent_authored_tests(
        "npx ava test/grid.tsx", agent_tests
    )
    assert verify_command_qualifies_for_completion(
        "npx ava",
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    assert verify_command_qualifies_for_completion(
        "cd /app && FORCE_COLOR=false npx ava 2>&1 | tail -30",
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    assert not verify_command_qualifies_for_completion(
        "npx ava test/grid.tsx",
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )


def test_typescript_scope_rejects_agent_only_initialize_tests() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_typescript_suite_command,
        typescript_command_matches_task_scope,
        verify_command_qualifies_for_completion,
        verify_command_targets_agent_authored_tests,
    )

    task = (
        "Add support for asynchronous initialization of container registrations "
        "with automatic dependency-aware startup ordering.\n\n"
        "Call container.initialize({ concurrency: 5 })."
    )
    agent_tests = frozenset(
        {"container.initialize.test.ts", "container.initialize"}
    )
    assert verify_command_targets_agent_authored_tests(
        "npx jest src/__tests__/container.initialize.test.ts", agent_tests
    )
    assert verify_command_targets_agent_authored_tests(
        "npx jest container.initialize", agent_tests
    )
    assert not verify_command_targets_agent_authored_tests(
        "npm test -- --runInBand", agent_tests
    )
    assert is_full_typescript_suite_command("npm test -- --runInBand")
    assert typescript_command_matches_task_scope(task, "npm test -- --runInBand")
    assert not verify_command_qualifies_for_completion(
        "npx jest src/__tests__/container.initialize.test.ts",
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    assert verify_command_qualifies_for_completion(
        "npm test -- --runInBand",
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )


def test_typescript_gate_accepts_pnpm_package_suites() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_typescript_suite_command,
        verify_command_qualifies_for_completion,
    )

    task = (
        "Export createFilter for value-based item filtering. "
        "Filters compose with existing selectors."
    )
    core_suite = (
        "cd /app/packages/core && pnpm vitest run 2>&1 | tail -30"
    )
    publish_suite = "cd /app && pnpm -F koota test run"

    # A bare Vitest run can include only an agent-authored test in repos with
    # narrow config, so keep requiring stronger package-script evidence.
    assert not is_full_typescript_suite_command(core_suite)
    assert is_full_typescript_suite_command(publish_suite)
    assert is_full_typescript_suite_command(
        "pnpm -F react test run && pnpm -F koota build"
    )
    assert not is_full_typescript_suite_command(
        "pnpm vitest run tests/value-filter.test.ts"
    )
    assert verify_command_qualifies_for_completion(
        publish_suite,
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=frozenset(
            {"value-filter.test.ts", "value-filter"}
        ),
    )


def test_typescript_gate_rejects_plain_js_test_created_under_test_dir() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_typescript_suite_command,
        verify_command_qualifies_for_completion,
        verify_command_targets_agent_authored_tests,
    )

    task = "Add atomic signal selectors and expose selectorHealth."
    agent_tests = frozenset({"atomic-selectors.js", "atomic-selectors"})
    targeted = "BABEL_ENV=test npx jest test/jest/atomic-selectors.js"
    targeted_in_band = f"{targeted} --runInBand"

    assert verify_command_targets_agent_authored_tests(targeted, agent_tests)
    assert not is_full_typescript_suite_command(targeted_in_band)
    assert verify_command_targets_agent_authored_tests(
        targeted_in_band, agent_tests
    )
    assert not verify_command_qualifies_for_completion(
        targeted,
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    assert verify_command_qualifies_for_completion(
        "BABEL_ENV=test npx jest --runInBand",
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
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


def test_bash_result_background_launch_is_not_completion() -> None:
    launch = "{'pid': 3076, 'status': 'started'}"
    running = '{"pid": 3076, "status": "running"}'

    assert bash_result_succeeded(launch, tool_success=True) is None
    assert bash_result_succeeded(running, tool_success=True) is None


def test_dict_bash_result_preserves_full_suite_command() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_typescript_suite_command,
    )

    result = {
        "content": (
            "Command: cd /app && npm test\n"
            "Stdout: > css-tree@3.2.1 test\n"
            "> mocha lib/__tests --require lib/__tests/helpers/setup.js\n"
            "16800 passing\n"
            "Stderr: (empty)\n"
            "Exit Code: 0"
        )
    }

    command = extract_bash_command_from_result(result)

    assert command == "cd /app && npm test"
    assert bash_result_succeeded(result) is True
    assert is_full_typescript_suite_command(command)
    assert verify_command_qualifies_for_completion(
        command,
        native_mutated=False,
        typescript_mutated=True,
        success=True,
        user_text="Add expandShorthand and compressShorthand to the lexer.",
    )


def test_bash_result_detects_jest_failure_with_piped_zero_exit() -> None:
    """Piped ``tail`` can mask jest's non-zero exit; stdout summary must fail."""
    piped_fail = (
        "Command: cd /app && npx jest foo.test.ts 2>&1 | tail -60\n"
        "Stdout: FAIL src/__tests__/foo.test.ts\n"
        "  ● Test suite failed to run\n\n"
        "Test Suites: 1 failed, 1 total\n"
        "Tests:       0 total\n"
        "Stderr: (empty)\n"
        "Exit Code: 0"
    )
    assert bash_result_succeeded(piped_fail) is False
    assert bash_result_succeeded(piped_fail, tool_success=True) is False

    piped_pass = (
        "Command: cd /app && npx jest container.initialize 2>&1 | tail -22\n"
        "Stdout: PASS src/__tests__/container.initialize.test.ts\n"
        "Test Suites: 1 passed, 1 total\n"
        "Tests:       12 passed, 12 total\n"
        "Stderr: (empty)\n"
        "Exit Code: 0"
    )
    assert bash_result_succeeded(piped_pass) is True


def test_bash_result_detects_pytest_and_go_failures_in_stdout() -> None:
    pytest_fail = (
        "Command: pytest -q\nStdout: ===== 2 failed, 1 passed in 0.4s =====\n"
        "Exit Code: 0"
    )
    assert bash_result_succeeded(pytest_fail) is False

    piped_pytest_fail = (
        "Command: pytest tests -q -x 2>&1 | tail -6\n"
        "Stdout: !!!!!!!!! stopping after 1 failures !!!!!!!!!\n"
        "1 failed, 1086 passed in 4.05s\n"
        "Exit Code: 0"
    )
    assert bash_result_succeeded(piped_pytest_fail) is False

    go_fail = (
        "Command: go test ./pkg\nStdout: --- FAIL: TestFoo (0.00s)\n"
        "FAIL\texample.com/pkg\t0.01s\nExit Code: 0"
    )
    assert bash_result_succeeded(go_fail) is False


def test_deno_test_commands_clear_typescript_verify_gate() -> None:
    from openjiuwen_icode.features.implement_gate import (
        TS_SUITE_NUDGE,
        is_full_typescript_suite_command,
        looks_like_deno_test_command,
        looks_like_typescript_suite_command,
        looks_like_verify_command,
        next_implement_continuation,
        verify_command_qualifies_for_completion,
        verify_command_targets_agent_authored_tests,
    )

    full_suite = (
        "cd /app && deno test --allow-run=deno --allow-env --allow-read "
        "--allow-write=./ --parallel command/test/"
    )
    agent_only = (
        "cd /app && deno test --allow-env --allow-read --allow-write=./ "
        "command/test/command/config_test.ts"
    )
    task = (
        "Add config file parsing to Command with config() and getConfigValues(). "
        "Support JSON and rc formats with config config config."
    )
    agent_tests = frozenset({"config_test.ts", "config_test"})

    assert looks_like_deno_test_command(full_suite)
    assert looks_like_verify_command(full_suite)
    assert looks_like_typescript_suite_command(full_suite)
    assert is_full_typescript_suite_command(full_suite)
    assert is_full_typescript_suite_command("deno task test:deno-v2")
    assert not is_full_typescript_suite_command(agent_only)
    assert verify_command_targets_agent_authored_tests(agent_only, agent_tests)
    assert not verify_command_targets_agent_authored_tests(
        full_suite, agent_tests
    )
    assert verify_command_qualifies_for_completion(
        full_suite,
        native_mutated=False,
        typescript_mutated=True,
        success=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    assert not verify_command_qualifies_for_completion(
        agent_only,
        native_mutated=False,
        typescript_mutated=True,
        success=True,
        user_text=task,
        agent_created_test_names=agent_tests,
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


def test_bash_result_detects_deno_failure_with_piped_zero_exit() -> None:
    piped_fail = (
        "Command: cd /app && deno test command/test/ 2>&1 | tail -15\n"
        "Stdout: ok | 330 passed | 5 failed (1s)\n"
        "Stderr: (empty)\n"
        "Exit Code: 0"
    )
    assert bash_result_succeeded(piped_fail) is False

    piped_pass = (
        "Command: cd /app && deno test command/test/ 2>&1 | tail -10\n"
        "Stdout: ok | 335 passed | 0 failed (1s)\n"
        "Stderr: (empty)\n"
        "Exit Code: 0"
    )
    assert bash_result_succeeded(piped_pass) is True


def test_bash_result_detects_missing_pytest_and_stestr_failures() -> None:
    missing_pytest = (
        "Command: cd /app && python -m pytest tests/unit/core/test_x.py -v 2>&1 | head -120\n"
        "Stdout: /usr/local/bin/python: No module named pytest\n\n"
        "Stderr: (empty)\nExit Code: 0"
    )
    assert bash_result_succeeded(missing_pytest) is False
    assert bash_result_succeeded(missing_pytest, tool_success=True) is False

    stestr_discovery = (
        "Command: cd /app && python -m stestr run tests/unit/core/test_x.py 2>&1 | tail -60\n"
        "Stdout: =========================\nFailures during discovery\n"
        "=========================\nFailed to import test module: tests.unit.core.test_x\n"
        "ModuleNotFoundError: No module named 'pytest'\nExit Code: 0"
    )
    assert bash_result_succeeded(stestr_discovery) is False

    stestr_failed = (
        "Command: cd /app && python -m stestr run 2>&1 | grep Passed\n"
        "Stdout: Ran: 78 tests in 0.05 sec.\n - Passed: 75\n - Failed: 3\n"
        "Exit Code: 0"
    )
    assert bash_result_succeeded(stestr_failed) is False

    stestr_ok = (
        "Command: cd /app && python -m stestr run 2>&1 | tail -5\n"
        "Stdout: Ran: 318 tests in 6.3 sec.\n - Passed: 318\n - Failed: 0\n"
        "Exit Code: 0"
    )
    assert bash_result_succeeded(stestr_ok) is True


def test_stestr_is_python_suite_and_scope() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_python_suite_command,
        looks_like_python_suite_command,
        python_suite_command_matches_task_scope,
        stestr_command_matches_task_scope,
        verify_command_qualifies_for_completion,
    )

    assert looks_like_python_suite_command("python -m stestr run")
    assert is_full_python_suite_command("cd /app && python -m stestr run")
    assert not is_full_python_suite_command(
        "python -m stestr run tests.unit.core.test_nosec_directives"
    )

    task = (
        "Add nosec-begin/end/next-line directives. nosec region nosec metrics "
        "nosec selector parsing for nosec suppression."
    )
    assert not stestr_command_matches_task_scope(task, "python -m stestr run")
    assert stestr_command_matches_task_scope(
        task, "python -m stestr run tests.unit.core.test_nosec_directives"
    )
    assert not python_suite_command_matches_task_scope(task, "python -m stestr run")
    assert not verify_command_qualifies_for_completion(
        "python -m stestr run",
        native_mutated=False,
        python_mutated=True,
        success=True,
        user_text=task,
    )
    assert verify_command_qualifies_for_completion(
        "python -m stestr run tests.unit.core.test_nosec_directives",
        native_mutated=False,
        python_mutated=True,
        success=True,
        user_text=task,
    )


def test_stestr_rejects_agent_authored_target_from_bash() -> None:
    from openjiuwen_icode.features.implement_gate import (
        verify_command_qualifies_for_completion,
        verify_command_targets_agent_authored_tests,
    )

    agent_tests = frozenset({"test_nosec_directives.py", "nosec_directives"})
    cmd = "python -m stestr run tests.unit.core.test_nosec_directives"
    assert verify_command_targets_agent_authored_tests(cmd, agent_tests)
    assert not verify_command_qualifies_for_completion(
        cmd,
        native_mutated=False,
        python_mutated=True,
        success=True,
        user_text="Add nosec-begin/end/next-line directives.",
        agent_created_test_names=agent_tests,
    )


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
    assert looks_like_explore_bash("npx tsc --noEmit")
    assert looks_like_explore_bash("npm run build")
    assert not looks_like_explore_bash("cargo check -p ruff")
    assert not looks_like_explore_bash("git status")


def test_mutation_args_under_workspace(tmp_path: Path) -> None:
    from openjiuwen_icode.features.implement_gate import (
        mutation_args_under_workspace,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    inside = ws / "src" / "errors.ts"
    inside.parent.mkdir(parents=True)
    outside = tmp_path / "errors.ts"

    assert mutation_args_under_workspace({"path": str(inside)}, ws)
    assert mutation_args_under_workspace({"path": "src/errors.ts"}, ws)
    assert not mutation_args_under_workspace({"path": str(outside)}, ws)


def test_go_command_matches_task_scope() -> None:
    from openjiuwen_icode.features.implement_gate import (
        go_command_matches_task_scope,
    )

    task = (
        "Add support for default argument values written as `name = expression`. "
        "When a call omits trailing arguments, assign default values. "
        "Invalid declarations should use `invalid default argument declaration`."
    )
    assert go_command_matches_task_scope(task, "go test ./... -count=1")
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
    assert go_command_matches_task_scope(task, "go test ./...")
    assert (
        verify_command_qualifies_for_completion(
            "go test ./...",
            native_mutated=False,
            go_mutated=True,
            success=True,
            user_text=task,
        )
        is True
    )
    assert not go_command_matches_task_scope(task, "go test -count=1")
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


def test_go_scope_rejects_agent_authored_html_tests() -> None:
    from openjiuwen_icode.features.implement_gate import (
        GO_SUITE_NUDGE,
        is_full_go_suite_command,
        go_command_matches_task_scope,
        verify_command_targets_agent_authored_tests,
    )

    task = (
        "Dasel should support HTML documents as a format named html. "
        "Documents normalize to include head and body. The writer escapes "
        "entities with named entities like &quot;. html html html."
    )
    agent_tests = frozenset(
        {"html_test.go", "html", "parsing/html"}
    )
    pkg_cmd = "go test ./parsing/html/ -count=1"
    suite_cmd = "go clean -testcache && go test ./... -count=1"
    assert verify_command_targets_agent_authored_tests(pkg_cmd, agent_tests)
    assert not verify_command_targets_agent_authored_tests(suite_cmd, agent_tests)
    assert is_full_go_suite_command(suite_cmd)
    assert not is_full_go_suite_command(
        "go test ./... -run XXXNoMatchXXX -count=1"
    )
    assert not is_full_go_suite_command(
        "go test ./... -skip TestNetwork -count=1"
    )
    assert not is_full_go_suite_command(
        "go build ./... && go test ./parsing/html -run HTML -count=1"
    )
    assert not is_full_go_suite_command(pkg_cmd)
    assert go_command_matches_task_scope(task, suite_cmd)
    assert go_command_matches_task_scope(task, pkg_cmd)
    assert not verify_command_qualifies_for_completion(
        "go test ./... -skip TestNetwork -count=1",
        native_mutated=False,
        go_mutated=True,
        success=True,
        user_text="",
    )
    assert not verify_command_qualifies_for_completion(
        pkg_cmd,
        native_mutated=False,
        go_mutated=True,
        success=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    assert verify_command_qualifies_for_completion(
        suite_cmd,
        native_mutated=False,
        go_mutated=True,
        success=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    assert (
        next_implement_continuation(
            user_text=task,
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
    assert (
        next_implement_continuation(
            user_text=task,
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


def test_next_implement_continuation_chain() -> None:
    from openjiuwen_icode.features.implement_gate import (
        zero_mutation_continuation_nudge,
    )

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
        == zero_mutation_continuation_nudge(text)
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
        wrap_headless_implement_prompt,
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
    enveloped = wrap_headless_implement_prompt(text)
    assert extract_required_prompt_symbols(enveloped) == symbols
    assert "list_files" not in extract_required_prompt_symbols(enveloped)
    assert "edit_file" not in extract_required_prompt_symbols(enveloped)
    assert "exit" not in extract_required_prompt_symbols(enveloped)

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
    assert pytest_command_matches_task_scope(
        task, "pytest -q -k snapshot"
    )


def test_full_aiomonitor_instruction_rejects_p2p_pytest() -> None:
    """DeepSWE snapshot prompt must not treat test_monitor.py as verification."""
    task = (
        "aiomonitor lacks the ability to capture and compare task state "
        "over time.\n\n"
        "Add snapshots to Monitor freezing running and terminated task "
        "state. IDs auto-increment from 1 with optional name. "
        "Monitor/start_monitor accept max_snapshots (default 10), "
        "evicting oldest unnamed first, preserving named. Diff by task "
        "object ID reports added, removed, common task items.\n\n"
        "Monitor methods: capture_snapshot (async, optional name, "
        "returns ID), list_snapshots, get_snapshot, delete_snapshot, "
        "format_snapshot_task_list, format_snapshot_diff.\n\n"
        "---\n"
        "Execution rules for this DeepSWE eval:\n"
        "5. After edits, discover and run this repo's real checks via "
        "`bash` until they pass (Python: `pytest` on relevant tests).\n"
    )
    assert not pytest_command_matches_task_scope(task, "pytest -q")
    assert not pytest_command_matches_task_scope(
        task, "pytest -q tests/test_monitor.py"
    )
    assert pytest_command_matches_task_scope(
        task, "pytest -q tests/test_snapshot.py"
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


def test_eval_execution_rules_are_not_required_prompt_symbols() -> None:
    from openjiuwen_icode.features.implement_gate import missing_prompt_symbols

    task = (
        "Implement grid_template_rows().\n\n"
        "---\n"
        "Execution rules for this DeepSWE eval:\n"
        "1. Work only in the repository under evaluation.\n"
        "2. Prefer `edit_file` and run checks with `bash`.\n"
    )

    assert extract_required_prompt_symbols(task) == ("grid_template_rows",)
    assert missing_prompt_symbols(
        user_text=task,
        mutation_blob="def grid_template_rows(): ...",
    ) == ()


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
    assert (
        verify_command_qualifies_for_completion(
            "pytest -q tests/test_snapshot.py",
            native_mutated=False,
            python_mutated=True,
            success=True,
            user_text="",
        )
        is False
    )


def test_python_scope_rejects_agent_authored_cache_tests() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_python_suite_command,
        python_cli_integration_verify_matches,
        verify_command_targets_agent_authored_tests,
    )

    task = (
        "CLI must support --incremental/--no-incremental, --cache-dir, "
        "--cache-size-limit, --warm-cache, and --cache-stats. "
        "JSON metrics output must include cache_hits and cache_misses. "
        "incremental_analysis.enabled must be read from config."
    )
    agent_tests = frozenset({"test_cache.py", "test_cache"})
    cmd = "python -m pytest tests/unit/core/test_cache.py -v"
    assert verify_command_targets_agent_authored_tests(cmd, agent_tests)
    assert not is_full_python_suite_command(cmd)
    assert not verify_command_qualifies_for_completion(
        cmd,
        native_mutated=False,
        python_mutated=True,
        success=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    suite_cmd = "python -m pytest tests/ -q"
    assert is_full_python_suite_command(suite_cmd)
    assert not verify_command_targets_agent_authored_tests(
        suite_cmd, agent_tests
    )
    assert not python_cli_integration_verify_matches(
        task, "python -m pytest tests/unit/ -q"
    )
    assert python_cli_integration_verify_matches(
        task, "python -m pytest tests/functional/ -q"
    )
    assert python_cli_integration_verify_matches(
        task, "python -m bandit --incremental --cache-dir /tmp/c issue.py"
    )


def test_nested_pytest_path_matches_task_scope() -> None:
    task = (
        "Add incremental cache with cache_hits and cache_misses metrics. "
        "incremental incremental incremental."
    )
    assert pytest_command_matches_task_scope(
        task, "pytest tests/functional/test_incremental_cli.py"
    )
    assert not pytest_command_matches_task_scope(
        task, "pytest tests/unit/core/test_util.py"
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


def test_typescript_scope_rejects_agent_only_initialize_tests() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_typescript_suite_command,
        typescript_command_matches_task_scope,
        verify_command_qualifies_for_completion,
        verify_command_targets_agent_authored_tests,
    )

    task = (
        "Add support for asynchronous initialization of container registrations "
        "with automatic dependency-aware startup ordering.\n\n"
        "Call container.initialize({ concurrency: 5 })."
    )
    agent_tests = frozenset(
        {"container.initialize.test.ts", "container.initialize"}
    )
    assert verify_command_targets_agent_authored_tests(
        "npx jest src/__tests__/container.initialize.test.ts", agent_tests
    )
    assert verify_command_targets_agent_authored_tests(
        "npx jest container.initialize", agent_tests
    )
    assert not verify_command_targets_agent_authored_tests(
        "npm test -- --runInBand", agent_tests
    )
    assert is_full_typescript_suite_command("npm test -- --runInBand")
    assert typescript_command_matches_task_scope(task, "npm test -- --runInBand")
    assert not verify_command_qualifies_for_completion(
        "npx jest src/__tests__/container.initialize.test.ts",
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
    )
    assert verify_command_qualifies_for_completion(
        "npm test -- --runInBand",
        native_mutated=False,
        success=True,
        typescript_mutated=True,
        user_text=task,
        agent_created_test_names=agent_tests,
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


def test_zero_mutation_nudge_lists_task_apis() -> None:
    from openjiuwen_icode.features.implement_gate import (
        zero_mutation_continuation_nudge,
    )

    task = (
        "Add support for async init. "
        "Use container.initialize() and .initializer() on registrations. "
        "Throw AwilixNotInitializedError when unresolved."
    )
    nudge = zero_mutation_continuation_nudge(task)
    assert "edit_file" in nudge
    assert "initialize" in nudge
    assert "initializer" in nudge


def test_verify_rejected_without_workspace_changes() -> None:
    assert (
        verify_command_qualifies_for_completion(
            "npm test -- async-initialization",
            native_mutated=False,
            typescript_mutated=True,
            success=True,
            workspace_mutated=False,
        )
        is False
    )


def test_chat_only_nudge_and_greeting_detection() -> None:
    from openjiuwen_icode.features.implement_gate import (
        CHAT_ONLY_NUDGE,
        chat_only_continuation_nudge,
        looks_like_greeting_response,
        wrap_headless_implement_prompt,
        zero_mutation_continuation_nudge,
    )

    greeting = (
        "I'm **iCode**, your AI coding agent.\n\n"
        "What would you like me to work on?"
    )
    assert looks_like_greeting_response(greeting)
    assert looks_like_greeting_response(
        "It looks like the message contains the system configuration and "
        "guidelines rather than a specific task."
    )
    assert not looks_like_greeting_response(
        "I'll edit src/foo.ts to add the flag."
    )
    assert is_headless_continuation_nudge(CHAT_ONLY_NUDGE)
    assert "system configuration" in CHAT_ONLY_NUDGE.lower()

    task = (
        "Add a Content rule Link Style.\n\n"
        "## Configuration\n\n- linkStyle: wiki\n"
    )
    enveloped = wrap_headless_implement_prompt(task)
    assert enveloped.lstrip().startswith("# Implement this task now")
    assert "## Configuration" in enveloped
    assert wrap_headless_implement_prompt(enveloped) == enveloped

    chat = zero_mutation_continuation_nudge(task, any_tool_attempted=False)
    assert chat.startswith(CHAT_ONLY_NUDGE[:40])
    assert "NOT claim there is no task" in chat or "was wrong" in chat

    explored = zero_mutation_continuation_nudge(task, any_tool_attempted=True)
    from openjiuwen_icode.features.implement_gate import EDIT_ONLY_NUDGE

    assert explored.startswith(EDIT_ONLY_NUDGE[:40])
    assert "STOP using" in explored
    assert chat != explored

    assert (
        next_implement_continuation(
            user_text=task,
            mutate_attempted=False,
            verify_attempted=False,
            verify_succeeded=False,
            submit_attempted=False,
            shallow_only=True,
            any_tool_attempted=False,
        )
        == chat_only_continuation_nudge(task)
    )

    from openjiuwen_icode.features.implement_gate import RESUME_AFTER_CHAT_NUDGE

    resume = chat_only_continuation_nudge(task, any_tool_attempted=True)
    assert resume.startswith(RESUME_AFTER_CHAT_NUDGE[:40])
    assert is_headless_continuation_nudge(RESUME_AFTER_CHAT_NUDGE)


def test_fatal_provider_error_detection() -> None:
    from openjiuwen_icode.features.implement_gate import is_fatal_provider_error

    assert is_fatal_provider_error(
        "openAI API async stream error: APIError: insufficient balance — deposit USDC"
    )
    assert is_fatal_provider_error("Invalid API key provided")
    assert not is_fatal_provider_error("File name too long")
    assert not is_fatal_provider_error("connection reset")


def test_broken_tool_history_error_detection() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_broken_tool_history_error,
    )

    assert is_broken_tool_history_error(
        "An assistant message with 'tool_calls' must be followed by tool "
        "messages responding to each 'tool_call_id' "
        "(insufficient tool messages following tool_calls message)"
    )
    assert is_broken_tool_history_error(
        "Tool message has an invalid tool_call_id for the assistant message"
    )
    assert not is_broken_tool_history_error("Tool execution error: bad path")
    assert not is_broken_tool_history_error("connection reset")


BANDIT_CLI_TASK = (
    "CLI must support --incremental/--no-incremental, --cache-dir, "
    "--cache-size-limit. --cache-summary prints \"Cached files: N\". "
    "CLI must support --warm-cache to pre-populate cache without reporting "
    "issues (exit 0, results empty). JSON output must include cache_info."
)


def test_cli_contract_pending_for_bandit_like_task() -> None:
    from openjiuwen_icode.features.implement_gate import (
        cli_contract_pending_items,
        cli_flag_dense_task,
        mentions_empty_results_formatter_contract,
    )

    assert cli_flag_dense_task(BANDIT_CLI_TASK)
    assert mentions_empty_results_formatter_contract(BANDIT_CLI_TASK)
    pending = cli_contract_pending_items(BANDIT_CLI_TASK, ())
    assert any("Live CLI smoke" in line for line in pending)
    assert any("results empty" in line.lower() or "without reporting" in line.lower()
               for line in pending)
    assert any("Cached files" in line for line in pending)


def test_cli_contract_satisfied_after_targeted_smokes() -> None:
    from openjiuwen_icode.features.implement_gate import (
        cli_contract_nudge,
        cli_contract_pending_items,
        cli_contract_satisfied,
        next_implement_continuation,
    )

    smokes = (
        "python -m bandit --incremental --cache-dir /tmp/c issue.py",
        "python -m bandit --no-incremental --cache-dir /tmp/c issue.py",
        "python -m bandit --cache-dir /tmp/c --cache-size-limit 10 issue.py",
        "python -m bandit --cache-summary --cache-dir /tmp/c",
        "python -m bandit --warm-cache --cache-dir /tmp/c -f json issue.py",
        "python -m bandit --cache-stats --cache-dir /tmp/c",
    )
    assert cli_contract_satisfied(BANDIT_CLI_TASK, smokes)
    assert cli_contract_pending_items(BANDIT_CLI_TASK, smokes) == ()
    nudge = next_implement_continuation(
        user_text=BANDIT_CLI_TASK,
        mutate_attempted=True,
        verify_attempted=True,
        verify_succeeded=True,
        submit_attempted=False,
        shallow_only=False,
        bash_commands=smokes,
    )
    assert nudge is None
    partial = cli_contract_nudge(
        BANDIT_CLI_TASK,
        ("python -m pytest tests/unit/core/test_cache.py -q",),
    )
    assert "STOP re-running the full suite" in partial


def test_suite_verify_redundant_switches_to_cli_contract() -> None:
    from openjiuwen_icode.features.implement_gate import (
        CLI_CONTRACT_NUDGE_PREFIX,
        next_implement_continuation,
        suite_verify_continuation_redundant,
    )

    assert suite_verify_continuation_redundant(
        verify_succeeded=True,
        python_suite_verified=True,
        go_suite_verified=False,
        typescript_suite_verified=False,
        suite_verify_without_mutation=2,
    )
    nudge = next_implement_continuation(
        user_text=BANDIT_CLI_TASK,
        mutate_attempted=True,
        verify_attempted=True,
        verify_succeeded=True,
        submit_attempted=False,
        shallow_only=False,
        python_mutated=True,
        python_suite_verified=True,
        bash_commands=("python -m stestr run",),
        suite_verify_without_mutation=3,
    )
    assert nudge is not None
    assert nudge.startswith(CLI_CONTRACT_NUDGE_PREFIX[:40])


def test_headless_envelope_includes_formatter_semantics() -> None:
    from openjiuwen_icode.features.implement_gate import wrap_headless_implement_prompt

    wrapped = wrap_headless_implement_prompt(BANDIT_CLI_TASK)
    assert "empty `results`" in wrapped or "empty `results` list" in wrapped
    assert "sys.exit(0)" in wrapped


EFFECT_SSE_TASK = open(
    "/data/deepswe/repo/tasks/effect-sse-httpapi-streaming/instruction.md"
).read()


def test_vitest_piped_command_counts_as_verify() -> None:
    from openjiuwen_icode.features.implement_gate import (
        bash_command_verify_subject,
        looks_like_verify_command,
        verify_command_qualifies_for_completion,
    )

    cmd = (
        "cd /app && npx vitest run --project @effect/platform 2>&1 | tail -30"
    )
    assert "vitest" in bash_command_verify_subject(cmd)
    assert looks_like_verify_command(cmd)
    assert not verify_command_qualifies_for_completion(
        cmd,
        native_mutated=False,
        typescript_mutated=True,
        success=True,
        user_text=EFFECT_SSE_TASK,
        agent_created_test_names=frozenset({"HttpApiSSE.test.ts"}),
    )


def test_effect_sse_rejects_agent_test_and_accepts_consumer_suite() -> None:
    from openjiuwen_icode.features.implement_gate import (
        is_full_typescript_suite_command,
        post_verify_contract_pending_items,
        typescript_monorepo_integration_verify_matches,
        typescript_wrong_package_only,
        verify_command_qualifies_for_completion,
    )

    wrong = "npx vitest run --project @effect/platform test/HttpApiSSE.test.ts"
    agent_only = (
        "npx vitest run --project @effect/platform-node test/HttpApiSSE.test.ts"
    )
    consumer_suite = "npx vitest run --project @effect/platform-node"
    agent_tests = frozenset({"HttpApiSSE.test.ts", "httpapisse.test.ts"})

    assert typescript_wrong_package_only(wrong, EFFECT_SSE_TASK)
    assert not typescript_monorepo_integration_verify_matches(
        EFFECT_SSE_TASK, wrong
    )
    assert typescript_monorepo_integration_verify_matches(
        EFFECT_SSE_TASK, agent_only
    )
    assert typescript_monorepo_integration_verify_matches(
        EFFECT_SSE_TASK, consumer_suite
    )
    assert not is_full_typescript_suite_command(agent_only)
    assert is_full_typescript_suite_command(consumer_suite)
    assert not verify_command_qualifies_for_completion(
        wrong,
        native_mutated=False,
        typescript_mutated=True,
        success=True,
        user_text=EFFECT_SSE_TASK,
        agent_created_test_names=agent_tests,
    )
    assert not verify_command_qualifies_for_completion(
        agent_only,
        native_mutated=False,
        typescript_mutated=True,
        success=True,
        user_text=EFFECT_SSE_TASK,
        agent_created_test_names=agent_tests,
    )
    assert verify_command_qualifies_for_completion(
        consumer_suite,
        native_mutated=False,
        typescript_mutated=True,
        success=True,
        user_text=EFFECT_SSE_TASK,
        agent_created_test_names=agent_tests,
    )
    pending = post_verify_contract_pending_items(EFFECT_SSE_TASK, (wrong,))
    assert any("platform-node" in line for line in pending)
    assert (
        post_verify_contract_pending_items(EFFECT_SSE_TASK, (consumer_suite,))
        == ()
    )


def test_wire_format_contract_pending_for_effect_sse() -> None:
    from openjiuwen_icode.features.implement_gate import (
        wire_format_contract_pending_items,
        wire_format_contract_task,
    )

    assert wire_format_contract_task(EFFECT_SSE_TASK)
    pending = wire_format_contract_pending_items(EFFECT_SSE_TASK, ())
    assert any("data:" in line for line in pending)
    assert any("text/event-stream" in line.lower() or "toResponse" in line for line in pending)

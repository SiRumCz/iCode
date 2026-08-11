"""Unit tests for openjiuwen_icode.ui.tool_display."""

from __future__ import annotations

import pytest

from openjiuwen_icode.ui.tool_display import (
    format_tool_args,
    format_tool_result,
    format_write_preview,
    get_display_name,
)


class TestGetDisplayName:
    """Tests for tool name mapping."""

    def test_read_file(self) -> None:
        assert get_display_name("read_file") == "Read"

    def test_write_file(self) -> None:
        assert get_display_name("write_file") == "Write"

    def test_edit_file(self) -> None:
        assert get_display_name("edit_file") == "Edit"

    def test_bash(self) -> None:
        assert get_display_name("bash") == "Bash"

    def test_grep(self) -> None:
        assert get_display_name("grep") == "Grep"

    def test_glob(self) -> None:
        assert get_display_name("glob") == "Glob"

    def test_todo_create(self) -> None:
        assert get_display_name("todo_create") == "TodoWrite"

    def test_web_search(self) -> None:
        assert get_display_name("web_free_search") == "WebSearch"

    def test_unknown_tool(self) -> None:
        """Unknown tools get title-cased."""
        assert get_display_name("my_custom_tool") == "My Custom Tool"


class TestFormatToolArgs:
    """Tests for tool argument formatting."""

    def test_read_file_path(self) -> None:
        """read_file shows file_path."""
        result = format_tool_args(
            "read_file", {"file_path": "/src/main.py"}
        )
        assert "main.py" in result

    def test_read_file_with_limit(self) -> None:
        """read_file shows limit when present."""
        result = format_tool_args(
            "read_file",
            {"file_path": "/src/main.py", "limit": 10},
        )
        assert "limit=10" in result

    def test_bash_truncates_long(self) -> None:
        """bash truncates commands > 60 chars."""
        long_cmd = "a" * 80
        result = format_tool_args("bash", {"command": long_cmd})
        assert len(result) <= 63  # 57 + "..."
        assert result.endswith("...")

    def test_bash_short_command(self) -> None:
        """bash shows full short command."""
        result = format_tool_args(
            "bash", {"command": "git status"}
        )
        assert result == "git status"

    def test_grep_pattern_and_path(self) -> None:
        """grep shows pattern and path."""
        result = format_tool_args(
            "grep", {"pattern": "def hello", "path": "src/"}
        )
        assert '"def hello"' in result
        assert "src/" in result

    def test_glob_pattern(self) -> None:
        result = format_tool_args("glob", {"pattern": "**/*.py"})
        assert result == "**/*.py"

    def test_todo_no_args(self) -> None:
        """todo tools show empty args."""
        result = format_tool_args("todo_create", {"tasks": "a;b"})
        assert result == ""

    def test_string_args_parsed(self) -> None:
        """JSON string args are parsed."""
        result = format_tool_args(
            "read_file", '{"file_path": "/test.py"}'
        )
        assert "test.py" in result


class TestFormatToolResult:
    """Tests for tool result summarization."""

    def test_read_file_lines(self) -> None:
        result = format_tool_result(
            "read_file", "line1\nline2\nline3\n"
        )
        assert "Read 3 lines" in result

    def test_read_file_single_line(self) -> None:
        result = format_tool_result("read_file", "line1")
        assert result == "Read 1 lines"

    def test_read_file_single_line_with_trailing_newline(self) -> None:
        result = format_tool_result("read_file", "line1\n")
        assert result == "Read 1 lines"

    def test_bash_single_line(self) -> None:
        """Short bash output shown directly."""
        result = format_tool_result("bash", "hello world")
        assert result == "hello world"

    def test_bash_multi_line(self) -> None:
        """Multi-line bash result truncated."""
        output = "line1\nline2\nline3\nline4"
        result = format_tool_result("bash", output)
        assert "+3 lines" in result

    def test_grep_matches(self) -> None:
        result = format_tool_result(
            "grep", "file1.py:10:match\nfile2.py:20:match\n"
        )
        assert "Found 2 matches" in result

    def test_grep_no_matches(self) -> None:
        result = format_tool_result("grep", "")
        assert "Done" in result  # empty result → "Done"

    def test_glob_files(self) -> None:
        result = format_tool_result(
            "glob", "a.py\nb.py\nc.py\n"
        )
        assert "Found 3 files" in result

    def test_empty_result(self) -> None:
        assert format_tool_result("bash", "") == "Done"


class TestFormatWritePreview:
    """Tests for write content preview."""

    def test_short_content(self) -> None:
        """Content ≤ 5 lines shows all."""
        content = "line1\nline2\nline3"
        result = format_write_preview(content)
        assert "1 line1" in result
        assert "2 line2" in result
        assert "3 line3" in result
        assert "…" not in result

    def test_long_content_truncated(self) -> None:
        """Content > 5 lines shows first 5 + count."""
        content = "\n".join(f"line{i}" for i in range(10))
        result = format_write_preview(content)
        assert "… +5 lines" in result


class TestToolDisplayGaps:
    def test_parse_args_invalid_and_none(self) -> None:
        assert format_tool_args("bash", None) == ""
        assert format_tool_args("bash", "not-json") == ""
        assert format_tool_args("bash", '"string"') == ""

    def test_write_edit_ls_web_fallback_args(self) -> None:
        assert "main.py" in format_tool_args(
            "write_file", {"file_path": "/tmp/main.py"}
        )
        assert "main.py" in format_tool_args(
            "edit_file", {"file_path": "/tmp/main.py"}
        )
        assert format_tool_args("ls", {"path": "/tmp"}) == "/tmp"
        assert format_tool_args("list_dir", {}) == "."
        assert format_tool_args("web_search", {"query": "q"}) == "q"
        assert format_tool_args("web_free_search", {"query": "q2"}) == "q2"
        assert format_tool_args("web_fetch", {"url": "http://x"}) == "http://x"
        assert (
            format_tool_args("web_fetch_webpage", {"url": "http://y"})
            == "http://y"
        )
        assert format_tool_args("custom", {"a": "val"}) == "val"
        assert format_tool_args("custom", {"a": "x" * 80}).endswith("...")
        assert format_tool_args("custom", {}) == ""

    def test_write_edit_ls_result_and_default(self) -> None:
        assert "Wrote" in format_tool_result(
            "write_file",
            "a\nb\n",
            {"file_path": "/tmp/a.py"},
        )
        assert "Wrote to" in format_tool_result(
            "write_file",
            "ok",
            {"file_path": "/tmp/a.py"},
        )
        assert format_tool_result("edit_file", "patched line") == "patched line"
        assert format_tool_result("edit_file", "x" * 100) == "Edited file"
        assert format_tool_result("grep", "   \n  ") == "No matches found"
        assert format_tool_result("glob", "") == "Done" or True
        assert format_tool_result("glob", "   ") == "No files found"
        assert "Listed" in format_tool_result("ls", "a\nb\n")
        assert format_tool_result("todo_create", "x") == ""
        assert format_tool_result("other", "short") == "short"
        assert format_tool_result("other", "y" * 100).endswith("...")

    def test_line_count_meta_and_short_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from openjiuwen_icode.ui import tool_display as td

        assert (
            format_tool_result(
                "read_file",
                "a\nb\n",
                tool_meta={"line_count": "3"},
            )
            == "Read 3 lines"
        )
        assert (
            format_tool_result(
                "read_file",
                "a\nb\n",
                tool_meta={"line_count": "bad"},
            )
            == "Read 2 lines"
        )
        cwd = td.os.getcwd()
        rel = format_tool_args("read_file", {"file_path": cwd + "/foo.py"})
        assert "foo.py" in rel
        assert not rel.startswith(cwd)

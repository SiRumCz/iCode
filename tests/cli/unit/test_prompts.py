"""Unit tests for openjiuwen_icode.prompts.builder."""

from __future__ import annotations

from openjiuwen_icode.prompts.builder import build_system_prompt
from openjiuwen_icode.prompts.code_profile import (
    build_code_todo_section,
    is_code_profile,
)


class TestBuildSystemPrompt:
    """Tests for system prompt assembly."""

    def test_contains_environment_section(self) -> None:
        """System prompt contains the environment section."""
        prompt = build_system_prompt(
            cwd="/tmp/test",
            model="gpt-4o",
            provider="OpenAI",
        )
        assert "Environment" in prompt

    def test_contains_cwd(self) -> None:
        """Dynamic section includes the working directory."""
        prompt = build_system_prompt(
            cwd="/my/project/dir",
            model="gpt-4o",
            provider="OpenAI",
        )
        assert "/my/project/dir" in prompt

    def test_contains_model_name(self) -> None:
        """Dynamic section includes the model name."""
        prompt = build_system_prompt(
            cwd="/tmp/test",
            model="qwen-max",
            provider="DashScope",
        )
        assert "qwen-max" in prompt
        assert "DashScope" in prompt

    def test_contains_platform_info(self) -> None:
        """Dynamic section includes platform info."""
        prompt = build_system_prompt(
            cwd="/tmp/test",
            model="gpt-4o",
            provider="OpenAI",
        )
        assert "Platform" in prompt
        assert "Python" in prompt

    def test_contains_date(self) -> None:
        """Dynamic section includes the current date."""
        prompt = build_system_prompt(
            cwd="/tmp/test",
            model="gpt-4o",
            provider="OpenAI",
        )
        assert "Date" in prompt

    def test_code_profile_includes_coding_identity_and_policy(self) -> None:
        """Code profile injects coding identity and edit-first policy."""
        prompt = build_system_prompt(
            cwd="/tmp/test",
            model="gpt-4o",
            provider="OpenAI",
            agent_profile="code",
        )
        assert "iCode" in prompt
        assert "Coding execution policy" in prompt
        assert "edit_file" in prompt
        assert "Do not stop after analysis" in prompt
        assert "authoritative repository metadata" in prompt
        assert "never weaken an expectation" in prompt

    def test_non_code_profile_skips_coding_overlay(self) -> None:
        """Non-code profiles omit coding identity / execution policy."""
        prompt = build_system_prompt(
            cwd="/tmp/test",
            model="gpt-4o",
            provider="OpenAI",
            agent_profile="explore_agent",
        )
        assert "Coding execution policy" not in prompt
        assert "Environment" in prompt


class TestCodeProfileHelpers:
    """Tests for coding-profile helpers."""

    def test_is_code_profile(self) -> None:
        assert is_code_profile("code")
        assert is_code_profile(None)
        assert is_code_profile("  CODE  ")
        assert not is_code_profile("explore_agent")

    def test_code_todo_section_has_overrides(self) -> None:
        section = build_code_todo_section(language="en")
        text = section.render("en")
        assert "Coding-agent task planning overrides" in text
        assert "Inspect" in text
        assert "Implement" in text
        assert "edit_file" in text

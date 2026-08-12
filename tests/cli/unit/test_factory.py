"""Unit tests for vision/audio config fallback in factory."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openjiuwen_icode.agent.config import CLIConfig
from openjiuwen_icode.agent.factory import (
    _filter_none_values,
    _inline_skills_for_rail,
    _load_audio_config,
    _load_cli_content,
    _load_vision_config,
    _script_timeout,
)
from openjiuwen_icode.skills.config import (
    InlineSkillConfig,
    SkillsUserConfig,
)


@pytest.fixture()
def cli_cfg() -> CLIConfig:
    """Minimal CLIConfig with a test API key."""
    return CLIConfig(
        api_key="sk-main-key",
        api_base="https://main.example.com/v1",
    )


class TestLoadVisionConfig:
    """Tests for _load_vision_config()."""

    def test_fallback_to_main_model(
        self,
        cli_cfg: CLIConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Uses main model key when VISION_API_KEY unset."""
        monkeypatch.delenv(
            "VISION_API_KEY", raising=False
        )
        result = _load_vision_config(cli_cfg)
        assert result is not None
        assert result.api_key == "sk-main-key"
        assert (
            result.base_url
            == "https://main.example.com/v1"
        )

    def test_uses_env_when_set(
        self,
        cli_cfg: CLIConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Uses VISION_API_KEY when explicitly set."""
        monkeypatch.setenv(
            "VISION_API_KEY", "sk-vision-key"
        )
        monkeypatch.setenv(
            "VISION_BASE_URL",
            "https://vision.example.com/v1",
        )
        result = _load_vision_config(cli_cfg)
        assert result is not None
        assert result.api_key == "sk-vision-key"
        assert (
            result.base_url
            == "https://vision.example.com/v1"
        )


class TestLoadAudioConfig:
    """Tests for _load_audio_config()."""

    def test_fallback_to_main_model(
        self,
        cli_cfg: CLIConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Uses main model key when AUDIO_API_KEY unset."""
        monkeypatch.delenv(
            "AUDIO_API_KEY", raising=False
        )
        result = _load_audio_config(cli_cfg)
        assert result is not None
        assert result.api_key == "sk-main-key"
        assert (
            result.base_url
            == "https://main.example.com/v1"
        )

    def test_uses_env_when_set(
        self,
        cli_cfg: CLIConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Uses AUDIO_API_KEY when explicitly set."""
        monkeypatch.setenv(
            "AUDIO_API_KEY", "sk-audio-key"
        )
        monkeypatch.setenv(
            "AUDIO_BASE_URL",
            "https://audio.example.com/v1",
        )
        result = _load_audio_config(cli_cfg)
        assert result is not None
        assert result.api_key == "sk-audio-key"
        assert (
            result.base_url
            == "https://audio.example.com/v1"
        )


class TestFilterNoneValues:
    def test_drops_none_keeps_falsey(self) -> None:
        assert _filter_none_values(
            {"a": 1, "b": None, "c": "", "d": 0, "e": False}
        ) == {"a": 1, "c": "", "d": 0, "e": False}

    def test_empty_dict(self) -> None:
        assert _filter_none_values({}) == {}


class TestLoadCliContent:
    def test_loads_existing_identity(self) -> None:
        text = _load_cli_content("en", "IDENTITY.md")
        assert "iCode" in text

    def test_missing_file_returns_empty(self) -> None:
        assert _load_cli_content("en", "DOES_NOT_EXIST.md") == ""

    def test_unknown_language_returns_empty(self) -> None:
        assert _load_cli_content("zz", "IDENTITY.md") == ""


class TestInlineSkillsAndTimeout:
    def test_inline_skills_for_rail_maps_resources(self) -> None:
        cfg = SkillsUserConfig(
            inline=(
                InlineSkillConfig(
                    name="demo",
                    description="d",
                    instructions="do it",
                    resources=(("note.txt", "hi"),),
                ),
            ),
            script_timeout=42,
        )
        with patch(
            "openjiuwen_icode.skills.load_skills_config",
            return_value=cfg,
        ):
            rows = _inline_skills_for_rail()
        assert rows == [
            {
                "name": "demo",
                "description": "d",
                "instructions": "do it",
                "resources": [{"name": "note.txt", "content": "hi"}],
            }
        ]

    def test_script_timeout_reads_config(self) -> None:
        with patch(
            "openjiuwen_icode.skills.load_skills_config",
            return_value=SimpleNamespace(script_timeout=77),
        ):
            assert _script_timeout() == 77

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Unit tests for pure helpers in host.profiles."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from openjiuwen_icode.host import profiles as profiles_mod
from openjiuwen_icode.host.profiles import (
    _looks_like_env_var_name,
    _safe_filename,
    apply_model_to_backend,
    current_model_from_settings,
    get_agent_profile,
    list_agent_profiles,
    list_model_profiles,
    rebuild_backend_agent,
    resolve_profile_api_key,
    save_model_profile,
    switch_agent_profile_in_settings,
    unique_model_profile_id,
)


class TestSafeFilename:
    def test_replaces_unsafe_chars(self) -> None:
        assert _safe_filename("foo/bar baz!") == "foo-bar-baz"

    def test_strips_edge_dots(self) -> None:
        assert _safe_filename("..weird..") == "weird"

    def test_empty_becomes_model(self) -> None:
        assert _safe_filename("") == "model"
        assert _safe_filename("@@@") == "model"


class TestLooksLikeEnvVarName:
    def test_valid_names(self) -> None:
        assert _looks_like_env_var_name("OPENAI_API_KEY") is True
        assert _looks_like_env_var_name("_PRIVATE") is True

    def test_rejects_secrets_and_junk(self) -> None:
        assert _looks_like_env_var_name("sk-abcdef") is False
        assert _looks_like_env_var_name("1BAD") is False
        assert _looks_like_env_var_name("") is False
        assert _looks_like_env_var_name("has space") is False


class TestResolveProfileApiKey:
    def test_literal_api_key(self) -> None:
        assert (
            resolve_profile_api_key({"apiKey": " sk-live "}) == "sk-live"
        )

    def test_literal_api_key_snake(self) -> None:
        assert resolve_profile_api_key({"api_key": "abc"}) == "abc"

    def test_env_var_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MY_TEST_KEY", "from-env")
        assert (
            resolve_profile_api_key({"api_key_env": "MY_TEST_KEY"})
            == "from-env"
        )

    def test_missing_env_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISSING_ICODE_KEY", raising=False)
        assert (
            resolve_profile_api_key({"apiKeyEnv": "MISSING_ICODE_KEY"})
            is None
        )

    def test_mispasted_secret_in_env_field(self) -> None:
        assert (
            resolve_profile_api_key({"api_key_env": "sk-pasted-secret"})
            == "sk-pasted-secret"
        )

    def test_empty_returns_none(self) -> None:
        assert resolve_profile_api_key({}) is None
        assert resolve_profile_api_key({"api_key_env": "  "}) is None


class TestListModelProfilesHelpers:
    def test_skips_invalid_json(
        self, tmp_path: Path
    ) -> None:
        models = tmp_path / "models"
        models.mkdir()
        (models / "bad.json").write_text("{nope", encoding="utf-8")
        (models / "ok.json").write_text(
            json.dumps({"id": "ok", "provider": "OpenAI"}),
            encoding="utf-8",
        )
        (models / "not-obj.json").write_text("[1]", encoding="utf-8")
        rows = list_model_profiles(models_dir=models)
        assert [r["id"] for r in rows] == ["ok"]

    def test_unique_copy_id_increments(
        self, tmp_path: Path
    ) -> None:
        models = tmp_path / "models"
        save_model_profile({"id": "m"}, models_dir=models)
        save_model_profile({"id": "m-copy"}, models_dir=models)
        save_model_profile({"id": "m-copy-2"}, models_dir=models)
        assert unique_model_profile_id("m", models_dir=models) == "m-copy-3"


class TestCurrentModelFromSettings:
    def test_reads_defaults_and_overrides(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{}", encoding="utf-8")
        defaults = current_model_from_settings(path)
        assert defaults["model"] == "gpt-4o"
        assert defaults["provider"] == "OpenAI"
        assert "openai.com" in defaults["apiBase"]

        path.write_text(
            json.dumps(
                {
                    "model": "kimi",
                    "provider": "OpenAI",
                    "api_base": "https://x/v1",
                }
            ),
            encoding="utf-8",
        )
        got = current_model_from_settings(path)
        assert got["model"] == "kimi"
        assert got["apiBase"] == "https://x/v1"


class TestApplyModelToBackend:
    def test_updates_cfg_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        saved: list[dict] = []
        monkeypatch.setattr(
            profiles_mod,
            "save_settings_json",
            lambda data, path=None: saved.append(data),
        )
        cfg = SimpleNamespace(
            model="old",
            provider="OpenAI",
            api_base="",
            api_key="",
            extra_headers={},
            extra_body={},
        )
        backend = SimpleNamespace(cfg=cfg)
        apply_model_to_backend(
            backend,
            {
                "id": "new-model",
                "provider": "OpenAI",
                "apiBase": "https://api.example/v1",
                "apiKey": "sk-xyz",
                "headers": {"X-A": "1"},
                "extra_body": {"temp": 0.2},
            },
        )
        assert cfg.model == "new-model"
        assert cfg.api_base == "https://api.example/v1"
        assert cfg.api_key == "sk-xyz"
        assert cfg.extra_headers == {"X-A": "1"}
        assert cfg.extra_body == {"temp": 0.2}
        assert saved and saved[0]["apiKey"] == "sk-xyz"

    def test_noop_without_cfg(self) -> None:
        apply_model_to_backend(SimpleNamespace(), {"id": "x"})


class TestRebuildBackendAgent:
    @pytest.mark.asyncio
    async def test_sync_rebuild(self) -> None:
        called = {"n": 0}

        def rebuild() -> None:
            called["n"] += 1

        backend = SimpleNamespace(rebuild=rebuild)
        assert await rebuild_backend_agent(backend) is True
        assert called["n"] == 1

    @pytest.mark.asyncio
    async def test_async_rebuild(self) -> None:
        async def rebuild() -> None:
            return None

        backend = SimpleNamespace(rebuild=rebuild)
        assert await rebuild_backend_agent(backend) is True

    @pytest.mark.asyncio
    async def test_missing_rebuild(self) -> None:
        assert await rebuild_backend_agent(SimpleNamespace()) is False


class TestAgentProfiles:
    def test_builtin_get(self) -> None:
        row = get_agent_profile("explore_agent")
        assert row is not None
        assert "Explore" in row["label"]

    def test_missing_returns_none(self) -> None:
        assert get_agent_profile("no-such-profile-xyz") is None

    def test_lists_user_yaml_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "custom.json").write_text(
            json.dumps({"id": "custom", "label": "Custom"}),
            encoding="utf-8",
        )
        (agents / "from-yaml.yaml").write_text(
            yaml.safe_dump({"label": "YAML agent"}),
            encoding="utf-8",
        )
        (agents / "bad.json").write_text("{", encoding="utf-8")
        monkeypatch.setattr(profiles_mod, "AGENTS_DIR", agents)
        rows = list_agent_profiles()
        ids = {r["id"] for r in rows}
        assert "code" in ids
        assert "custom" in ids
        assert "from-yaml" in ids

    def test_switch_agent_requires_id(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="required"):
            switch_agent_profile_in_settings("  ", path=tmp_path / "s.json")

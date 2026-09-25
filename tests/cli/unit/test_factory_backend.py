# coding: utf-8
"""Unit tests for factory helpers, create_agent wiring, and LocalBackend."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openjiuwen_icode.agent.config import CLIConfig
from openjiuwen_icode.agent.factory import (
    LocalBackend,
    _build_cli_workspace,
    _build_memory_rail,
    _build_subagents,
    _default_skill_dirs,
    _load_mcp_configs,
    create_agent,
    create_backend,
)
from openjiuwen_icode.skills.config import SkillsUserConfig


@pytest.fixture()
def cli_cfg(tmp_path: Path) -> CLIConfig:
    return CLIConfig(
        api_key="sk-test",
        api_base="https://api.example.com/v1",
        workspace=str(tmp_path / "ws"),
        cwd=str(tmp_path),
        model="demo-model",
        provider="OpenAI",
    )


class TestDefaultSkillDirs:
    def test_delegates_to_skills_helpers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = SkillsUserConfig(
            paths=(str(tmp_path / "extra"),),
            auto_load_chrys_skills=False,
            auto_load_user_agents_skills=False,
            auto_load_cwd_agents_skills=False,
        )
        monkeypatch.setattr(
            "openjiuwen_icode.skills.load_skills_config",
            lambda: cfg,
        )
        with patch(
            "openjiuwen_icode.skills.collect_default_skill_dirs",
            return_value=["/a", "/b"],
        ) as collect:
            assert _default_skill_dirs(cwd=str(tmp_path)) == ["/a", "/b"]
        kwargs = collect.call_args.kwargs
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["extra_paths"] == cfg.paths
        assert kwargs["include_chrys"] is False


class TestBuildCliWorkspace:
    def test_sets_identity_when_present(self, cli_cfg: CLIConfig) -> None:
        ws = MagicMock()
        with patch(
            "openjiuwen_icode.agent.factory.Workspace",
            return_value=ws,
        ), patch(
            "openjiuwen_icode.agent.factory._load_cli_content",
            return_value="# Identity",
        ):
            out = _build_cli_workspace(cli_cfg, "en")
        assert out is ws
        ws.set_directory.assert_called_once()
        arg = ws.set_directory.call_args[0][0]
        assert arg["name"] == "IDENTITY.md"
        assert arg["default_content"] == "# Identity"

    def test_skips_identity_when_empty(self, cli_cfg: CLIConfig) -> None:
        ws = MagicMock()
        with patch(
            "openjiuwen_icode.agent.factory.Workspace",
            return_value=ws,
        ), patch(
            "openjiuwen_icode.agent.factory._load_cli_content",
            return_value="",
        ):
            _build_cli_workspace(cli_cfg, "en")
        ws.set_directory.assert_not_called()


class TestBuildMemoryRail:
    def test_returns_none_on_exception(self, cli_cfg: CLIConfig) -> None:
        with patch(
            "openjiuwen.core.memory.lite.embeddings.resolve_embedding_config_from_env",
            side_effect=RuntimeError("boom"),
        ):
            assert _build_memory_rail(cli_cfg) is None

    def test_returns_none_when_embedding_absent(
        self, cli_cfg: CLIConfig
    ) -> None:
        with patch(
            "openjiuwen.core.foundation.store.base_embedding.EmbeddingConfig",
        ), patch(
            "openjiuwen.core.memory.lite.embeddings.resolve_embedding_config_from_env",
            return_value=None,
        ), patch(
            "openjiuwen.harness.rails.memory.memory_rail.MemoryRail",
        ):
            assert _build_memory_rail(cli_cfg) is None

    def test_builds_rail(self, cli_cfg: CLIConfig) -> None:
        rail = object()
        with patch(
            "openjiuwen.core.foundation.store.base_embedding.EmbeddingConfig",
        ), patch(
            "openjiuwen.core.memory.lite.embeddings.resolve_embedding_config_from_env",
            return_value=object(),
        ), patch(
            "openjiuwen.harness.rails.memory.memory_rail.MemoryRail",
            return_value=rail,
        ):
            assert _build_memory_rail(cli_cfg) is rail


class TestBuildSubagents:
    def test_respects_merged_opts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENJIUWEN_CLI_RESEARCH_SUBAGENT", "1")
        model = object()
        with patch(
            "openjiuwen_icode.agent.profile_loader.merged_cli_subagent_options",
            return_value={
                "include_browser": False,
                "include_research": False,
                "roster_names": ["code_agent"],
            },
        ), patch(
            "openjiuwen_icode.subagents.build_cli_subagents",
            return_value=["sub"],
        ) as build:
            out = _build_subagents(model)
        assert out == ["sub"]
        build.assert_called_once_with(
            model,
            language="en",
            include_browser=False,
            include_research=False,
            roster_names=["code_agent"],
        )

    def test_env_research_when_opts_omit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENJIUWEN_CLI_RESEARCH_SUBAGENT", "yes")
        with patch(
            "openjiuwen_icode.agent.profile_loader.merged_cli_subagent_options",
            return_value={"include_browser": True},
        ), patch(
            "openjiuwen_icode.subagents.build_cli_subagents",
            return_value=[],
        ) as build:
            _build_subagents(object())
        assert build.call_args.kwargs["include_research"] is True


class TestLoadMcpConfigs:
    def test_missing_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "openjiuwen_icode.paths.mcp_path",
            lambda: tmp_path / "missing-mcp.json",
        )
        assert _load_mcp_configs() == []

    def test_loads_stdio_server(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        mcp_file = tmp_path / "mcp.json"
        mcp_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "demo": {
                            "transport": "stdio",
                            "command": "npx",
                            "args": ["-y", "pkg"],
                            "env": {"A": "1"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "openjiuwen_icode.paths.mcp_path",
            lambda: mcp_file,
        )
        captured: dict[str, Any] = {}

        class FakeMcpServerConfig:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        with patch(
            "openjiuwen.core.foundation.tool.McpServerConfig",
            FakeMcpServerConfig,
        ), patch(
            "openjiuwen_icode.features.mcp_cache.assign_stable_server_id",
        ) as assign:
            configs = _load_mcp_configs(cwd="/proj")
        assert len(configs) == 1
        assert captured["server_name"] == "demo"
        assert captured["client_type"] == "stdio"
        assert captured["params"]["command"] == "npx"
        assign.assert_called_once()

    def test_invalid_json_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        mcp_file = tmp_path / "mcp.json"
        mcp_file.write_text("{not-json", encoding="utf-8")
        monkeypatch.setattr(
            "openjiuwen_icode.paths.mcp_path",
            lambda: mcp_file,
        )
        assert _load_mcp_configs() == []


def _agent_ns() -> SimpleNamespace:
    return SimpleNamespace(
        deep_config=SimpleNamespace(
            workspace=SimpleNamespace(root_path="")
        ),
        subagent_concurrency=None,
    )


class TestCreateAgent:
    def test_wires_skills_mcp_vision_subagents(
        self, cli_cfg: CLIConfig
    ) -> None:
        agent = _agent_ns()
        captured: dict[str, Any] = {}
        skill_kwargs: dict[str, Any] = {}

        def fake_create(*_a: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return agent

        def fake_skill_call(cls: Any, **kwargs: Any) -> Any:
            skill_kwargs.update(kwargs)
            return MagicMock(name="skill_rail")

        limiter_inst = MagicMock(name="limiter")
        limiter_cls = MagicMock(return_value=limiter_inst)

        with ExitStack() as es:
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.init_model",
                    return_value=object(),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.build_system_prompt",
                    return_value="sys",
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._build_memory_rail",
                    return_value=MagicMock(name="mem"),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._load_mcp_configs",
                    return_value=[MagicMock()],
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._load_vision_config",
                    return_value=SimpleNamespace(kind="vision"),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._load_audio_config",
                    return_value=SimpleNamespace(kind="audio"),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._build_subagents",
                    return_value=["sa"],
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.create_web_tools",
                    return_value=["web"],
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._build_cli_workspace",
                    return_value=MagicMock(name="workspace"),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._default_skill_dirs",
                    return_value=["/skills"],
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._inline_skills_for_rail",
                    return_value=[{"name": "s"}],
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory._script_timeout",
                    return_value=33,
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.call_with_supported_kwargs",
                    side_effect=fake_skill_call,
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.create_deep_agent",
                    side_effect=fake_create,
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.load_concurrency_types",
                    return_value=(None, limiter_cls),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen.harness.rails.context_engineer.ContextProcessorRail",
                    return_value=MagicMock(name="ctx"),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen.harness.rails.context_engineer.ContextAssembleRail",
                    return_value=MagicMock(name="asm"),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.subagents.load_subagent_concurrency_config",
                    return_value=object(),
                )
            )
            out_agent, tracker = create_agent(cli_cfg)

        assert out_agent is agent
        assert tracker is not None
        assert skill_kwargs["skills_dir"] == ["/skills"]
        assert skill_kwargs["inline_skills"] == [{"name": "s"}]
        assert skill_kwargs["script_timeout"] == 33
        assert captured["tools"] == ["web"]
        assert captured["subagents"] == ["sa"]
        assert captured["enable_async_subagent"] is True
        assert "mcps" in captured
        assert "vision_model_config" in captured
        assert "audio_model_config" in captured
        assert agent.deep_config.workspace.root_path == cli_cfg.workspace
        assert agent.subagent_concurrency is limiter_inst

    def test_without_subagents(self, cli_cfg: CLIConfig) -> None:
        agent = _agent_ns()
        captured: dict[str, Any] = {}

        with ExitStack() as es:
            for target, value in (
                ("init_model", object()),
                ("build_system_prompt", "sys"),
                ("_build_memory_rail", None),
                ("_load_mcp_configs", []),
                ("_load_vision_config", None),
                ("_load_audio_config", None),
                ("_build_subagents", []),
                ("create_web_tools", []),
                ("_build_cli_workspace", MagicMock()),
                ("_default_skill_dirs", []),
                ("_inline_skills_for_rail", []),
                ("_script_timeout", 10),
            ):
                es.enter_context(
                    patch(
                        f"openjiuwen_icode.agent.factory.{target}",
                        return_value=value,
                    )
                )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.call_with_supported_kwargs",
                    return_value=MagicMock(),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.create_deep_agent",
                    side_effect=lambda *_a, **kw: (
                        captured.update(kw) or agent
                    ),
                )
            )
            es.enter_context(
                patch(
                    "openjiuwen_icode.agent.factory.load_concurrency_types",
                    return_value=(None, None),
                )
            )
            create_agent(cli_cfg)

        assert captured["subagents"] is None
        assert captured["enable_async_subagent"] is False
        assert "mcps" not in captured


class TestCreateBackend:
    def test_local(self, cli_cfg: CLIConfig) -> None:
        assert isinstance(create_backend(cli_cfg), LocalBackend)

    def test_remote_raises(self, cli_cfg: CLIConfig) -> None:
        cli_cfg.server_url = "https://remote.example"
        with pytest.raises(NotImplementedError, match="RemoteBackend"):
            create_backend(cli_cfg)


class TestLocalBackendMethods:
    @pytest.mark.asyncio
    async def test_start_stop_and_usage(self, cli_cfg: CLIConfig) -> None:
        tracker = MagicMock()
        tracker.get_summary.return_value = {"input_tokens": 1}
        with patch(
            "openjiuwen_icode.agent.factory.create_agent",
            return_value=(MagicMock(), tracker),
        ), patch(
            "openjiuwen_icode.agent.factory.Runner"
        ) as runner:
            runner.start = AsyncMock()
            runner.stop = AsyncMock()
            backend = LocalBackend(cli_cfg)
            await backend.start()
            assert backend.get_usage() == {"input_tokens": 1}
            await backend.stop()
            runner.stop.assert_awaited_once()

    def test_get_usage_without_tracker(self, cli_cfg: CLIConfig) -> None:
        assert LocalBackend(cli_cfg).get_usage() is None

    @pytest.mark.asyncio
    async def test_steer_follow_up_rebuild_abort(
        self, cli_cfg: CLIConfig
    ) -> None:
        backend = LocalBackend(cli_cfg)
        await backend.steer("x")
        await backend.follow_up("y")

        agent = MagicMock()
        agent.steer = AsyncMock()
        agent.follow_up = AsyncMock()
        agent.abort = AsyncMock(side_effect=RuntimeError("boom"))
        backend.agent = agent
        await backend.steer("a")
        await backend.follow_up("b")
        await backend.abort()

        agent.steer = AsyncMock(side_effect=RuntimeError("x"))
        agent.follow_up = AsyncMock(side_effect=RuntimeError("y"))
        await backend.steer("a")
        await backend.follow_up("b")

        with patch(
            "openjiuwen_icode.agent.factory.create_agent",
            return_value=(MagicMock(name="new"), MagicMock()),
        ):
            backend._loaded_extensions.add("old")
            await backend.rebuild()
        assert backend._loaded_extensions == set()

    @pytest.mark.asyncio
    async def test_run_streaming_and_extensions(
        self, cli_cfg: CLIConfig
    ) -> None:
        ws = Path(cli_cfg.workspace)
        ext = ws / "auto_harness" / "runtime_extensions" / "ext1"
        ext.mkdir(parents=True)
        (ext / "harness_config.yaml").write_text("x: 1", encoding="utf-8")
        bare = ws / "auto_harness" / "runtime_extensions" / "bare"
        bare.mkdir()

        chunks = [
            SimpleNamespace(type="llm_output", payload={"content": "hi"})
        ]

        async def _stream(*_a: Any, **_k: Any) -> AsyncIterator[Any]:
            for c in chunks:
                yield c

        agent = MagicMock()
        agent.load_harness_config = AsyncMock(return_value=["tool_a"])
        backend = LocalBackend(cli_cfg)
        backend.agent = agent

        with patch(
            "openjiuwen_icode.agent.factory.Runner"
        ) as runner, patch(
            "openjiuwen_icode.host.workdirs.apply_pending_workdir_cwd",
        ):
            runner.run_agent_streaming = MagicMock(side_effect=_stream)
            out = [
                c async for c in backend.run_streaming("q", session_id="s1")
            ]
        assert len(out) == 1
        assert backend._loaded_extensions

        agent.load_harness_config = AsyncMock(side_effect=RuntimeError("bad"))
        backend._loaded_extensions.clear()
        with patch(
            "openjiuwen_icode.agent.factory.Runner"
        ) as runner, patch(
            "openjiuwen_icode.host.workdirs.apply_pending_workdir_cwd",
        ):
            runner.run_agent_streaming = MagicMock(side_effect=_stream)
            _ = [c async for c in backend.run_streaming("q2")]

    @pytest.mark.asyncio
    async def test_reset_runtime_session_isolates_corrupt_history(
        self, cli_cfg: CLIConfig
    ) -> None:
        sessions: list[str] = []

        async def _stream(
            *_a: Any, session: str, **_k: Any
        ) -> AsyncIterator[Any]:
            sessions.append(session)
            yield SimpleNamespace(type="llm_output", payload={"content": "ok"})

        backend = LocalBackend(cli_cfg)
        backend.agent = MagicMock(abort=AsyncMock())

        with patch(
            "openjiuwen_icode.agent.factory.Runner"
        ) as runner, patch(
            "openjiuwen_icode.host.workdirs.apply_pending_workdir_cwd",
        ), patch(
            "openjiuwen_icode.agent.factory.cancel_in_flight_agent_tasks",
            new=AsyncMock(),
        ):
            runner.run_agent_streaming = MagicMock(side_effect=_stream)
            _ = [c async for c in backend.run_streaming("q1", session_id="s1")]
            recovered = await backend.reset_runtime_session("s1")
            _ = [c async for c in backend.run_streaming("q2", session_id="s1")]

        assert sessions == ["s1", recovered]
        assert recovered.startswith("s1-recovery-")

    @pytest.mark.asyncio
    async def test_load_extensions_noop(
        self, cli_cfg: CLIConfig
    ) -> None:
        backend = LocalBackend(cli_cfg)
        await backend._load_runtime_extensions()

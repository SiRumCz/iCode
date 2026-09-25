"""Agent factory and backend abstraction.

Provides:
- :func:`create_agent` — build a DeepAgent with rails
- :class:`LocalBackend` — direct SDK Runner backend (MVP)
- :func:`create_backend` — backend factory
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol
from uuid import uuid4

from openjiuwen.core.foundation.llm import init_model
from openjiuwen.core.runner import Runner
from openjiuwen.harness import create_deep_agent
from openjiuwen.harness.rails.sys_operation_rail import SysOperationRail
from openjiuwen.harness.tools import (
    create_web_tools,
)
from openjiuwen.harness.workspace.workspace import Workspace

from openjiuwen_icode.agent.config import CLIConfig
from openjiuwen_icode.prompts import build_system_prompt
from openjiuwen_icode.rails import TokenTrackingRail
from openjiuwen_icode.rails.tool_tracker import (
    ToolTrackingRail,
)
from openjiuwen_icode.sdk_compat import (
    call_with_supported_kwargs,
    load_concurrency_types,
)
from openjiuwen_icode.sdk_compat_cancel import (
    cancel_in_flight_agent_tasks,
    patch_cancel_cycle_guards,
    wait_abandon,
)
from openjiuwen.harness.rails import (
    AskUserRail,
    ConfirmInterruptRail,
    SkillUseRail,
)

logger = logging.getLogger(__name__)

# Guard DeepAgent stall/abort cancel against asyncio Task.cancel cycles.
patch_cancel_cycle_guards()

# Prefer iCode-vendored ripgrep before agent-core GrepTool resolves PATH.
try:
    from openjiuwen_icode.vendor.rg_binary import ensure_rg_env

    _rg = ensure_rg_env()
    if _rg:
        logger.debug("using ripgrep at %s", _rg)
except Exception as exc:  # noqa: BLE001
    logger.debug("vendored ripgrep not configured: %s", exc)


# ---------------------------------------------------------------------------
# Default skill directories (priority high → low)
# ---------------------------------------------------------------------------

def _default_skill_dirs(cwd: str | None = None) -> list[str]:
    """Return CLI skill roots (OpenJiuWen + Chrys/Agents compatible)."""
    from openjiuwen_icode.skills import (
        collect_default_skill_dirs,
        load_skills_config,
    )

    cfg = load_skills_config()
    return collect_default_skill_dirs(
        cwd=cwd,
        extra_paths=cfg.paths,
        include_chrys=cfg.auto_load_chrys_skills,
        include_user_agents=cfg.auto_load_user_agents_skills,
        include_cwd_agents=cfg.auto_load_cwd_agents_skills,
    )


def _inline_skills_for_rail() -> list[dict]:
    from openjiuwen_icode.skills import load_skills_config

    cfg = load_skills_config()
    return [
        {
            "name": s.name,
            "description": s.description,
            "instructions": s.instructions,
            "resources": [
                {"name": n, "content": c} for n, c in s.resources
            ],
        }
        for s in cfg.inline
    ]


def _script_timeout() -> int:
    from openjiuwen_icode.skills import load_skills_config

    return load_skills_config().script_timeout


def _get_cli_content_base_dir() -> Path:
    """Get the base directory for CLI-specific workspace content files."""
    return Path(__file__).parent.parent / "prompts" / "workspace_content"


def _load_cli_content(language: str, file_path: str) -> str:
    """Load CLI-specific workspace content.

    Falls back to empty string if the file does not exist.

    Args:
        language: ``'cn'`` or ``'en'``.
        file_path: Relative path inside the content directory
            (e.g. ``"IDENTITY.md"``).

    Returns:
        File content as a string, or ``""`` when missing.
    """
    full_path = _get_cli_content_base_dir() / language / file_path
    if full_path.exists():
        return full_path.read_text(encoding="utf-8")
    return ""


def _build_cli_workspace(cfg: CLIConfig, language: str) -> Workspace:
    """Build a :class:`Workspace` with CLI-specific content overrides.

    Starts from the default schema for *language*, then replaces
    ``IDENTITY.md`` with a pre-defined coding-assistant identity
    (instead of the generic "fill this in yourself" template).

    Args:
        cfg: CLI configuration (provides ``workspace`` root path).
        language: Resolved prompt language (``"en"`` or ``"cn"``).

    Returns:
        A fully-initialised :class:`Workspace` ready for
        ``create_deep_agent``.
    """
    workspace = Workspace(root_path=cfg.workspace, language=language)

    cli_identity = _load_cli_content(language, "IDENTITY.md")
    if cli_identity:
        workspace.set_directory({
            "name": "IDENTITY.md",
            "description": "Identity credentials and permissions",
            "path": "IDENTITY.md",
            "is_file": True,
            "children": [],
            "default_content": cli_identity,
        })

    return workspace


# ---------------------------------------------------------------------------
# MemoryRail and Subagent helpers
# ---------------------------------------------------------------------------


def _build_memory_rail(cfg: CLIConfig) -> Any:
    """Build a :class:`MemoryRail` if embedding config is available.

    Reads embedding settings from environment variables:

    - ``EMBEDDING_MODEL_NAME`` — embedding model name
      (default ``"text-embedding-3-small"``).
    - ``EMBEDDING_BASE_URL`` — embedding API base URL
      (falls back to ``cfg.api_base``).
    - ``EMBEDDING_API_KEY`` — embedding API key
      (falls back to ``cfg.api_key``).

    Returns:
        :class:`MemoryRail` instance, or ``None`` when the
        required dependencies are not importable.
    """
    try:
        from openjiuwen.core.foundation.store.base_embedding import (
            EmbeddingConfig,
        )
        from openjiuwen.core.memory.lite.embeddings import (
            resolve_embedding_config_from_env,
        )
        from openjiuwen.harness.rails.memory.memory_rail import MemoryRail

        embedding_config = resolve_embedding_config_from_env(
            model_name="text-embedding-3-small",
            fallback_base_url=cfg.api_base,
            fallback_api_key=cfg.api_key,
        )
        if embedding_config is None:
            return None
        return MemoryRail(embedding_config=embedding_config)
    except Exception:  # noqa: BLE001
        logger.debug(
            "MemoryRail not available", exc_info=True
        )
        return None


def _build_subagents(
    model: Any,
) -> list[Any]:
    """Build subagent configs for the CLI agent (Chrys Code profile roster)."""
    from openjiuwen_icode.agent.profile_loader import (
        merged_cli_subagent_options,
    )
    from openjiuwen_icode.subagents import build_cli_subagents

    include_research = os.environ.get(
        "OPENJIUWEN_CLI_RESEARCH_SUBAGENT", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    opts = merged_cli_subagent_options()
    if "include_research" in opts:
        include_research = bool(opts["include_research"])
    return build_cli_subagents(
        model,
        language="en",
        include_browser=opts.get("include_browser", True),
        include_research=include_research,
        roster_names=opts.get("roster_names"),
    )


# ---------------------------------------------------------------------------
# MCP config loading
# ---------------------------------------------------------------------------


def _filter_none_values(
    d: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy of *d* with ``None`` values removed."""
    return {k: v for k, v in d.items() if v is not None}


def _load_mcp_configs(cwd: str | None = None) -> List[Any]:
    """Load MCP server configs from ``~/.icode/mcp.json``.

    The file format follows Claude Code conventions::

        {
            "mcpServers": {
                "server-name": {
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@mcp/server"],
                    "env": {}
                }
            }
        }

    Each config gets a stable ``server_id`` from cwd+config hash so
    ToolMgr reuses live connections across agent rebuilds (T-24).

    Returns:
        List of :class:`McpServerConfig` instances, or empty.
    """
    from openjiuwen_icode.features.mcp_cache import (
        assign_stable_server_id,
    )
    from openjiuwen_icode.paths import mcp_path

    mcp_file = mcp_path()
    if not mcp_file.exists():
        return []

    try:
        from openjiuwen.core.foundation.tool import (
            McpServerConfig,
        )

        data = json.loads(mcp_file.read_text())
        servers = data.get("mcpServers", {})
        configs: List[Any] = []
        for name, spec in servers.items():
            transport = spec.get(
                "transport",
                spec.get("client_type", "stdio"),
            )
            config = McpServerConfig(
                server_name=name,
                server_path=spec.get(
                    "url",
                    spec.get("server_path", ""),
                ),
                client_type=transport,
                params=_filter_none_values({
                    "command": spec.get("command"),
                    "args": spec.get("args"),
                    "env": spec.get("env"),
                    "cwd": spec.get("cwd"),
                }),
                auth_headers=spec.get(
                    "auth_headers", {}
                ),
            )
            assign_stable_server_id(config, cwd=cwd)
            configs.append(config)
        return configs
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to load MCP config from %s",
            mcp_path,
            exc_info=True,
        )
        return []


def _load_vision_config(cfg: CLIConfig) -> Any:
    """Load vision model config.

    If ``VISION_API_KEY`` is set, uses
    :meth:`VisionModelConfig.from_env`.  Otherwise falls back
    to the main model's ``api_key`` / ``api_base``.

    Returns:
        :class:`VisionModelConfig` or ``None``.
    """
    try:
        from openjiuwen.harness.schema.config import (
            VisionModelConfig,
        )

        if os.getenv("VISION_API_KEY"):
            return VisionModelConfig.from_env()
        # Fallback: reuse main model credentials
        return VisionModelConfig(
            api_key=cfg.api_key,
            base_url=cfg.api_base,
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to load VisionModelConfig",
            exc_info=True,
        )
        return None


def _load_audio_config(cfg: CLIConfig) -> Any:
    """Load audio model config.

    If ``AUDIO_API_KEY`` is set, uses
    :meth:`AudioModelConfig.from_env`.  Otherwise falls back
    to the main model's ``api_key`` / ``api_base``.

    Returns:
        :class:`AudioModelConfig` or ``None``.
    """
    try:
        from openjiuwen.harness.schema.config import (
            AudioModelConfig,
        )

        if os.getenv("AUDIO_API_KEY"):
            return AudioModelConfig.from_env()
        # Fallback: reuse main model credentials
        return AudioModelConfig(
            api_key=cfg.api_key,
            base_url=cfg.api_base,
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to load AudioModelConfig",
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# AgentBackend protocol
# ---------------------------------------------------------------------------


class AgentBackend(Protocol):
    """Abstraction over local / remote agent execution."""

    async def start(self) -> None:
        """Initialize the backend (start Runner / connect)."""
        ...

    async def stop(self) -> None:
        """Release resources (stop Runner / disconnect)."""
        ...

    async def run_streaming(
        self,
        query: Any,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Any]:
        """Execute *query* and stream OutputSchema chunks."""
        ...

    async def abort(self) -> None:
        """Abort the currently running query."""
        ...

    async def steer(self, msg: str) -> None:
        """Inject a mid-turn steering message (task loop)."""
        ...

    async def follow_up(self, msg: str) -> None:
        """Queue a follow-up message for the task loop."""
        ...

    def get_usage(self) -> Optional[Dict[str, Any]]:
        """Return token-usage summary, or ``None`` if unavailable."""
        ...


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_agent(
    cfg: CLIConfig,
) -> tuple[Any, TokenTrackingRail]:
    """Create a :class:`DeepAgent` and its :class:`TokenTrackingRail`.

    Uses the harness ``SysOperationRail`` to auto-register file system
    tools (BashTool, ReadFileTool, etc.) and ``SecurityRail`` (auto-
    mounted by ``create_deep_agent``).  Web tools are added manually
    since they are not part of ``SysOperationRail``.

    Also integrates:
    - ``ToolTrackingRail`` — emits tool call/result chunks
    - ``AskUserRail`` — interrupt flow for asking the user
    - ``ConfirmInterruptRail`` — human-approval for write/edit
    - ``ContextEngineeringRail`` — context window management
      (includes ``DialogueCompressor`` for ``/compact`` support)
    - ``MemoryRail`` — vector-memory tools (when embedding
      config is available)
    - ``SessionRail`` — async subagent spawning (auto-injected
      when subagents are present)
    - Subagents — ``code_agent``, ``research_agent``,
      ``browser_agent``
    - MCP servers — from ``~/.icode/mcp.json``
    - Vision/Audio — conditional on environment variables

    Args:
        cfg: CLI configuration.

    Returns:
        ``(agent, tracker)`` tuple.
    """
    from openjiuwen_icode.agent.reasoning import (
        merge_request_kwargs,
        preferred_provider_for_api_base,
    )

    provider = cfg.provider
    preferred = preferred_provider_for_api_base(
        cfg.api_base, current=provider
    )
    if preferred:
        provider = preferred

    request_kwargs = merge_request_kwargs(
        api_base=cfg.api_base,
        reasoning_effort=getattr(cfg, "reasoning_effort", None),
        extra_body=getattr(cfg, "extra_body", None) or None,
        extra_headers=getattr(cfg, "extra_headers", None) or None,
    )
    model = init_model(
        provider=provider,
        model_name=cfg.model,
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        max_tokens=cfg.max_tokens,
        **request_kwargs,
    )

    from openjiuwen_icode.agent.profile_loader import (
        active_agent_profile_id,
    )
    from openjiuwen_icode.prompts.code_profile import is_code_profile
    from openjiuwen_icode.rails.code_task_planning import (
        CodeTaskPlanningRail,
    )

    agent_profile = active_agent_profile_id() or "code"
    system_prompt = build_system_prompt(
        cwd=cfg.cwd,
        model=cfg.model,
        provider=cfg.provider,
        agent_profile=agent_profile,
    )

    tracker = TokenTrackingRail()
    tool_tracker = ToolTrackingRail()
    fs_rail = SysOperationRail()

    # Build rails list
    rails: list[Any] = [tracker, tool_tracker, fs_rail]

    # Code profile: coding-oriented todo guidance (suppresses the default
    # TaskPlanningRail inject via isinstance check in create_deep_agent).
    if is_code_profile(agent_profile):
        from openjiuwen_icode.rails.code_edit_nudge import (
            CodeEditNudgeRail,
        )
        from openjiuwen_icode.features.implement_gate import (
            IMPLEMENT_EXPLORE_ABORT_CAP,
            IMPLEMENT_EXPLORE_BUDGET,
            IMPLEMENT_MODEL_ABORT_CAP,
        )
        from openjiuwen_icode.rails.implement_completeness import (
            ImplementCompletenessRail,
        )

        rails.append(CodeTaskPlanningRail())
        rails.append(
            CodeEditNudgeRail(
                explore_budget=IMPLEMENT_EXPLORE_BUDGET,
                explore_abort_cap=IMPLEMENT_EXPLORE_ABORT_CAP,
                model_abort_cap=IMPLEMENT_MODEL_ABORT_CAP,
            )
        )
        rails.append(ImplementCompletenessRail())

    # --- Interrupt rails ---
    # AskUserRail: intercepts ask_user tool calls and
    # presents questions to the user via interrupt flow.
    rails.append(AskUserRail())

    # ConfirmInterruptRail: human-approval gate for
    # potentially dangerous file mutation tools.
    rails.append(
        ConfirmInterruptRail(
            tool_names=["write_file", "edit_file"]
        )
    )

    # Default skill directories — SkillUseRail silently
    # skips directories that do not exist. Newer SDK kwargs
    # (inline_skills / script_timeout) are filtered when absent.
    cwd = getattr(cfg, "cwd", None) or getattr(cfg, "workspace", None)
    skill_rail = call_with_supported_kwargs(
        SkillUseRail,
        skills_dir=_default_skill_dirs(cwd=cwd),
        skill_mode="all",
        include_tools=False,
        inline_skills=_inline_skills_for_rail(),
        script_timeout=_script_timeout(),
    )
    rails.append(skill_rail)

    # ContextProcessorRail — context window management
    # (includes DialogueCompressor for /compact support)
    try:
        from openjiuwen.harness.rails.context_engineer import (
            ContextProcessorRail,
            ContextAssembleRail
        )

        rails.append(ContextProcessorRail(preset=True))
        rails.append(ContextAssembleRail())
    except ImportError:
        logger.debug(
            "ContextProcessorRail or ContextAssembleRail not available"
        )

    # --- MemoryRail ---
    # Integrates vector-memory tools when embedding config
    # is available via environment variables.
    _memory_rail = _build_memory_rail(cfg)
    if _memory_rail is not None:
        rails.append(_memory_rail)

    # --- SessionRail ---
    # Enables spawning async subagent tasks (browser,
    # code, research) in the background.  Automatically
    # mounted by ``create_deep_agent`` when subagents are
    # present and ``enable_async_subagent=True``.
    # We do NOT add SessionRail manually here — it is
    # auto-injected by the factory.

    # Web tools are not part of SysOperationRail
    web_tools = create_web_tools(language="en")

    # MCP servers from ~/.icode/mcp.json (stable server_id = cwd+hash)
    mcp_configs = _load_mcp_configs(cwd=getattr(cfg, "cwd", None))

    # Multimodal configs (fallback to main model credentials)
    vision_config = _load_vision_config(cfg)
    audio_config = _load_audio_config(cfg)

    # --- Subagents ---
    subagents = _build_subagents(model)

    # Build extra kwargs for create_deep_agent
    extra_kwargs: dict[str, Any] = {}
    if mcp_configs:
        extra_kwargs["mcps"] = mcp_configs
    if vision_config is not None:
        extra_kwargs["vision_model_config"] = (
            vision_config
        )
    if audio_config is not None:
        extra_kwargs["audio_model_config"] = audio_config

    # Build CLI-specific workspace with overridden IDENTITY.md
    workspace = _build_cli_workspace(cfg, language="en")

    agent = create_deep_agent(
        model,
        system_prompt=system_prompt,
        tools=web_tools,
        subagents=subagents or None,
        rails=rails,
        enable_task_loop=True,
        enable_task_planning=True,
        enable_async_subagent=bool(subagents),
        add_general_purpose_agent=bool(subagents),
        max_iterations=cfg.max_iterations,
        workspace=workspace,
        restrict_to_work_dir=False,
        language="en",
        **extra_kwargs,
    )

    if subagents:
        _cfg_type, limiter_cls = load_concurrency_types()
        if limiter_cls is not None:
            from openjiuwen_icode.subagents import (
                load_subagent_concurrency_config,
            )

            agent.subagent_concurrency = limiter_cls(
                load_subagent_concurrency_config()
            )
        else:
            logger.debug(
                "SubagentConcurrencyLimiter not available; skipping limits"
            )

    # Override workspace root_path to bypass the factory's
    # automatic ``{agent_id}_workspace`` suffix.  This is safe
    # because ``restrict_to_work_dir=False`` makes SysOperation
    # scope independent of workspace path, and rails read from
    # ``deep_config.workspace`` lazily at first ``invoke()``.
    if agent.deep_config.workspace is not None:
        agent.deep_config.workspace.root_path = cfg.workspace

    return agent, tracker


# ---------------------------------------------------------------------------
# LocalBackend (MVP)
# ---------------------------------------------------------------------------


class LocalBackend:
    """Backend that calls the SDK Runner directly."""

    def __init__(self, cfg: CLIConfig) -> None:
        self.cfg = cfg
        self.agent: Any = None
        self.tracker: Optional[TokenTrackingRail] = None
        self._session_id: str = f"cli-{uuid4().hex[:8]}"
        self._runtime_session_overrides: dict[str, str] = {}
        self._loaded_extensions: set[str] = set()
        self._pending_workdir: Optional[str] = None

    async def start(self) -> None:
        """Create the agent and start the Runner."""
        self.agent, self.tracker = create_agent(self.cfg)
        await Runner.start()

    async def stop(self) -> None:
        """Stop the Runner."""
        await Runner.stop()

    async def run_streaming(
        self,
        query: Any,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Any]:
        """Stream OutputSchema chunks for *query*.

        *query* may be a plain string (normal user turn) or
        an ``InteractiveInput`` (interrupt resume).

        Applies T-43 idle stall detection: if no chunk arrives within
        the stall window, reopen the stream up to ``max_retries`` times.
        Mid-stream stalls reopen with a continuation nudge so long
        reasoning hangs do not abort the whole headless turn.
        """
        from openjiuwen_icode.features.implement_gate import (
            STALL_CONTINUATION_NUDGE,
            ZERO_MUTATION_NUDGE,
            is_wrapped_implement_continuation_query,
            looks_like_implement_task,
            original_task_from_query,
            wrap_implement_continuation_query,
        )
        from openjiuwen_icode.features.stream_stall import (
            iter_with_stall_retry,
        )
        from openjiuwen_icode.host.workdirs import (
            apply_pending_workdir_cwd,
        )
        from openjiuwen_icode.rails.code_edit_nudge import (
            reset_stream_rails,
            tighten_edit_rails_for_continuation,
        )

        apply_pending_workdir_cwd(self)
        await self._load_runtime_extensions()
        requested_sid = session_id or self._session_id
        sid = self._runtime_session_overrides.get(
            requested_sid, requested_sid
        )
        attempt = {"n": 0}
        continuation_retry = isinstance(query, str) and (
            is_wrapped_implement_continuation_query(query)
        )
        verify_only_continuation = False
        if continuation_retry and isinstance(query, str):
            from openjiuwen_icode.features.implement_gate import (
                POST_MUTATION_EXPLORE_NUDGE,
                TS_SUITE_NUDGE,
                VERIFY_FAILED_NUDGE,
                VERIFY_NUDGE,
            )

            head = query.lstrip()
            verify_only_continuation = any(
                head.startswith(marker[:48])
                for marker in (
                    VERIFY_NUDGE,
                    VERIFY_FAILED_NUDGE,
                    POST_MUTATION_EXPLORE_NUDGE,
                    TS_SUITE_NUDGE,
                )
            )
        task_for_stall = (
            original_task_from_query(query) if isinstance(query, str) else ""
        )
        # Prefer an edit-now nudge when the original query is an implement task
        # so mid-stream stall retries do not resume as more archaeology.
        stall_nudge = (
            ZERO_MUTATION_NUDGE
            if task_for_stall and looks_like_implement_task(task_for_stall)
            else STALL_CONTINUATION_NUDGE
        )

        def _open() -> AsyncIterator[Any]:
            attempt["n"] += 1
            if continuation_retry:
                tighten_edit_rails_for_continuation(
                    self.agent, verify_only=verify_only_continuation
                )
            else:
                reset_stream_rails(self.agent)
            payload_query: Any = query
            if attempt["n"] > 1 and isinstance(query, str):
                payload_query = wrap_implement_continuation_query(
                    task_for_stall or query,
                    stall_nudge,
                )
            return Runner.run_agent_streaming(
                self.agent,
                {"query": payload_query},
                session=sid,
            )

        async def _abort_before_retry(attempt: int, stall: float) -> None:
            # Tear down prior DeepAgent task-loop / parallel tools before
            # reopening; otherwise stall aclose leaves zombie gathers and
            # orphan ToolCallStarts while the continuation runs.
            _ = attempt, stall
            try:
                abort_task = asyncio.create_task(
                    self.abort(), name="stall-abort"
                )
                await wait_abandon(abort_task, timeout=5.0)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "abort before stream stall retry failed",
                    exc_info=True,
                )
            await cancel_in_flight_agent_tasks()

        async for chunk in iter_with_stall_retry(
            _open,
            retry_midstream=True,
            on_retry=_abort_before_retry,
        ):
            yield chunk

    async def abort(self) -> None:
        """Request the agent to abort the current task loop."""
        if self.agent is not None:
            try:
                await self.agent.abort()
            except RecursionError:
                logger.warning("DeepAgent.abort RecursionError (cancel cycle)")
            except Exception:  # noqa: BLE001
                pass
        try:
            await cancel_in_flight_agent_tasks()
        except RecursionError:
            logger.warning(
                "RecursionError cancelling leftover agent tasks after abort"
            )
        except Exception:  # noqa: BLE001
            logger.debug("cancel leftover agent tasks failed", exc_info=True)

    async def reset_runtime_session(self, session_id: str | None = None) -> str:
        """Use a clean SDK session after provider history corruption.

        The public iCode session remains unchanged for event storage and UI
        continuity. Only subsequent Runner calls move to a fresh provider
        context, where the headless continuation can safely restate the task.
        """
        await self.abort()
        requested_sid = session_id or self._session_id
        recovered_sid = f"{requested_sid}-recovery-{uuid4().hex[:8]}"
        self._runtime_session_overrides[requested_sid] = recovered_sid
        logger.warning(
            "reset corrupted runtime session %s as %s",
            requested_sid,
            recovered_sid,
        )
        return recovered_sid

    async def steer(self, msg: str) -> None:
        """Forward mid-turn inject to DeepAgent ``steer``."""
        if self.agent is None:
            return
        try:
            await self.agent.steer(msg)
        except Exception:  # noqa: BLE001
            logger.debug("steer failed", exc_info=True)

    async def follow_up(self, msg: str) -> None:
        """Forward follow-up text to DeepAgent ``follow_up``."""
        if self.agent is None:
            return
        try:
            await self.agent.follow_up(msg)
        except Exception:  # noqa: BLE001
            logger.debug("follow_up failed", exc_info=True)

    def get_usage(self) -> Optional[Dict[str, Any]]:
        """Return TokenTrackingRail summary when available."""
        if self.tracker is None:
            return None
        return self.tracker.get_summary()

    async def rebuild(self) -> None:
        """Recreate the DeepAgent from current ``cfg`` (model hot-switch)."""
        self._loaded_extensions.clear()
        self.agent, self.tracker = create_agent(self.cfg)

    async def _load_runtime_extensions(self) -> None:
        """Scan runtime_extensions/ and hot-load new configs."""
        if self.agent is None:
            return

        ext_root = (
            Path(self.cfg.workspace)
            / "auto_harness"
            / "runtime_extensions"
        )
        if not ext_root.is_dir():
            return
        for child in sorted(ext_root.iterdir()):
            if not child.is_dir():
                continue
            config_path = child / "harness_config.yaml"
            if not config_path.is_file():
                continue
            ext_key = str(config_path)
            if ext_key in self._loaded_extensions:
                continue
            try:
                loaded = await self.agent.load_harness_config(
                    ext_key,
                )
                self._loaded_extensions.add(ext_key)
                if loaded:
                    logger.info(
                        "Hot-loaded runtime extension: %s",
                        ", ".join(loaded),
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to load runtime extension: %s",
                    config_path,
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------


def create_backend(cfg: CLIConfig) -> LocalBackend:
    """Select and instantiate the appropriate backend.

    Args:
        cfg: CLI configuration.

    Returns:
        A :class:`LocalBackend` (MVP).

    Raises:
        NotImplementedError: If ``cfg.server_url`` is set
            (remote mode not yet supported).
    """
    if cfg.server_url:
        raise NotImplementedError(
            "RemoteBackend is not supported in the MVP. "
            "Remove OPENJIUWEN_SERVER_URL to use local mode."
        )
    return LocalBackend(cfg)

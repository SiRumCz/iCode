"""Configuration management for OpenJiuWen iCode CLI.

Three-layer priority:
    settings.json < environment variables < CLI arguments.

Machine settings live under **iCode home** (``~/.icode/``).
Agent workspace lives under the active **iCode project** (``<project>/workspace``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from openjiuwen_icode.paths import (
    IcodeProject,
    resolve_project_path,
    settings_path,
)


def _default_workspace() -> str:
    """Return agent workspace under the default iCode project."""
    return str(IcodeProject.open().workspace_dir)


#: Fixed path for the user-level settings file (iCode home).
SETTINGS_PATH = settings_path()


def load_settings_json(
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """Load settings from ``~/.icode/settings.json``.

    Args:
        path: Override for the settings file path
            (useful in tests).

    Returns:
        Parsed dict, or ``{}`` on missing / invalid file.
        Never raises.
    """
    p = path or SETTINGS_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_settings_json(
    data: dict[str, Any],
    path: Optional[Path] = None,
) -> Path:
    """Save settings to ``~/.icode/settings.json``.

    Merges *data* into the existing file (new keys override).

    Args:
        data: Key-value pairs to write.
        path: Override for the settings file path.

    Returns:
        The resolved file path.
    """
    p = path or SETTINGS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = load_settings_json(p)
    existing.update(data)
    p.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return p


@dataclass
class CLIConfig:
    """CLI runtime configuration.

    Args:
        provider: LLM provider name (e.g. ``"OpenAI"``, ``"DashScope"``).
        model: Model name (e.g. ``"gpt-4o"``).
        api_key: Provider API key.
        api_base: Provider API base URL.
        max_iterations: Maximum ReAct + TaskLoop iterations.
        max_tokens: Maximum tokens per model call.
        server_url: Remote agent-server URL; empty means local mode.
        cwd: Working directory (filled at runtime; usually primary directory).
        workspace: Agent workspace directory (``<icode-project>/workspace``).
        project: iCode project root path.
        verbose: Enable verbose logging.
    """

    provider: str = "OpenAI"
    model: str = "gpt-4o"
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    extra_headers: dict = field(default_factory=dict)
    extra_body: dict = field(default_factory=dict)
    max_iterations: int = 30
    max_tokens: int = 8192
    server_url: str = ""
    cwd: str = field(default_factory=os.getcwd)
    workspace: str = field(default_factory=_default_workspace)
    project: str = field(
        default_factory=lambda: str(resolve_project_path())
    )
    verbose: bool = False

    def validate(self) -> None:
        """Validate configuration values.

        Raises:
            ValueError: If ``api_key`` is missing (local mode) or
                ``max_tokens`` is dangerously small.
        """
        if not self.api_key and not self.server_url:
            raise ValueError(
                "API key not set. Use --api-key, "
                "OPENJIUWEN_API_KEY / ICODE_API_KEY, or add to "
                "~/.icode/settings.json."
            )
        if self.max_tokens < 256:
            raise ValueError(
                f"max_tokens={self.max_tokens} is dangerously small "
                f"(min 256). Check OPENJIUWEN_MAX_TOKENS."
            )
        if self.max_iterations < 1:
            raise ValueError(
                f"max_iterations={self.max_iterations} must be >= 1."
            )


def load_config(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    server_url: Optional[str] = None,
    workspace: Optional[str] = None,
    project: Optional[str] = None,
    verbose: bool = False,
) -> CLIConfig:
    """Build a :class:`CLIConfig` by merging three layers.

    Priority (highest first):
        *CLI arguments* > *environment variables* >
        *settings.json* > *defaults*.

    Args:
        provider: Override for ``OPENJIUWEN_PROVIDER`` / ``ICODE_PROVIDER``.
        model: Override for ``OPENJIUWEN_MODEL`` / ``ICODE_MODEL``.
        api_key: Override for ``OPENJIUWEN_API_KEY`` / ``ICODE_API_KEY``.
        api_base: Override for ``OPENJIUWEN_API_BASE`` / ``ICODE_API_BASE``.
        server_url: Override for ``OPENJIUWEN_SERVER_URL``.
        workspace: Explicit agent workspace (rare; normally derived from project).
        project: iCode project root (``-p`` / ``ICODE_PROJECT``).
        verbose: Enable verbose logging.

    Returns:
        Validated :class:`CLIConfig` instance.
    """
    settings = load_settings_json()
    proj = IcodeProject.open(project)
    agent_ws = (
        workspace
        or os.getenv("ICODE_AGENT_WORKSPACE")
        or str(proj.workspace_dir)
    )

    def _env(*names: str) -> str | None:
        for name in names:
            val = os.getenv(name)
            if val:
                return val
        return None

    def _stream_iteration_cap() -> int:
        """Upper bound on inner ReAct loops per SessionHost continuation."""
        raw = _env("ICODE_STREAM_ITERATION_CAP", "OPENJIUWEN_STREAM_ITERATION_CAP")
        try:
            return max(1, int(raw or 50))
        except ValueError:
            return 50

    requested_iterations = int(
        _env("ICODE_MAX_ITERATIONS", "OPENJIUWEN_MAX_ITERATIONS")
        or settings.get("maxIterations")
        or 30
    )
    stream_cap = _stream_iteration_cap()
    effective_iterations = (
        min(requested_iterations, stream_cap)
        if requested_iterations > stream_cap
        else requested_iterations
    )

    cfg = CLIConfig(
        provider=(
            provider
            or _env("ICODE_PROVIDER", "OPENJIUWEN_PROVIDER")
            or settings.get("provider")
            or "OpenAI"
        ),
        model=(
            model
            or _env("ICODE_MODEL", "OPENJIUWEN_MODEL")
            or settings.get("model")
            or "gpt-4o"
        ),
        api_key=(
            api_key
            or _env("ICODE_API_KEY", "OPENJIUWEN_API_KEY")
            or settings.get("apiKey")
            or ""
        ),
        api_base=(
            api_base
            or _env("ICODE_API_BASE", "OPENJIUWEN_API_BASE")
            or settings.get("apiBase")
            or "https://api.openai.com/v1"
        ),
        max_iterations=effective_iterations,
        max_tokens=int(
            _env("ICODE_MAX_TOKENS", "OPENJIUWEN_MAX_TOKENS")
            or settings.get("maxTokens")
            or 8192
        ),
        server_url=(
            server_url
            or _env("ICODE_SERVER_URL", "OPENJIUWEN_SERVER_URL")
            or settings.get("serverUrl")
            or ""
        ),
        workspace=agent_ws,
        project=str(proj.root),
        verbose=verbose,
    )
    cfg.validate()
    return cfg

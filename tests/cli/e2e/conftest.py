# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Shared helpers for CLI E2E / smoke tests.

Environment (LLM e2e):
  ICODE_E2E_API_KEY          Dedicated test API key (required for LLM tests)
  ICODE_E2E_MODEL            Preset id from models.yaml (default: yaml ``default``)
  ICODE_E2E_MODELS           ``default`` | ``all`` | comma-separated preset ids
  ICODE_E2E_API_BASE         Optional override for api_base
  ICODE_E2E_PROVIDER         Optional override for provider
  ICODE_E2E_MODEL_ID         Optional override for the wire model id

If the resolved API key env var is missing/empty, LLM tests are skipped with a
pytest skip message (and a warnings.warn reminder).
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

# ── Paths ─────────────────────────────────────────────────────────────
_E2E_DIR = Path(__file__).resolve().parent
_MODELS_YAML = _E2E_DIR / "models.yaml"
PROJECT_ROOT = _E2E_DIR.parents[2]

PYTHON = sys.executable
CLI_CMD = [PYTHON, "-m", "openjiuwen_icode"]

# Dedicated test credentials (do not reuse interactive OPENLUX_TOKEN by default).
E2E_API_KEY_ENV = "ICODE_E2E_API_KEY"
DEFAULT_LLM_TIMEOUT = 120


@dataclass(frozen=True)
class ModelPreset:
    """One named LLM configuration for e2e runs."""

    id: str
    label: str
    model: str
    provider: str
    api_base: str
    api_key_env: str = E2E_API_KEY_ENV

    def resolve_api_key(self) -> str:
        """Return the API key for this preset, or ``\"\"`` if unset."""
        primary = os.getenv(self.api_key_env, "").strip()
        if primary:
            return primary
        # Allow a shared test key when a preset declares a dedicated env name.
        if self.api_key_env != E2E_API_KEY_ENV:
            return os.getenv(E2E_API_KEY_ENV, "").strip()
        return ""


def _load_models_doc() -> dict[str, Any]:
    with _MODELS_YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid models.yaml: {_MODELS_YAML}")
    return data


def load_presets() -> dict[str, ModelPreset]:
    """Load all presets from ``models.yaml``."""
    doc = _load_models_doc()
    raw = doc.get("presets") or {}
    out: dict[str, ModelPreset] = {}
    for pid, body in raw.items():
        if not isinstance(body, dict):
            continue
        out[str(pid)] = ModelPreset(
            id=str(pid),
            label=str(body.get("label") or pid),
            model=str(body.get("model") or pid),
            provider=str(body.get("provider") or "OpenAI"),
            api_base=str(body.get("api_base") or ""),
            api_key_env=str(body.get("api_key_env") or E2E_API_KEY_ENV),
        )
    return out


def default_preset_id() -> str:
    doc = _load_models_doc()
    env = os.getenv("ICODE_E2E_MODEL", "").strip()
    if env:
        return env
    return str(doc.get("default") or "deepseek-v4-pro")


def selected_preset_ids() -> list[str]:
    """Preset ids selected via ``ICODE_E2E_MODELS`` / ``ICODE_E2E_MODEL``."""
    presets = load_presets()
    raw = os.getenv("ICODE_E2E_MODELS", "").strip()
    if not raw or raw.lower() == "default":
        pid = default_preset_id()
        if pid not in presets:
            raise RuntimeError(
                f"Unknown ICODE_E2E_MODEL={pid!r}; "
                f"known={sorted(presets)}"
            )
        return [pid]
    if raw.lower() == "all":
        return list(presets.keys())
    ids = [p.strip() for p in raw.split(",") if p.strip()]
    unknown = [i for i in ids if i not in presets]
    if unknown:
        raise RuntimeError(
            f"Unknown ICODE_E2E_MODELS entries {unknown}; "
            f"known={sorted(presets)}"
        )
    return ids


def selected_presets() -> list[ModelPreset]:
    catalog = load_presets()
    return [catalog[i] for i in selected_preset_ids()]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize LLM tests on ``model_preset`` from models.yaml selection."""
    if "model_preset" not in metafunc.fixturenames:
        return
    presets = selected_presets()
    metafunc.parametrize(
        "model_preset",
        presets,
        ids=[p.id for p in presets],
    )


@pytest.fixture
def llm_env(
    model_preset: ModelPreset, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, str]:
    """Build a subprocess env for an LLM e2e run, or skip with a reminder.

    Uses an isolated ``ICODE_HOME`` so real ``~/.icode`` directories /
    user ``OPENJIUWEN.md`` do not leak into tool / memory e2e cases.
    """
    key = model_preset.resolve_api_key()
    key_env = model_preset.api_key_env
    if not key:
        msg = (
            f"LLM e2e skipped: set {key_env} "
            f"(preset={model_preset.id}, {model_preset.label}). "
            f"Shared fallback: {E2E_API_KEY_ENV}."
        )
        warnings.warn(msg, UserWarning, stacklevel=1)
        pytest.skip(msg)

    api_base = (
        os.getenv("ICODE_E2E_API_BASE", "").strip()
        or model_preset.api_base
    )
    provider = (
        os.getenv("ICODE_E2E_PROVIDER", "").strip()
        or model_preset.provider
    )
    model_id = (
        os.getenv("ICODE_E2E_MODEL_ID", "").strip()
        or model_preset.model
    )

    icode_home = tmp_path_factory.mktemp("icode_home")
    project = icode_home / "projects" / "e2e"

    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT),
        # Isolate product state from the developer's real ~/.icode.
        "ICODE_HOME": str(icode_home),
        "ICODE_PROJECT": str(project),
        # Product runtime still reads OPENJIUWEN_* / ICODE_*.
        "ICODE_API_KEY": key,
        "OPENJIUWEN_API_KEY": key,
        "ICODE_API_BASE": api_base,
        "OPENJIUWEN_API_BASE": api_base,
        "ICODE_MODEL": model_id,
        "OPENJIUWEN_MODEL": model_id,
        "ICODE_PROVIDER": provider,
        "OPENJIUWEN_PROVIDER": provider,
        # Keep the dedicated test var visible for debugging.
        E2E_API_KEY_ENV: key,
    }
    return env


def _with_workdir_flag(args: tuple[str, ...], cwd: str | None) -> list[str]:
    """Insert ``-C <cwd>`` for ``run`` when cwd is set and not already passed.

    Headless ``run`` otherwise may keep a stale primary from directories.json
    and never see files / OPENJIUWEN.md under the test temp dir.
    """
    out = list(args)
    if not cwd or not out or out[0] != "run":
        return out
    if "-C" in out or "--workdir" in out:
        return out
    return ["run", "-C", cwd, *out[1:]]


_AGENT_MESSAGE_RE = re.compile(r"^\[AgentMessage\] (.+)$", re.MULTILINE)


def agent_message_text(stdout: str) -> str:
    """Join streamed ``[AgentMessage]`` payloads from text event output.

    Token streaming prints many short events, so markers like
    ``MAGIC_MARKER_XYZ`` may not appear contiguously in raw stdout.
    """
    parts: list[str] = []
    for match in _AGENT_MESSAGE_RE.finditer(stdout):
        raw = match.group(1).strip()
        try:
            value = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            value = raw.strip("'\"")
        parts.append(value if isinstance(value, str) else str(value))
    return "".join(parts)


def run_cli(
    *args: str,
    input: str | None = None,
    timeout: int = DEFAULT_LLM_TIMEOUT,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m openjiuwen_icode`` as a subprocess."""
    return subprocess.run(
        [*CLI_CMD, *_with_workdir_flag(args, cwd)],
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input,
        env=env or {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        cwd=cwd,
    )


def run_icode(
    *args: str,
    input: str | None = None,
    timeout: int = 30,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the ``icode`` console script when available, else ``-m``."""
    import shutil

    icode = shutil.which("icode")
    cmd = [icode, *args] if icode else [*CLI_CMD, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input,
        env=env or {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        cwd=cwd,
    )

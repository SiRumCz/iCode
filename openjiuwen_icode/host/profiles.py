# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Lightweight model / agent profile helpers for EventBus CLI (P2 T-20)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from openjiuwen_icode.agent.config import (
    SETTINGS_PATH,
    load_settings_json,
    save_settings_json,
)

from openjiuwen_icode.paths import agents_dir, models_dir

MODELS_DIR = models_dir()
AGENTS_DIR = agents_dir()

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_filename(model_id: str) -> str:
    cleaned = _SAFE_ID_RE.sub("-", (model_id or "").strip()).strip("-._")
    return cleaned or "model"


def _looks_like_env_var_name(value: str) -> bool:
    """Return True if *value* is an env var name, not a pasted secret."""
    return bool(_ENV_NAME_RE.fullmatch((value or "").strip()))


def resolve_profile_api_key(profile: dict[str, Any]) -> str | None:
    """Resolve an API key from a model profile.

    Supports:
    - ``apiKey`` / ``api_key``: literal key stored on the profile
    - ``api_key_env`` / ``apiKeyEnv``: environment variable *name*
    - Mis-pasted secrets in ``api_key_env`` (e.g. ``sk-…``): treated as
      literal keys so switching models still works
    """
    for key_name in ("apiKey", "api_key"):
        raw = profile.get(key_name)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    env_or_key = profile.get("api_key_env") or profile.get("apiKeyEnv")
    if env_or_key is None or not str(env_or_key).strip():
        return None
    value = str(env_or_key).strip()
    if _looks_like_env_var_name(value):
        import os

        return os.environ.get(value) or None
    # User likely pasted the secret into the "env var" field.
    return value


def list_model_profiles(
    *,
    models_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Return user model profiles from ``~/.icode/models/*.json``."""
    root = models_dir if models_dir is not None else MODELS_DIR
    by_id: dict[str, dict[str, Any]] = {}
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            model_id = str(data.get("id") or data.get("model") or path.stem)
            by_id[model_id] = {
                "id": model_id,
                "provider": str(data.get("provider") or "OpenAI"),
                "label": str(
                    data.get("label") or data.get("name") or model_id
                ),
                "apiBase": data.get("apiBase") or data.get("api_base"),
                "headers": data.get("headers") or {},
                "extra_body": data.get("extra_body")
                or data.get("extraBody")
                or {},
                "api_key_env": data.get("api_key_env")
                or data.get("apiKeyEnv")
                or "",
                "apiKey": data.get("apiKey") or data.get("api_key") or "",
                "path": str(path),
                "builtin": False,
            }
    return sorted(by_id.values(), key=lambda row: str(row["id"]))


def unique_model_profile_id(
    base_id: str,
    *,
    models_dir: Path | None = None,
) -> str:
    """Return an unused profile id derived from *base_id* (e.g. ``foo-copy``)."""
    cleaned = (base_id or "model").strip() or "model"
    existing = {
        str(row["id"]) for row in list_model_profiles(models_dir=models_dir)
    }
    candidate = f"{cleaned}-copy"
    if candidate not in existing:
        return candidate
    n = 2
    while f"{cleaned}-copy-{n}" in existing:
        n += 1
    return f"{cleaned}-copy-{n}"


def get_model_profile(
    model_id: str,
    *,
    models_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Return one profile by id, or ``None``."""
    for row in list_model_profiles(models_dir=models_dir):
        if row["id"] == model_id:
            return row
    return None


def save_model_profile(
    profile: dict[str, Any],
    *,
    models_dir: Path | None = None,
) -> Path:
    """Create/update a user model profile JSON under models dir."""
    root = models_dir if models_dir is not None else MODELS_DIR
    root.mkdir(parents=True, exist_ok=True)
    model_id = str(profile.get("id") or "").strip()
    if not model_id:
        raise ValueError("model id is required")
    path = root / f"{_safe_filename(model_id)}.json"
    payload = {
        "id": model_id,
        "label": str(profile.get("label") or model_id).strip() or model_id,
        "provider": str(profile.get("provider") or "OpenAI").strip()
        or "OpenAI",
    }
    api_base = profile.get("apiBase") or profile.get("api_base")
    if api_base:
        payload["apiBase"] = str(api_base).strip()
    headers = profile.get("headers")
    if isinstance(headers, dict) and headers:
        payload["headers"] = {
            str(k): str(v) for k, v in headers.items() if str(k).strip()
        }
    elif isinstance(headers, str) and headers.strip():
        try:
            parsed = json.loads(headers)
        except json.JSONDecodeError as exc:
            raise ValueError(f"headers must be JSON object: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("headers must be a JSON object")
        payload["headers"] = {
            str(k): str(v) for k, v in parsed.items() if str(k).strip()
        }
    extra_body = profile.get("extra_body") or profile.get("extraBody")
    if isinstance(extra_body, dict) and extra_body:
        payload["extra_body"] = extra_body
    elif isinstance(extra_body, str) and extra_body.strip():
        try:
            parsed = json.loads(extra_body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"extra_body must be JSON object: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("extra_body must be a JSON object")
        payload["extra_body"] = parsed
    api_key_env = profile.get("api_key_env") or profile.get("apiKeyEnv")
    api_key_literal = profile.get("apiKey") or profile.get("api_key")
    if api_key_literal and str(api_key_literal).strip():
        payload["apiKey"] = str(api_key_literal).strip()
    elif api_key_env and str(api_key_env).strip():
        value = str(api_key_env).strip()
        if _looks_like_env_var_name(value):
            payload["api_key_env"] = value
        else:
            # Normalize accidental paste of the secret into the env-var field.
            payload["apiKey"] = value
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def delete_model_profile(
    model_id: str,
    *,
    models_dir: Path | None = None,
) -> bool:
    """Delete a user profile file. Returns False if missing."""
    profile = get_model_profile(model_id, models_dir=models_dir)
    if profile is None:
        return False
    path_str = profile.get("path")
    if not path_str:
        root = models_dir if models_dir is not None else MODELS_DIR
        path = root / f"{_safe_filename(model_id)}.json"
    else:
        path = Path(path_str)
    if not path.is_file():
        return False
    path.unlink()
    return True


def current_model_from_settings(
    path: Path | None = None,
) -> dict[str, str]:
    """Read current model/provider from settings.json."""
    data = load_settings_json(path or SETTINGS_PATH)
    return {
        "model": str(data.get("model") or "gpt-4o"),
        "provider": str(data.get("provider") or "OpenAI"),
        "apiBase": str(
            data.get("apiBase")
            or data.get("api_base")
            or "https://api.openai.com/v1"
        ),
    }


def switch_model_in_settings(
    model: str,
    *,
    provider: str | None = None,
    api_base: str | None = None,
    path: Path | None = None,
    models_dir: Path | None = None,
) -> dict[str, str]:
    """Persist model selection into settings.json."""
    payload: dict[str, Any] = {"model": model}
    if provider:
        payload["provider"] = provider
    if api_base:
        payload["apiBase"] = api_base
    else:
        for profile in list_model_profiles(models_dir=models_dir):
            if profile["id"] == model:
                payload.setdefault("provider", profile.get("provider"))
                if profile.get("apiBase"):
                    payload["apiBase"] = profile["apiBase"]
                break
    save_settings_json(payload, path=path or SETTINGS_PATH)
    return current_model_from_settings(path or SETTINGS_PATH)


def apply_model_to_backend(backend: Any, profile: dict[str, Any]) -> None:
    """Update ``backend.cfg`` fields from a profile (display + next rebuild)."""
    cfg = getattr(backend, "cfg", None)
    if cfg is None:
        return
    cfg.model = str(profile.get("id") or cfg.model)
    if profile.get("provider"):
        cfg.provider = str(profile["provider"])
    api_base = profile.get("apiBase") or profile.get("api_base")
    if api_base:
        cfg.api_base = str(api_base)
    key = resolve_profile_api_key(profile)
    if key and hasattr(cfg, "api_key"):
        cfg.api_key = key
        # Keep settings.json in sync so the next cold start uses the same key.
        try:
            save_settings_json({"apiKey": key})
        except Exception:  # noqa: BLE001
            pass
    if hasattr(cfg, "extra_headers"):
        headers = profile.get("headers") or {}
        if isinstance(headers, dict):
            cfg.extra_headers = {str(k): str(v) for k, v in headers.items()}
    if hasattr(cfg, "extra_body"):
        body = profile.get("extra_body") or profile.get("extraBody") or {}
        if isinstance(body, dict):
            cfg.extra_body = dict(body)


async def rebuild_backend_agent(backend: Any) -> bool:
    """Best-effort agent rebuild after model switch. Returns True if rebuilt."""
    rebuild = getattr(backend, "rebuild", None)
    if not callable(rebuild):
        return False
    result = rebuild()
    if hasattr(result, "__await__"):
        await result
    return True


def get_agent_profile(profile_id: str) -> dict[str, Any] | None:
    """Return one agent profile row by id, or ``None``."""
    for row in list_agent_profiles():
        if row["id"] == profile_id:
            return row
    return None


def switch_agent_profile_in_settings(
    profile_id: str,
    path: Path | None = None,
) -> str:
    """Persist active agent profile id to settings.json."""
    cleaned = (profile_id or "").strip()
    if not cleaned:
        raise ValueError("agent profile id is required")
    save_settings_json({"agent_profile": cleaned}, path=path or SETTINGS_PATH)
    return cleaned


def list_agent_profiles() -> list[dict[str, Any]]:
    """Return builtin agent role labels + optional user YAML/JSON stubs."""
    profiles: list[dict[str, Any]] = [
        {"id": "code", "label": "Code (coding agent)"},
        {"id": "general-purpose", "label": "General subagent"},
        {"id": "explore_agent", "label": "Explore subagent (read-only)"},
        {"id": "plan_agent", "label": "Plan subagent (read-only)"},
        {"id": "browser_agent", "label": "Browser subagent (optional)"},
        {"id": "research_agent", "label": "Research subagent (opt-in env)"},
    ]
    if AGENTS_DIR.is_dir():
        for path in sorted(AGENTS_DIR.glob("*.json")) + sorted(
            AGENTS_DIR.glob("*.yaml")
        ) + sorted(AGENTS_DIR.glob("*.yml")):
            try:
                if path.suffix.lower() in {".yaml", ".yml"}:
                    data = yaml.safe_load(path.read_text(encoding="utf-8"))
                else:
                    data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, yaml.YAMLError):
                continue
            if isinstance(data, dict) and data.get("id"):
                profiles.append(
                    {
                        "id": str(data["id"]),
                        "label": str(data.get("label") or data["id"]),
                        "path": str(path),
                    }
                )
            elif isinstance(data, dict) and path.suffix.lower() in {
                ".yaml",
                ".yml",
            }:
                profiles.append(
                    {
                        "id": path.stem,
                        "label": str(data.get("label") or path.stem),
                        "path": str(path),
                    }
                )
    return profiles

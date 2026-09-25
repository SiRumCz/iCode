# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Persist and restore session-level metadata (model, workdir, agent profile)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openjiuwen_icode.host.workdirs import (
    apply_workdir_to_backend,
    resolve_workdir,
)
from openjiuwen_icode.storage.session_store import (
    SessionStore,
    StoredSession,
)


def _model_from_host(host: Any) -> str:
    cfg = getattr(getattr(host, "_backend", None), "cfg", None)
    if cfg is not None:
        model = getattr(cfg, "model", None)
        if model:
            return str(model)
    return str(getattr(host, "_model_name", "") or "unknown")


def _agent_profile_from_host(host: Any, fallback: str = "") -> str:
    from openjiuwen_icode.agent.profile_loader import (
        active_agent_profile_id,
    )

    pid = active_agent_profile_id().strip()
    if pid:
        return pid
    return (fallback or "code").strip() or "code"


def persist_session_metadata(host: Any) -> bool:
    """Write model / primary workdir / agent profile onto the current session."""
    store: SessionStore | None = getattr(host, "session_store", None)
    if store is None or store.current is None:
        return False
    cur = store.current
    workdir = ""
    reg = getattr(host, "workdirs", None)
    if reg is not None and reg.primary:
        workdir = reg.primary
    return store.update_metadata(
        model=_model_from_host(host),
        workdir=workdir,
        agent_profile=_agent_profile_from_host(host, cur.agent_profile),
    )


def apply_stored_workdir_to_host(host: Any, session: StoredSession) -> bool:
    """Restore persisted primary workdir when resuming or forking."""
    raw = (session.workdir or "").strip()
    if not raw:
        return False
    reg = getattr(host, "workdirs", None)
    backend = getattr(host, "_backend", None)
    if reg is None or backend is None:
        return False
    try:
        target = str(resolve_workdir(raw))
    except OSError:
        return False
    if not Path(target).is_dir():
        return False
    try:
        reg.use(target)
    except ValueError:
        return False
    apply_workdir_to_backend(backend, target)
    return True


def export_directory_for_session(
    session: StoredSession,
    *,
    fallback: str = "",
) -> str:
    """Directory field for OpenCode export and session list."""
    stored = (session.workdir or "").strip()
    if stored:
        return stored
    return (fallback or "").strip()

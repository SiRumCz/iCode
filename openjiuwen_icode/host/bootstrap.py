# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Shared bootstrap for ``run`` / ``tui`` / future ACP (P2 T-29)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openjiuwen_icode.agent.config import CLIConfig
from openjiuwen_icode.branding import window_title
from openjiuwen_icode.events import EventBus
from openjiuwen_icode.host.demo_backend import DemoBackend
from openjiuwen_icode.host.session_host import SessionHost
from openjiuwen_icode.host.workdirs import (
    WorkdirRegistry,
    apply_workdir_to_backend,
)
from openjiuwen_icode.paths import IcodeProject
from openjiuwen_icode.storage.session_store import SessionStore


@dataclass
class HostBundle:
    """Bus + Host + backend + session store wired for one CLI process."""

    bus: EventBus
    host: SessionHost
    backend: Any
    store: SessionStore
    session_id: str
    title: str
    project: IcodeProject


def build_host_bundle(
    cfg: CLIConfig | None,
    *,
    demo: bool = False,
    auto_approve: bool = False,
    session_id: str | None = None,
    project: IcodeProject | None = None,
) -> HostBundle:
    """Create EventBus + SessionHost + SessionStore for interactive/headless."""
    bus = EventBus()
    if project is None:
        project_path = getattr(cfg, "project", None) if cfg else None
        project = IcodeProject.open(project_path)
    store = SessionStore(store_dir=project.sessions_dir)
    workdirs = WorkdirRegistry.load(project.directories_json)

    if demo:
        backend: Any = DemoBackend()
        sid = session_id or "demo-session"
        model = "demo"
        title = window_title("demo")
        workdirs.ensure_seed(str(Path.cwd()))
    else:
        if cfg is None:
            raise ValueError("cfg is required when demo=False")
        from openjiuwen_icode.agent.factory import create_backend

        # Ensure agent workspace stays under the iCode project.
        cfg.workspace = str(project.workspace_dir)
        cfg.project = str(project.root)
        backend = create_backend(cfg)
        sid = session_id or getattr(backend, "_session_id", None) or "cli-session"
        model = cfg.model
        title = window_title(cfg.model)
        # Seed directories from process cwd when empty (not from agent workspace).
        workdirs.ensure_seed(str(Path.cwd()))
        if workdirs.primary:
            apply_workdir_to_backend(backend, workdirs.primary)
            primary_name = Path(workdirs.primary).name
            title = window_title(cfg.model, workspace=primary_name)

    host = SessionHost(
        bus,
        backend,
        session_id=sid,
        auto_approve=auto_approve,
        session_store=store,
        model_name=model,
        workdirs=workdirs,
    )
    return HostBundle(
        bus=bus,
        host=host,
        backend=backend,
        store=store,
        session_id=sid,
        title=title,
        project=project,
    )

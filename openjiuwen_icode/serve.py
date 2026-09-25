# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Browser-hosted TUI via textual-serve (``icode serve``).

Mirrors Chrys ``chrys serve``: each browser tab spawns a Textual TUI process
bound to EventBus + SessionHost. Stdout of the serve process is the HTTP
server; the TUI itself runs in child processes.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from openjiuwen_icode.branding import PRODUCT_NAME

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
_SERVE_DEMO_ENV = "OPENJIUWEN_SERVE_DEMO"
_SERVE_PROJECT_ENV = "OPENJIUWEN_SERVE_PROJECT"


def _looks_like_python(executable: str) -> bool:
    name = Path(executable).name.lower()
    return name.startswith(("python", "pypy"))


def _shell_join(argv: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(argv))
    return shlex.join(list(argv))


def entrypoint_argv() -> list[str]:
    """Return argv that invokes the OpenJiuWen CLI entrypoint."""
    if _looks_like_python(sys.executable):
        return [sys.executable, "-m", "openjiuwen_icode"]
    # Installed console script (e.g. ``icode``).
    return [sys.argv[0] if sys.argv else "icode"]


def build_tui_command(
    *,
    demo: bool = False,
    project: str | None = None,
) -> str:
    """Shell command textual-serve uses to spawn one TUI session."""
    argv = list(entrypoint_argv())
    if project:
        argv.extend(["--project", project])
    argv.append("tui")
    if demo:
        argv.append("--demo")
    return _shell_join(argv)


def effective_public_url(
    *,
    host: str,
    port: int,
    public_url: str | None = None,
) -> str | None:
    """Return explicit public URL, or None to let textual-serve derive it."""
    if public_url:
        return public_url.rstrip("/")
    if host in {"0.0.0.0", "::", "[::]"}:
        # Callers should pass --public-url when binding all interfaces.
        return None
    return None


def load_textual_serve_server() -> type[Any]:
    """Import textual-serve Server or raise a helpful error."""
    try:
        from textual_serve.server import Server
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "openjiuwen serve requires textual-serve. "
            "Install with: pip install 'openjiuwen[tui]' "
            "(or: uv sync --extra tui after adding textual-serve)."
        ) from exc
    return Server


def run_serve(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    public_url: str | None = None,
    demo: bool = False,
    project: str | None = None,
    debug: bool = False,
    title: str | None = None,
) -> None:
    """Start textual-serve hosting the EventBus TUI in the browser."""
    server_cls = load_textual_serve_server()
    command = build_tui_command(demo=demo, project=project)
    # Propagate demo/project into child env as a belt-and-suspenders signal.
    if demo:
        os.environ[_SERVE_DEMO_ENV] = "1"
    if project:
        os.environ[_SERVE_PROJECT_ENV] = project

    pub = effective_public_url(host=host, port=port, public_url=public_url)
    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "title": title or PRODUCT_NAME,
    }
    if pub:
        kwargs["public_url"] = pub
    elif public_url:
        kwargs["public_url"] = public_url.rstrip("/")

    if host in {"0.0.0.0", "::", "[::]"} and not kwargs.get("public_url"):
        print(
            f"Warning: --host {host} binds all interfaces; pass "
            f"--public-url http://<reachable-host>:{port} so browsers "
            "get a usable link.",
            file=sys.stderr,
        )

    print(
        f"Serving {PRODUCT_NAME} TUI in the browser "
        f"(spawn: {command})",
        file=sys.stderr,
    )
    server = server_cls(command, **kwargs)
    server.serve(debug=debug)


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "build_tui_command",
    "effective_public_url",
    "entrypoint_argv",
    "load_textual_serve_server",
    "run_serve",
]

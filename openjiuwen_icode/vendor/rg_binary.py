# coding: utf-8
"""Resolve the iCode-vendored ripgrep binary for the current platform.

Search order used by callers / agent-core ``GrepTool``:

1. ``OPENJIUWEN_RG`` / ``ICODE_RG`` environment overrides
2. This package's ``vendor/rg/<platform>/rg``
3. ``PATH`` (``shutil.which("rg")``)

Harbor / LoLBench sandboxes often lack system ``rg``; shipping the binary
inside iCode removes that dependency.
"""
from __future__ import annotations

import os
import platform
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Optional


def platform_key(
    system: str | None = None,
    machine: str | None = None,
) -> Optional[str]:
    """Map ``platform.system()`` / ``machine()`` to a vendor directory name."""
    sys_name = (system or platform.system()).lower()
    mach = (machine or platform.machine()).lower()

    if mach in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif mach in {"aarch64", "arm64"}:
        arch = "arm64" if sys_name == "darwin" else "aarch64"
    else:
        return None

    if sys_name == "linux":
        return f"linux-{arch if arch != 'arm64' else 'aarch64'}"
    if sys_name == "darwin":
        return f"darwin-{arch}"
    if sys_name in {"windows", "win32", "win"}:
        if arch != "x86_64":
            return None
        return "windows-x86_64"
    return None


def vendor_rg_root() -> Path:
    """Return ``…/openjiuwen_icode/vendor/rg``."""
    return Path(__file__).resolve().parent / "rg"


def bundled_rg_path(
    system: str | None = None,
    machine: str | None = None,
) -> Optional[Path]:
    """Path to the vendored binary for this platform, if the file exists."""
    key = platform_key(system, machine)
    if not key:
        return None
    name = "rg.exe" if key.startswith("windows-") else "rg"
    path = vendor_rg_root() / key / name
    return path if path.is_file() else None


def _is_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt":
        return True
    return os.access(path, os.X_OK)


@lru_cache(maxsize=1)
def resolve_rg_binary() -> Optional[str]:
    """Best available ``rg`` absolute path, or ``None``."""
    for env_key in ("OPENJIUWEN_RG", "ICODE_RG"):
        raw = (os.environ.get(env_key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if _is_executable(path):
            return str(path.resolve())

    bundled = bundled_rg_path()
    if bundled is not None and _is_executable(bundled):
        return str(bundled.resolve())

    which = shutil.which("rg")
    return which


def ensure_rg_env() -> Optional[str]:
    """Set ``OPENJIUWEN_RG`` from the bundled binary when unset.

    Safe to call at iCode startup so agent-core ``GrepTool`` (which prefers
    this env var) finds the vendored binary without importing iCode.
    """
    existing = (os.environ.get("OPENJIUWEN_RG") or "").strip()
    if existing and _is_executable(Path(existing).expanduser()):
        return existing

    path = resolve_rg_binary()
    if path:
        os.environ.setdefault("OPENJIUWEN_RG", path)
    return path


__all__ = [
    "bundled_rg_path",
    "ensure_rg_env",
    "platform_key",
    "resolve_rg_binary",
    "vendor_rg_root",
]

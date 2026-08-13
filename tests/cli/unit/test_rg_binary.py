# coding: utf-8
"""Unit tests for vendored ripgrep resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openjiuwen_icode.vendor import rg_binary


@pytest.fixture(autouse=True)
def _clear_rg_cache(monkeypatch: pytest.MonkeyPatch):
    rg_binary.resolve_rg_binary.cache_clear()
    monkeypatch.delenv("OPENJIUWEN_RG", raising=False)
    monkeypatch.delenv("ICODE_RG", raising=False)
    yield
    rg_binary.resolve_rg_binary.cache_clear()


def test_platform_key_linux_x86_64() -> None:
    assert rg_binary.platform_key("Linux", "x86_64") == "linux-x86_64"
    assert rg_binary.platform_key("Linux", "amd64") == "linux-x86_64"


def test_platform_key_darwin_arm64() -> None:
    assert rg_binary.platform_key("Darwin", "arm64") == "darwin-arm64"
    assert rg_binary.platform_key("Darwin", "aarch64") == "darwin-arm64"


def test_platform_key_windows() -> None:
    assert rg_binary.platform_key("Windows", "AMD64") == "windows-x86_64"


def test_bundled_linux_binary_present_on_this_tree() -> None:
    # Fetched by scripts/fetch_rg.py; required for Harbor / offline use.
    path = rg_binary.vendor_rg_root() / "linux-x86_64" / "rg"
    assert path.is_file(), f"missing vendored rg at {path}; run scripts/fetch_rg.py"


def test_resolve_prefers_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "custom-rg"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("OPENJIUWEN_RG", str(fake))
    rg_binary.resolve_rg_binary.cache_clear()
    assert rg_binary.resolve_rg_binary() == str(fake.resolve())


def test_ensure_rg_env_sets_openjiuwen_rg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENJIUWEN_RG", raising=False)
    rg_binary.resolve_rg_binary.cache_clear()
    path = rg_binary.ensure_rg_env()
    assert path
    assert Path(path).is_file()
    assert os.environ.get("OPENJIUWEN_RG") == path

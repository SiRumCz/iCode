# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for browser TUI serve helpers."""

from __future__ import annotations

import builtins
import sys
import types

import pytest

from openjiuwen_icode.serve import (
    _looks_like_python,
    build_tui_command,
    effective_public_url,
    entrypoint_argv,
    load_textual_serve_server,
)


def test_build_tui_command_includes_demo() -> None:
    cmd = build_tui_command(demo=True)
    assert "tui" in cmd
    assert "--demo" in cmd


def test_build_tui_command_with_project() -> None:
    cmd = build_tui_command(project="/tmp/proj")
    assert "--project" in cmd
    assert "/tmp/proj" in cmd
    assert cmd.rstrip().endswith("tui") or " tui" in cmd


def test_effective_public_url_passthrough() -> None:
    assert (
        effective_public_url(
            host="0.0.0.0",
            port=8000,
            public_url="http://example:8000/",
        )
        == "http://example:8000"
    )


def test_effective_public_url_wildcard_without_override() -> None:
    assert (
        effective_public_url(host="0.0.0.0", port=8000, public_url=None)
        is None
    )


def test_effective_public_url_localhost_without_override() -> None:
    assert (
        effective_public_url(host="localhost", port=8000, public_url=None)
        is None
    )


def test_effective_public_url_ipv6_wildcard() -> None:
    assert effective_public_url(host="::", port=9, public_url=None) is None
    assert effective_public_url(host="[::]", port=9, public_url=None) is None


def test_looks_like_python() -> None:
    assert _looks_like_python("/usr/bin/python3.13")
    assert _looks_like_python("pypy3")
    assert not _looks_like_python("/usr/local/bin/icode")


def test_entrypoint_argv_python_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "executable", "/opt/bin/python3")
    assert entrypoint_argv() == ["/opt/bin/python3", "-m", "openjiuwen_icode"]


def test_entrypoint_argv_console_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "executable", "/usr/local/bin/icode")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/icode", "serve"])
    assert entrypoint_argv() == ["/usr/local/bin/icode"]


def test_load_textual_serve_server_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = object()
    mod = types.ModuleType("textual_serve.server")
    mod.Server = fake  # type: ignore[attr-defined]
    parent = types.ModuleType("textual_serve")
    monkeypatch.setitem(sys.modules, "textual_serve", parent)
    monkeypatch.setitem(sys.modules, "textual_serve.server", mod)
    assert load_textual_serve_server() is fake


def test_load_textual_serve_server_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _deny(name: str, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name == "textual_serve" or name.startswith("textual_serve."):
            raise ModuleNotFoundError(name)
        return real_import(name, globals, locals, fromlist, level)

    # Ensure a prior successful mock does not satisfy the import.
    for key in list(sys.modules):
        if key == "textual_serve" or key.startswith("textual_serve."):
            monkeypatch.delitem(sys.modules, key, raising=False)

    monkeypatch.setattr(builtins, "__import__", _deny)
    with pytest.raises(RuntimeError, match="textual-serve"):
        load_textual_serve_server()

# coding: utf-8
"""Packaging metadata for openjiuwen-icode."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _load_pyproject() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    with (repo_root / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_build_system() -> None:
    pyproject = _load_pyproject()
    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"


def test_console_scripts() -> None:
    pyproject = _load_pyproject()
    scripts = pyproject["project"]["scripts"]
    assert scripts["openjiuwen"] == "openjiuwen_icode.cli:cli"
    assert scripts["icode"] == "openjiuwen_icode.cli:cli"


def test_depends_on_openjiuwen_sdk() -> None:
    pyproject = _load_pyproject()
    deps = pyproject["project"]["dependencies"]
    assert any(d.startswith("openjiuwen") for d in deps)

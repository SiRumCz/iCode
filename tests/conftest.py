# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Root pytest hooks (HTML report + coverage summary)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


def _cov_plugin(config: Any) -> Any | None:
    pm = config.pluginmanager
    if not pm.hasplugin("_cov"):
        return None
    return pm.getplugin("_cov")


def _cov_html_dir(config: Any) -> Path | None:
    """Return directory of ``--cov-report=html:DIR`` if configured."""
    reports = config.getoption("cov_report", default=None) or {}
    if isinstance(reports, dict):
        if "html" not in reports:
            return None
        dest = reports.get("html")
        return Path(dest) if dest else Path("htmlcov")
    # Older pytest-cov shapes may expose a list of "html" / "html:DIR".
    for item in reports:
        text = str(item)
        if text == "html":
            return Path("htmlcov")
        if text.startswith("html:"):
            return Path(text.split(":", 1)[1])
    return None


def _html_report_path(config: Any) -> Path | None:
    raw = config.getoption("htmlpath", default=None)
    if not raw:
        return None
    return Path(str(raw))


def _relative_coverage_href(config: Any) -> str | None:
    """Href from the pytest-html report to coverage ``index.html``."""
    cov_dir = _cov_html_dir(config)
    html_path = _html_report_path(config)
    if cov_dir is None or html_path is None:
        return None
    report_dir = html_path.resolve().parent
    target = (Path.cwd() / cov_dir / "index.html").resolve()
    try:
        return os.path.relpath(target, report_dir).replace(os.sep, "/")
    except ValueError:
        return target.as_uri()


def _coverage_snapshot(config: Any) -> tuple[float, int, int] | None:
    """Return ``(percent, covered_lines, total_lines)`` from pytest-cov."""
    plugin = _cov_plugin(config)
    if plugin is None or plugin.cov_total is None:
        return None

    percent = float(plugin.cov_total)
    covered = total = 0
    report_text = ""
    if getattr(plugin, "cov_report", None) is not None:
        report_text = plugin.cov_report.getvalue()
    match = re.search(
        r"^TOTAL\s+(\d+)\s+(\d+)\s+(\d+)%",
        report_text,
        flags=re.MULTILINE,
    )
    if match:
        total = int(match.group(1))
        missing = int(match.group(2))
        covered = max(0, total - missing)
        percent = float(match.group(3))
    return percent, covered, total


def pytest_html_results_summary(
    prefix: list[str],
    summary: list[str],
    postfix: list[str],
    session: Any,
) -> None:
    """Embed a coverage blurb (+ link) at the top of the HTML summary."""
    del summary, postfix  # unused hook args
    snap = _coverage_snapshot(session.config)
    if snap is None:
        return

    percent, covered, total = snap
    href = _relative_coverage_href(session.config)
    if href:
        link = (
            f'<a href="{href}" id="coverage-report-link">'
            "Open detailed coverage report</a>"
        )
        note = f'<p style="margin:0.4em 0 0;">{link}</p>'
    else:
        note = (
            '<p style="margin:0.4em 0 0;color:#666;">'
            "Re-run with <code>--cov-report=html:…</code> "
            "to generate a detailed coverage report.</p>"
        )

    counts = ""
    if total:
        counts = f" &mdash; {covered:,} / {total:,} statements covered"

    prefix.append(
        '<div id="coverage-summary" style="'
        "margin:0.75em 0 1em;padding:0.75em 1em;"
        "border:1px solid #e6e6e6;border-radius:6px;"
        'background:#f8faf8;color:#222;">'
        "<h3 style=\"margin:0 0 0.35em;font-size:14px;\">"
        "Code coverage</h3>"
        f'<p style="margin:0;font-size:13px;">'
        f"<strong>{percent:.0f}%</strong>{counts}</p>"
        f"{note}"
        "</div>"
    )

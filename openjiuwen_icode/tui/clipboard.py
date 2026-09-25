# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Clipboard helpers for the EventBus Textual TUI (Chrys-style dual write)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from typing import Any, Protocol

logger = logging.getLogger(__name__)

OSC52_COPY_MAX_BYTES = 64 * 1024


class ClipboardApp(Protocol):
    def copy_to_clipboard(self, text: str) -> None: ...


def _clipboard_safe_text(text: str) -> str:
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def os_clipboard_copy(text: str) -> bool:
    """Best-effort copy to the host OS clipboard (pbcopy / Win32 / xclip|xsel)."""
    text = _clipboard_safe_text(text)
    try:
        if sys.platform == "darwin":
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=2,
            )
            return proc.returncode == 0
        if sys.platform == "win32":
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Set-Clipboard -Value $input",
                ],
                input=text,
                text=True,
                check=False,
                capture_output=True,
                timeout=5,
            )
            return proc.returncode == 0
        # Linux / BSD
        for cmd in (
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
            ["wl-copy"],
        ):
            if shutil.which(cmd[0]) is None:
                continue
            proc = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=2,
            )
            if proc.returncode == 0:
                return True
    except Exception:  # noqa: BLE001
        logger.debug("OS clipboard copy failed", exc_info=True)
    return False


def copy_text_to_clipboards(
    app: ClipboardApp | Any,
    text: str,
    *,
    max_terminal_bytes: int = OSC52_COPY_MAX_BYTES,
) -> bool:
    """Copy to Textual OSC-52 clipboard and the host OS clipboard.

    Returns True if at least one path succeeded.
    """
    text = _clipboard_safe_text(text)
    if not text:
        return False
    ok = False
    payload = text.encode("utf-8")
    if len(payload) <= max_terminal_bytes:
        try:
            app.copy_to_clipboard(text)
            ok = True
        except Exception:  # noqa: BLE001
            logger.debug("Terminal clipboard copy failed", exc_info=True)
    if os_clipboard_copy(text):
        ok = True
    return ok

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Slash-command suggestion overlay for the EventBus TUI."""

from __future__ import annotations

from textual.widgets import OptionList
from textual.widgets.option_list import Option

# Keep in sync with host/commands.py help surface.
SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "Show help"),
    ("/status", "Model + token usage"),
    ("/models", "Open Models modal / switch model"),
    ("/agents", "List or switch agent profiles"),
    ("/skills", "List loaded skills"),
    ("/subagents", "Background sub-agents + audit"),
    ("/sessions", "Open Sessions modal / list"),
    ("/title", "Show or set session title"),
    ("/new", "Start a new session"),
    ("/resume", "Resume a saved session"),
    ("/fork", "Clone session to a new id"),
    ("/export", "Export OpenCode-compatible transcript"),
    ("/compact", "Request context compaction"),
    ("/mcp", "MCP config note"),
    ("/clear", "Clear transcript"),
    ("/cwd", "iCode home + directories + tool cwd"),
    ("/directories", "List project directories (primary *)"),
    ("/directories add", "Pick a folder to add (TUI browser)"),
    ("/directories use", "Set primary directory"),
    ("/workdirs", "Same as /directories"),
]


def _option_id(cmd: str) -> str:
    """CSS-safe option id (Option ids must be valid identifiers)."""
    return "cmd-" + cmd.strip("/").replace(" ", "-").replace(".", "-")


class SuggestionList(OptionList):
    """Filterable slash command list shown above the input."""

    DEFAULT_CSS = """
    SuggestionList {
        height: auto;
        max-height: 8;
        width: 100%;
        border: solid $accent;
        display: none;
        background: $surface;
    }
    SuggestionList.-visible {
        display: block;
    }
    """

    # Keep focus on the Input; Tab should complete, not move here.
    can_focus = False

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._query = ""
        self._id_to_cmd: dict[str, str] = {}
        self._extra_commands: list[tuple[str, str]] = []

    def set_extra_commands(
        self, commands: list[tuple[str, str]]
    ) -> None:
        """Attach dynamic commands (e.g. discovered skills)."""
        # Skip builtins already listed.
        builtin = {cmd for cmd, _ in SLASH_COMMANDS}
        self._extra_commands = [
            (cmd, desc)
            for cmd, desc in commands
            if cmd not in builtin
        ]

    def _all_commands(self) -> list[tuple[str, str]]:
        return [*SLASH_COMMANDS, *self._extra_commands]

    def show_for(self, text: str) -> None:
        """Update visibility/filter from the current input value."""
        if not text.startswith("/") or "\n" in text:
            self.hide()
            return
        self._query = text
        needle = text.lower()
        matches = [
            (cmd, desc)
            for cmd, desc in self._all_commands()
            if cmd.startswith(needle) or needle[1:] in cmd
        ]
        self.clear_options()
        self._id_to_cmd.clear()
        if not matches:
            self.hide()
            return
        for cmd, desc in matches[:12]:
            oid = _option_id(cmd)
            # Option ids must be unique; skill names can collide with
            # sanitization — suffix with a short hash of the raw cmd.
            if oid in self._id_to_cmd:
                oid = f"{oid}-{abs(hash(cmd)) % 10_000}"
            self._id_to_cmd[oid] = cmd
            self.add_option(Option(f"{cmd}  — {desc}", id=oid))
        self.add_class("-visible")
        if self.option_count:
            self.highlighted = 0

    def hide(self) -> None:
        self.remove_class("-visible")
        self.clear_options()
        self._id_to_cmd.clear()

    @property
    def is_open(self) -> bool:
        return self.has_class("-visible")

    def selected_command(self) -> str | None:
        if not self.is_open or self.highlighted is None:
            return None
        try:
            opt = self.get_option_at_index(self.highlighted)
        except Exception:  # noqa: BLE001
            return None
        if opt.id is None:
            return None
        return self._id_to_cmd.get(str(opt.id))

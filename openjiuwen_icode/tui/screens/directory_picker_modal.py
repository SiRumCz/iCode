# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Directory picker modal for /directories add (file-explorer style)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Label, Static, Tree
from textual.widgets._directory_tree import DirEntry
from textual.widgets._tree import TreeNode


def default_browse_root(start: str | Path | None = None) -> Path:
    """Pick an existing directory to open in the tree."""
    if start:
        raw = Path(start).expanduser()
        try:
            resolved = raw.resolve()
        except OSError:
            resolved = raw
        if resolved.is_dir():
            return resolved
        parent = resolved.parent
        if parent.is_dir():
            return parent.resolve()
    return Path.home().resolve()


def path_from_tree_node(node: TreeNode[DirEntry] | None) -> Path | None:
    """Directory to add for a highlighted tree node (files → parent folder)."""
    if node is None or node.data is None:
        return None
    path = node.data.path
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    if resolved.is_dir():
        return resolved
    try:
        return resolved.parent.resolve()
    except OSError:
        return None


class DirectoryPickerModal(ModalScreen[dict[str, Any] | None]):
    """Browse folders and pick one to register as a project directory.

    Dismiss payload:
    * ``{"action": "select", "path": "/abs/..."}``
    * ``None`` — cancelled
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Close"),
        Binding("ctrl+enter", "confirm", "Add folder"),
    ]

    DEFAULT_CSS = """
    DirectoryPickerModal {
        align: center middle;
    }
    DirectoryPickerModal > #picker-root {
        width: 92%;
        max-width: 100;
        height: 82%;
        max-height: 36;
        border: round $primary;
        background: $surface;
        padding: 0 1 1 1;
    }
    DirectoryPickerModal #picker-title {
        text-style: bold;
        height: 1;
        margin: 1 0;
        color: $primary;
    }
    DirectoryPickerModal #picker-hint {
        height: auto;
        color: $text-muted;
        margin-bottom: 1;
    }
    DirectoryPickerModal #dir-tree {
        width: 100%;
        height: 1fr;
        min-height: 10;
        border: solid $accent 40%;
    }
    DirectoryPickerModal #path-row {
        height: auto;
        margin: 1 0;
    }
    DirectoryPickerModal #path-label {
        height: auto;
        color: $text-muted;
    }
    DirectoryPickerModal #selected-path {
        height: auto;
        text-style: bold;
    }
    DirectoryPickerModal #footer {
        height: 3;
        margin-top: 1;
    }
    DirectoryPickerModal #footer Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        *,
        start_path: str | Path | None = None,
        existing_dirs: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._start = default_browse_root(start_path)
        self._existing = {str(Path(p).expanduser().resolve()) for p in (existing_dirs or [])}
        self._selected: Path = self._start

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-root") as root:
            root.border_title = "Add project directory"
            yield Label("Add project directory", id="picker-title")
            yield Static(
                "Choose a folder to register. ↑↓ navigate, Enter expands. "
                "Ctrl+Enter or Add folder confirms.",
                id="picker-hint",
            )
            yield DirectoryTree(str(self._start), id="dir-tree")
            with Vertical(id="path-row"):
                yield Static("Selected folder:", id="path-label")
                yield Static(str(self._start), id="selected-path")
            with Horizontal(id="footer"):
                yield Button("Parent folder", id="parent", variant="default")
                yield Button("Add folder", id="confirm", variant="success")
                yield Button("Cancel", id="cancel", variant="warning")

    def on_mount(self) -> None:
        self._refresh_path_label()
        self.query_one("#dir-tree", DirectoryTree).focus()

    def _refresh_path_label(self) -> None:
        text = str(self._selected)
        if str(self._selected) in self._existing:
            text += "  (already registered)"
        self.query_one("#selected-path", Static).update(text)

    def _set_selected(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            self._selected = path.resolve()
        except OSError:
            self._selected = path
        self._refresh_path_label()

    @on(Tree.NodeHighlighted, "#dir-tree")
    def _on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        self._set_selected(path_from_tree_node(event.node))

    @on(DirectoryTree.DirectorySelected, "#dir-tree")
    def _on_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self._set_selected(path_from_tree_node(event.node))

    @on(Button.Pressed, "#parent")
    def _on_parent(self, event: Button.Pressed) -> None:
        tree = self.query_one("#dir-tree", DirectoryTree)
        base = self._selected
        parent = base.parent
        if parent == base:
            return
        tree.path = str(parent)
        self._set_selected(parent)

    @on(Button.Pressed, "#confirm")
    def _on_confirm_button(self, event: Button.Pressed) -> None:
        self.action_confirm()

    @on(Button.Pressed, "#cancel")
    def _on_cancel_button(self, event: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_confirm(self) -> None:
        path = self._selected
        if not path.is_dir():
            self.notify(
                "Not a directory.",
                severity="error",
                title="Add directory",
            )
            return
        self.dismiss({"action": "select", "path": str(path)})

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Sessions browser modal (Chrys-style DataTable + hover tooltips)."""

from __future__ import annotations

import contextlib
from typing import Any, ClassVar

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from openjiuwen_icode.tui.screens.sessions_presenter import (
    COLUMNS,
    SessionRow,
    build_session_rows,
    column_by_key,
    row_tooltip_lines,
    short_id,
)

_SEARCH_DEBOUNCE = 0.15


class _SessionTable(DataTable):
    """DataTable with per-row hover tooltips (Chrys pattern)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._row_tooltips: dict[int, Text] = {}
        self._last_hover_row: int = -1

    def set_row_tooltips(self, tooltips: dict[int, Text]) -> None:
        self._row_tooltips = tooltips

    def _on_mouse_move(self, event: Any) -> None:
        # Do not call super(): Textual still dispatches the base handler.
        meta = getattr(getattr(event, "style", None), "meta", None) or {}
        if meta and "row" in meta:
            row_idx = int(meta["row"])
            if row_idx != self._last_hover_row:
                self._last_hover_row = row_idx
                tip = self._row_tooltips.get(row_idx)
                self.call_later(self._apply_row_tooltip, tip)
        else:
            self._last_hover_row = -1
            self.tooltip = None

    def _apply_row_tooltip(self, tip: Text | None) -> None:
        self.tooltip = tip
        if tip is not None:
            with contextlib.suppress(Exception):
                self.screen._handle_tooltip_timer(self)  # type: ignore[attr-defined]


class _SearchInput(Input):
    """Escape clears query, then posts Escaped when already empty."""

    class Escaped(Message):
        """Escape pressed on an empty search box."""

    async def _on_key(self, event: Any) -> None:
        if getattr(event, "key", None) != "escape":
            return
        event.stop()
        event.prevent_default()
        if self.value:
            self.value = ""
        else:
            self.post_message(self.Escaped())


class SessionsModal(ModalScreen[dict[str, Any] | None]):
    """Browse persisted sessions: search, sort, hover info, resume/delete.

    Dismiss payload:
    * ``{"action": "resume", "id": "..."}``
    * ``{"action": "deleted", "id": "..."}``
    * ``None`` — closed without action
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Close"),
        Binding("delete", "delete_session", "Delete"),
    ]

    DEFAULT_CSS = """
    SessionsModal {
        align: center middle;
    }
    SessionsModal > #sessions-root {
        width: 90%;
        max-width: 120;
        height: 80%;
        max-height: 34;
        border: round $primary;
        background: $surface;
        padding: 0 1 1 1;
    }
    SessionsModal > #sessions-root.-empty {
        width: 50%;
        max-width: 60;
        height: auto;
        max-height: 12;
    }
    SessionsModal #sessions-title {
        text-style: bold;
        height: 1;
        margin: 1 0;
        color: $primary;
    }
    SessionsModal #empty-note {
        height: auto;
        color: $text-muted;
        margin: 1 0;
    }
    SessionsModal #sessions-table {
        width: 100%;
        height: 1fr;
        min-height: 6;
    }
    SessionsModal #footer {
        height: 3;
        margin-top: 1;
    }
    SessionsModal #search-box {
        width: 1fr;
        height: 3;
        margin-right: 1;
        border: solid $accent;
    }
    SessionsModal #search {
        width: 1fr;
        border: none;
        background: $panel;
    }
    SessionsModal #buttons {
        width: auto;
        height: 3;
        align: right middle;
    }
    SessionsModal #buttons Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        sessions: list[dict[str, Any]] | None = None,
        *,
        current_session_id: str = "",
        on_delete: Any | None = None,
    ) -> None:
        super().__init__()
        self._sessions: list[dict[str, Any]] = list(sessions or [])
        self._current_session_id = current_session_id
        self._on_delete = on_delete
        self._rows: list[SessionRow] = []
        self._session_ids: list[str] = []
        self._sort_column = "updated"
        self._sort_reverse = True
        self._search_timer: Any = None
        self._cursor_initialized = False
        self._deleted_current = False

    def compose(self) -> ComposeResult:
        with Vertical(id="sessions-root") as root:
            root.border_title = "Sessions"
            yield Label("Sessions", id="sessions-title")
            yield Static("No saved sessions.", id="empty-note")
            table = _SessionTable(id="sessions-table", cursor_type="row")
            table.zebra_stripes = True
            yield table
            with Horizontal(id="footer"):
                with Horizontal(id="search-box"):
                    yield _SearchInput(
                        placeholder=(
                            "Search sessions… "
                            "(matches any column & your prompts)"
                        ),
                        id="search",
                    )
                with Horizontal(id="buttons"):
                    yield Button(
                        "Resume",
                        id="resume",
                        variant="success",
                        disabled=True,
                    )
                    yield Button(
                        "Delete",
                        id="delete",
                        variant="error",
                        disabled=True,
                    )
                    yield Button("Close", id="cancel", variant="warning")

    def on_mount(self) -> None:
        self._render_table()
        table = self.query_one("#sessions-table", _SessionTable)
        if table.row_count:
            table.focus()
        else:
            self.query_one("#search", _SearchInput).focus()

    def _render_table(self) -> None:
        table = self.query_one("#sessions-table", _SessionTable)
        query = self.query_one("#search", _SearchInput).value
        previous = self._get_selected_session_id()
        rows = build_session_rows(
            self._sessions,
            sort_column=self._sort_column,
            sort_reverse=self._sort_reverse,
            query=query,
        )
        self._rows = rows
        self._session_ids = [str(r.meta.get("id") or "") for r in rows]

        table.clear(columns=True)
        for column in COLUMNS:
            label = column.label
            if column.key == self._sort_column:
                label += " ↓" if self._sort_reverse else " ↑"
            width = column.width
            if width is not None:
                width = max(width, len(label))
            table.add_column(Text(label), width=width, key=column.key)

        highlight = query.strip()
        match_style = Style(reverse=True, color="yellow")
        tooltips: dict[int, Text] = {}
        for idx, row in enumerate(rows):
            sid = str(row.meta.get("id") or "")
            table.add_row(
                *self._row_texts(row, highlight, match_style),
                key=sid,
            )
            tooltips[idx] = Text("\n".join(row_tooltip_lines(row)))
        table.set_row_tooltips(tooltips)

        has_rows = bool(rows)
        self.query_one("#resume", Button).disabled = not has_rows
        self.query_one("#delete", Button).disabled = not has_rows
        self.query_one("#empty-note").display = not has_rows and not highlight
        table.display = has_rows
        self.query_one("#footer").display = True
        root = self.query_one("#sessions-root")
        if has_rows or highlight:
            root.remove_class("-empty")
        else:
            root.add_class("-empty")
        count = (
            f"{len(rows)}/{len(self._sessions)}"
            if highlight
            else f"{len(self._sessions)}"
        )
        root.border_subtitle = f"{count} sessions" if self._sessions else ""

        self._restore_cursor(previous)

    def _row_texts(
        self, row: SessionRow, highlight: str, match_style: Style
    ) -> list[Text]:
        texts: list[Text] = []
        for column in COLUMNS:
            value = Text(
                row.cells[column.key],
                justify="right" if column.numeric else "left",
            )
            if highlight:
                value.highlight_words(
                    [highlight], match_style, case_sensitive=False
                )
            texts.append(value)
        return texts

    def _restore_cursor(self, previous_selected: str | None) -> None:
        table = self.query_one("#sessions-table", _SessionTable)
        if table.row_count == 0:
            return
        target = previous_selected if previous_selected in self._session_ids else None
        if (
            target is None
            and not self._cursor_initialized
            and self._current_session_id in self._session_ids
        ):
            target = self._current_session_id
            self._cursor_initialized = True
        if target is not None:
            table.move_cursor(row=self._session_ids.index(target))
        else:
            table.move_cursor(row=0)
            self._cursor_initialized = True

    def _get_selected_session_id(self) -> str | None:
        table = self.query_one("#sessions-table", _SessionTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:  # noqa: BLE001
            return None
        if row_key is not None and row_key.value is not None:
            return str(row_key.value)
        return None

    @on(DataTable.HeaderSelected, "#sessions-table")
    def _on_header_selected(self, event: DataTable.HeaderSelected) -> None:
        key = event.column_key.value
        if key is None:
            return
        column = column_by_key(str(key))
        if self._sort_column == column.key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column.key
            self._sort_reverse = column.default_reverse
        self._render_table()

    @on(Input.Changed, "#search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(_SEARCH_DEBOUNCE, self._render_table)

    @on(Input.Submitted, "#search")
    def _on_search_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#sessions-table", _SessionTable).focus()

    @on(_SearchInput.Escaped)
    def _on_search_escaped(self, event: _SearchInput.Escaped) -> None:
        self.query_one("#sessions-table", _SessionTable).focus()

    @on(DataTable.RowSelected, "#sessions-table")
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        session_id = self._get_selected_session_id()
        if session_id:
            self.dismiss({"action": "resume", "id": session_id})

    @on(Button.Pressed, "#resume")
    def _on_resume(self, event: Button.Pressed) -> None:
        session_id = self._get_selected_session_id()
        if session_id:
            self.dismiss({"action": "resume", "id": session_id})

    @on(Button.Pressed, "#cancel")
    def _on_cancel(self, event: Button.Pressed) -> None:
        self.action_cancel()

    @on(Button.Pressed, "#delete")
    def _on_delete_button(self, event: Button.Pressed) -> None:
        self.action_delete_session()

    def action_cancel(self) -> None:
        if self._deleted_current:
            self.dismiss({"action": "deleted_current"})
        else:
            self.dismiss(None)

    def action_delete_session(self) -> None:
        session_id = self._get_selected_session_id()
        if not session_id:
            return
        from openjiuwen_icode.tui.screens.confirm_modal import (
            ConfirmModal,
        )

        dialog = ConfirmModal(
            title="Delete Session",
            message=(
                f'Delete session "{short_id(session_id)}"?\n\n'
                "This cannot be undone."
            ),
            confirm_label="Delete",
        )
        self.app.push_screen(dialog, callback=self._on_delete_confirmed)

    def _on_delete_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        session_id = self._get_selected_session_id()
        if not session_id:
            return
        if callable(self._on_delete):
            try:
                self._on_delete(session_id)
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", title="Delete failed")
                return
        was_current = session_id == self._current_session_id
        self._sessions = [
            s for s in self._sessions if str(s.get("id")) != session_id
        ]
        if was_current:
            self._deleted_current = True
            self._current_session_id = ""
        self._render_table()
        self.notify(
            f"Deleted {session_id}",
            title="Sessions",
            severity="information",
        )

# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Models configuration modal (Chrys-style list + form MVP)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from openjiuwen_icode.host.profiles import (
    MODELS_DIR,
    current_model_from_settings,
    delete_model_profile,
    list_model_profiles,
    save_model_profile,
    unique_model_profile_id,
)


def _option_id(model_id: str) -> str:
    return "m-" + model_id.replace(" ", "-")


class ModelsModal(ModalScreen[dict[str, Any] | None]):
    """List / edit / create / duplicate model profiles and optionally switch.

    Dismiss payload:
    * ``{"action": "use", "id": "..."}`` — apply selection
    * ``{"action": "saved", "id": "..."}`` — profile written
    * ``{"action": "deleted", "id": "..."}`` — profile removed
    * ``None`` — closed without action
    """

    DEFAULT_CSS = """
    ModelsModal {
        align: center middle;
    }
    ModelsModal > #models-root {
        width: 90%;
        max-width: 110;
        height: 80%;
        max-height: 32;
        border: solid $primary;
        background: $surface;
        padding: 1;
    }
    ModelsModal #models-title {
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }
    ModelsModal #models-body {
        height: 1fr;
    }
    ModelsModal #list-pane {
        width: 36%;
        height: 1fr;
        border: solid $primary 40%;
        padding: 0 1;
    }
    ModelsModal #form-pane {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }
    ModelsModal #model-list {
        height: 1fr;
        border: none;
    }
    ModelsModal .field-label {
        height: 1;
        color: $text-muted;
        margin-top: 1;
    }
    ModelsModal Input {
        margin-bottom: 0;
    }
    ModelsModal #form-hint {
        height: auto;
        color: $text-muted;
        margin: 1 0;
    }
    ModelsModal #list-actions,
    ModelsModal #form-actions {
        height: auto;
        margin-top: 1;
        align: left middle;
    }
    ModelsModal Button {
        margin-right: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(
        self,
        *,
        models_dir: Path | None = None,
        current_model: str | None = None,
    ) -> None:
        super().__init__()
        self._models_dir = models_dir or MODELS_DIR
        self._current = current_model or current_model_from_settings()["model"]
        self._profiles: list[dict[str, Any]] = []
        self._id_map: dict[str, str] = {}
        self._selected_id: str | None = None
        self._creating = False
        self._pending_api_key: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="models-root"):
            yield Label("Model profiles", id="models-title")
            with Horizontal(id="models-body"):
                with Vertical(id="list-pane"):
                    yield OptionList(id="model-list")
                    with Horizontal(id="list-actions"):
                        yield Button("New", id="btn-new")
                        yield Button("Duplicate", id="btn-duplicate")
                        yield Button("Delete", id="btn-delete", variant="error")
                with VerticalScroll(id="form-pane"):
                    yield Static("Label", classes="field-label")
                    yield Input(placeholder="Display name", id="field-label")
                    yield Static("Model name", classes="field-label")
                    yield Input(
                        placeholder="API model id, e.g. deepseek-v4-pro",
                        id="field-id",
                    )
                    yield Static("Provider", classes="field-label")
                    yield Input(
                        placeholder="OpenAI / DashScope / …",
                        id="field-provider",
                    )
                    yield Static("API base", classes="field-label")
                    yield Input(
                        placeholder="https://api.openai.com/v1",
                        id="field-api-base",
                    )
                    yield Static(
                        "API key env var name "
                        "(e.g. OPENJIUWEN_API_KEY — not the secret itself)",
                        classes="field-label",
                    )
                    yield Input(
                        placeholder="OPENJIUWEN_API_KEY",
                        id="field-api-key-env",
                    )
                    yield Static(
                        "Headers (JSON object)", classes="field-label"
                    )
                    yield Input(
                        placeholder='{"X-Custom":"value"}',
                        id="field-headers",
                    )
                    yield Static(
                        "extra_body (JSON object)", classes="field-label"
                    )
                    yield Input(
                        placeholder='{"temperature":0.2}',
                        id="field-extra-body",
                    )
                    yield Static(
                        "Model name is the API model id. "
                        "Put the API key in ~/.icode/settings.json "
                        "(apiKey) or an env var named in "
                        "'API key env var' — do not paste sk-… into that "
                        "field. Duplicate copies the current form into a "
                        "new id; Save writes ~/.icode/models/<name>.json",
                        id="form-hint",
                    )
                    with Horizontal(id="form-actions"):
                        yield Button(
                            "Use", id="btn-use", variant="success"
                        )
                        yield Button("Save", id="btn-save", variant="primary")
                        yield Button("Close", id="btn-close")

    def on_mount(self) -> None:
        self._reload_list(select_id=self._current)

    def _reload_list(self, *, select_id: str | None = None) -> None:
        listing = self.query_one("#model-list", OptionList)
        listing.clear_options()
        self._id_map.clear()
        self._profiles = list_model_profiles(models_dir=self._models_dir)
        highlight = 0
        for i, row in enumerate(self._profiles):
            oid = _option_id(str(row["id"]))
            self._id_map[oid] = str(row["id"])
            mark = "*" if row["id"] == self._current else " "
            listing.add_option(
                Option(
                    f"{mark} {row['id']}  [{row.get('provider')}]",
                    id=oid,
                )
            )
            if select_id and row["id"] == select_id:
                highlight = i
        if self._profiles:
            listing.highlighted = highlight
            self._load_profile(self._profiles[highlight])
        else:
            self._blank_form()

    def _load_profile(self, row: dict[str, Any]) -> None:
        self._creating = False
        self._selected_id = str(row["id"])
        self.query_one("#field-id", Input).value = str(row.get("id") or "")
        self.query_one("#field-label", Input).value = str(row.get("label") or "")
        self.query_one("#field-provider", Input).value = str(
            row.get("provider") or ""
        )
        self.query_one("#field-api-base", Input).value = str(
            row.get("apiBase") or ""
        )
        # Prefer env-var name; fall back to blank (literal apiKey stays on disk).
        self.query_one("#field-api-key-env", Input).value = str(
            row.get("api_key_env") or ""
        )
        headers = row.get("headers") or {}
        self.query_one("#field-headers", Input).value = (
            json.dumps(headers, ensure_ascii=False)
            if headers
            else ""
        )
        extra = row.get("extra_body") or {}
        self.query_one("#field-extra-body", Input).value = (
            json.dumps(extra, ensure_ascii=False) if extra else ""
        )
        for field_id in (
            "field-id",
            "field-label",
            "field-provider",
            "field-api-base",
            "field-api-key-env",
            "field-headers",
            "field-extra-body",
        ):
            self.query_one(f"#{field_id}", Input).disabled = False
        self.query_one("#form-hint", Static).update(
            f"Profile → {row.get('path') or self._models_dir}"
        )

    def _blank_form(self) -> None:
        self._creating = True
        self._selected_id = None
        for field_id in (
            "field-id",
            "field-label",
            "field-provider",
            "field-api-base",
            "field-api-key-env",
            "field-headers",
            "field-extra-body",
        ):
            widget = self.query_one(f"#{field_id}", Input)
            widget.disabled = False
            widget.value = ""
        self.query_one("#field-provider", Input).value = "OpenAI"
        self.query_one("#form-hint", Static).update(
            "New profile — Label is display-only; Model name is the API model."
        )

    def _duplicate_selected(self) -> None:
        """Copy the current form into a new unsaved profile with a unique id."""
        payload = self._form_payload()
        source_id = payload["id"] or self._selected_id or "model"
        if not payload["id"] and self._selected_id:
            # Form empty/incomplete — reload from selected profile first.
            row = next(
                (r for r in self._profiles if r["id"] == self._selected_id),
                None,
            )
            if row is None:
                self.notify("Select a profile to duplicate", severity="warning")
                return
            self._load_profile(row)
            payload = self._form_payload()
            source_id = str(row["id"])

        new_id = unique_model_profile_id(
            source_id, models_dir=self._models_dir
        )
        # Preserve apiKey from the source profile when form only has env field.
        source = next(
            (r for r in self._profiles if r["id"] == source_id), None
        )
        self._creating = True
        self._selected_id = None
        self.query_one("#field-id", Input).value = new_id
        label = payload.get("label") or source_id
        self.query_one("#field-label", Input).value = f"{label} (copy)"
        if source and source.get("apiKey") and not payload.get("api_key_env"):
            # Keep literal key on the pending save via form hint; attach on save.
            self._pending_api_key = str(source["apiKey"])
        else:
            self._pending_api_key = None
        self.query_one("#form-hint", Static).update(
            f"Duplicated from {source_id!r} — edit Model name if needed, then Save."
        )
        self.query_one("#field-id", Input).focus()
        self.notify(f"Duplicated as {new_id} (not saved yet)")

    def _form_payload(self) -> dict[str, Any]:
        headers_raw = self.query_one("#field-headers", Input).value.strip()
        extra_raw = self.query_one("#field-extra-body", Input).value.strip()
        payload: dict[str, Any] = {
            "id": self.query_one("#field-id", Input).value.strip(),
            "label": self.query_one("#field-label", Input).value.strip(),
            "provider": self.query_one("#field-provider", Input).value.strip()
            or "OpenAI",
            "apiBase": self.query_one("#field-api-base", Input).value.strip()
            or None,
            "api_key_env": self.query_one(
                "#field-api-key-env", Input
            ).value.strip()
            or None,
            "headers": headers_raw or None,
            "extra_body": extra_raw or None,
        }
        pending = getattr(self, "_pending_api_key", None)
        if pending and not payload.get("api_key_env"):
            payload["apiKey"] = pending
        return payload

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id != "model-list":
            return
        oid = str(event.option.id) if event.option.id else ""
        model_id = self._id_map.get(oid)
        if not model_id:
            return
        for row in self._profiles:
            if row["id"] == model_id:
                self._pending_api_key = None
                self._load_profile(row)
                break

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss(None)
            return
        if bid == "btn-new":
            self._pending_api_key = None
            self._blank_form()
            self.query_one("#field-id", Input).focus()
            return
        if bid == "btn-duplicate":
            self._duplicate_selected()
            return
        if bid == "btn-delete":
            self._delete_selected()
            return
        if bid == "btn-save":
            self._save_form()
            return
        if bid == "btn-use":
            self._use_selected()
            return

    def _delete_selected(self) -> None:
        model_id = self._selected_id
        if not model_id:
            self.notify("Nothing to delete", severity="warning")
            return
        if not delete_model_profile(model_id, models_dir=self._models_dir):
            self.notify("Profile not found", severity="error")
            return
        self.notify(f"Deleted {model_id}")
        next_id = self._current if self._current != model_id else None
        self._reload_list(select_id=next_id)

    def _save_form(self) -> None:
        payload = self._form_payload()
        if not payload["id"]:
            self.notify("Model name is required", severity="error")
            return
        try:
            path = save_model_profile(payload, models_dir=self._models_dir)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self._pending_api_key = None
        self.notify(f"Saved {path.name}")
        self._reload_list(select_id=payload["id"])

    def _use_selected(self) -> None:
        payload = self._form_payload()
        model_id = payload["id"] or self._selected_id
        if not model_id:
            self.notify("Select a profile first", severity="warning")
            return
        # Save before use so switch finds apiBase / keys.
        if payload["id"]:
            try:
                save_model_profile(payload, models_dir=self._models_dir)
            except ValueError as exc:
                self.notify(str(exc), severity="error")
                return
            self._pending_api_key = None
        self.dismiss({"action": "use", "id": model_id})

    def action_cancel(self) -> None:
        self.dismiss(None)

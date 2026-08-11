# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for /fork session cloning."""

from __future__ import annotations

import json
from pathlib import Path

from openjiuwen_icode.storage.event_log import event_log_path
from openjiuwen_icode.storage.session_store import SessionStore


class TestForkSession:
    def test_fork_copies_messages_and_metadata(self, tmp_path: Path) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("cli-src", "gpt-4o", agent_profile="code")
        store.add_message("user", "hello")
        store.add_message("assistant", "world")
        store.set_title("My chat", source="manual", force=True)

        forked = store.fork_session("cli-src", "cli-new")

        assert forked.session_id == "cli-new"
        assert forked.forked_from == "cli-src"
        assert forked.model == "gpt-4o"
        assert forked.agent_profile == "code"
        assert len(forked.messages) == 2
        assert forked.title.endswith("(fork)")

        data = json.loads((tmp_path / "cli-new.json").read_text())
        assert data["forked_from"] == "cli-src"
        assert len(data["messages"]) == 2

    def test_fork_copies_event_log_with_new_session_id(
        self, tmp_path: Path
    ) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("cli-src", "m")
        store.add_message("user", "x")
        log_path = event_log_path(tmp_path, "cli-src")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(
                {"type": "UserMessage", "session_id": "cli-src", "text": "x"}
            )
            + "\n",
            encoding="utf-8",
        )

        store.fork_session("cli-src", "cli-new")

        dest = event_log_path(tmp_path, "cli-new")
        assert dest.is_file()
        row = json.loads(dest.read_text().strip())
        assert row["session_id"] == "cli-new"

    def test_fork_rejects_existing_id(self, tmp_path: Path) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("cli-a", "m")
        store.add_message("user", "a")
        store.new_session("cli-b", "m")
        store.add_message("user", "b")
        try:
            store.fork_session("cli-a", "cli-b")
        except FileExistsError:
            pass
        else:
            raise AssertionError("expected FileExistsError")

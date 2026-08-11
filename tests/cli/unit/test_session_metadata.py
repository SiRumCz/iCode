# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Tests for session metadata persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from openjiuwen_icode.features.session_metadata import (
    export_directory_for_session,
    persist_session_metadata,
)
from openjiuwen_icode.storage.session_store import (
    SessionStore,
    StoredSession,
)


class TestUpdateMetadata:
    def test_persists_workdir_and_model(self, tmp_path: Path) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("s1", "old-model")
        store.add_message("user", "hi")
        assert store.update_metadata(
            model="new-model",
            workdir="/tmp/project",
            agent_profile="code",
        )
        data = json.loads((tmp_path / "s1.json").read_text())
        assert data["model"] == "new-model"
        assert data["workdir"] == "/tmp/project"
        assert data["agent_profile"] == "code"

    def test_list_includes_agent_profile(self, tmp_path: Path) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("s2", "m", agent_profile="research")
        store.add_message("user", "q")
        store.update_metadata(workdir="/data/repo")
        rows = store.list_sessions()
        assert len(rows) == 1
        assert rows[0]["agent_profile"] == "research"
        assert rows[0]["directory"] == "/data/repo"


class TestPersistFromHost:
    def test_reads_backend_model_and_workdir(self, tmp_path: Path) -> None:
        store = SessionStore(store_dir=tmp_path)
        store.new_session("s3", "ignored")
        store.add_message("user", "x")
        host = MagicMock()
        host.session_store = store
        host._model_name = "fallback"
        host._backend = MagicMock(cfg=MagicMock(model="gpt-test"))
        host.workdirs = MagicMock(primary="/abs/ws")
        assert persist_session_metadata(host)
        data = json.loads((tmp_path / "s3.json").read_text())
        assert data["model"] == "gpt-test"
        assert data["workdir"] == "/abs/ws"


def test_export_directory_prefers_stored() -> None:
    session = StoredSession(
        session_id="x",
        model="m",
        created_at="t",
        workdir="/stored",
    )
    assert export_directory_for_session(session, fallback="/live") == "/stored"

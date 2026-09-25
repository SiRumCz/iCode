# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Broad coverage for openjiuwen_icode.host.commands (fake SessionHost)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openjiuwen_icode.events import (
    CompactionFinished,
    CompactionStarted,
    ProfileSwitched,
    SessionCreated,
    SessionListed,
    SessionRestored,
    SessionTitleUpdated,
    SystemNotice,
    UserCommand,
    UserMessage,
)
from openjiuwen_icode.features.session_resume import (
    AGENT_CONTEXT_UNAVAILABLE,
    SessionResumeResult,
)
from openjiuwen_icode.host import commands as cmd_mod
from openjiuwen_icode.host.commands import handle_user_command
from openjiuwen_icode.host.workdirs import WorkdirRegistry
from openjiuwen_icode.storage.session_store import StoredSession


def _published(host: MagicMock) -> list:
    return [c.args[0] for c in host._bus.publish.await_args_list]


def _notices(host: MagicMock) -> list[SystemNotice]:
    return [e for e in _published(host) if isinstance(e, SystemNotice)]


def make_host(
    *,
    session_id: str = "s1",
    turn_active: bool = False,
    session_store: object | None = None,
    workdirs: WorkdirRegistry | None = None,
    mutations: object | None = None,
    backend: object | None = None,
    bind_event_log: object | None = None,
) -> MagicMock:
    host = MagicMock()
    host.session_id = session_id
    host._session_id = session_id
    host.turn_active = turn_active
    host._last_user_text = "prev"
    host.session_store = session_store
    host.workdirs = workdirs or MagicMock(
        primary="/ws", dirs=["/ws"], format_list=lambda: "Directories:\n* /ws"
    )
    host.mutations = mutations
    if backend is None:
        backend = SimpleNamespace(
            cfg=SimpleNamespace(
                model="gpt-test",
                provider="OpenAI",
                workspace="/ws",
                project="",
            ),
            get_usage=lambda: {
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "model_calls": 4,
            },
            agent=None,
            compact=None,
        )
    host._backend = backend
    bus = MagicMock()
    bus.publish = AsyncMock()
    host._bus = bus
    if bind_event_log is not None:
        host._bind_event_log = bind_event_log
    else:
        # MagicMock auto-attrs are truthy/callable; clear unless provided
        del host._bind_event_log
    return host


# ---------------------------------------------------------------------------
# handle_user_command routing / aliases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_aliases() -> None:
    host = make_host()
    for name in ("help", "h", "?"):
        host._bus.publish.reset_mock()
        await handle_user_command(host, UserCommand(name=name, session_id="s1"))
        notice = host._bus.publish.await_args.args[0]
        assert isinstance(notice, SystemNotice)
        assert notice.kind == "help"
        assert "/status" in notice.text


@pytest.mark.asyncio
async def test_status_clear_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    await handle_user_command(host, UserCommand(name="status", session_id="s1"))
    text = _notices(host)[-1].text
    assert "session: s1" in text
    assert "gpt-test" in text
    assert "tokens:" in text
    assert "primary workdir" in text

    host._bus.publish.reset_mock()
    await handle_user_command(host, UserCommand(name="clear", session_id="s1"))
    assert _notices(host)[-1].kind == "clear"
    assert _notices(host)[-1].text == "__CLEAR__"

    monkeypatch.setattr(
        "openjiuwen_icode.paths.icode_home",
        lambda: tmp_path / "icode",
    )
    monkeypatch.setattr(
        "openjiuwen_icode.paths.agents_home",
        lambda: tmp_path / "agents",
    )
    monkeypatch.setattr(
        "openjiuwen_icode.paths.IcodeProject.open",
        lambda: SimpleNamespace(root=tmp_path / "proj"),
    )
    with patch(
        "openjiuwen.core.sys_operation.cwd.get_cwd",
        side_effect=RuntimeError("no agent"),
    ):
        host._bus.publish.reset_mock()
        await handle_user_command(host, UserCommand(name="cwd", session_id="s1"))
    cwd_text = _notices(host)[-1].text
    assert "iCode home:" in cwd_text
    assert "unavailable" in cwd_text or "tool cwd:" in cwd_text


@pytest.mark.asyncio
async def test_directories_and_workdirs_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    a.mkdir()
    reg = WorkdirRegistry(store_path=tmp_path / "w.json")
    host = make_host(workdirs=reg)
    monkeypatch.setattr(
        "openjiuwen_icode.features.session_metadata.persist_session_metadata",
        lambda _h: False,
    )

    await handle_user_command(
        host, UserCommand(name="directories", session_id="s1")
    )
    assert "Directories" in _notices(host)[-1].text or "No" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host,
        UserCommand(name="directories-add", args=str(a), session_id="s1"),
    )
    assert str(a.resolve()) in _notices(host)[-1].text
    assert str(a.resolve()) in host.workdirs.dirs

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="directories-use", args="1", session_id="s1")
    )
    assert "Primary workdir" in _notices(host)[-1].text

    # `/workdir <path|#>` → use primary (alias)
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdir", args="1", session_id="s1")
    )
    assert "Primary workdir" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdir", args="", session_id="s1")
    )
    assert isinstance(_notices(host)[-1], SystemNotice)


@pytest.mark.asyncio
async def test_skill_slash_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    monkeypatch.setattr(
        "openjiuwen_icode.skills.resolve_skill_user_text",
        lambda name, args, host=None: f"SKILL:{name}:{args}" if name == "myskill" else None,
    )
    await handle_user_command(
        host, UserCommand(name="myskill", args="go", session_id="s1")
    )
    ev = _published(host)[-1]
    assert isinstance(ev, UserMessage)
    assert "SKILL:myskill:go" in ev.text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="notacommand", session_id="s1")
    )
    notice = _notices(host)[-1]
    assert notice.kind == "error"
    assert "Unknown command" in notice.text


# ---------------------------------------------------------------------------
# sessions / title / new / resume / fork
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_list_and_no_store() -> None:
    host = make_host(session_store=None)
    await handle_user_command(host, UserCommand(name="sessions", session_id="s1"))
    assert "No session store" in _notices(host)[-1].text

    store = MagicMock()
    store.list_sessions.return_value = [
        {
            "id": "s1",
            "title": "T",
            "model": "m",
            "updated_at": "t",
            "message_count": 1,
        }
    ]
    host = make_host(session_store=store)
    await handle_user_command(host, UserCommand(name="sessions", session_id="s1"))
    kinds = [type(e).__name__ for e in _published(host)]
    assert "SessionListed" in kinds
    assert any(isinstance(e, SystemNotice) for e in _published(host))


@pytest.mark.asyncio
async def test_title_show_set_unchanged() -> None:
    cur = SimpleNamespace(title="Hello", title_source="auto", session_id="s1")
    store = MagicMock()
    store.current = cur
    store.set_title.return_value = True
    host = make_host(session_store=store)

    await handle_user_command(host, UserCommand(name="title", session_id="s1"))
    assert "Title: Hello" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="title", args="New Title", session_id="s1")
    )
    pubs = _published(host)
    assert any(isinstance(e, SessionTitleUpdated) for e in pubs)
    assert any("Title set:" in e.text for e in pubs if isinstance(e, SystemNotice))

    store.set_title.return_value = False
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="title", args="Same", session_id="s1")
    )
    assert "unchanged" in _notices(host)[-1].text.lower()

    host = make_host(session_store=None)
    await handle_user_command(host, UserCommand(name="title", session_id="s1"))
    assert "No active session store" in _notices(host)[-1].text


@pytest.mark.asyncio
async def test_cmd_new_paths() -> None:
    store = MagicMock()
    bind = MagicMock()
    host = make_host(session_store=store, bind_event_log=bind)
    await handle_user_command(host, UserCommand(name="new", session_id="s1"))
    pubs = _published(host)
    assert any(isinstance(e, SessionCreated) for e in pubs)
    assert host._session_id.startswith("cli-")
    store.new_session.assert_called_once()
    bind.assert_called_once()

    host2 = make_host(turn_active=True)
    await handle_user_command(host2, UserCommand(name="new", session_id="s1"))
    assert "Cannot /new" in _notices(host2)[-1].text


@pytest.mark.asyncio
async def test_cmd_resume_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    await handle_user_command(host, UserCommand(name="resume", session_id="s1"))
    assert "Usage: /resume" in _notices(host)[-1].text

    host = make_host(turn_active=True)
    await handle_user_command(
        host, UserCommand(name="resume", args="other", session_id="s1")
    )
    assert "Cannot /resume" in _notices(host)[-1].text

    host = make_host(session_store=None)
    await handle_user_command(
        host, UserCommand(name="resume", args="other", session_id="s1")
    )
    assert "No session store" in _notices(host)[-1].text

    store = MagicMock()
    store.switch_session.side_effect = FileNotFoundError("missing")
    host = make_host(session_store=store)
    await handle_user_command(
        host, UserCommand(name="resume", args="gone", session_id="s1")
    )
    assert "missing" in _notices(host)[-1].text

    session = StoredSession(
        session_id="res-1",
        model="m",
        created_at="t",
        messages=[],
        title="R",
    )
    store = MagicMock()
    store.switch_session.return_value = session
    store.current = session
    bind = MagicMock()
    host = make_host(session_store=store, bind_event_log=bind)
    monkeypatch.setattr(
        "openjiuwen_icode.features.session_resume.align_backend_session_after_resume",
        AsyncMock(
            return_value=SessionResumeResult(
                session_id="res-1",
                agent_context=AGENT_CONTEXT_UNAVAILABLE,
                store_messages=0,
            )
        ),
    )
    monkeypatch.setattr(
        "openjiuwen_icode.features.session_metadata.persist_session_metadata",
        lambda _h: True,
    )
    await handle_user_command(
        host, UserCommand(name="resume", args="res-1", session_id="s1")
    )
    pubs = _published(host)
    assert any(isinstance(e, SessionRestored) for e in pubs)
    assert any("Restored res-1" in e.text for e in pubs if isinstance(e, SystemNotice))
    bind.assert_called_with("res-1")


@pytest.mark.asyncio
async def test_cmd_fork_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host(turn_active=True)
    await handle_user_command(host, UserCommand(name="fork", session_id="s1"))
    assert "Cannot /fork" in _notices(host)[-1].text

    host = make_host(session_store=None)
    await handle_user_command(host, UserCommand(name="fork", session_id="s1"))
    assert "No session store" in _notices(host)[-1].text

    store = MagicMock()
    host = make_host(session_store=store)
    host._session_id = ""
    host.session_id = ""
    await handle_user_command(host, UserCommand(name="fork", session_id=None))
    assert "Usage: /fork" in _notices(host)[-1].text

    store = MagicMock()
    store.fork_session.side_effect = FileNotFoundError("no src")
    host = make_host(session_store=store)
    await handle_user_command(
        host, UserCommand(name="fork", args="missing", session_id="s1")
    )
    assert "no src" in _notices(host)[-1].text

    store = MagicMock()
    store.fork_session.side_effect = FileExistsError("exists")
    host = make_host(session_store=store)
    await handle_user_command(
        host, UserCommand(name="fork", args="s1", session_id="s1")
    )
    assert "exists" in _notices(host)[-1].text

    session = StoredSession(
        session_id="fork-1",
        model="m",
        created_at="t",
        messages=[],
        title="F",
    )
    store = MagicMock()
    store.fork_session.return_value = session
    store.current = session
    bind = MagicMock()
    host = make_host(session_store=store, bind_event_log=bind)
    monkeypatch.setattr(
        "openjiuwen_icode.features.session_resume.align_backend_session_after_resume",
        AsyncMock(
            return_value=SessionResumeResult(
                session_id="fork-1",
                agent_context=AGENT_CONTEXT_UNAVAILABLE,
                store_messages=0,
            )
        ),
    )
    monkeypatch.setattr(
        "openjiuwen_icode.features.session_metadata.persist_session_metadata",
        lambda _h: True,
    )
    await handle_user_command(
        host, UserCommand(name="fork", args="s1", session_id="s1")
    )
    pubs = _published(host)
    assert any(isinstance(e, SessionRestored) for e in pubs)
    assert any("Forked" in e.text for e in pubs if isinstance(e, SystemNotice))
    bind.assert_called_with("fork-1")


# ---------------------------------------------------------------------------
# export / diff / rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_export_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host(session_store=None)
    await handle_user_command(host, UserCommand(name="export", session_id="s1"))
    assert "No session store" in _notices(host)[-1].text

    session = StoredSession(
        session_id="s1", model="m", created_at="t", messages=[], workdir=str(tmp_path)
    )
    store = MagicMock()
    store.current = session
    store.store_dir = tmp_path
    store.load_session.return_value = session
    host = make_host(session_store=store)

    await handle_user_command(
        host, UserCommand(name="export", args="--out", session_id="s1")
    )
    assert "Usage: /export" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="export", args="--bogus", session_id="s1")
    )
    assert "Unknown flag" in _notices(host)[-1].text

    host2 = make_host(session_store=store)
    host2.session_id = ""
    host2._session_id = ""
    await handle_user_command(
        host2, UserCommand(name="export", args="", session_id=None)
    )
    assert "Usage: /export" in _notices(host2)[-1].text

    monkeypatch.setattr(
        "openjiuwen_icode.export.opencode.export_session_opencode",
        lambda *a, **k: {"messages": [{"x": 1}], "harness": {"fidelity": "high"}},
    )
    out = tmp_path / "out.json"
    wrote: list[Path] = []

    def _write(doc, path):
        wrote.append(path)
        path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "openjiuwen_icode.export.opencode.write_opencode_export",
        _write,
    )
    host._bus.publish.reset_mock()
    await handle_user_command(
        host,
        UserCommand(
            name="export",
            args=f"s1 --sanitize --out {out}",
            session_id="s1",
        ),
    )
    assert wrote and wrote[0] == out
    assert "Exported s1" in _notices(host)[-1].text
    assert "sanitized" in _notices(host)[-1].text

    # FileNotFoundError path
    monkeypatch.setattr(
        "openjiuwen_icode.export.opencode.export_session_opencode",
        MagicMock(side_effect=FileNotFoundError("gone")),
    )
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="export", args="gone", session_id="s1")
    )
    assert "gone" in _notices(host)[-1].text

    # generic Exception
    monkeypatch.setattr(
        "openjiuwen_icode.export.opencode.export_session_opencode",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="export", args="s1", session_id="s1")
    )
    assert "Export failed" in _notices(host)[-1].text

    # OSError on write
    monkeypatch.setattr(
        "openjiuwen_icode.export.opencode.export_session_opencode",
        lambda *a, **k: {"messages": [], "harness": {}},
    )
    monkeypatch.setattr(
        "openjiuwen_icode.export.opencode.write_opencode_export",
        MagicMock(side_effect=OSError("disk")),
    )
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="export", args="s1", session_id="s1")
    )
    assert "Failed to write export" in _notices(host)[-1].text


@pytest.mark.asyncio
async def test_diff_and_rollback() -> None:
    host = make_host(mutations=None)
    await handle_user_command(host, UserCommand(name="diff", session_id="s1"))
    assert "Mutation tracker not available" in _notices(host)[-1].text

    tracker = MagicMock()
    tracker.format_diff.return_value = "diff-out"
    tracker.rollback_turn.return_value = "rolled"
    host = make_host(mutations=tracker)
    await handle_user_command(
        host, UserCommand(name="diff", args="t1", session_id="s1")
    )
    assert _notices(host)[-1].text == "diff-out"
    tracker.format_diff.assert_called_with("t1")

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="rollback", args="t1", session_id="s1")
    )
    assert _notices(host)[-1].text == "rolled"

    host = make_host(mutations=tracker, turn_active=True)
    await handle_user_command(host, UserCommand(name="rollback", session_id="s1"))
    assert "Cannot /rollback" in _notices(host)[-1].text

    host = make_host(mutations=None)
    await handle_user_command(host, UserCommand(name="rollback", session_id="s1"))
    assert "Mutation tracker not available" in _notices(host)[-1].text


# ---------------------------------------------------------------------------
# compact / hooks / mcp / skills / theme / notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compact_with_and_without_backend() -> None:
    backend = SimpleNamespace(cfg=None, compact=None, agent=None)
    host = make_host(backend=backend)
    await handle_user_command(host, UserCommand(name="compact", session_id="s1"))
    pubs = _published(host)
    assert any(isinstance(e, CompactionStarted) for e in pubs)
    finished = [e for e in pubs if isinstance(e, CompactionFinished)]
    assert finished and finished[0].ok is True
    assert "Manual /compact" in finished[0].summary

    async def _ok():
        return "summarized"

    backend2 = SimpleNamespace(cfg=None, compact=_ok, agent=None)
    host2 = make_host(backend=backend2)
    await handle_user_command(host2, UserCommand(name="compact", session_id="s1"))
    fin = [e for e in _published(host2) if isinstance(e, CompactionFinished)]
    assert fin and fin[0].summary == "summarized"

    async def _bad():
        raise RuntimeError("compact fail")

    backend3 = SimpleNamespace(cfg=None, compact=_bad, agent=None)
    host3 = make_host(backend=backend3)
    await handle_user_command(host3, UserCommand(name="compact", session_id="s1"))
    fin3 = [e for e in _published(host3) if isinstance(e, CompactionFinished)]
    assert fin3 and fin3[0].ok is False


@pytest.mark.asyncio
async def test_hooks_empty_and_with_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    monkeypatch.setattr(
        "openjiuwen_icode.paths.icode_home",
        lambda: tmp_path,
    )
    host = make_host()
    await handle_user_command(host, UserCommand(name="hooks", session_id="s1"))
    assert "No hook scripts found" in _notices(host)[-1].text

    (hooks / "pre.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (hooks / ".hidden").write_text("x", encoding="utf-8")
    host._bus.publish.reset_mock()
    await handle_user_command(host, UserCommand(name="hooks", session_id="s1"))
    assert "pre.sh" in _notices(host)[-1].text
    assert ".hidden" not in _notices(host)[-1].text


@pytest.mark.asyncio
async def test_mcp_status_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    monkeypatch.setattr(
        "openjiuwen_icode.agent.factory._load_mcp_configs",
        lambda cwd=None: [],
    )
    monkeypatch.setattr(
        "openjiuwen_icode.features.mcp_cache.collect_mcp_status",
        lambda **kw: SimpleNamespace(note=""),
    )
    monkeypatch.setattr(
        "openjiuwen_icode.features.mcp_cache.format_mcp_status",
        lambda status: "MCP STATUS",
    )
    monkeypatch.setattr(
        "openjiuwen_icode.paths.mcp_path",
        lambda: Path("/tmp/mcp.json"),
    )
    await handle_user_command(host, UserCommand(name="mcp", session_id="s1"))
    assert "MCP STATUS" in _notices(host)[-1].text

    monkeypatch.setattr(
        cmd_mod,
        "_format_mcp_tools",
        lambda filter_name="": f"TOOLS:{filter_name or 'all'}",
    )
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="mcp", args="tools demo", session_id="s1")
    )
    assert _notices(host)[-1].text == "TOOLS:demo"


@pytest.mark.asyncio
async def test_skills_status(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    monkeypatch.setattr(
        "openjiuwen_icode.skills.skills_status_text",
        lambda host: "skills ok",
    )
    await handle_user_command(host, UserCommand(name="skills", session_id="s1"))
    assert _notices(host)[-1].text == "skills ok"


@pytest.mark.asyncio
async def test_theme_and_notifications_via_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "openjiuwen_icode.features.tui_prefs.SETTINGS_PATH",
        settings,
    )
    monkeypatch.setattr(
        "openjiuwen_icode.agent.config.SETTINGS_PATH",
        settings,
    )
    host = make_host()
    await handle_user_command(host, UserCommand(name="theme", session_id="s1"))
    assert "Theme:" in _notices(host)[-1].text
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="theme", args="dark", session_id="s1")
    )
    assert "dark" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="notifications", session_id="s1")
    )
    assert "Notifications:" in _notices(host)[-1].text


# ---------------------------------------------------------------------------
# models / agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_models_list_and_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    monkeypatch.setattr(
        cmd_mod,
        "current_model_from_settings",
        lambda: {"model": "gpt-a", "provider": "OpenAI"},
    )
    monkeypatch.setattr(
        cmd_mod,
        "list_model_profiles",
        lambda: [
            {"id": "gpt-a", "provider": "OpenAI", "label": "A"},
            {"id": "gpt-b", "provider": "OpenAI", "label": "B"},
        ],
    )
    await handle_user_command(host, UserCommand(name="models", session_id="s1"))
    text = _notices(host)[-1].text
    assert "Current: gpt-a" in text
    assert "gpt-b" in text

    monkeypatch.setattr(cmd_mod, "list_model_profiles", lambda: [])
    host._bus.publish.reset_mock()
    await handle_user_command(host, UserCommand(name="model", session_id="s1"))
    assert "(none" in _notices(host)[-1].text

    monkeypatch.setattr(cmd_mod, "get_model_profile", lambda mid: None)
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="models", args="missing", session_id="s1")
    )
    assert "Unknown model" in _notices(host)[-1].text

    host = make_host(turn_active=True)
    monkeypatch.setattr(
        cmd_mod,
        "get_model_profile",
        lambda mid: {"id": mid, "provider": "OpenAI", "apiBase": None},
    )
    await handle_user_command(
        host, UserCommand(name="models", args="gpt-b", session_id="s1")
    )
    assert "Cannot switch model" in _notices(host)[-1].text

    host = make_host()
    monkeypatch.setattr(
        cmd_mod,
        "switch_model_in_settings",
        lambda mid, provider=None, api_base=None: {
            "model": mid,
            "provider": provider or "OpenAI",
        },
    )
    monkeypatch.setattr(cmd_mod, "apply_model_to_backend", lambda *a, **k: None)
    monkeypatch.setattr(
        cmd_mod, "rebuild_backend_agent", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "openjiuwen_icode.features.session_metadata.persist_session_metadata",
        lambda _h: True,
    )
    await handle_user_command(
        host, UserCommand(name="models", args="gpt-b", session_id="s1")
    )
    pubs = _published(host)
    assert any(isinstance(e, ProfileSwitched) for e in pubs)
    assert any("Model set to gpt-b" in e.text for e in pubs if isinstance(e, SystemNotice))

    monkeypatch.setattr(
        cmd_mod, "rebuild_backend_agent", AsyncMock(return_value=False)
    )
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="models", args="gpt-b", session_id="s1")
    )
    assert "Active cfg updated" in _notices(host)[-1].text


@pytest.mark.asyncio
async def test_agents_list_and_use_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    monkeypatch.setattr(
        "openjiuwen_icode.agent.profile_loader.active_agent_profile_id",
        lambda: "code",
    )
    monkeypatch.setattr(
        cmd_mod,
        "list_agent_profiles",
        lambda: [
            {"id": "code", "label": "Code"},
            {"id": "plan", "label": "Plan"},
        ],
    )
    await handle_user_command(host, UserCommand(name="agents", session_id="s1"))
    text = _notices(host)[-1].text
    assert "Current: code" in text
    assert "plan" in text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="agents", args="use", session_id="s1")
    )
    assert "Usage: /agents use" in _notices(host)[-1].text

    monkeypatch.setattr(cmd_mod, "get_agent_profile", lambda pid: None)
    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="agents", args="use missing", session_id="s1")
    )
    assert "Unknown agent profile" in _notices(host)[-1].text

    monkeypatch.setattr(
        cmd_mod,
        "get_agent_profile",
        lambda pid: {"id": pid, "label": "Plan"},
    )
    host = make_host(turn_active=True)
    await handle_user_command(
        host, UserCommand(name="agents", args="use plan", session_id="s1")
    )
    assert "Cannot switch agent" in _notices(host)[-1].text

    host = make_host()
    monkeypatch.setattr(
        cmd_mod, "switch_agent_profile_in_settings", lambda pid, path=None: pid
    )
    monkeypatch.setattr(
        cmd_mod, "rebuild_backend_agent", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        "openjiuwen_icode.features.session_metadata.persist_session_metadata",
        lambda _h: True,
    )
    await handle_user_command(
        host, UserCommand(name="agent", args="use plan", session_id="s1")
    )
    pubs = _published(host)
    assert any(isinstance(e, ProfileSwitched) for e in pubs)
    assert "backend support" in _notices(host)[-1].text


# ---------------------------------------------------------------------------
# workdirs add/rm/use error + success paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workdirs_add_rm_use_errors_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    reg = WorkdirRegistry(store_path=tmp_path / "w.json")
    host = make_host(workdirs=reg)
    monkeypatch.setattr(
        "openjiuwen_icode.features.session_metadata.persist_session_metadata",
        lambda _h: False,
    )
    monkeypatch.setattr(
        "openjiuwen_icode.host.commands.apply_workdir_to_backend",
        lambda backend, path: ["cfg.workspace"],
    )

    await handle_user_command(
        host, UserCommand(name="workdirs", args="add", session_id="s1")
    )
    assert "Usage: /directories add" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args="add /no/such", session_id="s1")
    )
    assert _notices(host)[-1].kind == "error"

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args=f"add {a}", session_id="s1")
    )
    assert "Added workdir" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args=f"add {b}", session_id="s1")
    )

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args="rm", session_id="s1")
    )
    assert "Usage: /workdirs rm" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args="rm 1", session_id="s1")
    )
    # cannot remove primary
    assert _notices(host)[-1].kind == "error"

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args="use", session_id="s1")
    )
    assert "Usage: /workdirs use" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args="use 99", session_id="s1")
    )
    assert _notices(host)[-1].kind == "error"

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args="use 2", session_id="s1")
    )
    assert "Primary workdir" in _notices(host)[-1].text
    assert "cfg.workspace" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args="rm 1", session_id="s1")
    )
    assert "Removed workdir" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs", args="xyz", session_id="s1")
    )
    assert "Unknown /workdirs action" in _notices(host)[-1].text

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="workdirs-rm", args="1", session_id="s1")
    )
    # only one dir left — removing primary fails
    assert _notices(host)[-1].kind == "error"


# ---------------------------------------------------------------------------
# subagents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagents_list_cancel_abort_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = make_host()
    monkeypatch.setattr(
        "openjiuwen_icode.features.subagent_status.format_subagent_status_text",
        lambda agent, sid: "sub list",
    )
    await handle_user_command(
        host, UserCommand(name="subagents", session_id="s1")
    )
    assert _notices(host)[-1].text == "sub list"

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="subagents", args="cancel", session_id="s1")
    )
    assert "Usage: /subagents cancel" in _notices(host)[-1].text

    abort = AsyncMock()
    retry = AsyncMock()
    monkeypatch.setattr(
        "openjiuwen_icode.features.subagent_control_bus.handle_subagent_abort",
        abort,
    )
    monkeypatch.setattr(
        "openjiuwen_icode.features.subagent_control_bus.handle_subagent_retry",
        retry,
    )

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="sub-agents", args="abort tid-1", session_id="s1")
    )
    abort.assert_awaited_once()
    assert abort.await_args.args[2] == "tid-1"

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="subagent", args="cancel tid-2", session_id="s1")
    )
    assert abort.await_count == 2

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="subagents", args="retry tid-3", session_id="s1")
    )
    retry.assert_awaited_once()
    assert retry.await_args.args[2] == "tid-3"

    host._bus.publish.reset_mock()
    await handle_user_command(
        host, UserCommand(name="subagents", args="retry", session_id="s1")
    )
    assert "Usage: /subagents retry" in _notices(host)[-1].text

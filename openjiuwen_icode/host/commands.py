# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Slash-command handling for SessionHost (P2 TUI / EventBus)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

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
)
from openjiuwen_icode.features.session_title import (
    TITLE_MANUAL,
    format_session_list,
)
from openjiuwen_icode.host.profiles import (
    apply_model_to_backend,
    current_model_from_settings,
    get_model_profile,
    get_agent_profile,
    list_agent_profiles,
    list_model_profiles,
    rebuild_backend_agent,
    switch_agent_profile_in_settings,
    switch_model_in_settings,
)
from openjiuwen_icode.host.workdirs import apply_workdir_to_backend

if TYPE_CHECKING:
    from openjiuwen_icode.host.session_host import SessionHost

_HELP = """\
/help                 Show this help
/status               Model + token usage
/models [name]        List models, or switch model in settings
                      (TUI: bare /models or F4 opens Models modal)
/agents [use <id>]    List agent profiles, or switch active profile
/skills               List discovered skills (file + inline)
/subagents            List background sub-agents + recent audit
/subagents cancel <id>  Cancel a background spawn task
/subagents abort <id>  Same as cancel
/subagents retry <id>   Re-submit a failed/canceled spawn
/sessions             Open Sessions modal (TUI: F1); REPL prints a table
/title [text]         Show or set the current session title
/new                  Start a new session id
/resume <id>          Restore a saved session metadata into the host
/fork [source_id]     Clone a session to a new id (transcript + event log)
/export [id] [--sanitize] [--out path]
                      Export session as OpenCode-compatible JSON
/diff [turn_id]       Show filesystem mutations for recent turns
/rollback [turn_id]   Restore files from turn snapshots (last turn default)
/compact              Request context compaction
/theme [name]         Show or set TUI theme preference
/notifications [on|off]  Show or toggle notification preference
/hooks                Show external hooks status (T-41 stub)
/mcp [tools [server]] Show MCP cache status; tools lists live tool names
/clear                Ask UI to clear transcript
/cwd                  Show iCode home, directories, and tool cwd
/quit                 Exit the TUI (alias: /exit; also Ctrl+Q)
/exit                 Same as /quit
/directories          List project directories (alias: /workdirs)
/directories add …    Add a project directory (TUI: folder picker)
/directories rm …    Remove a non-primary directory
/directories use …    Set primary directory (hot)
/workdirs             Same as /directories (legacy name)
/workdirs add <path>  Add a project directory
/workdirs rm <path|#> Remove a non-primary directory
/workdirs use <path|#>  Set primary directory (hot)
Aliases: /directories-add /directories-rm /directories-use
         /workdirs-add /workdirs-rm /workdirs-use

Skills: type /<skill-name> [args] to inject SKILL.md as the
user turn (same as Chrys load-then-follow via slash).

Shell mode (TUI): type ! or ！ alone to enter; run local commands;
type ! again or press Esc to leave. One-shot: !ls

Copy (TUI, Chrys-style): drag to select; Ctrl/Cmd+C or right-click
to copy; Ctrl+B to interrupt the agent. Type / for slash suggestions;
Tab completes, Enter runs. Ctrl+G toggles the Messages/Tasks/Context sidebar.
Approvals open a modal (Approve / Reject). Quit with Ctrl+Q or /quit.
"""


async def handle_user_command(host: SessionHost, event: UserCommand) -> None:
    """Dispatch a :class:`UserCommand` and publish UI events."""
    name = (event.name or "").lstrip("/").lower().strip()
    args = (event.args or "").strip()
    sid = event.session_id or host.session_id

    # Normalize hyphen aliases into workdirs + subcommand.
    if name in {"workdirs-add", "workdir-add", "directories-add", "directory-add"}:
        name, args = "workdirs", f"add {args}".strip()
    elif name in {
        "workdirs-rm",
        "workdir-rm",
        "workdirs-remove",
        "directories-rm",
        "directory-rm",
        "directories-remove",
    }:
        name, args = "workdirs", f"rm {args}".strip()
    elif name in {"workdirs-use", "workdir-use", "directories-use", "directory-use"}:
        name, args = "workdirs", f"use {args}".strip()
    elif name in {"directories", "directory"}:
        name = "workdirs"
    elif name == "workdir":
        # `/workdir` → list; `/workdir <path|#>` → use primary.
        if args:
            name, args = "workdirs", f"use {args}".strip()
        else:
            name = "workdirs"

    if name in {"help", "h", "?"}:
        await host._bus.publish(
            SystemNotice(text=_HELP, kind="help", session_id=sid)
        )
        return

    if name == "status":
        lines = [f"session: {host.session_id or '-'}"]
        cfg = getattr(host._backend, "cfg", None)
        if cfg is not None:
            lines.append(f"model: {cfg.model} ({cfg.provider})")
            lines.append(f"workspace: {getattr(cfg, 'workspace', '')}")
        primary = host.workdirs.primary
        if primary:
            lines.append(f"primary workdir: {primary}")
        usage = None
        get_usage = getattr(host._backend, "get_usage", None)
        if callable(get_usage):
            usage = get_usage()
        if usage:
            lines.append(
                "tokens: "
                f"in={usage.get('input_tokens', 0)} "
                f"out={usage.get('output_tokens', 0)} "
                f"total={usage.get('total_tokens', 0)} "
                f"calls={usage.get('model_calls', 0)}"
            )
        await host._bus.publish(
            SystemNotice(
                text="\n".join(lines), kind="status", session_id=sid
            )
        )
        return

    if name in {"models", "model"}:
        await _cmd_models(host, args, sid)
        return

    if name in {"agents", "agent"}:
        await _cmd_agents(host, args, sid)
        return

    if name == "skills":
        from openjiuwen_icode.skills import skills_status_text

        await host._bus.publish(
            SystemNotice(
                text=skills_status_text(host),
                kind="info",
                session_id=sid,
            )
        )
        return

    if name in {"subagents", "sub-agents", "subagent"}:
        from openjiuwen_icode.features.subagent_control_bus import (
            handle_subagent_abort,
            handle_subagent_retry,
        )
        from openjiuwen_icode.features.subagent_status import (
            format_subagent_status_text,
        )

        agent = getattr(host._backend, "agent", None)
        lowered = args.lower()
        if lowered.startswith(("cancel", "abort", "retry")):
            verb = lowered.split(maxsplit=1)[0]
            parts = args.split(maxsplit=1)
            task_id = parts[1].strip() if len(parts) > 1 else ""
            if not task_id:
                await host._bus.publish(
                    SystemNotice(
                        text=f"Usage: /subagents {verb} <task_id>",
                        kind="error",
                        session_id=sid,
                    )
                )
                return
            if verb == "retry":
                await handle_subagent_retry(
                    host._bus, host._backend, task_id, sid
                )
            else:
                await handle_subagent_abort(
                    host._bus, host._backend, task_id, sid
                )
            return

        text = format_subagent_status_text(agent, sid)
        await host._bus.publish(
            SystemNotice(text=text, kind="info", session_id=sid)
        )
        return

    if name == "sessions":
        store = host.session_store
        if store is None:
            await host._bus.publish(
                SystemNotice(
                    text="No session store attached.",
                    kind="error",
                    session_id=sid,
                )
            )
            return
        sessions = store.list_sessions()
        await host._bus.publish(
            SessionListed(sessions=sessions, session_id=sid)
        )
        await host._bus.publish(
            SystemNotice(
                text=format_session_list(
                    sessions, current_id=host.session_id
                ),
                kind="info",
                session_id=sid,
            )
        )
        return

    if name == "title":
        await _cmd_title(host, args, sid)
        return

    if name == "new":
        await _cmd_new(host, sid)
        return

    if name == "resume":
        await _cmd_resume(host, args, sid)
        return

    if name == "fork":
        await _cmd_fork(host, args, sid)
        return

    if name == "export":
        await _cmd_export(host, args, sid)
        return

    if name == "diff":
        await _cmd_diff(host, args, sid)
        return

    if name == "rollback":
        await _cmd_rollback(host, args, sid)
        return

    if name == "compact":
        await _cmd_compact(host, sid)
        return

    if name == "theme":
        await _cmd_theme(host, args, sid)
        return

    if name in {"notifications", "notification"}:
        await _cmd_notifications(host, args, sid)
        return

    if name == "hooks":
        await _cmd_hooks(host, sid)
        return

    if name == "mcp":
        await _cmd_mcp(host, args, sid)
        return

    if name == "clear":
        await host._bus.publish(
            SystemNotice(text="__CLEAR__", kind="clear", session_id=sid)
        )
        return

    if name in {"workdirs", "workdir"}:
        await _cmd_workdirs(host, args, sid)
        return

    if name == "cwd":
        from openjiuwen_icode.paths import (
            IcodeProject,
            agents_home,
            icode_home,
        )

        cfg = getattr(host._backend, "cfg", None)
        agent_workspace = getattr(cfg, "workspace", "") if cfg else ""
        project_root = getattr(cfg, "project", "") if cfg else ""
        if not project_root:
            project_root = str(IcodeProject.open().root)
        try:
            from openjiuwen.core.sys_operation.cwd import get_cwd

            agent_cwd = get_cwd()
        except Exception:  # noqa: BLE001
            agent_cwd = "(unavailable before agent init)"
        primary = host.workdirs.primary or "(none)"
        n_dirs = len(host.workdirs.dirs)
        text = (
            f"Agents home: {agents_home()}\n"
            f"iCode home: {icode_home()}\n"
            f"iCode project: {project_root}\n"
            f"primary directory: {primary}\n"
            f"tool cwd: {agent_cwd}\n"
            f"agent workspace: {agent_workspace or '(none)'}\n"
            f"directories: {n_dirs} registered (see /directories)"
        )
        await host._bus.publish(
            SystemNotice(text=text, kind="info", session_id=sid)
        )
        return

    # Unknown builtin — try skill slash (inject SKILL.md as user turn).
    from openjiuwen_icode.events import UserMessage
    from openjiuwen_icode.skills import resolve_skill_user_text

    skill_text = resolve_skill_user_text(name, args, host=host)
    if skill_text is not None:
        await host._bus.publish(
            UserMessage(text=skill_text, session_id=sid)
        )
        return

    await host._bus.publish(
        SystemNotice(
            text=f"Unknown command: /{name}. Type /help.",
            kind="error",
            session_id=sid,
        )
    )


async def _cmd_workdirs(
    host: SessionHost, args: str, sid: str | None
) -> None:
    reg = host.workdirs
    parts = args.split(maxsplit=1)
    action = (parts[0] if parts else "").lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if not action or action in {"list", "ls"}:
        await host._bus.publish(
            SystemNotice(
                text=reg.format_list(), kind="info", session_id=sid
            )
        )
        return

    if action in {"add", "a"}:
        if not rest:
            await host._bus.publish(
                SystemNotice(
                    text=(
                        "Usage: /directories add <path>\n"
                        "In the TUI, run /directories add to open the folder picker."
                    ),
                    kind="error",
                    session_id=sid,
                )
            )
            return
        try:
            path = reg.add(rest)
        except ValueError as exc:
            await host._bus.publish(
                SystemNotice(text=str(exc), kind="error", session_id=sid)
            )
            return
        await host._bus.publish(
            SystemNotice(
                text=f"Added workdir: {path}\n{reg.format_list()}",
                kind="info",
                session_id=sid,
            )
        )
        return

    if action in {"rm", "remove", "del", "delete"}:
        if not rest:
            await host._bus.publish(
                SystemNotice(
                    text="Usage: /workdirs rm <path|#>",
                    kind="error",
                    session_id=sid,
                )
            )
            return
        try:
            path = reg.remove(rest)
        except ValueError as exc:
            await host._bus.publish(
                SystemNotice(text=str(exc), kind="error", session_id=sid)
            )
            return
        await host._bus.publish(
            SystemNotice(
                text=f"Removed workdir: {path}\n{reg.format_list()}",
                kind="info",
                session_id=sid,
            )
        )
        return

    if action in {"use", "set", "switch"}:
        if not rest:
            await host._bus.publish(
                SystemNotice(
                    text="Usage: /workdirs use <path|#>",
                    kind="error",
                    session_id=sid,
                )
            )
            return
        try:
            path = reg.use(rest)
        except ValueError as exc:
            await host._bus.publish(
                SystemNotice(text=str(exc), kind="error", session_id=sid)
            )
            return
        notes = apply_workdir_to_backend(host._backend, path)
        detail = ", ".join(notes) if notes else "registry only"
        from openjiuwen_icode.features.session_metadata import (
            persist_session_metadata,
        )

        persist_session_metadata(host)
        await host._bus.publish(
            SystemNotice(
                text=(
                    f"Primary workdir → {path}\n"
                    f"Applied: {detail}\n"
                    "Agent tool cwd updates on the next turn."
                ),
                kind="info",
                session_id=sid,
            )
        )
        return

    await host._bus.publish(
        SystemNotice(
            text=(
                f"Unknown /workdirs action: {action}\n"
                "Use: /workdirs | add | rm | use"
            ),
            kind="error",
            session_id=sid,
        )
    )


async def _cmd_agents(host: SessionHost, args: str, sid: str | None) -> None:
    from openjiuwen_icode.agent.profile_loader import (
        active_agent_profile_id,
    )

    tokens = args.split()
    if tokens and tokens[0].lower() == "use":
        if len(tokens) < 2:
            await host._bus.publish(
                SystemNotice(
                    text="Usage: /agents use <profile_id>",
                    kind="error",
                    session_id=sid,
                )
            )
            return
        profile_id = tokens[1].strip()
        profile = get_agent_profile(profile_id)
        if profile is None:
            await host._bus.publish(
                SystemNotice(
                    text=f"Unknown agent profile: {profile_id}",
                    kind="error",
                    session_id=sid,
                )
            )
            return
        if host.turn_active:
            await host._bus.publish(
                SystemNotice(
                    text="Cannot switch agent profile while a turn is active.",
                    kind="error",
                    session_id=sid,
                )
            )
            return
        switch_agent_profile_in_settings(profile_id)
        rebuilt = await rebuild_backend_agent(host._backend)
        detail = (
            "Agent rebuilt with new profile."
            if rebuilt
            else (
                "Profile saved; full agent rebuild needs backend support."
            )
        )
        from openjiuwen_icode.features.session_metadata import (
            persist_session_metadata,
        )

        persist_session_metadata(host)
        await host._bus.publish(
            ProfileSwitched(
                kind="agent",
                profile_id=profile_id,
                detail=detail,
                session_id=sid,
            )
        )
        await host._bus.publish(
            SystemNotice(
                text=(
                    f"Agent profile set to {profile_id} "
                    f"({profile.get('label', profile_id)}). {detail}"
                ),
                kind="info",
                session_id=sid,
            )
        )
        return

    current = active_agent_profile_id() or "code"
    rows = list_agent_profiles()
    lines = [f"Current: {current or '(default code)'}", "Available:"]
    for row in rows:
        mark = "*" if row["id"] == current else " "
        lines.append(f" {mark} {row['id']}: {row['label']}")
    lines.append("Switch: /agents use <id>")
    await host._bus.publish(
        SystemNotice(text="\n".join(lines), kind="info", session_id=sid)
    )


async def _cmd_mcp(
    host: SessionHost, args: str, sid: str | None
) -> None:
    from openjiuwen_icode.agent.factory import _load_mcp_configs
    from openjiuwen_icode.features.mcp_cache import (
        collect_mcp_status,
        format_mcp_status,
    )
    from openjiuwen_icode.paths import mcp_path

    tokens = args.split()
    cwd = host.workdirs.primary or None
    configs = _load_mcp_configs(cwd=cwd)

    if tokens and tokens[0].lower() in {"tools", "list", "ls"}:
        filter_name = tokens[1].strip() if len(tokens) > 1 else ""
        text = _format_mcp_tools(filter_name=filter_name)
        await host._bus.publish(
            SystemNotice(text=text, kind="info", session_id=sid)
        )
        return

    status = collect_mcp_status(
        configs=configs,
        cwd=cwd,
        config_path=str(mcp_path()),
    )
    status.note = (
        "Commands: /mcp  |  /mcp tools [server]  "
        "(progressive list of live MCP tools)"
    )
    await host._bus.publish(
        SystemNotice(
            text=format_mcp_status(status),
            kind="info",
            session_id=sid,
        )
    )


def _format_mcp_tools(*, filter_name: str = "") -> str:
    """List live MCP tools from ToolMgr (progressive disclosure UX)."""
    try:
        from openjiuwen.core.runner import Runner

        mgr = getattr(Runner, "resource_mgr", None)
        tool_mgr = getattr(mgr, "tool_mgr", None) if mgr else None
        resources = getattr(tool_mgr, "_mcp_server_resources", None)
        if not isinstance(resources, dict) or not resources:
            return (
                "No live MCP tools yet.\n"
                "Servers connect on the first agent turn after start/rebuild.\n"
                "Use /mcp to see configured cache keys."
            )
        lines = ["MCP tools (live):"]
        for sid, resource in resources.items():
            cfg = getattr(resource, "config", None)
            name = str(getattr(cfg, "server_name", "") or sid)
            if filter_name and filter_name not in (name, sid):
                continue
            tool_ids = list(getattr(resource, "tool_ids", None) or [])
            lines.append(f"  [{name}] id={sid} ({len(tool_ids)} tools)")
            for tid in tool_ids[:40]:
                short = tid.rsplit(".", 1)[-1] if "." in tid else tid
                lines.append(f"    - {short}")
            if len(tool_ids) > 40:
                lines.append(f"    … +{len(tool_ids) - 40} more")
        if len(lines) == 1:
            return f"No live MCP server matching {filter_name!r}."
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Failed to list MCP tools: {exc}"


async def _cmd_models(host: SessionHost, args: str, sid: str | None) -> None:
    if not args:
        current = current_model_from_settings()
        rows = list_model_profiles()
        lines = [
            f"Current: {current['model']} ({current['provider']})",
            "Available:",
        ]
        for row in rows:
            mark = "*" if row["id"] == current["model"] else " "
            lines.append(
                f" {mark} {row['id']}  [{row['provider']}] "
                f"{row['label']}"
            )
        if not rows:
            lines.append(" (none — create one in the Models modal / F4)")
        lines.append("Switch: /models <id>")
        lines.append("TUI: F4 or bare /models opens the Models modal.")
        await host._bus.publish(
            SystemNotice(text="\n".join(lines), kind="info", session_id=sid)
        )
        return

    model_id = args.split()[0]
    profile = get_model_profile(model_id)
    if profile is None:
        await host._bus.publish(
            SystemNotice(
                text=f"Unknown model: {model_id}",
                kind="error",
                session_id=sid,
            )
        )
        return
    if host.turn_active:
        await host._bus.publish(
            SystemNotice(
                text="Cannot switch model while a turn is active.",
                kind="error",
                session_id=sid,
            )
        )
        return
    updated = switch_model_in_settings(
        model_id,
        provider=str(profile.get("provider") or "OpenAI"),
        api_base=profile.get("apiBase"),
    )
    apply_model_to_backend(host._backend, profile)
    rebuilt = await rebuild_backend_agent(host._backend)
    detail = (
        "Agent rebuilt with new model."
        if rebuilt
        else (
            "Active cfg updated; full provider swap needs agent restart "
            "(backend has no rebuild)."
        )
    )
    await host._bus.publish(
        ProfileSwitched(
            kind="model",
            profile_id=model_id,
            detail=detail,
            session_id=sid,
        )
    )
    from openjiuwen_icode.features.session_metadata import (
        persist_session_metadata,
    )

    persist_session_metadata(host)
    await host._bus.publish(
        SystemNotice(
            text=(
                f"Model set to {model_id} ({updated['provider']}). {detail}"
            ),
            kind="info",
            session_id=sid,
        )
    )


async def _cmd_new(host: SessionHost, sid: str | None) -> None:
    if host.turn_active:
        await host._bus.publish(
            SystemNotice(
                text="Cannot /new while a turn is active.",
                kind="error",
                session_id=sid,
            )
        )
        return
    new_id = f"cli-{uuid4().hex[:8]}"
    model = "demo"
    cfg = getattr(host._backend, "cfg", None)
    if cfg is not None:
        model = cfg.model
    store = host.session_store
    if store is not None:
        store.new_session(
            new_id,
            model,
            workdir=host.workdirs.primary or None,
        )
    host._session_id = new_id
    host._last_user_text = ""
    bind = getattr(host, "_bind_event_log", None)
    if callable(bind):
        bind(new_id)
    await host._bus.publish(
        SessionCreated(model=model, session_id=new_id)
    )
    await host._bus.publish(
        SystemNotice(
            text=f"New session {new_id}",
            kind="info",
            session_id=new_id,
        )
    )


async def _cmd_resume(
    host: SessionHost, args: str, sid: str | None
) -> None:
    if not args:
        await host._bus.publish(
            SystemNotice(
                text="Usage: /resume <session_id>",
                kind="error",
                session_id=sid,
            )
        )
        return
    if host.turn_active:
        await host._bus.publish(
            SystemNotice(
                text="Cannot /resume while a turn is active.",
                kind="error",
                session_id=sid,
            )
        )
        return
    store = host.session_store
    if store is None:
        await host._bus.publish(
            SystemNotice(
                text="No session store attached.",
                kind="error",
                session_id=sid,
            )
        )
        return
    try:
        session = store.switch_session(args.split()[0])
    except FileNotFoundError as exc:
        await host._bus.publish(
            SystemNotice(text=str(exc), kind="error", session_id=sid)
        )
        return
    from openjiuwen_icode.features.session_resume import (
        align_backend_session_after_resume,
        format_resume_agent_context_note,
    )

    resume_result = await align_backend_session_after_resume(host, session)
    from openjiuwen_icode.features.session_metadata import (
        persist_session_metadata,
    )

    persist_session_metadata(host)
    bind = getattr(host, "_bind_event_log", None)
    if callable(bind):
        bind(session.session_id)
    await host._bus.publish(
        SessionRestored(
            model=session.model,
            message_count=len(session.messages),
            title=session.title,
            agent_context=resume_result.agent_context,
            session_id=session.session_id,
        )
    )
    title_bit = f" — {session.title}" if session.title else ""
    context_note = format_resume_agent_context_note(resume_result)
    await host._bus.publish(
        SystemNotice(
            text=(
                f"Restored {session.session_id}{title_bit} "
                f"({len(session.messages)} messages, model={session.model}). "
                f"{context_note}"
            ),
            kind="info",
            session_id=session.session_id,
        )
    )


async def _cmd_fork(
    host: SessionHost, args: str, sid: str | None
) -> None:
    if host.turn_active:
        await host._bus.publish(
            SystemNotice(
                text="Cannot /fork while a turn is active.",
                kind="error",
                session_id=sid,
            )
        )
        return
    store = host.session_store
    if store is None:
        await host._bus.publish(
            SystemNotice(
                text="No session store attached.",
                kind="error",
                session_id=sid,
            )
        )
        return
    parts = args.split()
    source_id = parts[0] if parts else (host._session_id or "")
    if not source_id:
        await host._bus.publish(
            SystemNotice(
                text="Usage: /fork [source_session_id]",
                kind="error",
                session_id=sid,
            )
        )
        return
    new_id = f"cli-{uuid4().hex[:8]}"
    try:
        session = store.fork_session(source_id, new_id)
    except FileNotFoundError as exc:
        await host._bus.publish(
            SystemNotice(text=str(exc), kind="error", session_id=sid)
        )
        return
    except FileExistsError as exc:
        await host._bus.publish(
            SystemNotice(text=str(exc), kind="error", session_id=sid)
        )
        return
    from openjiuwen_icode.features.session_resume import (
        align_backend_session_after_resume,
        format_resume_agent_context_note,
    )

    host._last_user_text = ""
    resume_result = await align_backend_session_after_resume(host, session)
    from openjiuwen_icode.features.session_metadata import (
        persist_session_metadata,
    )

    persist_session_metadata(host)
    bind = getattr(host, "_bind_event_log", None)
    if callable(bind):
        bind(session.session_id)
    await host._bus.publish(
        SessionRestored(
            model=session.model,
            message_count=len(session.messages),
            title=session.title,
            agent_context=resume_result.agent_context,
            session_id=session.session_id,
        )
    )
    title_bit = f" — {session.title}" if session.title else ""
    context_note = format_resume_agent_context_note(resume_result)
    await host._bus.publish(
        SystemNotice(
            text=(
                f"Forked {source_id} → {session.session_id}{title_bit} "
                f"({len(session.messages)} messages, model={session.model}). "
                f"{context_note}"
            ),
            kind="info",
            session_id=session.session_id,
        )
    )


async def _cmd_export(
    host: SessionHost, args: str, sid: str | None
) -> None:
    """Export session as OpenCode-compatible ``{info, messages}`` JSON."""
    from pathlib import Path

    from openjiuwen_icode.export.opencode import (
        export_session_opencode,
        write_opencode_export,
    )

    store = host.session_store
    if store is None:
        await host._bus.publish(
            SystemNotice(
                text="No session store attached.",
                kind="error",
                session_id=sid,
            )
        )
        return

    tokens = args.split() if args else []
    sanitize = False
    out_path: Path | None = None
    session_id = sid or host.session_id or ""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in {"--sanitize", "-s"}:
            sanitize = True
            i += 1
            continue
        if tok in {"--out", "-o"}:
            if i + 1 >= len(tokens):
                await host._bus.publish(
                    SystemNotice(
                        text="Usage: /export [id] [--sanitize] [--out path]",
                        kind="error",
                        session_id=sid,
                    )
                )
                return
            out_path = Path(tokens[i + 1]).expanduser()
            i += 2
            continue
        if tok.startswith("-"):
            await host._bus.publish(
                SystemNotice(
                    text=f"Unknown flag: {tok}",
                    kind="error",
                    session_id=sid,
                )
            )
            return
        session_id = tok
        i += 1

    if not session_id:
        await host._bus.publish(
            SystemNotice(
                text="Usage: /export [id] [--sanitize] [--out path]",
                kind="error",
                session_id=sid,
            )
        )
        return

    try:
        from openjiuwen_icode.features.session_metadata import (
            export_directory_for_session,
        )

        session = store.current
        if session is None or session.session_id != session_id:
            session = store.load_session(session_id)
        directory = export_directory_for_session(
            session,
            fallback=host.workdirs.primary or "",
        )
        document = export_session_opencode(
            store,
            session_id,
            directory=directory,
            sanitize=sanitize,
        )
    except FileNotFoundError as exc:
        await host._bus.publish(
            SystemNotice(text=str(exc), kind="error", session_id=sid)
        )
        return
    except Exception as exc:
        await host._bus.publish(
            SystemNotice(
                text=f"Export failed: {exc}",
                kind="error",
                session_id=sid,
            )
        )
        return

    if out_path is None:
        out_path = (
            store.store_dir / session_id / "export.opencode.json"
        )
    try:
        write_opencode_export(document, out_path)
    except OSError as exc:
        await host._bus.publish(
            SystemNotice(
                text=f"Failed to write export: {exc}",
                kind="error",
                session_id=sid,
            )
        )
        return

    fidelity = (
        document.get("harness", {}) or {}
    ).get("fidelity", "unknown")
    n_msgs = len(document.get("messages") or [])
    await host._bus.publish(
        SystemNotice(
            text=(
                f"Exported {session_id} → {out_path} "
                f"({n_msgs} messages, fidelity={fidelity}"
                f"{', sanitized' if sanitize else ''})."
            ),
            kind="info",
            session_id=sid or session_id,
        )
    )


async def _cmd_diff(
    host: SessionHost, args: str, sid: str | None
) -> None:
    tracker = getattr(host, "mutations", None)
    if tracker is None:
        await host._bus.publish(
            SystemNotice(
                text="Mutation tracker not available for this session.",
                kind="error",
                session_id=sid,
            )
        )
        return
    turn_id = args.split()[0] if args.strip() else None
    text = tracker.format_diff(turn_id)
    await host._bus.publish(
        SystemNotice(text=text, kind="info", session_id=sid)
    )


async def _cmd_rollback(
    host: SessionHost, args: str, sid: str | None
) -> None:
    if host.turn_active:
        await host._bus.publish(
            SystemNotice(
                text="Cannot /rollback while a turn is active.",
                kind="error",
                session_id=sid,
            )
        )
        return
    tracker = getattr(host, "mutations", None)
    if tracker is None:
        await host._bus.publish(
            SystemNotice(
                text="Mutation tracker not available for this session.",
                kind="error",
                session_id=sid,
            )
        )
        return
    turn_id = args.split()[0] if args.strip() else None
    text = tracker.rollback_turn(turn_id)
    await host._bus.publish(
        SystemNotice(text=text, kind="info", session_id=sid)
    )


async def _cmd_title(
    host: SessionHost, args: str, sid: str | None
) -> None:
    store = host.session_store
    if store is None or store.current is None:
        await host._bus.publish(
            SystemNotice(
                text="No active session store.",
                kind="error",
                session_id=sid,
            )
        )
        return
    if not args:
        title = store.current.title or "(untitled)"
        source = store.current.title_source or "-"
        await host._bus.publish(
            SystemNotice(
                text=f"Title: {title}\nSource: {source}",
                kind="info",
                session_id=sid,
            )
        )
        return
    if store.set_title(args, source=TITLE_MANUAL, force=True):
        await host._bus.publish(
            SessionTitleUpdated(
                title=store.current.title,
                source=TITLE_MANUAL,
                session_id=sid or host.session_id,
            )
        )
        await host._bus.publish(
            SystemNotice(
                text=f"Title set: {store.current.title}",
                kind="info",
                session_id=sid,
            )
        )
    else:
        await host._bus.publish(
            SystemNotice(
                text="Title unchanged.",
                kind="info",
                session_id=sid,
            )
        )


async def _cmd_compact(host: SessionHost, sid: str | None) -> None:
    await host._bus.publish(
        CompactionStarted(reason="user:/compact", session_id=sid)
    )
    compact = getattr(host._backend, "compact", None)
    if callable(compact):
        try:
            summary = await compact()
            await host._bus.publish(
                CompactionFinished(
                    summary=str(summary or "ok"),
                    ok=True,
                    session_id=sid,
                )
            )
            return
        except Exception as exc:  # noqa: BLE001
            await host._bus.publish(
                CompactionFinished(
                    summary=str(exc), ok=False, session_id=sid
                )
            )
            return
    await host._bus.publish(
        CompactionFinished(
            summary=(
                "Manual /compact: DialogueCompressor auto-runs on token "
                "threshold; explicit force API not exposed on LocalBackend yet. "
                "Chrys four-phase (turn-boundary + last_words) alignment is "
                "partial — DeepAgent ContextProcessorRail handles mid-turn "
                "pressure; user /compact marks CompactionStarted/Finished."
            ),
            ok=True,
            session_id=sid,
        )
    )


async def _cmd_theme(
    host: SessionHost, args: str, sid: str | None
) -> None:
    from openjiuwen_icode.features.tui_prefs import (
        BUILTIN_THEMES,
        get_theme,
        set_theme,
    )

    if not args.strip():
        cur = get_theme()
        text = (
            f"Theme: {cur}\n"
            f"Available: {', '.join(BUILTIN_THEMES)}\n"
            "Set: /theme <name>"
        )
        await host._bus.publish(
            SystemNotice(text=text, kind="info", session_id=sid)
        )
        return
    name = args.split()[0]
    set_theme(name)
    await host._bus.publish(
        SystemNotice(
            text=f"Theme set to {name} (persisted in settings.json).",
            kind="info",
            session_id=sid,
        )
    )


async def _cmd_notifications(
    host: SessionHost, args: str, sid: str | None
) -> None:
    from openjiuwen_icode.features.tui_prefs import (
        notifications_enabled,
        set_notifications,
    )

    token = args.split()[0].lower() if args.strip() else ""
    if token in {"on", "off", "1", "0", "true", "false"}:
        enabled = token in {"on", "1", "true"}
        set_notifications(enabled)
        await host._bus.publish(
            SystemNotice(
                text=f"Notifications {'enabled' if enabled else 'disabled'}.",
                kind="info",
                session_id=sid,
            )
        )
        return
    state = "on" if notifications_enabled() else "off"
    await host._bus.publish(
        SystemNotice(
            text=(
                f"Notifications: {state}\n"
                "Toggle: /notifications on|off"
            ),
            kind="info",
            session_id=sid,
        )
    )


async def _cmd_hooks(host: SessionHost, sid: str | None) -> None:
    from openjiuwen_icode.paths import icode_home

    hooks_dir = icode_home() / "hooks"
    entries: list[str] = []
    if hooks_dir.is_dir():
        for path in sorted(hooks_dir.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                entries.append(path.name)
    text = (
        f"Hooks dir: {hooks_dir}\n"
        "Status: T-41 MVP — discovery only; subprocess hooks are not "
        "auto-executed yet (cannot batch-approve).\n"
    )
    if entries:
        text += "Found:\n" + "\n".join(f"  - {e}" for e in entries)
    else:
        text += "No hook scripts found."
    await host._bus.publish(
        SystemNotice(text=text, kind="info", session_id=sid)
    )

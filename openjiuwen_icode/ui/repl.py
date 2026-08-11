"""Interactive REPL for OpenJiuWen iCode.

Features:
- Multi-turn conversation with context
- Slash commands (/help, /exit, /clear, /status, /cost, /compact, /sessions)
- Shell passthrough (``! <command>``)
- Ctrl+C three-layer interrupt
- HITL interaction support
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import (
    Completer,
    Completion,
)
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.table import Table

from openjiuwen_icode import __version__
from openjiuwen_icode.agent.config import CLIConfig
from openjiuwen_icode.branding import PRODUCT_NAME
from openjiuwen_icode.rails.token_tracker import (
    TokenTrackingRail,
)
from openjiuwen_icode.storage.session_store import (
    SessionStore,
)
from openjiuwen_icode.ui.renderer import render_stream

if TYPE_CHECKING:
    from openjiuwen_icode.agent.factory import (
        AgentBackend,
    )


# ---------------------------------------------------------------------------
# Interrupt manager
# ---------------------------------------------------------------------------


class InterruptManager:
    """Three-layer Ctrl+C handler.

    - 1st press: abort current stream
    - 2nd press within window: warn user
    - 3rd press within window: exit
    """

    def __init__(self, window: float = 2.0) -> None:
        self._count: int = 0
        self._last_time: float = 0.0
        self._window: float = window

    def handle(self, backend: AgentBackend) -> str:
        """Process a Ctrl+C event.

        Returns:
            ``"abort"`` | ``"warn"`` | ``"exit"``.
        """
        now = time.monotonic()
        if now - self._last_time > self._window:
            self._count = 0
        self._count += 1
        self._last_time = now

        if self._count == 1:
            asyncio.ensure_future(backend.abort())
            return "abort"
        elif self._count == 2:
            return "warn"
        else:
            return "exit"


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------


async def _cmd_help(
    console: Console, **_: Any
) -> None:
    """Display available commands."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("/help", "Show this help message")
    table.add_row("/exit", f"Exit {PRODUCT_NAME}")
    table.add_row("/clear", "Clear screen")
    table.add_row("/status", "Show token usage and model info")
    table.add_row("/cost", "Show token cost summary")
    table.add_row("/compact", "Compact conversation history")
    table.add_row(
        "/sessions", "List saved sessions"
    )
    table.add_row(
        "/auto-harness",
        "Run auto-harness optimization",
    )
    table.add_row("! <cmd>", "Execute a shell command")
    console.print(table)

    if _SKILL_COMMANDS:
        console.print(
            "\n[bold]Skills[/bold] "
            "[dim](invoke with /<skill-name>)[/dim]"
        )
        skill_table = Table(
            show_header=False, box=None, padding=(0, 2)
        )
        skill_table.add_column(style="bold cyan")
        skill_table.add_column()
        for cmd in sorted(_SKILL_COMMANDS):
            desc = _SLASH_DESCRIPTIONS.get(cmd, "")
            skill_table.add_row(cmd, desc)
        console.print(skill_table)


async def _cmd_exit(**_: Any) -> None:
    """Signal REPL exit (handled by caller)."""
    raise _ExitREPL


async def _cmd_clear(console: Console, **_: Any) -> None:
    """Clear the terminal screen."""
    console.clear()


async def _cmd_status(
    console: Console,
    tracker: Optional[TokenTrackingRail] = None,
    cfg: Optional[CLIConfig] = None,
    **_: Any,
) -> None:
    """Show model info and token usage."""
    if cfg:
        console.print(
            f"[bold]Model:[/bold] {cfg.model} ({cfg.provider})"
        )
    if tracker:
        s = tracker.get_summary()
        console.print(
            f"[bold]Input tokens:[/bold]  "
            f"{s['input_tokens']:,}"
        )
        console.print(
            f"[bold]Output tokens:[/bold] "
            f"{s['output_tokens']:,}"
        )
        console.print(
            f"[bold]Total tokens:[/bold]  "
            f"{s['total_tokens']:,}"
        )
        console.print(
            f"[bold]Model calls:[/bold]   "
            f"{s['model_calls']}"
        )


async def _cmd_cost(
    console: Console,
    tracker: Optional[TokenTrackingRail] = None,
    **_: Any,
) -> None:
    """Show token cost summary."""
    if tracker is None:
        console.print("[dim]No token data available.[/dim]")
        return
    s = tracker.get_summary()
    console.print("[bold]Token usage:[/bold]")
    console.print(f"  Input:  {s['input_tokens']:,} tokens")
    console.print(
        f"  Output: {s['output_tokens']:,} tokens"
    )
    console.print(f"  Total:  {s['total_tokens']:,} tokens")
    console.print(f"  Calls:  {s['model_calls']}")


async def _cmd_compact(console: Console, **_: Any) -> None:
    """Compact conversation (MVP: simple info message)."""
    console.print(
        "[dim]Conversation compaction is not yet "
        "implemented in MVP.[/dim]"
    )


def _auto_harness_help(console: Console) -> None:
    """Print /auto-harness subcommand usage."""
    console.print("[bold]Usage:[/bold]")
    tbl = Table(
        show_header=False, box=None, padding=(0, 2),
    )
    tbl.add_column(style="bold cyan")
    tbl.add_column()
    tbl.add_row(
        "/auto-harness run [--task TOPIC] "
        "[--goal TEXT] "
        "[--pipeline meta|extended|auto] "
        "[--dry-run] "
        "[--no-push] [--budget N]",
        "执行优化周期",
    )
    tbl.add_row(
        "/auto-harness <自然语言目标>",
        "直接把自然语言作为本轮优化目标并执行全流程",
    )
    tbl.add_row(
        "/auto-harness experience search <query>",
        "搜索经验库",
    )
    tbl.add_row(
        "/auto-harness experience list "
        "[--type TYPE] [--limit N]",
        "列出经验库记录",
    )
    tbl.add_row(
        "/auto-harness gap-analyze",
        "差距分析",
    )
    tbl.add_row(
        "/auto-harness history [--limit N]",
        "查看优化历史",
    )
    console.print(tbl)


async def _cmd_auto_harness(
    console: Console,
    text: str = "",
    cfg: Optional[CLIConfig] = None,
    backend: Any = None,
    **_: Any,
) -> None:
    """Dispatch /auto-harness subcommands."""
    import os
    import shlex

    parts = text.split(None, 1)
    args_str = parts[1] if len(parts) > 1 else ""

    try:
        tokens = shlex.split(args_str)
    except ValueError as exc:
        console.print(f"[red]参数解析错误: {exc}[/red]")
        return

    if not tokens:
        _auto_harness_help(console)
        return

    subcmd = tokens[0]
    rest = tokens[1:]
    workspace = ""
    if cfg:
        workspace = cfg.workspace or ""
    if not workspace:
        workspace = os.getcwd()

    if subcmd == "run":
        await _subcmd_run(
            console, rest, workspace, cfg,
            backend=backend,
        )
    elif subcmd == "experience":
        await _subcmd_memory(console, rest, workspace)
    elif subcmd == "gap-analyze":
        await _subcmd_gap_analyze(console, rest, workspace)
    elif subcmd == "history":
        await _subcmd_history(console, rest, workspace)
    else:
        await _subcmd_run(
            console,
            ["--goal", args_str],
            workspace,
            cfg,
            backend=backend,
        )


async def _subcmd_run(
    console: Console,
    args: list[str],
    workspace: str,
    cfg: Optional[CLIConfig] = None,
    *,
    backend: Any = None,
) -> None:
    """Handle /auto-harness run."""
    import time as _time

    from openjiuwen.auto_harness.schema import (
        OptimizationTask,
        normalize_pipeline_preference,
        is_placeholder_local_repo,
        load_auto_harness_config,
    )
    from openjiuwen.auto_harness.pipelines import (
        META_EVOLVE_PIPELINE,
    )
    from openjiuwen.auto_harness.orchestrator import (
        create_auto_harness_orchestrator,
    )
    from openjiuwen.auto_harness.infra.github_cli import (
        ensure_github_cli_ready,
    )

    # Parse flags
    task: Optional[str] = None
    dry_run = False
    no_push = False
    budget: Optional[float] = None
    goal: Optional[str] = None
    pipeline: Optional[str] = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--task" and i + 1 < len(args):
            task = args[i + 1]
            i += 2
        elif a == "--dry-run":
            dry_run = True
            i += 1
        elif a == "--no-push":
            no_push = True
            i += 1
        elif a == "--budget" and i + 1 < len(args):
            try:
                budget = float(args[i + 1])
            except ValueError:
                console.print(
                    "[red]--budget 需要数字[/red]"
                )
                return
            i += 2
        elif a == "--goal" and i + 1 < len(args):
            goal = args[i + 1]
            i += 2
        elif a == "--pipeline" and i + 1 < len(args):
            raw_pipeline = args[i + 1]
            if raw_pipeline not in ("meta", "extended", "auto"):
                console.print(
                    "[red]--pipeline 只支持 meta、extended 或 auto[/red]"
                )
                return
            pipeline = raw_pipeline
            i += 2
        else:
            console.print(
                f"[red]未知参数: {a}[/red]"
            )
            return

    # data_dir 由 CLI workspace 决定
    data_dir = str(
        Path(workspace) / "auto_harness"
    )
    config_path = str(
        Path(data_dir) / "config.yaml"
    )
    config = load_auto_harness_config(
        config_path, workspace_hint=workspace,
    )
    config.data_dir = data_dir
    if (
        config.local_repo
        and (
            is_placeholder_local_repo(
                config.local_repo
            )
            or not Path(config.local_repo).exists()
        )
    ):
        console.print(
            "[yellow]忽略无效的 local_repo 配置: "
            f"{config.local_repo}[/yellow]"
        )
        config.local_repo = ""
    if config.config_bootstrapped:
        console.print(
            "[yellow]已初始化 auto-harness 配置模板:"
            f" {config.config_path}[/yellow]"
        )
    if not config.local_repo and config.suggested_local_repo:
        config.local_repo = config.suggested_local_repo
        console.print(
            "[yellow]检测到本地仓库，临时使用 "
            f"local_repo={config.local_repo}。"
            "建议写回 config.yaml。[/yellow]"
        )
    elif not config.local_repo:
        console.print(
            "[yellow]未配置 local_repo，"
            "auto-harness 将使用 clone 缓存。"
            f"请编辑 {config.config_path or config_path}"
            " 补充 local_repo。[/yellow]"
        )
    if config.local_repo:
        config.workspace = config.local_repo
    elif not config.workspace:
        config.workspace = workspace

    # 从 CLIConfig 构建 Model
    if cfg:
        from openjiuwen.core.foundation.llm.model import (
            Model,
        )
        from openjiuwen.core.foundation.llm.schema.config import (
            ModelClientConfig,
            ModelRequestConfig,
        )

        config.model = Model(
            model_client_config=ModelClientConfig(
                client_provider=cfg.provider,
                api_key=cfg.api_key,
                api_base=cfg.api_base,
                timeout=config.model_timeout_secs,
                verify_ssl=False,
            ),
            model_config=ModelRequestConfig(
                model=cfg.model,
                temperature=0.2,
                top_p=0.9,
            ),
        )

    # CLI 参数覆盖
    if budget is not None:
        config.session_budget_secs = budget
    if no_push:
        config.git_remote = ""
    if goal:
        config.optimization_goal = goal
    config.pipeline_preference = normalize_pipeline_preference(
        pipeline or META_EVOLVE_PIPELINE
    )

    ensure_github_cli_ready(
        lambda msg: console.print(
            f"[yellow]{msg}[/yellow]"
        )
    )

    debug_dir = Path(config.runs_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)

    # tasks=None 时 orchestrator 自动走
    # assess → plan → implement → learnings
    tasks: Optional[list[OptimizationTask]] = None
    if task:
        tasks = [OptimizationTask(topic=task)]

    if dry_run and tasks:
        import json

        data = [
            {
                "topic": t.topic,
                "description": t.description,
                "files": t.files,
            }
            for t in tasks
        ]
        console.print(json.dumps(
            data, ensure_ascii=False, indent=2,
        ))
        console.print(
            "[dim][dry-run] 跳过执行[/dim]"
        )
        return

    from openjiuwen_icode.rails.tool_tracker import (
        ToolTrackingRail,
    )

    t0 = _time.monotonic()
    agent = (
        getattr(backend, "agent", None)
        if backend
        else None
    )
    orch = create_auto_harness_orchestrator(
        config,
        agent=agent,
        stream_rails=[ToolTrackingRail()],
    )

    async def _on_activate_interaction(
        iid: str, value: Any,
    ) -> str:
        """Handle activate_confirm interaction in CLI."""
        if (
            isinstance(value, dict)
            and value.get("interaction_type")
            == "activate_confirm"
        ):
            ext_name = value.get(
                "extension_name", "unknown"
            )
            summary = value.get("components_summary", {})
            console.print()
            console.print(
                f"[bold]扩展 {ext_name} 已就绪[/bold]"
            )
            if value.get("runtime_path"):
                console.print(
                    f"  路径: {value['runtime_path']}"
                )
            if summary:
                console.print(
                    f"  组件: "
                    f"{summary.get('rails', 0)} rails, "
                    f"{summary.get('tools', 0)} tools, "
                    f"{summary.get('skills', 0)} skills"
                )
            console.print()
            console.print(
                "  [green][A][/green] 接受并热加载"
            )
            console.print(
                "  [red][R][/red] 拒绝并清理"
            )
            console.print()
            while True:
                choice = console.input(
                    "[bold]选择 (A/R): [/bold]"
                ).strip().lower()
                if choice in ("a", "accept", ""):
                    action = "accept"
                    break
                if choice in ("r", "reject"):
                    action = "reject"
                    break
                console.print(
                    "[dim]请输入 A 或 R[/dim]"
                )
            orch.run_session_stream(
                message={
                    "interaction_id": iid,
                    "action": action,
                },
            )
            return action
        return ""

    stream = orch.run_session_stream(tasks=tasks)
    await render_stream(
        stream,
        console,
        on_interaction=_on_activate_interaction,
    )
    results = orch.results
    elapsed = _time.monotonic() - t0
    ok = sum(1 for r in results if r.success)
    console.print(
        f"Session 完成: {ok}/{len(results)} 成功, "
        f"耗时 {elapsed:.1f}s"
    )
    for i_r, r in enumerate(results):
        s = (
            "[green]OK[/green]"
            if r.success
            else "[red]FAIL[/red]"
        )
        console.print(
            f"  Task {i_r + 1}: {s}"
            f" | pr={r.pr_url or 'N/A'}"
            f" | error={r.error or 'none'}"
        )
        if r.summary:
            console.print(
                f"    summary={r.summary}"
            )


async def _subcmd_memory(
    console: Console,
    args: list[str],
    workspace: str,
) -> None:
    """Handle /auto-harness experience <search|list>."""
    from openjiuwen.auto_harness.experience.experience_store import (
        ExperienceStore,
    )

    mem_dir = str(
        Path(workspace) / "auto_harness" / "experience"
    )

    if not args:
        console.print(
            "[red]用法: /auto-harness experience "
            "<search|list>[/red]"
        )
        return

    action = args[0]
    rest = args[1:]

    if action == "search":
        query = " ".join(rest)
        if not query:
            console.print(
                "[red]用法: /auto-harness experience "
                "search <query>[/red]"
            )
            return
        store = ExperienceStore(mem_dir)
        results = await store.search(query, top_k=10)
        if not results:
            console.print("[dim]无匹配结果[/dim]")
            return
        for m in results:
            console.print(
                f"[{m.type.value}] {m.topic}: "
                f"{m.summary or m.outcome}"
            )

    elif action == "list":
        mem_type: Optional[str] = None
        limit = 10
        i = 0
        while i < len(rest):
            if rest[i] == "--type" and i + 1 < len(rest):
                mem_type = rest[i + 1]
                i += 2
            elif rest[i] == "--limit" and i + 1 < len(rest):
                try:
                    limit = int(rest[i + 1])
                except ValueError:
                    console.print(
                        "[red]--limit 需要整数[/red]"
                    )
                    return
                i += 2
            else:
                console.print(
                    f"[red]未知参数: {rest[i]}[/red]"
                )
                return
        store = ExperienceStore(mem_dir)
        entries = await store.list_recent(limit=limit)
        if mem_type:
            entries = [
                e for e in entries
                if e.type.value == mem_type
            ]
        if not entries:
            console.print("[dim]无记录[/dim]")
            return
        for m in entries:
            console.print(
                f"[{m.type.value}] {m.topic}: "
                f"{m.summary or m.outcome}"
            )
    else:
        console.print(
            f"[red]未知 experience 子命令: {action}[/red]"
        )


async def _subcmd_gap_analyze(
    console: Console,
    args: list[str],
    workspace: str,
) -> None:
    """Handle /auto-harness gap-analyze."""
    from openjiuwen.auto_harness.schema import (
        AutoHarnessConfig,
    )
    from openjiuwen.auto_harness.stages.assess import (
        run_gap_analysis,
    )

    if args:
        console.print(
            f"[red]未知参数: {args[0]}[/red]"
        )
        return

    config = AutoHarnessConfig(workspace=workspace)
    gaps = await run_gap_analysis(
        config, harness_state="",
    )
    if not gaps:
        console.print(
            "[dim]Phase 1 占位: "
            "差距分析尚未接入 LLM[/dim]"
        )
        return
    for g in gaps:
        console.print(
            f"[{g.priority:.1f}] {g.feature}: "
            f"{g.gap_description}"
        )




async def _subcmd_history(
    console: Console,
    args: list[str],
    workspace: str,
) -> None:
    """Handle /auto-harness history."""
    from openjiuwen.auto_harness.experience.experience_store import (
        ExperienceStore,
    )

    limit = 20
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                console.print(
                    "[red]--limit 需要整数[/red]"
                )
                return
            i += 2
        else:
            console.print(
                f"[red]未知参数: {args[i]}[/red]"
            )
            return

    mem_dir = str(
        Path(workspace) / "auto_harness" / "experience"
    )
    store = ExperienceStore(mem_dir)
    entries = await store.list_recent(limit=limit)
    if not entries:
        console.print("[dim]无记录[/dim]")
        return
    for m in entries:
        console.print(
            f"[{m.type.value}] {m.topic}: "
            f"{m.summary or m.outcome}"
        )


async def _cmd_sessions(
    console: Console,
    store: Optional[SessionStore] = None,
    **_: Any,
) -> None:
    """List saved sessions."""
    if store is None:
        console.print("[dim]No session store.[/dim]")
        return
    sessions = store.list_sessions()
    if not sessions:
        console.print("[dim]No saved sessions.[/dim]")
        return
    table = Table(
        title="Sessions", show_lines=False
    )
    table.add_column("", width=1)
    table.add_column("Title", style="bold")
    table.add_column("ID", style="cyan")
    table.add_column("Model")
    table.add_column("Updated")
    table.add_column("Msgs", justify="right")
    current_id = getattr(store.current, "session_id", None) if store.current else None
    for s in sessions:
        mark = "*" if current_id and s["id"] == current_id else ""
        when = str(s.get("updated_at") or s.get("created_at") or "")[:16]
        table.add_row(
            mark,
            str(s.get("title") or "Untitled"),
            s["id"],
            s.get("model", ""),
            when.replace("T", " "),
            str(s.get("turns", 0)),
        )
    console.print(table)


class _ExitREPL(Exception):
    """Sentinel exception to break the REPL loop."""


SLASH_COMMANDS: dict[str, Any] = {
    "/help": _cmd_help,
    "/exit": _cmd_exit,
    "/quit": _cmd_exit,
    "/clear": _cmd_clear,
    "/status": _cmd_status,
    "/cost": _cmd_cost,
    "/compact": _cmd_compact,
    "/sessions": _cmd_sessions,
    "/auto-harness": _cmd_auto_harness,
}

#: Human-readable descriptions shown as completion meta text.
#: ``/quit`` is intentionally omitted (hidden alias).
_SLASH_DESCRIPTIONS: dict[str, str] = {
    "/help": "Show available commands",
    "/exit": "Exit the REPL",
    "/clear": "Clear the screen",
    "/status": "Show model and token usage",
    "/cost": "Show token cost breakdown",
    "/compact": "Compact conversation history",
    "/sessions": "List saved sessions",
    "/config": "Show current configuration",
    "/auto-harness": "Run auto-harness optimization",
}

#: Skill commands registered dynamically at startup.
#: Maps ``/skill-name`` → ``Skill`` object.
_SKILL_COMMANDS: dict[str, Any] = {}


class SlashCompleter(Completer):
    """Tab-completion for ``/`` slash commands.

    Completes only when the cursor is on the first word
    and the text starts with ``/``.
    """

    def get_completions(
        self,
        document: Document,
        complete_event: Any,
    ):  # type: ignore[override]
        """Yield :class:`Completion` for matching commands."""
        text = document.text_before_cursor
        # Only complete the first word
        if " " in text:
            return
        if not text.startswith("/"):
            return
        # Built-in commands
        for cmd in sorted(SLASH_COMMANDS):
            # Skip /quit — it's a hidden alias
            if cmd == "/quit":
                continue
            if cmd.startswith(text):
                meta = _SLASH_DESCRIPTIONS.get(cmd, "")
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=meta,
                )


# ---------------------------------------------------------------------------
# Shell passthrough
# ---------------------------------------------------------------------------


async def _handle_shell(
    cmd: str, console: Console, store: Optional[SessionStore] = None
) -> None:
    """Execute a shell command directly (no agent)."""
    from openjiuwen_icode.shell_passthrough import (
        persist_shell_turn,
        run_shell_command,
    )

    result = await run_shell_command(cmd)
    if result.stdout:
        console.print(result.stdout.rstrip("\n"))
    if result.stderr:
        err = result.stderr.rstrip("\n")
        console.print(f"[red]{err}[/red]")
    if result.returncode != 0:
        console.print(f"[dim]exit {result.returncode}[/dim]")
    persist_shell_turn(store, result)


# ---------------------------------------------------------------------------
# Skill registration
# ---------------------------------------------------------------------------

#: Inline skill bodies registered for slash invocation.
_INLINE_SKILL_COMMANDS: dict[str, Any] = {}


def _scan_skill_dirs() -> dict[str, Path]:
    """Scan default skill directories and return discovered skills."""
    from openjiuwen_icode.skills import (
        collect_default_skill_dirs,
        discover_skills,
        load_skills_config,
    )

    cfg = load_skills_config()
    roots = collect_default_skill_dirs(
        cwd=Path.cwd(),
        extra_paths=cfg.paths,
        include_chrys=cfg.auto_load_chrys_skills,
        include_user_agents=cfg.auto_load_user_agents_skills,
        include_cwd_agents=cfg.auto_load_cwd_agents_skills,
    )
    discovered = discover_skills(roots)
    # Stash descriptions for registration.
    _scan_skill_dirs._descs = {  # type: ignore[attr-defined]
        name: skill.description for name, skill in discovered.items()
    }
    return {name: skill.skill_md for name, skill in discovered.items()}


def _register_skill_commands(
    skills: dict[str, Path],
) -> None:
    """Register discovered skills as slash commands."""
    from openjiuwen_icode.skills import load_skills_config
    from openjiuwen_icode.skills.scan import _read_frontmatter_fields

    descs = getattr(_scan_skill_dirs, "_descs", {})
    for name, skill_md in skills.items():
        cmd = f"/{name}"
        if cmd in SLASH_COMMANDS and cmd not in _SKILL_COMMANDS:
            continue
        SLASH_COMMANDS[cmd] = None
        desc = str(descs.get(name) or "")
        if not desc:
            try:
                desc = (
                    _read_frontmatter_fields(skill_md).get("description")
                    or ""
                ).strip()
            except OSError:
                desc = ""
        if len(desc) > 60:
            desc = desc[:57] + "..."
        _SLASH_DESCRIPTIONS[cmd] = desc or "Skill"
        _SKILL_COMMANDS[cmd] = skill_md

    cfg = load_skills_config()
    for inline in cfg.inline:
        cmd = f"/{inline.name}"
        if cmd in _SKILL_COMMANDS:
            continue  # file skill wins
        if cmd in SLASH_COMMANDS and cmd not in _INLINE_SKILL_COMMANDS:
            continue
        SLASH_COMMANDS[cmd] = None
        desc = inline.description or "Inline skill"
        if len(desc) > 60:
            desc = desc[:57] + "..."
        _SLASH_DESCRIPTIONS[cmd] = desc
        _INLINE_SKILL_COMMANDS[cmd] = inline


def _build_skill_query(skill_md: Path, args: str) -> str:
    """Build a structured query for skill invocation."""
    from openjiuwen_icode.skills import build_skill_query

    return build_skill_query(skill_md, args)


def _scan_skills() -> None:
    """Convenience: scan and register all default skills."""
    skills = _scan_skill_dirs()
    _register_skill_commands(skills)


# ---------------------------------------------------------------------------
# Slash command dispatcher (extracted for testability)
# ---------------------------------------------------------------------------


async def _handle_slash(
    text: str,
    console: Console,
    backend: Any,
    store: Any,
    *,
    tracker: Any = None,
    cfg: Any = None,
) -> Optional[str]:
    """Dispatch a slash command.

    Returns the slash command name (e.g. ``/my-skill``) when
    the command maps to a skill (caller must build the query
    and forward it to the agent).  Returns ``None`` for
    built-in commands (handled internally).

    Raises:
        _ExitREPL: When the user invokes ``/exit`` or ``/quit``.\
    """
    cmd_name = text.split(None, 1)[0].lower()

    # Known command?
    if cmd_name not in SLASH_COMMANDS:
        console.print(
            f"[red]Unknown command: {cmd_name}[/red]"
        )
        console.print(
            "Type /help to see available commands."
        )
        return None

    handler = SLASH_COMMANDS[cmd_name]

    # Skill command (handler is None)?
    if handler is None:
        if cmd_name in _SKILL_COMMANDS or cmd_name in _INLINE_SKILL_COMMANDS:
            return cmd_name
        return None

    # Built-in command
    await handler(
        console=console,
        backend=backend,
        store=store,
        tracker=tracker,
        cfg=cfg,
        text=text,
    )
    return None


# ---------------------------------------------------------------------------
# HITL interaction — display + answer collection
# ---------------------------------------------------------------------------


def _extract_question_text(request: Any) -> str:
    """Extract the human-readable question from an interrupt request.

    The *request* is typically a ``ToolCallInterruptRequest`` (or
    plain ``InterruptRequest``).  This function tries, in order:

    1. ``tool_args`` → parse ``query`` from the JSON/dict args
       (preferred for ``AskUserRail``; the ``message`` field
       may still be the generic ``"Please input"`` fallback).
    2. ``message`` field.
    3. ``str(request)`` as last resort.

    Args:
        request: The raw interrupt request payload.

    Returns:
        A clean string to show the user.
    """
    # 1. Try to get the actual query from tool_args
    tool_args = getattr(request, "tool_args", None)
    if tool_args:
        import json as _json

        if isinstance(tool_args, str):
            try:
                tool_args = _json.loads(tool_args)
            except (ValueError, TypeError):
                pass
        if isinstance(tool_args, dict):
            query = tool_args.get("query", "")
            if query:
                return str(query)

    # 2. Use the message field
    message = getattr(request, "message", "")
    if message and message != "Please input":
        return message

    # 3. Fallback
    return str(request)


def _render_interaction(
    request: Any, console: Console
) -> None:
    """Render an interaction request to the terminal.

    Shows different formats for different interrupt types:

    - **AskUserRail** (``tool_name == "ask_user"``):
      prints questions with options in a user-friendly style.
    - **ConfirmInterruptRail** (other tool names):
      shows which tool wants approval + its arguments.

    Args:
        request: The ``ToolCallInterruptRequest`` payload.
        console: Rich console for output.
    """
    tool_name = getattr(request, "tool_name", "")

    if tool_name == "ask_user":
        questions = getattr(request, "questions", None)
        console.print("\n[bold]Agent needs your input:[/bold]")
        if questions:
            for i, q in enumerate(questions, 1):
                header = q.get("header", f"Q{i}")
                question_text = q.get("question", "")
                options = q.get("options", [])

                console.print(f"\n[cyan]{header}:[/cyan] {question_text}")
                if options:
                    for j, opt in enumerate(options, 1):
                        label = opt.get("label", "")
                        desc = opt.get("description", "")
                        console.print(f"  [dim]{j}.[/dim] {label} - {desc}")
    else:
        from openjiuwen_icode.ui.tool_display import (
            get_display_name,
        )

        display_name = get_display_name(tool_name)
        console.print(
            f"\n[bold yellow]⚠ Approve {display_name}?"
            f"[/bold yellow]"
        )
        tool_args = getattr(request, "tool_args", None)
        if tool_args:
            import json as _json

            if isinstance(tool_args, str):
                try:
                    parsed = _json.loads(tool_args)
                    for k, v in parsed.items():
                        val = str(v)
                        if len(val) > 200:
                            val = val[:200] + "..."
                        console.print(f"[dim]  {k}: {val}[/dim]")
                except (ValueError, TypeError):
                    console.print(f"[dim]  args: {tool_args}[/dim]")
            elif isinstance(tool_args, dict):
                for k, v in tool_args.items():
                    val = str(v)
                    if len(val) > 200:
                        val = val[:200] + "..."
                    console.print(f"[dim]  {k}: {val}[/dim]")
        console.print(
            "[dim]  (y/yes=approve, n/no=reject,"
            " or type feedback)[/dim]"
        )


async def _collect_interaction_answers(
    pending: list[Any],
    prompt_session: PromptSession,
    console: Console,
) -> Any:
    """Collect user answers for pending interactions.

    Prompts the user for each pending interaction and
    builds an ``InteractiveInput`` ready to resume the agent.

    Args:
        pending: List of ``PendingInteraction`` objects from
            :func:`render_stream`.
        prompt_session: prompt_toolkit session for input.
        console: Rich console for output.

    Returns:
        An ``InteractiveInput`` instance to pass as query
        for the resume call, or ``None`` if no pending
        interactions exist.
    """
    if not pending:
        return None

    from openjiuwen.core.session import InteractiveInput

    interactive_input = InteractiveInput()

    for item in pending:
        iid = item.interaction_id
        request = item.request
        tool_name = getattr(request, "tool_name", "")

        if tool_name == "ask_user":
            questions = getattr(request, "questions", None)
            if questions:
                answers = {}
                for q in questions:
                    question_text = q.get("question", "")
                    q_answer = await prompt_session.prompt_async(
                        f"Answer for '{question_text}'> "
                    )
                    answers[question_text] = q_answer.strip()
                interactive_input.update(iid, {"answers": answers})
            else:
                answer = await prompt_session.prompt_async("Answer> ")
                interactive_input.update(iid, {"answer": answer.strip()})
        else:
            answer = await prompt_session.prompt_async("Approve? (y/n)> ")
            answer = answer.strip()
            approved = answer.lower() in (
                "y",
                "yes",
                "ok",
                "approve",
                "true",
                "1",
                "",
            )
            feedback = (
                ""
                if approved
                else (answer or "User rejected")
            )
            interactive_input.update(
                iid,
                {
                    "approved": approved,
                    "feedback": feedback,
                    "auto_confirm": False,
                },
            )

    return interactive_input


# ---------------------------------------------------------------------------
# Welcome banner (Claude Code inspired)
# ---------------------------------------------------------------------------


def _print_welcome(
    console: Console, cfg: CLIConfig
) -> None:
    """Display the REPL welcome banner in Claude Code style."""
    from rich.columns import Columns
    from rich.panel import Panel
    from rich.text import Text

    # ── Left side: branding ──
    brand = Text(justify="center")
    brand.append("\n")
    brand.append(f"Welcome to {PRODUCT_NAME}\n", style="dim")
    brand.append("\n")
    brand.append("  \u2588\u2588\u2588\u2588\n", style="bold cyan")
    brand.append(" \u2588\u2588  \u2588\u2588\n", style="bold cyan")
    brand.append("  \u2588\u2588\u2588\u2588\n", style="bold cyan")
    brand.append("\n")
    brand.append(
        f"  {cfg.model} ({cfg.provider})\n",
        style="dim",
    )
    brand.append(f"  {cfg.cwd}\n", style="dim")

    # ── Right side: tips ──
    tips = Text()
    tips.append(
        "Tips for getting started\n", style="bold"
    )
    tips.append(
        "Create an OPENJIUWEN.md for project rules\n",
        style="dim",
    )
    tips.append(
        "\u2500" * 40 + "\n", style="dim"
    )
    tips.append("Commands\n", style="bold")
    tips.append(
        "  /help      Show available commands\n",
        style="dim",
    )
    tips.append(
        "  /status    Token usage & model info\n",
        style="dim",
    )
    tips.append(
        f"  /exit      Exit {PRODUCT_NAME}\n",
        style="dim",
    )
    tips.append(
        "  ! <cmd>    Run a shell command\n",
        style="dim",
    )

    columns = Columns(
        [brand, tips],
        equal=True,
        expand=True,
    )

    panel = Panel(
        columns,
        title=f"[bold]{PRODUCT_NAME} v{__version__}[/bold]",
        border_style="cyan",
        expand=True,
    )
    console.print(panel)
    console.print()


# ---------------------------------------------------------------------------
# Main REPL loop
# ---------------------------------------------------------------------------


async def run_repl(
    backend: AgentBackend,
    cfg: CLIConfig,
    session_store: SessionStore,
) -> None:
    """Run the interactive REPL.

    Args:
        backend: Agent execution backend.
        cfg: CLI configuration.
        session_store: Session persistence store.
    """
    console = Console()
    history_path = Path.home() / ".icode_history"
    prompt_session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        completer=SlashCompleter(),
    )
    interrupt_mgr = InterruptManager()

    # Retrieve tracker from backend for /status and /cost
    tracker: Optional[TokenTrackingRail] = getattr(
        backend, "tracker", None
    )

    # Scan default skill directories and register slash commands
    _scan_skills()

    _print_welcome(console, cfg)

    while True:
        try:
            user_input = await prompt_session.prompt_async(
                "You> ",
                multiline=False,
            )
        except (EOFError, KeyboardInterrupt):
            break

        text = user_input.strip()
        if not text:
            continue

        # ---- Slash commands ----
        if text.startswith("/"):
            try:
                skill_cmd = await _handle_slash(
                    text,
                    console,
                    backend,
                    session_store,
                    tracker=tracker,
                    cfg=cfg,
                )
            except _ExitREPL:
                console.print("[dim]Goodbye![/dim]")
                break
            if skill_cmd is None:
                continue
            # Skill command — build query and forward
            parts = text.split(None, 1)
            skill_args = parts[1] if len(parts) > 1 else ""
            skill_md = _SKILL_COMMANDS.get(skill_cmd)
            if skill_md is not None:
                text = _build_skill_query(skill_md, skill_args)
            else:
                inline = _INLINE_SKILL_COMMANDS.get(skill_cmd)
                if inline is None:
                    continue
                from openjiuwen_icode.skills import (
                    build_inline_skill_query,
                )

                text = build_inline_skill_query(
                    name=inline.name,
                    instructions=inline.instructions,
                    args=skill_args,
                )

        # ---- Shell passthrough ----
        if text.startswith("!"):
            shell_cmd = text[1:].strip()
            if shell_cmd:
                await _handle_shell(shell_cmd, console, session_store)
            continue

        # ---- Normal query ----
        session_store.add_message("user", text)
        try:
            stream = backend.run_streaming(text)

            async def interaction_cb(
                iid: str, q: Any
            ) -> str:
                _render_interaction(q, console)
                return ""

            render_result = await render_stream(
                stream,
                console,
                on_interaction=interaction_cb,
                show_reasoning=cfg.verbose,
            )

            # Handle pending interactions (interrupt
            # resume loop).
            while render_result.pending_interactions:
                interactive_input = (
                    await _collect_interaction_answers(
                        render_result.pending_interactions,
                        prompt_session,
                        console,
                    )
                )
                if interactive_input is None:
                    break

                resume_stream = (
                    backend.run_streaming(
                        interactive_input
                    )
                )
                render_result = await render_stream(
                    resume_stream,
                    console,
                    on_interaction=interaction_cb,
                    show_reasoning=cfg.verbose,
                )

            session_store.add_message(
                "assistant", render_result.text
            )
        except KeyboardInterrupt:
            action = interrupt_mgr.handle(backend)
            if action == "abort":
                console.print(
                    "\n[dim]\u23f9 Interrupted[/dim]"
                )
            elif action == "warn":
                console.print(
                    "\n[dim]Press Ctrl+C once more to "
                    "exit.[/dim]"
                )
            else:
                console.print("[dim]Goodbye![/dim]")
                break
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"[red]\u2717 Error: {exc}[/red]"
            )

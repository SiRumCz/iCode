"""Click CLI entry point for OpenJiuWen iCode.

Commands:
    ``openjiuwen`` / ``chat`` / ``tui`` — EventBus Textual TUI (default interactive)
    ``openjiuwen serve``               — host TUI in a browser (textual-serve)
    ``openjiuwen acp``                 — ACP JSON-RPC for editors
    ``openjiuwen chat --repl``         — legacy Rich REPL escape hatch
    ``openjiuwen run PROMPT``          — non-interactive via EventBus (auto-approve)
    ``openjiuwen bus-run --demo``      — demo alias (no API key)
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any, Optional

import click

from openjiuwen_icode import __version__
from openjiuwen_icode.agent.config import load_config
from openjiuwen_icode.branding import PRODUCT_NAME


def _bootstrap_logging() -> None:
    """Ensure SDK LogManager is initialised before any SDK import.

    In standalone CLI mode the ``extensions.common.configs.log_config``
    entry-point is absent, causing a ``RuntimeError`` on the first
    SDK import that touches the logger.  Setting ``_initialized = True``
    lets the SDK fall through to stdlib-backed loggers.

    Also: never let the SDK create ``./logs`` under a read-only cwd
    (VS Code / Cursor extension hosts often spawn with cwd ``/``).
    """
    try:
        import logging
        import os
        from pathlib import Path

        if "pytest" in sys.modules:
            return

        # Prefer a writable log root when the process cwd is unusable
        # (e.g. ``/`` under a GUI extension host).
        try:
            cwd = Path.cwd()
            probe = cwd / ".icode-log-write-probe"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError:
            home = Path(
                os.environ.get("ICODE_HOME")
                or (Path.home() / ".icode")
            )
            log_root = home / "logs"
            log_root.mkdir(parents=True, exist_ok=True)
            try:
                os.chdir(home)
            except OSError:
                pass

        # Suppress ALL SDK logs in CLI mode.
        logging.getLogger("openjiuwen").setLevel(logging.CRITICAL)
        logging.getLogger().setLevel(logging.WARNING)

        from openjiuwen.core.common.logging import (
            manager as log_mgr,
        )

        LogMgr = log_mgr.LogManager  # noqa: N806
        if not getattr(LogMgr, "_initialized", False):

            class _NullLogger:
                """Completely silent logger for CLI mode."""

                def __init__(self, lt: str, cfg: object = None) -> None:
                    self._lt = lt

                def _noop(self, *a: object, **kw: object) -> None:
                    pass

                debug = info = warning = error = critical = _noop
                warn = exception = log = _noop

                def __getattr__(self, n: str) -> object:
                    return self._noop

                def logger(self) -> object:
                    lg = logging.getLogger(f"openjiuwen.{self._lt}")
                    lg.setLevel(logging.CRITICAL)
                    lg.handlers.clear()
                    return lg

            @classmethod  # type: ignore[misc]
            def _safe(cls: type, lt: str = "default") -> object:
                # Always use NullLogger in CLI/ACP — avoid SDK file handlers
                # that mkdir relative ``./logs`` (fails when cwd is ``/``).
                if lt not in cls._loggers:
                    cls._loggers[lt] = _NullLogger(lt)
                return cls._loggers[lt]

            LogMgr.get_logger = _safe  # type: ignore[assignment]
            setattr(LogMgr, "_initialized", True)

            # Also silence the root openjiuwen logger
            # and disable propagation
            for name in list(logging.Logger.manager.loggerDict):
                if name.startswith("openjiuwen"):
                    lg = logging.getLogger(name)
                    lg.setLevel(logging.CRITICAL)
                    lg.handlers.clear()

    except Exception:  # noqa: BLE001
        pass


_bootstrap_logging()


# ---------------------------------------------------------------------------
# Interactive onboarding (when API key is missing)
# ---------------------------------------------------------------------------


def _interactive_setup() -> dict[str, str]:
    """Guide the user through first-time API configuration.

    Returns:
        Dict with provider, model, api_key, api_base values.
    """
    from openjiuwen_icode.agent.config import (
        save_settings_json,
    )

    click.echo()
    click.secho(
        f"  Welcome to {PRODUCT_NAME}!", fg="cyan", bold=True
    )
    click.echo(
        "  No API key found. Let's set one up.\n"
    )

    provider = click.prompt(
        "  LLM Provider",
        type=click.Choice(
            ["OpenAI", "DashScope", "SiliconFlow"],
            case_sensitive=False,
        ),
        default="OpenAI",
    )

    default_bases = {
        "OpenAI": "https://api.openai.com/v1",
        "DashScope": (
            "https://dashscope.aliyuncs.com"
            "/compatible-mode/v1"
        ),
        "SiliconFlow": "https://api.siliconflow.cn/v1",
    }

    api_base = click.prompt(
        "  API Base URL",
        default=default_bases.get(
            provider, default_bases["OpenAI"]
        ),
    )
    model = click.prompt(
        "  Model name", default="gpt-4o"
    )
    api_key = click.prompt(
        "  API Key", hide_input=True
    )

    # Save to ~/.icode/settings.json
    saved_path = save_settings_json(
        {
            "provider": provider,
            "model": model,
            "apiKey": api_key,
            "apiBase": api_base,
            "maxTokens": 8192,
            "maxIterations": 30,
        }
    )
    click.secho(
        f"\n  Config saved to {saved_path}",
        fg="green",
    )
    click.echo()

    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "api_base": api_base,
    }


# ---------------------------------------------------------------------------
# CLI option bundle
# ---------------------------------------------------------------------------


@dataclass
class CLIOptions:
    """Bundle of CLI options passed through click commands.

    Attributes:
        provider: LLM provider name.
        model: Model name.
        api_key: API key.
        api_base: API base URL.
        remote: Remote agent-server URL.
        verbose: Verbose logging flag.
        project: iCode project directory.
    """

    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    remote: Optional[str] = None
    verbose: bool = False
    project: Optional[str] = None


# ---------------------------------------------------------------------------
# Async runners (called from click commands)
# ---------------------------------------------------------------------------


async def _run_chat(opts: CLIOptions) -> None:
    """Start the legacy Rich / prompt_toolkit REPL session."""
    from openjiuwen_icode.agent.factory import create_backend
    from openjiuwen_icode.paths import IcodeProject
    from openjiuwen_icode.ui.repl import run_repl
    from openjiuwen_icode.storage.session_store import SessionStore

    cfg = load_config(
        provider=opts.provider,
        model=opts.model,
        api_key=opts.api_key,
        api_base=opts.api_base,
        server_url=opts.remote,
        project=opts.project,
        verbose=opts.verbose,
    )

    backend = create_backend(cfg)
    project = IcodeProject.open(cfg.project)
    store = SessionStore(store_dir=project.sessions_dir)
    store.new_session(
        getattr(backend, "_session_id", "cli"), cfg.model
    )

    try:
        await backend.start()
        await run_repl(backend, cfg, store)
    finally:
        await backend.stop()


async def _run_once(
    opts: CLIOptions,
    prompt: str,
    output_format: str,
    *,
    session_id: str | None = None,
    workdir: str | None = None,
    agent: str | None = None,
    result_json: bool = False,
) -> int:
    """Execute a non-interactive run via EventBus + SessionHost."""
    from openjiuwen_icode.host.bus_runner import run_via_bus

    cfg = load_config(
        provider=opts.provider,
        model=opts.model,
        api_key=opts.api_key,
        api_base=opts.api_base,
        server_url=opts.remote,
        project=opts.project,
        verbose=opts.verbose,
    )
    return await run_via_bus(
        cfg,
        prompt,
        demo=False,
        output_format=output_format,
        auto_approve=True,
        session_id=session_id,
        workdir=workdir,
        agent_profile=agent,
        result_json=result_json,
    )


async def _run_tui(opts: CLIOptions, *, demo: bool) -> int:
    """Start the EventBus Textual TUI."""
    from openjiuwen_icode.tui import run_tui

    if demo:
        return await run_tui(None, demo=True)

    cfg = load_config(
        provider=opts.provider,
        model=opts.model,
        api_key=opts.api_key,
        api_base=opts.api_base,
        server_url=opts.remote,
        project=opts.project,
        verbose=opts.verbose,
    )
    return await run_tui(cfg, demo=False)


async def _run_interactive(
    opts: CLIOptions,
    *,
    demo: bool = False,
    force_repl: bool = False,
) -> int:
    """Interactive entry: EventBus TUI by default, optional legacy REPL.

    Falls back to the Rich REPL when Textual is not installed (unless
    ``demo`` is set, which requires the TUI package).
    """
    if force_repl:
        if demo:
            raise ValueError(
                "Legacy REPL does not support --demo; "
                'use `openjiuwen tui --demo` or install "openjiuwen[tui]".'
            )
        await _run_chat(opts)
        return 0

    try:
        return await _run_tui(opts, demo=demo)
    except ImportError as exc:
        if demo:
            raise
        click.echo(f"Warning: {exc}", err=True)
        click.echo(
            "Falling back to legacy REPL. "
            'Install the TUI with: pip install "openjiuwen[tui]"',
            err=True,
        )
        await _run_chat(opts)
        return 0


def _run_interactive_with_setup(
    opts: CLIOptions,
    *,
    demo: bool = False,
    force_repl: bool = False,
) -> int:
    """Run interactive mode, offering first-time API key setup on TTY."""
    try:
        return asyncio.run(
            _run_interactive(
                opts, demo=demo, force_repl=force_repl
            )
        )
    except ValueError as exc:
        if (
            not demo
            and "API key" in str(exc)
            and sys.stdin.isatty()
        ):
            setup = _interactive_setup()
            patched = CLIOptions(
                provider=setup["provider"],
                model=setup["model"],
                api_key=setup["api_key"],
                api_base=setup["api_base"],
                remote=opts.remote,
                verbose=opts.verbose,
                project=opts.project,
            )
            return asyncio.run(
                _run_interactive(
                    patched, demo=False, force_repl=force_repl
                )
            )
        click.echo(f"Error: {exc}", err=True)
        return 1
    except ImportError as exc:
        click.echo(f"Error: {exc}", err=True)
        return 1


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.version_option(
    version=__version__, prog_name=PRODUCT_NAME
)
@click.option(
    "--model", "-m", default=None, help="Model name."
)
@click.option(
    "--provider", default=None, help="LLM provider."
)
@click.option(
    "--api-key", default=None, help="API key."
)
@click.option(
    "--api-base", default=None, help="API base URL."
)
@click.option(
    "--remote",
    default=None,
    help="Remote agent-server URL.",
)
@click.option(
    "--verbose", "-v", is_flag=True, help="Verbose logging."
)
@click.option(
    "--project",
    "-p",
    default=None,
    help="iCode project directory (directories.json, workspace/, sessions/). "
    "Default: ~/.icode/projects/default. Env: ICODE_PROJECT.",
)
@click.pass_context
def cli(ctx: click.Context, **kwargs: Any) -> None:
    """OpenJiuWen \u2014 terminal interactive AI programming assistant."""
    ctx.ensure_object(dict)
    ctx.obj["opts"] = CLIOptions(
        model=kwargs.get("model"),
        provider=kwargs.get("provider"),
        api_key=kwargs.get("api_key"),
        api_base=kwargs.get("api_base"),
        remote=kwargs.get("remote"),
        verbose=kwargs.get("verbose", False),
        project=kwargs.get("project"),
    )

    if ctx.invoked_subcommand is None:
        if sys.stdin.isatty():
            # Default interactive path: EventBus TUI.
            ctx.invoke(tui_cmd, demo=False)
        else:
            # Non-TTY stdin → treat as pipe to 'run'
            ctx.invoke(run)


@cli.command()
@click.option(
    "--repl",
    is_flag=True,
    help="Use legacy Rich REPL instead of the EventBus TUI.",
)
@click.option(
    "--demo",
    is_flag=True,
    help="Use DemoBackend (no API key). Requires openjiuwen[tui].",
)
@click.pass_context
def chat(ctx: click.Context, repl: bool, demo: bool) -> None:
    """Interactive EventBus TUI (same as ``tui``).

    Prefer ``openjiuwen`` / ``openjiuwen tui``. Pass ``--repl`` only if you
    need the legacy prompt_toolkit REPL.
    """
    opts: CLIOptions = ctx.obj["opts"]
    try:
        exit_code = _run_interactive_with_setup(
            opts, demo=demo, force_repl=repl
        )
        if exit_code:
            ctx.exit(exit_code)
    except KeyboardInterrupt:
        pass


@cli.command("agents")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def agents_cmd(ctx: click.Context, as_json: bool) -> None:
    """List available agent profiles (Chrys ``chrys agents``)."""
    from openjiuwen_icode.agent.profile_loader import (
        active_agent_profile_id,
    )
    from openjiuwen_icode.host.profiles import list_agent_profiles

    rows = list_agent_profiles()
    current = active_agent_profile_id() or "code"
    if as_json:
        click.echo(
            json.dumps(
                {
                    "current": current,
                    "agents": [
                        {"id": r["id"], "label": r.get("label", r["id"])}
                        for r in rows
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    click.echo(f"Current: {current}")
    for row in rows:
        mark = "*" if row["id"] == current else " "
        click.echo(f" {mark} {row['id']}: {row.get('label', row['id'])}")


@cli.command("models")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def models_cmd(ctx: click.Context, as_json: bool) -> None:
    """List available model profiles (Chrys ``chrys models``)."""
    from openjiuwen_icode.host.profiles import (
        current_model_from_settings,
        list_model_profiles,
    )

    current = current_model_from_settings()
    rows = list_model_profiles()
    if as_json:
        click.echo(
            json.dumps(
                {
                    "current": current,
                    "models": rows,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return
    click.echo(
        f"Current: {current['model']} ({current['provider']})"
    )
    for row in rows:
        mark = "*" if row["id"] == current["model"] else " "
        click.echo(
            f" {mark} {row['id']}  [{row.get('provider')}] "
            f"{row.get('label', row['id'])}"
        )
    if not rows:
        click.echo(" (none — create one via TUI Models modal / F4)")


@cli.command()
@click.argument("prompt", required=False)
@click.option(
    "-t",
    "--task",
    "task_file",
    default=None,
    metavar="FILE",
    help="Read prompt from text file (resolved relative to --workdir).",
)
@click.option(
    "-a",
    "--agent",
    default=None,
    help="Agent profile id to run (default: settings agent_profile / code).",
)
@click.option(
    "-s",
    "--session",
    "session_id",
    default=None,
    help="Optional session id to restore before running.",
)
@click.option(
    "-C",
    "--workdir",
    default=None,
    metavar="DIR",
    help="Working directory for the run (primary directory + process cwd).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit Chrys-compatible JSON: {session_id, result, duration}.",
)
@click.option(
    "--output-format",
    "-f",
    type=click.Choice(["text", "json", "stream-json"]),
    default="text",
    help="Event output format (ignored when --json is set).",
)
@click.pass_context
def run(
    ctx: click.Context,
    prompt: str | None,
    task_file: str | None,
    agent: str | None,
    session_id: str | None,
    workdir: str | None,
    as_json: bool,
    output_format: str,
) -> None:
    """Non-interactive run via EventBus + SessionHost (auto-approve / BYPASS).

    Chrys-aligned flags: ``-a/--agent``, ``-s/--session``, ``-C/--workdir``,
    ``-t/--task``, ``--json``. Example::

        openjiuwen run -a code -C ~/proj "fix the bug"
        openjiuwen run -t task.md --json
        openjiuwen run -s cli-abc123 "continue"
    """
    opts: CLIOptions = ctx.obj["opts"]
    from openjiuwen_icode.features.headless_run import (
        TaskFileError,
        apply_workdir,
        resolve_prompt,
    )

    # stdin pipe when neither prompt nor --task
    if prompt == "-":
        prompt = sys.stdin.read().strip() or None
    elif prompt is None and task_file is None and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip() or None

    if prompt is not None and task_file is not None:
        raise click.UsageError(
            "Provide either a prompt or --task FILE, not both."
        )
    if prompt is None and task_file is None:
        raise click.UsageError(
            "A prompt argument or --task FILE is required "
            "(or pipe via stdin)."
        )

    try:
        resolved_cwd = apply_workdir(workdir)
    except (FileNotFoundError, NotADirectoryError) as exc:
        _write_headless_error(str(exc), as_json=as_json, code="workdir_error")
        ctx.exit(1)
        return

    try:
        text = resolve_prompt(
            prompt=prompt,
            task=task_file,
            workdir=resolved_cwd,
        )
    except TaskFileError as exc:
        _write_headless_error(str(exc), as_json=as_json, code=exc.code)
        ctx.exit(1)
        return
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    if not (text or "").strip():
        raise click.UsageError("Prompt is empty.")

    try:
        exit_code = asyncio.run(
            _run_once(
                opts,
                text,
                output_format,
                session_id=session_id,
                workdir=resolved_cwd,
                agent=agent,
                result_json=as_json,
            )
        )
        ctx.exit(exit_code)
    except ValueError as exc:
        _write_headless_error(str(exc), as_json=as_json, code="error")
        ctx.exit(1)
    except KeyboardInterrupt:
        _write_headless_error(
            "Interrupted by user.", as_json=as_json, code="interrupted"
        )
        ctx.exit(130)


def _write_headless_error(
    message: str,
    *,
    as_json: bool,
    code: str = "error",
    session_id: str | None = None,
) -> None:
    if as_json:
        payload: dict[str, Any] = {"error": message, "code": code}
        if session_id:
            payload["session_id"] = session_id
        click.echo(json.dumps(payload, ensure_ascii=False), err=True)
        return
    click.echo(f"Error: {message}", err=True)


@cli.command("bus-run")
@click.argument("prompt", required=False)
@click.option(
    "--demo",
    is_flag=True,
    help="Use DemoBackend (no API key / LLM). Prints EventBus events.",
)
@click.option(
    "--output-format",
    "-f",
    type=click.Choice(["text", "json", "stream-json"]),
    default="text",
    help="Event output format.",
)
@click.pass_context
def bus_run(
    ctx: click.Context,
    prompt: str | None,
    demo: bool,
    output_format: str,
) -> None:
    """Alias of ``run`` for EventBus demos (prefer ``openjiuwen run``).

    Use ``--demo`` without an API key::

        openjiuwen bus-run --demo "hello"
        openjiuwen run --demo   # not supported; use bus-run --demo
    """
    opts: CLIOptions = ctx.obj["opts"]

    if prompt == "-" or (
        prompt is None and not sys.stdin.isatty()
    ):
        prompt = sys.stdin.read().strip()
    if not prompt:
        raise click.UsageError(
            "A prompt argument is required, or pipe via stdin."
        )

    try:
        exit_code = asyncio.run(
            _run_via_bus(
                opts,
                prompt,
                demo=demo,
                output_format=output_format,
            )
        )
        ctx.exit(exit_code)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        ctx.exit(1)
    except KeyboardInterrupt:
        pass


async def _run_via_bus(
    opts: CLIOptions,
    prompt: str,
    *,
    demo: bool,
    output_format: str,
) -> int:
    """Execute a single EventBus-driven run."""
    from openjiuwen_icode.host.bus_runner import run_via_bus

    if demo:
        return await run_via_bus(
            None,
            prompt,
            demo=True,
            output_format=output_format,
            auto_approve=True,
        )

    cfg = load_config(
        provider=opts.provider,
        model=opts.model,
        api_key=opts.api_key,
        api_base=opts.api_base,
        server_url=opts.remote,
        project=opts.project,
        verbose=opts.verbose,
    )
    return await run_via_bus(
        cfg,
        prompt,
        demo=False,
        output_format=output_format,
        auto_approve=True,
    )


@cli.command("serve")
@click.option(
    "--host",
    default="localhost",
    show_default=True,
    help="Bind address (use 0.0.0.0 to listen on all interfaces).",
)
@click.option(
    "--port",
    default=8000,
    show_default=True,
    type=click.IntRange(1, 65535),
    help="HTTP port for the browser TUI.",
)
@click.option(
    "--public-url",
    default=None,
    help=(
        "Externally reachable URL (required when --host is 0.0.0.0 "
        "or behind a reverse proxy)."
    ),
)
@click.option(
    "--demo",
    is_flag=True,
    help="Spawn DemoBackend TUI sessions (no API key).",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable textual-serve debug / Textual devtools.",
)
@click.pass_context
def serve_cmd(
    ctx: click.Context,
    host: str,
    port: int,
    public_url: str | None,
    demo: bool,
    debug: bool,
) -> None:
    """Host the EventBus Textual TUI in a browser (Chrys ``serve``).

    Requires ``pip install "openjiuwen[tui]"`` (includes textual-serve).

    Example::

        openjiuwen serve --demo
        openjiuwen serve --host 0.0.0.0 --port 8000 \\
            --public-url http://127.0.0.1:8000
    """
    opts: CLIOptions = ctx.obj["opts"]
    from openjiuwen_icode.serve import run_serve

    try:
        run_serve(
            host=host,
            port=port,
            public_url=public_url,
            demo=demo,
            project=opts.project,
            debug=debug,
        )
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(1)
    except KeyboardInterrupt:
        pass


@cli.command("acp")
@click.option(
    "--demo",
    is_flag=True,
    help="Use DemoBackend (no API key). For editor protocol smoke tests.",
)
@click.option(
    "--auto-approve/--no-auto-approve",
    default=True,
    show_default=True,
    help="Auto-approve tool confirms (disable for editor permission UI).",
)
@click.pass_context
def acp_cmd(ctx: click.Context, demo: bool, auto_approve: bool) -> None:
    """Run ACP JSON-RPC server on stdin/stdout (editor integration, T-30).

    Stdout is reserved for JSON-RPC only; logs go to stderr.

    Example::

        icode acp --demo
        icode acp --no-auto-approve
        # Editors launch: icode acp
    """
    opts: CLIOptions = ctx.obj["opts"]
    from openjiuwen_icode.acp import run_acp_server

    cfg = None
    if not demo:
        try:
            cfg = load_config(
                provider=opts.provider,
                model=opts.model,
                api_key=opts.api_key,
                api_base=opts.api_base,
                server_url=opts.remote,
                project=opts.project,
                verbose=opts.verbose,
            )
        except Exception as exc:  # noqa: BLE001
            click.echo(f"ACP config error: {exc}", err=True)
            # Fall back to demo so editors can still handshake.
            demo = True
            click.echo("Falling back to --demo backend.", err=True)

    async def _main() -> int:
        return await run_acp_server(
            demo=demo, cfg=cfg, auto_approve=auto_approve
        )

    try:
        exit_code = asyncio.run(_main())
        if exit_code:
            ctx.exit(exit_code)
    except KeyboardInterrupt:
        pass


@cli.command("tui")
@click.option(
    "--demo",
    is_flag=True,
    help="Use DemoBackend (no API key / LLM). EventBus Textual TUI.",
)
@click.pass_context
def tui_cmd(ctx: click.Context, demo: bool) -> None:
    """Launch the EventBus Textual TUI (default interactive shell).

    Requires ``pip install "openjiuwen[tui]"``. Example::

        openjiuwen
        openjiuwen tui --demo
        openjiuwen chat --repl   # legacy Rich REPL
    """
    opts: CLIOptions = ctx.obj["opts"]
    try:
        exit_code = _run_interactive_with_setup(
            opts, demo=demo, force_repl=False
        )
        if exit_code:
            ctx.exit(exit_code)
    except KeyboardInterrupt:
        pass


# -------------------------------------------------------------------
# auto-harness subcommand group
# -------------------------------------------------------------------


@dataclass
class AutoHarnessRunRequest:
    """Named request payload for auto-harness run parameters."""

    task: str | None = None
    task_file: str | None = None
    dry_run: bool = False
    stage: str | None = None
    no_push: bool = False
    budget: float | None = None
    goal: str | None = None
    pipeline: str | None = None

    @classmethod
    def from_kwargs(
        cls, kwargs: dict[str, Any]
    ) -> "AutoHarnessRunRequest":
        """Build request from click callback kwargs."""
        return cls(
            task=kwargs.get("task"),
            task_file=kwargs.get("task_file"),
            dry_run=bool(kwargs.get("dry_run", False)),
            stage=kwargs.get("stage"),
            no_push=bool(kwargs.get("no_push", False)),
            budget=kwargs.get("budget"),
            goal=kwargs.get("goal"),
            pipeline=kwargs.get("pipeline"),
        )


async def _run_auto_harness(
    opts: CLIOptions,
    request: AutoHarnessRunRequest,
) -> int:
    """Execute an auto-harness session.

    Returns:
        Exit code (0 = success).
    """
    import json
    import logging
    import time
    from pathlib import Path

    from openjiuwen.auto_harness.schema import (
        normalize_pipeline_preference,
        OptimizationTask,
        is_placeholder_local_repo,
        load_auto_harness_config,
    )
    from openjiuwen.auto_harness.pipelines import (
        META_EVOLVE_PIPELINE,
    )
    from openjiuwen.auto_harness.orchestrator import (
        create_auto_harness_orchestrator,
    )
    from openjiuwen.auto_harness.stages.assess import (
        run_assess_stream,
    )
    from openjiuwen.auto_harness.experience.experience_store import (
        ExperienceStore,
    )
    from openjiuwen.auto_harness.infra.ci_gate_runner import (
        CIGateRunner,
    )
    from openjiuwen.auto_harness.infra.github_cli import (
        ensure_github_cli_ready,
    )
    from openjiuwen.core.foundation.llm.model import Model
    from openjiuwen.core.foundation.llm.schema.config import (
        ModelClientConfig,
        ModelRequestConfig,
    )
    from openjiuwen_icode.agent.config import (
        load_config as load_cli_config,
    )

    if opts.verbose:
        for name in (
            "auto_harness",
            "openjiuwen.auto_harness",
        ):
            logging.getLogger(name).setLevel(
                logging.DEBUG,
            )

    # data_dir under iCode home
    from openjiuwen_icode.paths import IcodeProject, icode_home

    project = IcodeProject.open(opts.project)
    cli_home = str(icode_home())
    data_dir = str(Path(cli_home) / "auto_harness")
    config_path = str(
        Path(data_dir) / "config.yaml"
    )

    # 从 YAML 加载配置
    config = load_auto_harness_config(
        config_path, workspace_hint=str(project.root),
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
        click.echo(
            "忽略无效的 local_repo 配置: "
            f"{config.local_repo}"
        )
        config.local_repo = ""
    if config.config_bootstrapped:
        click.echo(
            "已初始化 auto-harness 配置模板: "
            f"{config.config_path}"
        )
    if not config.local_repo and config.suggested_local_repo:
        config.local_repo = config.suggested_local_repo
        click.echo(
            "检测到本地仓库，临时使用 "
            f"local_repo={config.local_repo}。"
            "建议写回 config.yaml。"
        )
    elif not config.local_repo:
        click.echo(
            "未配置 local_repo，auto-harness 将使用 "
            "clone 缓存。请编辑 "
            f"{config.config_path or config_path} "
            "补充 local_repo。"
        )
    if config.local_repo:
        config.workspace = config.local_repo
    elif not config.workspace:
        config.workspace = str(project.root)

    debug_dir = Path(config.runs_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)

    # 从 CLI 选项构建 Model
    cli_cfg = load_cli_config(
        provider=opts.provider,
        model=opts.model,
        api_key=opts.api_key,
        api_base=opts.api_base,
        project=opts.project,
        verbose=opts.verbose,
    )
    model = Model(
        model_client_config=ModelClientConfig(
            client_provider=cli_cfg.provider,
            api_key=cli_cfg.api_key,
            api_base=cli_cfg.api_base,
            timeout=config.model_timeout_secs,
            verify_ssl=False,
        ),
        model_config=ModelRequestConfig(
            model=cli_cfg.model,
            temperature=0.2,
            top_p=0.9,
        ),
    )

    # 将 Model 和 CLI 参数覆盖到已加载的 config 上
    config.model = model
    if request.budget is not None:
        config.session_budget_secs = request.budget
        config.task_timeout_secs = min(
            config.task_timeout_secs, request.budget * 0.95,
        )
    if request.no_push:
        config.git_remote = ""
    if request.goal:
        config.optimization_goal = request.goal
    config.pipeline_preference = normalize_pipeline_preference(
        request.pipeline or META_EVOLVE_PIPELINE
    )

    if request.stage in (None, "assess", "plan"):
        ensure_github_cli_ready(click.echo)

    # Load tasks
    tasks: list[OptimizationTask] = []
    if request.task:
        tasks = [OptimizationTask(topic=request.task)]
    elif request.task_file:
        raw = json.loads(
            Path(request.task_file).read_text(encoding="utf-8"),
        )
        if isinstance(raw, dict):
            raw = [raw]
        for item in raw:
            tasks.append(OptimizationTask(
                topic=item["topic"],
                description=item.get("description", ""),
                files=item.get("files", []),
            ))

    # Stage dispatch
    if request.stage == "assess":
        from rich.console import Console
        from openjiuwen_icode.ui.renderer import (
            render_stream,
        )

        experience_store = ExperienceStore(
            config.resolved_experience_dir
        )
        console = Console()
        stream = run_assess_stream(
            config, experience_store
        )
        result = await render_stream(stream, console)
        report = result.text or ""
        if report:
            out = debug_dir / "assessment.md"
            out.write_text(report, encoding="utf-8")
        return 0

    if request.stage == "verify":
        ci = CIGateRunner(
            workspace=(
                config.local_repo
                or config.cache_repo_dir
            ),
            config_path=config.ci_gate_config,
            python_executable=(
                config.resolve_ci_gate_python_executable()
            ),
            install_command=(
                config.ci_gate_install_command
            ),
        )
        result = await ci.run("all")
        passed = result.get("passed", False)
        click.echo(
            f"CI Gate: {'PASSED' if passed else 'FAILED'}"
        )
        if not passed:
            for err in result.get("errors", [])[:10]:
                click.echo(f"  {err}", err=True)
        return 0 if passed else 1

    # Full session or dry-run
    t0 = time.monotonic()

    if tasks:
        click.echo(
            f"使用手动指定的 {len(tasks)} 个任务",
        )
    else:
        click.echo(
            "未指定手动任务，将执行 "
            "assess → plan → implement → learnings"
        )

    if request.dry_run:
        task_data = [
            {
                "topic": t.topic,
                "description": t.description,
                "files": t.files,
            }
            for t in tasks
        ]
        out_path = debug_dir / "tasks.json"
        out_path.write_text(
            json.dumps(
                task_data, ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        click.echo(json.dumps(
            task_data, ensure_ascii=False, indent=2,
        ))
        click.echo(f"[dry-run] 任务列表 → {out_path}")
        return 0

    from openjiuwen_icode.rails.tool_tracker import (
        ToolTrackingRail,
    )

    orch = create_auto_harness_orchestrator(
        config,
        stream_rails=[ToolTrackingRail()],
    )
    stream = orch.run_session_stream(tasks=tasks or None)
    from rich.console import Console
    from openjiuwen_icode.ui.renderer import (
        render_stream,
    )

    console = Console()

    async def _on_activate_interaction(
        iid: str, value: Any,
    ) -> str:
        if (
            isinstance(value, dict)
            and value.get("interaction_type")
            == "activate_confirm"
        ):
            ext_name = value.get(
                "extension_name", "unknown"
            )
            click.echo()
            click.echo(f"扩展 {ext_name} 已就绪")
            if value.get("runtime_path"):
                click.echo(
                    f"  路径: {value['runtime_path']}"
                )
            click.echo()
            click.echo("  [A] 接受并热加载")
            click.echo("  [R] 拒绝并清理")
            click.echo()
            while True:
                choice = click.prompt(
                    "选择 (A/R)",
                    default="A",
                ).strip().lower()
                if choice in ("a", "accept"):
                    action = "accept"
                    break
                if choice in ("r", "reject"):
                    action = "reject"
                    break
                click.echo("请输入 A 或 R")
            orch.run_session_stream(
                message={
                    "interaction_id": iid,
                    "action": action,
                },
            )
            return action
        return ""

    await render_stream(
        stream,
        console,
        on_interaction=_on_activate_interaction,
    )
    results = orch.results
    elapsed = time.monotonic() - t0
    ok = sum(1 for r in results if r.success)
    click.echo(
        f"Session 完成: {ok}/{len(results)} 成功, "
        f"耗时 {elapsed:.1f}s"
    )
    for i, r in enumerate(results):
        s = "OK" if r.success else "FAIL"
        click.echo(
            f"Task {i + 1}: {s}"
            f" | pr={r.pr_url or 'N/A'}"
            f" | error={r.error or 'none'}"
        )
        if r.summary:
            click.echo(f"  summary={r.summary}")
    return 0


async def _run_experience_search(
    workspace: str, query: str,
) -> None:
    """Search the experience store."""
    import os
    from pathlib import Path

    from openjiuwen.auto_harness.experience.experience_store import (
        ExperienceStore,
    )

    ws = workspace or os.getcwd()
    store = ExperienceStore(
        str(Path(ws) / "auto_harness/experience"),
    )
    results = await store.search(query, top_k=10)
    if not results:
        click.echo("无匹配结果")
        return
    for m in results:
        click.echo(
            f"[{m.type.value}] {m.topic}: "
            f"{m.summary or m.outcome}"
        )


async def _run_experience_list(
    workspace: str,
    mem_type: str | None,
    limit: int,
) -> None:
    """List recent experience entries."""
    import os
    from pathlib import Path

    from openjiuwen.auto_harness.experience.experience_store import (
        ExperienceStore,
    )

    ws = workspace or os.getcwd()
    store = ExperienceStore(
        str(Path(ws) / "auto_harness/experience"),
    )
    entries = await store.list_recent(limit=limit)
    if mem_type:
        entries = [
            e for e in entries
            if e.type.value == mem_type
        ]
    if not entries:
        click.echo("无记录")
        return
    for m in entries:
        click.echo(
            f"[{m.type.value}] {m.topic}: "
            f"{m.summary or m.outcome}"
        )


async def _run_gap_analyze(
    workspace: str,
) -> None:
    """Run competitive gap analysis."""
    import os

    from openjiuwen.auto_harness.schema import (
        AutoHarnessConfig,
    )
    from openjiuwen.auto_harness.stages.assess import (
        run_gap_analysis,
    )

    ws = workspace or os.getcwd()
    config = AutoHarnessConfig(workspace=ws)
    gaps = await run_gap_analysis(
        config, harness_state="",
    )
    if not gaps:
        click.echo(
            "Phase 1 占位: 差距分析尚未接入 LLM"
        )
        return
    for g in gaps:
        click.echo(
            f"[{g.priority:.1f}] {g.feature}: "
            f"{g.gap_description}"
        )


# -------------------------------------------------------------------
# auto-harness Click group + subcommands
# -------------------------------------------------------------------


@cli.group("auto-harness")
@click.pass_context
def auto_harness(ctx: click.Context) -> None:
    """Auto Harness Agent — 自主优化 harness 框架。"""
    pass


@auto_harness.command("run")
@click.option(
    "--task", default=None,
    help="手动指定单个任务描述。",
)
@click.option(
    "--task-file", default=None,
    help="从 JSON 文件加载任务列表。",
)
@click.option(
    "--dry-run", is_flag=True,
    help="只执行 assess + plan，不 implement。",
)
@click.option(
    "--stage",
    type=click.Choice(
        ["assess", "plan", "implement", "verify"],
    ),
    default=None,
    help="只执行指定阶段。",
)
@click.option(
    "--no-push", is_flag=True,
    help="不 push / 不创建 MR。",
)
@click.option(
    "--budget", type=float, default=None,
    help="覆盖 session 预算（秒）。",
)
@click.option(
    "--goal", default=None,
    help="指定本轮自然语言优化目标，驱动 assess/plan 全流程。",
)
@click.option(
    "--pipeline",
    type=click.Choice(["meta", "extended", "auto"]),
    default=None,
    help="选择 session pipeline；默认 meta。",
)
@click.pass_context
def auto_harness_run(
    ctx: click.Context,
    **kwargs: Any,
) -> None:
    """执行优化周期。"""
    opts: CLIOptions = ctx.obj["opts"]
    try:
        request = AutoHarnessRunRequest.from_kwargs(kwargs)
        exit_code = asyncio.run(
            _run_auto_harness(opts, request)
        )
        ctx.exit(exit_code)
    except KeyboardInterrupt:
        pass


@auto_harness.group("experience")
def auto_harness_experience() -> None:
    """经验库操作。"""
    pass


@auto_harness_experience.command("search")
@click.argument("query")
@click.pass_context
def experience_search(
    ctx: click.Context, query: str,
) -> None:
    """搜索经验库。"""
    opts: CLIOptions = ctx.obj["opts"]
    asyncio.run(
        _run_experience_search(
            opts.project or "", query
        ),
    )


@auto_harness_experience.command("list")
@click.option(
    "--type", "mem_type", default=None,
    help="按类型过滤 (optimization/failure/insight)。",
)
@click.option(
    "--limit", default=10, type=int,
    help="返回条数。",
)
@click.pass_context
def experience_list(
    ctx: click.Context,
    mem_type: str | None,
    limit: int,
) -> None:
    """列出经验库记录。"""
    opts: CLIOptions = ctx.obj["opts"]
    asyncio.run(
        _run_experience_list(
            opts.project or "", mem_type, limit,
        ),
    )


@auto_harness.command("verify-ext")
@click.option(
    "--ext-path",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help=(
        "扩展包根目录（含 harness_config.yaml）。"
        "不传则自动生成 smoke-test scaffold。"
    ),
)
@click.pass_context
def auto_harness_verify_ext(
    ctx: click.Context,
    ext_path: str | None,
) -> None:
    """轻量验证扩展包（结构+lint）。"""
    asyncio.run(_run_verify_ext(ext_path))


def _generate_smoke_scaffold(
    base_dir: str | None = None,
) -> str:
    """Generate a minimal extension scaffold and return its path."""
    import tempfile
    from pathlib import Path as _P

    ext_name = "smoke_test_ext"
    if base_dir:
        root = _P(base_dir) / ext_name
    else:
        root = _P(
            tempfile.mkdtemp(prefix="verify_ext_")
        ) / ext_name
    rails_dir = root / "rails"
    tools_dir = root / "tools"
    for d in (root, rails_dir, tools_dir):
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").write_text(
            "", encoding="utf-8",
        )
    mod = (
        f"openjiuwen.extensions.harness.{ext_name}"
    )
    (rails_dir / "smoke_rail.py").write_text(
        "from openjiuwen.harness.rails.base "
        "import DeepAgentRail\n\n\n"
        "class SmokeRail(DeepAgentRail):\n"
        '    """Smoke-test rail."""\n\n'
        "    pass\n",
        encoding="utf-8",
    )
    (tools_dir / "helper.py").write_text(
        f"EXTENSION_NAME = '{ext_name}'\n",
        encoding="utf-8",
    )
    (tools_dir / "smoke_tool.py").write_text(
        "from __future__ import annotations\n\n"
        "from typing import Any, AsyncIterator, "
        "Dict\n\n"
        "from .helper import EXTENSION_NAME\n"
        "from openjiuwen.core.foundation.tool "
        "import Tool, ToolCard\n\n\n"
        "class SmokeTool(Tool):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(\n"
        "            ToolCard(\n"
        "                id='smoke_tool',\n"
        "                name='smoke_tool',\n"
        "                description=(\n"
        '                    "Smoke test tool "\n'
        "                    + EXTENSION_NAME\n"
        "                ),\n"
        "            )\n"
        "        )\n\n"
        "    async def invoke(\n"
        "        self,\n"
        "        inputs: Dict[str, Any],\n"
        "        **kwargs: Any,\n"
        "    ) -> Dict[str, Any]:\n"
        "        return {'ext': EXTENSION_NAME}\n\n"
        "    async def stream(\n"
        "        self,\n"
        "        inputs: Dict[str, Any],\n"
        "        **kwargs: Any,\n"
        "    ) -> AsyncIterator[Dict[str, Any]]:\n"
        "        yield await self.invoke("
        "inputs, **kwargs)\n",
        encoding="utf-8",
    )
    (root / "harness_config.yaml").write_text(
        "schema_version: harness_config.v0.1\n"
        f"name: {ext_name}\n"
        "resources:\n"
        "  rails:\n"
        "    - type: package\n"
        f"      module: {mod}.rails.smoke_rail\n"
        "      class: SmokeRail\n"
        "  tools:\n"
        "    - type: package\n"
        f"      module: {mod}.tools.smoke_tool\n"
        "      class: SmokeTool\n",
        encoding="utf-8",
    )
    return str(root)


async def _run_verify_ext(
    ext_path: str | None,
) -> None:
    import uuid
    from pathlib import Path as _Path

    from openjiuwen.auto_harness.infra.runtime_extension_loader import (
        load_runtime_rails,
        load_runtime_skill_dirs,
        load_runtime_tools,
    )
    from openjiuwen.auto_harness.schema import (
        RuntimeExtensionArtifact,
    )
    from openjiuwen.auto_harness.stages.verify import (
        _check_ruff,
    )

    generated = False
    if ext_path is None:
        click.echo("== Generating smoke-test scaffold ==")
        ext_path = _generate_smoke_scaffold()
        generated = True
        click.echo(f"  {ext_path}")

    root = _Path(ext_path).resolve()
    manifest = root / "harness_config.yaml"
    if not manifest.is_file():
        raise click.ClickException(
            f"{manifest} not found"
        )

    ext_name = root.name
    session_id = f"cli_verify_{uuid.uuid4().hex[:8]}"
    runtime_ext = RuntimeExtensionArtifact(
        extension_name=ext_name,
        runtime_path=str(root),
        config_path=str(manifest),
    )

    errors: list[str] = []
    rails_count = 0
    tools_count = 0
    skills_count = 0

    # Layer 1: structure check
    click.echo("== Layer 1: structure check ==")
    try:
        rails = load_runtime_rails(
            runtime_ext, session_id=session_id,
        )
        tools = load_runtime_tools(
            runtime_ext, session_id=session_id,
        )
        for cls in rails:
            cls()
        for cls in tools:
            cls()
        rails_count = len(rails)
        tools_count = len(tools)
        skill_dirs = load_runtime_skill_dirs(runtime_ext)
        for sd in skill_dirs:
            sd_path = _Path(sd)
            skill_mds = list(sd_path.rglob("SKILL.md"))
            skills_count += len(skill_mds)
            if not skill_mds:
                errors.append(
                    f"Skill dir has no SKILL.md: {sd}"
                )
        click.echo(
            f"  rails={rails_count} tools={tools_count}"
            f" skills={skills_count}"
        )
    except Exception as exc:
        errors.append(f"Structure check failed: {exc}")
        click.echo(f"  FAILED: {exc}", err=True)

    # Layer 2: ruff lint
    click.echo("== Layer 2: ruff lint ==")
    if root.is_dir():
        lint_errors = await _check_ruff(root)
        errors.extend(lint_errors)
        if lint_errors:
            for e in lint_errors:
                click.echo(f"  {e}", err=True)
        else:
            click.echo("  OK")

    # Cleanup generated scaffold
    if generated:
        import shutil
        shutil.rmtree(root.parent, ignore_errors=True)

    if errors:
        click.echo(
            f"\nFAILED ({len(errors)} error(s)):",
            err=True,
        )
        for e in errors:
            click.echo(f"  - {e}", err=True)
        raise click.ClickException(
            f"verify_ext failed ({len(errors)} error(s))"
        )
    click.echo(
        f"\nPASSED: rails={rails_count}"
        f" tools={tools_count}"
        f" skills={skills_count}"
    )


@auto_harness.command("gap-analyze")
@click.pass_context
def gap_analyze(
    ctx: click.Context,
) -> None:
    """差距分析。"""
    opts: CLIOptions = ctx.obj["opts"]
    asyncio.run(
        _run_gap_analyze(
            opts.project or "",
        ),
    )


@auto_harness.command("history")
@click.option(
    "--limit", default=20, type=int,
    help="返回条数。",
)
@click.pass_context
def auto_harness_history(
    ctx: click.Context, limit: int,
) -> None:
    """查看优化历史。"""
    opts: CLIOptions = ctx.obj["opts"]
    asyncio.run(
        _run_experience_list(
            opts.project or "", None, limit
        ),
    )


def pyapp_main() -> None:
    """PyApp binary entrypoint; preserves integer CLI return codes."""
    raise SystemExit(cli.main(standalone_mode=True))

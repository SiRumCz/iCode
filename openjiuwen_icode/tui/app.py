# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Textual TUI for the EventBus coding-assistant shell (P2 UX)."""

from __future__ import annotations

import asyncio
from typing import Any

from openjiuwen_icode.agent.config import CLIConfig
from openjiuwen_icode.branding import PRODUCT_NAME
from openjiuwen_icode.events import (
    AgentMessage,
    AgentThinking,
    ApprovalRequest,
    CompactionFinished,
    CompactionStarted,
    ErrorEvent,
    Event,
    EventBus,
    ProfileSwitched,
    QuestionToUser,
    SessionCreated,
    SessionListed,
    SessionRestored,
    SessionTitleUpdated,
    SubAgentsAwaiting,
    SubAgentsIdle,
    SubAgentAborted,
    SubAgentFailed,
    SubAgentFinished,
    SubAgentPaused,
    SubAgentProgress,
    SubAgentResumed,
    SubAgentRetryAttempt,
    SubAgentStarted,
    SubAgentToolCallResult,
    SubAgentToolCallStart,
    SystemNotice,
    TodoListUpdated,
    ToolCallResult,
    ToolCallStart,
    TurnFailed,
    TurnFinished,
    TurnStarted,
    UsageUpdate,
    UserApproval,
    UserAskAnswer,
    UserCommand,
    UserInject,
    UserInterrupt,
    UserMessage,
    UserRetry,
    UserSubAgentAbort,
    UserSubAgentRetry,
)
from openjiuwen_icode.host.bootstrap import build_host_bundle
from openjiuwen_icode.host.bus_runner import format_event
from openjiuwen_icode.host.session_host import SessionHost
from openjiuwen_icode.shell_passthrough import (
    is_shell_toggle,
    persist_shell_turn,
    run_shell_command,
    shell_command_from_bang_line,
)
from openjiuwen_icode.tui.right_click_copy import (
    cancel_textual_mouse_chain,
    copy_screen_selection,
)
from openjiuwen_icode.tui.screens.approval_modal import (
    ApprovalModal,
    AskModal,
)
from openjiuwen_icode.tui.screens.models_modal import ModelsModal
from openjiuwen_icode.tui.screens.sessions_modal import SessionsModal
from openjiuwen_icode.tui.widgets.messages import (
    AgentBubble,
    ErrorBubble,
    SystemBubble,
    UserBubble,
)
from openjiuwen_icode.tui.widgets.sidebar import (
    ConversationToc,
    SidebarPanel,
    TocItem,
    summarize_prompt,
)
from openjiuwen_icode.tui.widgets.sidebar.toc import plan_session_replay
from openjiuwen_icode.tui.widgets.status_bar import StatusBar
from openjiuwen_icode.tui.widgets.suggestion_list import SuggestionList
from openjiuwen_icode.tui.widgets.subagent_card import (
    SubAgentActionPressed,
    SubAgentCard,
)
from openjiuwen_icode.tui.widgets.tool_card import ToolCard

_WATCH_TYPES = (
    TurnStarted,
    TurnFinished,
    TurnFailed,
    AgentMessage,
    AgentThinking,
    ToolCallStart,
    ToolCallResult,
    ApprovalRequest,
    QuestionToUser,
    TodoListUpdated,
    UsageUpdate,
    SystemNotice,
    SessionListed,
    SessionRestored,
    SessionCreated,
    SessionTitleUpdated,
    CompactionStarted,
    CompactionFinished,
    SubAgentStarted,
    SubAgentProgress,
    SubAgentsAwaiting,
    SubAgentsIdle,
    SubAgentAborted,
    SubAgentFailed,
    SubAgentFinished,
    SubAgentPaused,
    SubAgentResumed,
    SubAgentRetryAttempt,
    SubAgentToolCallResult,
    SubAgentToolCallStart,
    ProfileSwitched,
    ErrorEvent,
)


def _subagent_meta_suffix(
    event: SubAgentStarted
    | SubAgentProgress
    | SubAgentFinished
    | SubAgentFailed
    | SubAgentPaused
    | SubAgentAborted
    | SubAgentResumed
    | SubAgentToolCallStart
    | SubAgentToolCallResult,
) -> str:
    bits: list[str] = []
    if getattr(event, "invocation_id", ""):
        bits.append(str(event.invocation_id))
    if getattr(event, "transport", ""):
        bits.append(str(event.transport))
    return f" [{', '.join(bits)}]" if bits else ""


def _require_textual() -> Any:
    try:
        import textual  # noqa: F401
        from textual.app import App, SkipAction
        from textual.binding import Binding
        from textual.containers import Horizontal, Vertical, VerticalScroll
        from textual.widgets import Footer, Header, Input
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            'Textual TUI requires: pip install "openjiuwen[tui]"'
        ) from exc
    return (
        App,
        Binding,
        Footer,
        Header,
        Horizontal,
        Input,
        SkipAction,
        Vertical,
        VerticalScroll,
    )


def _parse_slash(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    if "\n" in stripped:
        return None
    body = stripped[1:]
    if not body:
        return "help", ""
    parts = body.split(maxsplit=1)
    name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return name, args


class CodingAssistantApp:
    """Factory that builds the Textual App class (lazy Textual import)."""

    @staticmethod
    def create(
        *,
        bus: EventBus,
        host: SessionHost,
        title: str = PRODUCT_NAME,
    ) -> Any:
        (
            App,
            Binding,
            Footer,
            Header,
            Horizontal,
            Input,
            SkipAction,
            Vertical,
            VerticalScroll,
        ) = _require_textual()

        class _App(App[None]):
            """EventBus-driven coding assistant TUI."""

            CSS = """
            Screen { layout: vertical; }
            #main-row {
                height: 1fr;
                width: 100%;
            }
            #chat {
                width: 1fr;
                height: 1fr;
                border: solid $primary;
                padding: 0 1;
            }
            #transcript {
                height: 1fr;
                border: none;
                scrollbar-gutter: stable;
            }
            #input-row { height: auto; padding: 0 1 0 1; }
            #prompt { width: 1fr; border: solid $primary; }
            #prompt.shell-mode { border: solid $warning; color: $warning; }
            #suggest { margin: 0 1; }
            UserBubble.-toc-focus {
                background: $primary 25%;
            }
            """

            BINDINGS = [
                Binding(
                    "ctrl+c,super+c",
                    "copy_text",
                    "Copy",
                    show=True,
                    priority=True,
                ),
                Binding("ctrl+b", "interrupt", "Interrupt", show=True),
                Binding("ctrl+r", "retry", "Retry", show=True),
                Binding("ctrl+g", "toggle_sidebar", "Sidebar", show=True),
                Binding("f1", "open_sessions", "Sessions", show=True),
                Binding("f4", "open_models", "Models", show=True),
                Binding("ctrl+q", "quit", "Quit", show=True),
                Binding(
                    "escape",
                    "exit_shell",
                    "Exit shell",
                    show=False,
                    priority=True,
                ),
                Binding("up", "suggest_up", show=False, priority=True),
                Binding("down", "suggest_down", show=False, priority=True),
                Binding("tab", "suggest_complete", show=False, priority=True),
            ]

            _CHAT_PLACEHOLDER = "Message or /command…  (! = shell)"
            _SHELL_PLACEHOLDER = "$ command…  (! or Esc to exit)"
            _READY_STATUS = (
                "Ready — /help · F1 sessions · F4 models · Ctrl+G sidebar · "
                "drag select · Ctrl/Cmd+C copy · Ctrl+B interrupt · ! shell"
            )

            def __init__(self) -> None:
                super().__init__()
                self._bus = bus
                self._host = host
                self._consumer: asyncio.Task[None] | None = None
                self._stream_cm: Any = None
                self._busy = False
                self._shell_mode = False
                self._pending_approval: ApprovalRequest | None = None
                self._pending_question: QuestionToUser | None = None
                self._show_thinking = False
                self._stream_idle_task: asyncio.Task[None] | None = None
                self._last_agent_response = ""
                self._agent_response_buf = ""
                self._active_agent: AgentBubble | None = None
                self._open_tool_cards: list[ToolCard] = []
                self._turn_tool_cards: list[ToolCard] = []
                self._subagent_cards: dict[str, SubAgentCard] = {}
                self._base_title = title
                self._session_label = host.session_id or ""
                self._session_title = ""
                self._awaiting_subagents = 0
                self._toc_items: list[TocItem] = []
                self._turn_seq = 0
                store = host.session_store
                if store is not None and store.current is not None:
                    self._session_title = store.current.title or ""

            def _refresh_window_title(self) -> None:
                """Window title: product · session title [id]."""
                parts = [self._base_title]
                if self._session_title:
                    parts.append(self._session_title)
                if self._session_label:
                    parts.append(f"[{self._session_label}]")
                self.title = " · ".join(parts)

            def compose(self) -> Any:
                yield Header()
                yield StatusBar(self._READY_STATUS, id="status")
                with Horizontal(id="main-row"):
                    with Vertical(id="chat"):
                        yield VerticalScroll(id="transcript")
                    yield SidebarPanel(id="sidebar")
                yield SuggestionList(id="suggest")
                with Horizontal(id="input-row"):
                    yield Input(
                        placeholder=self._CHAT_PLACEHOLDER,
                        id="prompt",
                    )
                yield Footer()

            def _transcript(self) -> Any:
                return self.query_one("#transcript", VerticalScroll)

            def _sidebar(self) -> SidebarPanel:
                return self.query_one("#sidebar", SidebarPanel)

            def _status(self) -> StatusBar:
                return self.query_one("#status", StatusBar)

            def _suggestions(self) -> SuggestionList:
                return self.query_one("#suggest", SuggestionList)

            def _mount_msg(self, widget: Any) -> None:
                scroll = self._transcript()
                scroll.mount(widget)
                scroll.scroll_end(animate=False)

            def _ensure_subagent_card(self, event: Event) -> SubAgentCard | None:
                iid = str(getattr(event, "invocation_id", "") or "").strip()
                if not iid:
                    return None
                card = self._subagent_cards.get(iid)
                if card is None:
                    card = SubAgentCard(
                        iid,
                        str(getattr(event, "agent_name", "") or "subagent"),
                        str(getattr(event, "task", "") or ""),
                        transport=str(getattr(event, "transport", "") or ""),
                    )
                    self._subagent_cards[iid] = card
                    self._mount_msg(card)
                return card

            async def _publish_subagent_action(
                self, invocation_id: str, action: str
            ) -> None:
                sid = self._host.session_id
                if action == "retry":
                    await self._bus.publish(
                        UserSubAgentRetry(
                            invocation_id=invocation_id,
                            session_id=sid,
                        )
                    )
                else:
                    await self._bus.publish(
                        UserSubAgentAbort(
                            invocation_id=invocation_id,
                            session_id=sid,
                        )
                    )

            def on_sub_agent_action_pressed(
                self, event: SubAgentActionPressed
            ) -> None:
                self.run_worker(
                    self._publish_subagent_action(
                        event.invocation_id, event.action
                    )
                )

            def _write_system(self, text: str) -> None:
                self._mount_msg(SystemBubble(text))

            def _write_error(self, text: str) -> None:
                self._mount_msg(ErrorBubble(text))

            async def _clear_transcript(self) -> None:
                # Textual prune is deferred; await so remounted turn-* ids
                # cannot collide with widgets still leaving the DOM.
                await self._transcript().remove_children()
                self._active_agent = None
                self._open_tool_cards.clear()
                self._turn_tool_cards.clear()
                self._subagent_cards.clear()
                self._toc_items.clear()
                self._turn_seq = 0
                try:
                    self._sidebar().clear_session()
                except Exception:  # noqa: BLE001
                    pass

            async def _hydrate_session_from_store(self) -> None:
                """Replay stored user/assistant messages into chat + Messages TOC.

                Resume previously only filled the TOC, so clicks could not find
                matching bubbles in the transcript. Always clears first so
                re-resume does not remount duplicate ``turn-*`` widget ids.
                """
                await self._clear_transcript()
                store = self._host.session_store
                if store is None or store.current is None:
                    return
                toc, bubbles = plan_session_replay(store.current.messages)
                self._toc_items = toc
                self._turn_seq = len(toc)
                scroll = self._transcript()
                for item in bubbles:
                    if item.role == "user":
                        scroll.mount(
                            UserBubble(item.content, id=item.turn_id)
                        )
                    elif item.role == "assistant":
                        scroll.mount(AgentBubble(item.content))
                    else:
                        scroll.mount(SystemBubble(item.content))
                try:
                    self._sidebar().set_toc_items(toc)
                    self._sidebar().context_panel.seed_from_messages(
                        store.current.messages
                    )
                except Exception:  # noqa: BLE001
                    pass
                if bubbles:
                    scroll.scroll_end(animate=False)

            def _record_toc_turn(self, text: str) -> str:
                self._turn_seq += 1
                turn_id = f"turn-{self._turn_seq}"
                item = TocItem(
                    turn_id=turn_id,
                    summary=summarize_prompt(text),
                )
                self._toc_items.append(item)
                try:
                    self._sidebar().set_toc_items(self._toc_items)
                except Exception:  # noqa: BLE001
                    pass
                return turn_id

            async def on_mount(self) -> None:
                self._refresh_window_title()
                await self._hydrate_session_from_store()
                await self._host.start()
                self._stream_cm = self._bus.stream(*_WATCH_TYPES)
                stream = await self._stream_cm.__aenter__()
                self._consumer = asyncio.create_task(
                    self._consume(stream),
                    name="tui-bus-consumer",
                )
                try:
                    from openjiuwen_icode.skills import skill_slash_entries

                    self._suggestions().set_extra_commands(
                        skill_slash_entries(self._host)
                    )
                except Exception:  # noqa: BLE001
                    pass
                self.query_one("#prompt", Input).focus()

            async def on_unmount(self) -> None:
                self._cancel_stream_idle()
                if self._consumer is not None and not self._consumer.done():
                    self._consumer.cancel()
                    try:
                        await self._consumer
                    except asyncio.CancelledError:
                        pass
                if self._stream_cm is not None:
                    await self._stream_cm.__aexit__(None, None, None)
                    self._stream_cm = None
                await self._host.stop()

            def _set_status(self, text: str) -> None:
                self._status().set_phase(text)

            def _prompt_widget(self) -> Input:
                return self.query_one("#prompt", Input)

            def _shell_cwd(self) -> str | None:
                primary = getattr(self._host, "workdirs", None)
                if primary is not None and primary.primary:
                    return primary.primary
                backend = getattr(self._host, "_backend", None)
                cfg = getattr(backend, "cfg", None)
                workspace = getattr(cfg, "workspace", None) if cfg else None
                if workspace:
                    return str(workspace)
                return None

            def _enter_shell_mode(self) -> None:
                if self._shell_mode:
                    return
                self._shell_mode = True
                self._suggestions().hide()
                prompt = self._prompt_widget()
                prompt.placeholder = self._SHELL_PLACEHOLDER
                prompt.add_class("shell-mode")
                prompt.value = ""
                if not self._busy:
                    self._set_status("Shell mode · ! or Esc to exit")
                self._write_system("shell mode on — local commands, no agent")

            def _exit_shell_mode(self, *, notice: bool = True) -> None:
                if not self._shell_mode:
                    return
                self._shell_mode = False
                prompt = self._prompt_widget()
                prompt.remove_class("shell-mode")
                prompt.placeholder = self._CHAT_PLACEHOLDER
                if notice:
                    self._write_system("shell mode off")
                if not self._busy:
                    self._set_status(self._READY_STATUS)

            async def _run_local_shell(self, cmd: str) -> None:
                self._write_system(f"$ {cmd}")
                try:
                    result = await run_shell_command(
                        cmd, cwd=self._shell_cwd()
                    )
                except OSError as exc:
                    self._write_error(f"shell error: {exc}")
                    store = self._host.session_store
                    if store is not None:
                        store.add_message("user", f"$ {cmd}")
                        store.add_message(
                            "assistant", f"[shell]\n(error: {exc})"
                        )
                    return
                out_parts: list[str] = []
                if result.stdout:
                    out_parts.append(result.stdout.rstrip("\n"))
                if result.stderr:
                    out_parts.append(result.stderr.rstrip("\n"))
                if result.returncode != 0:
                    out_parts.append(f"(exit {result.returncode})")
                if out_parts:
                    self._write_system("\n".join(out_parts))
                else:
                    self._write_system("(no output)")
                persist_shell_turn(self._host.session_store, result)

            def _apply_ready_or_awaiting_status(self) -> None:
                if self._awaiting_subagents > 0:
                    self._set_status(
                        f"等待 {self._awaiting_subagents} 个后台子 Agent · /subagents"
                    )
                else:
                    self._set_status(self._READY_STATUS)

            def _set_phase(self, phase: str) -> None:
                if not self._busy and phase not in {
                    "Ready",
                    "Cleared",
                    "Failed — Ctrl+R to retry",
                    self._READY_STATUS,
                }:
                    if not phase.startswith(("等待审批", "等待你的回答")):
                        if not phase.startswith("Shell mode"):
                            if phase != self._READY_STATUS:
                                # Allow copy flash via StatusBar.flash.
                                if not phase.startswith("Copied"):
                                    return
                hint = ""
                if self._busy and (
                    phase.startswith("模型已返回")
                    or phase.startswith("框架")
                    or phase.startswith("工具已返回")
                    or phase.startswith("子 Agent 完成")
                ):
                    hint = " · 可输入注入"
                elif self._busy and phase.startswith("等待"):
                    hint = " · 可输入注入"
                self._set_status(phase + hint)

            def _cancel_stream_idle(self) -> None:
                task = self._stream_idle_task
                if task is not None and not task.done():
                    task.cancel()
                self._stream_idle_task = None

            def _arm_stream_idle(self) -> None:
                self._cancel_stream_idle()

                async def _idle() -> None:
                    try:
                        await asyncio.sleep(0.45)
                    except asyncio.CancelledError:
                        return
                    if not self._busy:
                        return
                    # Status only — do not finalize the bubble. A mid-stream
                    # pause used to close the Agent bubble, so the next token
                    # opened a second bubble (e.g. trailing "?").
                    if self._active_agent is not None:
                        self._set_phase("模型生成中（等待更多输出）")

                self._stream_idle_task = asyncio.create_task(
                    _idle(), name="tui-stream-idle"
                )

            def _finalize_agent_bubble(self) -> None:
                self._active_agent = None

            def _ensure_agent_bubble(self) -> AgentBubble:
                if self._active_agent is None:
                    bubble = AgentBubble("")
                    self._mount_msg(bubble)
                    self._active_agent = bubble
                return self._active_agent

            def _collapse_turn_tools(self) -> None:
                for card in self._turn_tool_cards:
                    card.collapse()
                self._turn_tool_cards.clear()
                self._open_tool_cards.clear()

            def _phase_from_event(self, event: Event) -> None:
                if isinstance(event, TurnStarted):
                    self._cancel_stream_idle()
                    self._set_phase("框架执行中")
                    return
                if isinstance(event, AgentThinking):
                    self._set_phase("模型思考中")
                    self._arm_stream_idle()
                    return
                if isinstance(event, AgentMessage):
                    if getattr(event, "stream", True):
                        self._set_phase("模型生成中")
                        self._arm_stream_idle()
                    else:
                        self._cancel_stream_idle()
                        self._set_phase("模型已返回 · 框架收尾中")
                    return
                if isinstance(event, ToolCallStart):
                    self._cancel_stream_idle()
                    self._finalize_agent_bubble()
                    name = event.tool_name or "tool"
                    self._set_phase(f"等待工具执行 · {name}")
                    return
                if isinstance(event, ToolCallResult):
                    name = event.tool_name or "tool"
                    self._set_phase(f"工具已返回 · {name} · 框架继续")
                    return
                if isinstance(event, SubAgentStarted):
                    self._cancel_stream_idle()
                    self._finalize_agent_bubble()
                    self._set_phase(
                        f"等待子 Agent · {event.agent_name or 'subagent'}"
                    )
                    return
                if isinstance(event, SubAgentProgress):
                    self._set_phase(
                        f"子 Agent 进行中 · {event.agent_name or 'subagent'}"
                    )
                    return
                if isinstance(event, SubAgentFinished):
                    label = "完成" if event.ok else "失败"
                    self._set_phase(f"子 Agent {label} · 框架继续")
                    return
                if isinstance(event, SubAgentRetryAttempt):
                    self._set_phase(
                        f"子 Agent 重试 {event.attempt}/{event.max_attempts}"
                        f" · {event.delay_seconds}s"
                    )
                    return
                if isinstance(event, SubAgentFailed):
                    self._set_phase(
                        f"子 Agent 失败 · {event.agent_name or 'subagent'}"
                    )
                    return
                if isinstance(event, SubAgentPaused):
                    self._set_phase(
                        f"子 Agent 暂停 · {event.agent_name or 'subagent'}"
                    )
                    return
                if isinstance(event, SubAgentToolCallStart):
                    self._set_phase(
                        f"子 Agent 工具 · {event.tool_name or 'tool'}"
                    )
                    return
                if isinstance(event, SubAgentsAwaiting):
                    self._awaiting_subagents = int(
                        event.count or len(event.items or [])
                    )
                    self._set_phase(
                        f"后台子 Agent ×{self._awaiting_subagents}"
                    )
                    return
                if isinstance(event, SubAgentsIdle):
                    self._awaiting_subagents = 0
                    return
                if isinstance(event, CompactionStarted):
                    self._cancel_stream_idle()
                    self._finalize_agent_bubble()
                    self._set_phase("压缩上下文中")
                    return
                if isinstance(event, CompactionFinished):
                    self._set_phase("框架执行中")
                    return
                if isinstance(event, ApprovalRequest):
                    self._cancel_stream_idle()
                    self._finalize_agent_bubble()
                    self._set_phase(
                        f"等待审批 · {event.tool_name or 'tool'}"
                    )
                    return
                if isinstance(event, QuestionToUser):
                    self._cancel_stream_idle()
                    self._finalize_agent_bubble()
                    self._set_phase("等待你的回答")
                    return
                if isinstance(event, (TurnFinished, TurnFailed)):
                    self._cancel_stream_idle()
                    return

            async def _consume(self, stream: Any) -> None:
                prompt = self.query_one("#prompt", Input)
                try:
                    async for event in stream:
                        try:
                            await self._handle_bus_event(prompt, event)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            self._write_error(f"TUI event error: {exc}")
                except asyncio.CancelledError:
                    return

            async def _handle_bus_event(
                self, prompt: Input, event: Event
            ) -> None:
                if isinstance(event, TurnStarted):
                    self._busy = True
                    self._agent_response_buf = ""
                    self._active_agent = None
                    self._open_tool_cards.clear()
                    self._turn_tool_cards.clear()
                self._append_event(event)
                self._phase_from_event(event)
                if isinstance(event, ApprovalRequest):
                    self._finalize_agent_bubble()
                    self._pending_approval = event
                    self._pending_question = None
                    # push_screen_wait requires a Textual worker; the bus
                    # consumer is an asyncio.Task, so schedule a worker.
                    self.run_worker(
                        self._show_approval_modal(event),
                        exclusive=False,
                        name="approval-modal",
                    )
                elif isinstance(event, QuestionToUser):
                    self._finalize_agent_bubble()
                    self._pending_question = event
                    self._pending_approval = None
                    self.run_worker(
                        self._show_ask_modal(event),
                        exclusive=False,
                        name="ask-modal",
                    )
                elif isinstance(event, UsageUpdate):
                    self._status().set_usage(
                        f"tokens {event.total_tokens} "
                        f"(in {event.input_tokens}/"
                        f"out {event.output_tokens})"
                    )
                    try:
                        self._sidebar().context_panel.apply_usage_event(event)
                    except Exception:  # noqa: BLE001
                        pass
                elif isinstance(event, CompactionFinished):
                    try:
                        self._sidebar().context_panel.add_compressed_block(
                            event.summary or "",
                            ok=bool(event.ok),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                elif isinstance(event, SystemNotice) and event.kind == "clear":
                    self._finalize_agent_bubble()
                    await self._clear_transcript()
                    self._set_status("Cleared")
                elif isinstance(event, SessionCreated):
                    self._session_label = event.session_id or ""
                    self._session_title = event.title or ""
                    self._refresh_window_title()
                    await self._clear_transcript()
                elif isinstance(event, SessionRestored):
                    self._session_label = event.session_id or ""
                    self._session_title = event.title or ""
                    self._refresh_window_title()
                    await self._hydrate_session_from_store()
                elif isinstance(event, SessionTitleUpdated):
                    self._session_title = event.title or ""
                    if event.session_id:
                        self._session_label = event.session_id
                    self._refresh_window_title()
                elif isinstance(event, TodoListUpdated):
                    try:
                        self._sidebar().set_todos(event.items)
                        self._sidebar().focus_tasks()
                    except Exception:  # noqa: BLE001
                        pass
                elif isinstance(event, TurnFinished):
                    self._finalize_agent_bubble()
                    self._collapse_turn_tools()
                    self._last_agent_response = self._agent_response_buf.strip()
                    self._agent_response_buf = ""
                    self._busy = False
                    self._pending_approval = None
                    self._pending_question = None
                    if self._shell_mode:
                        prompt.placeholder = self._SHELL_PLACEHOLDER
                        self._set_status("Shell mode · ! or Esc to exit")
                    else:
                        prompt.placeholder = self._CHAT_PLACEHOLDER
                        self._apply_ready_or_awaiting_status()
                elif isinstance(event, TurnFailed):
                    self._finalize_agent_bubble()
                    self._collapse_turn_tools()
                    self._busy = False
                    self._pending_approval = None
                    self._pending_question = None
                    if self._shell_mode:
                        prompt.placeholder = self._SHELL_PLACEHOLDER
                    else:
                        prompt.placeholder = self._CHAT_PLACEHOLDER
                    self._set_status("Failed — Ctrl+R to retry")

            async def _show_approval_modal(
                self, event: ApprovalRequest
            ) -> None:
                result = await self.push_screen_wait(
                    ApprovalModal(event.tool_name, event.tool_args)
                )
                self._pending_approval = None
                if result is None:
                    approved, feedback = False, "dismissed"
                else:
                    approved, feedback = result
                await self._bus.publish(
                    UserApproval(
                        interaction_id=event.interaction_id,
                        approved=approved,
                        feedback=feedback,
                        session_id=self._host.session_id,
                    )
                )
                self._write_system(
                    f"Approval> {'yes' if approved else 'no'}"
                )

            async def _show_ask_modal(self, event: QuestionToUser) -> None:
                answer = await self.push_screen_wait(
                    AskModal(list(event.questions or []))
                )
                self._pending_question = None
                text = (answer or "").strip()
                answers: dict[str, str] = {}
                for q in event.questions or []:
                    if isinstance(q, dict) and q.get("question"):
                        answers[str(q["question"])] = text
                        break
                await self._bus.publish(
                    UserAskAnswer(
                        interaction_id=event.interaction_id,
                        answers=answers,
                        answer=text,
                        session_id=self._host.session_id,
                    )
                )
                self._write_system(f"Answer> {text}")

            def _append_event(self, event: Event) -> None:
                if isinstance(event, TurnStarted):
                    turn_id = self._record_toc_turn(event.text)
                    self._mount_msg(UserBubble(event.text, id=turn_id))
                    self._subagent_cards.clear()
                    return
                if isinstance(event, AgentMessage):
                    if getattr(event, "stream", True):
                        bubble = self._ensure_agent_bubble()
                        bubble.append_text(event.text)
                    else:
                        self._finalize_agent_bubble()
                        text = event.text.rstrip("\n")
                        if text:
                            self._mount_msg(AgentBubble(text))
                    self._agent_response_buf += event.text
                    return
                if isinstance(event, AgentThinking):
                    if self._show_thinking:
                        self._write_system(f"think> {event.text}")
                    return
                if isinstance(
                    event,
                    (
                        ToolCallStart,
                        ToolCallResult,
                        SubAgentStarted,
                        SubAgentProgress,
                        SubAgentsAwaiting,
                        SubAgentsIdle,
                        SubAgentAborted,
                        SubAgentFailed,
                        SubAgentFinished,
                        SubAgentPaused,
                        SubAgentResumed,
                        SubAgentRetryAttempt,
                        SubAgentToolCallResult,
                        SubAgentToolCallStart,
                        CompactionStarted,
                        CompactionFinished,
                        ApprovalRequest,
                        QuestionToUser,
                        TodoListUpdated,
                        SystemNotice,
                        ProfileSwitched,
                        TurnFailed,
                        TurnFinished,
                        ErrorEvent,
                    ),
                ):
                    self._finalize_agent_bubble()

                if isinstance(event, ToolCallStart):
                    card = ToolCard(event.tool_name, event.tool_args)
                    self._mount_msg(card)
                    self._open_tool_cards.append(card)
                    self._turn_tool_cards.append(card)
                    return
                if isinstance(event, ToolCallResult):
                    card = None
                    for pending in reversed(self._open_tool_cards):
                        if pending.tool_name == (event.tool_name or "tool") and (
                            not pending.result
                        ):
                            card = pending
                            break
                    if card is None and self._open_tool_cards:
                        card = self._open_tool_cards[-1]
                    if card is not None:
                        card.set_result(event.result or "")
                        # Keep collapsed by default; user expands via click.
                        card.collapse()
                    else:
                        self._write_system(
                            f"⎿ {event.tool_name}: {(event.result or '')[:200]}"
                        )
                    return
                if isinstance(event, SubAgentStarted):
                    card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.set_running(task=event.task or "")
                    else:
                        self._write_system(
                            f"↳ subagent {event.agent_name}"
                            f"{_subagent_meta_suffix(event)} {event.task!r}"
                        )
                    return
                if isinstance(event, SubAgentProgress):
                    if event.text:
                        self._write_system(
                            f"… {event.agent_name} {event.text}"
                        )
                    return
                if isinstance(event, SubAgentFinished):
                    preview = event.result or ""
                    card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.set_done(preview=preview)
                    else:
                        if len(preview) > 160:
                            preview = preview[:157] + "..."
                        mark = "ok" if event.ok else "failed"
                        self._write_system(
                            f"↲ {event.agent_name}{_subagent_meta_suffix(event)} "
                            f"[{mark}] {preview}"
                        )
                    return
                if isinstance(event, SubAgentPaused):
                    card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.set_paused(
                            reason=event.reason or "",
                            last_error=event.last_error or "",
                        )
                    else:
                        self._write_system(
                            f"⏸ {event.agent_name} paused: {event.last_error}"
                        )
                    return
                if isinstance(event, SubAgentRetryAttempt):
                    card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.set_retry_attempt(
                            event.message or "",
                            int(event.attempt or 0),
                            int(event.max_attempts or 0),
                            int(event.delay_seconds or 0),
                        )
                    else:
                        self._write_system(
                            f"↻ {event.agent_name} retry "
                            f"{event.attempt}/{event.max_attempts} "
                            f"in {event.delay_seconds}s: {event.message}"
                        )
                    return
                if isinstance(event, SubAgentFailed):
                    err = (event.error or "")[:160]
                    transport = str(getattr(event, "transport", "") or "")
                    card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.set_failed(
                            error=err,
                            allow_retry=transport == "async",
                        )
                    else:
                        self._write_system(
                            f"↲ {event.agent_name}{_subagent_meta_suffix(event)} "
                            f"[failed] {err}"
                        )
                    return
                if isinstance(event, SubAgentAborted):
                    card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.set_aborted(reason=event.reason or "")
                    else:
                        self._write_system(
                            f"✗ {event.agent_name} aborted"
                        )
                    return
                if isinstance(event, SubAgentResumed):
                    card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.set_running(clear_tools=True)
                    return
                if isinstance(event, SubAgentToolCallStart):
                    card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.add_tool_start(
                            event.tool_name or "tool",
                            event.tool_args,
                        )
                    else:
                        self._write_system(
                            f"  ● {event.agent_name}"
                            f"{_subagent_meta_suffix(event)} "
                            f"· {event.tool_name or 'tool'}"
                        )
                    return
                if isinstance(event, SubAgentToolCallResult):
                    card = None
                    iid = str(getattr(event, "invocation_id", "") or "")
                    if iid:
                        card = self._subagent_cards.get(iid)
                    if card is None:
                        card = self._ensure_subagent_card(event)
                    if card is not None:
                        card.complete_tool(
                            event.tool_name or "tool",
                            event.result or "",
                        )
                    else:
                        preview = (event.result or "")[:120]
                        self._write_system(
                            f"  ⎿ {event.agent_name} · "
                            f"{event.tool_name or 'tool'} {preview}"
                        )
                    return
                if isinstance(event, SubAgentsAwaiting):
                    self._awaiting_subagents = int(
                        event.count or len(event.items or [])
                    )
                    self._write_system(
                        f"⏳ awaiting {self._awaiting_subagents} "
                        "background sub-agent(s) · /subagents"
                    )
                    return
                if isinstance(event, SubAgentsIdle):
                    self._awaiting_subagents = 0
                    self._write_system("✓ all background sub-agents finished")
                    return
                if isinstance(event, CompactionStarted):
                    self._write_system(f"compaction… {event.reason}")
                    return
                if isinstance(event, CompactionFinished):
                    mark = "ok" if event.ok else "failed"
                    self._write_system(f"compaction [{mark}] {event.summary}")
                    return
                if isinstance(event, TodoListUpdated):
                    return
                if isinstance(event, SystemNotice):
                    if event.kind == "clear":
                        return
                    self._write_system(event.text)
                    return
                if isinstance(event, ProfileSwitched):
                    self._write_system(
                        f"profile {event.kind}={event.profile_id} "
                        f"— {event.detail}"
                    )
                    if event.kind == "model" and event.profile_id:
                        import re

                        self._base_title = re.sub(
                            r"\([^)]*\)",
                            f"({event.profile_id})",
                            self._base_title,
                            count=1,
                        )
                        self._refresh_window_title()
                    return
                if isinstance(event, ApprovalRequest):
                    # Modal handles interaction; keep a transcript breadcrumb.
                    self._write_system(
                        f"⚠ Approve {event.tool_name}? {event.tool_args!r}"
                    )
                    return
                if isinstance(event, QuestionToUser):
                    self._write_system("Agent needs your input…")
                    return
                if isinstance(event, TurnFailed):
                    self._write_error(event.error)
                    return
                if isinstance(event, TurnFinished):
                    return
                if isinstance(event, ErrorEvent):
                    self._write_error(event.message)
                    return
                if isinstance(
                    event,
                    (
                        UsageUpdate,
                        SessionListed,
                        SessionCreated,
                        SessionRestored,
                        SessionTitleUpdated,
                    ),
                ):
                    return
                self._write_system(format_event(event))

            async def on_input_changed(self, event: Any) -> None:
                if self._shell_mode:
                    self._suggestions().hide()
                    return
                if self._pending_approval or self._pending_question:
                    self._suggestions().hide()
                    return
                value = event.value
                if is_shell_toggle(value):
                    self._enter_shell_mode()
                    return
                self._suggestions().show_for(value)

            async def on_input_submitted(self, event: Any) -> None:
                suggestions = self._suggestions()
                if suggestions.is_open:
                    chosen = suggestions.selected_command()
                    suggestions.hide()
                    if chosen:
                        # Replace bare "/" prefix selection into the prompt.
                        event.input.value = ""
                        await self._submit_text(chosen)
                        return

                prompt = event.value.strip()
                event.input.value = ""
                suggestions.hide()
                if not prompt:
                    return
                await self._submit_text(prompt)

            async def _submit_text(self, prompt: str) -> None:
                sid = self._host.session_id

                if self._shell_mode:
                    if is_shell_toggle(prompt):
                        self._exit_shell_mode()
                        return
                    await self._run_local_shell(prompt)
                    return

                if is_shell_toggle(prompt):
                    self._enter_shell_mode()
                    return
                bang_cmd = shell_command_from_bang_line(prompt)
                if bang_cmd is not None:
                    if bang_cmd:
                        await self._run_local_shell(bang_cmd)
                    else:
                        self._enter_shell_mode()
                    return

                slash = _parse_slash(prompt)
                if slash is not None:
                    name, _args = slash
                    # Allow quit even while a turn is busy (same as Ctrl+Q).
                    # Prefer App.exit() — action_quit is async and must be awaited.
                    if name in {"quit", "exit"}:
                        self.exit()
                        return
                if slash is not None and not self._busy:
                    from openjiuwen_icode.host.workdirs import (
                        format_directories_command_args,
                        parse_directories_slash,
                    )

                    dir_cmd = parse_directories_slash(prompt)
                    if dir_cmd is not None:
                        action, rest = dir_cmd
                        if action in {"add", "a"} and not rest.strip():
                            self._open_directory_picker_modal()
                            return
                        args = format_directories_command_args(action, rest)
                        await self._bus.publish(
                            UserCommand(
                                name="workdirs",
                                args=args,
                                session_id=sid,
                            )
                        )
                        return

                    name, args = slash
                    if name in {"models", "model"} and not args:
                        self._open_models_modal()
                        return
                    if name == "sessions" and not args:
                        self._open_sessions_modal()
                        return
                    await self._bus.publish(
                        UserCommand(name=name, args=args, session_id=sid)
                    )
                    return

                if self._busy:
                    await self._bus.publish(
                        UserInject(text=prompt, session_id=sid)
                    )
                    self._write_system(f"Inject> {prompt}")
                    return

                await self._bus.publish(
                    UserMessage(text=prompt, session_id=sid)
                )

            def action_suggest_up(self) -> None:
                sug = self._suggestions()
                if not sug.is_open:
                    raise SkipAction()
                if sug.highlighted is None:
                    sug.highlighted = 0
                elif sug.highlighted > 0:
                    sug.highlighted -= 1

            def action_suggest_down(self) -> None:
                sug = self._suggestions()
                if not sug.is_open:
                    raise SkipAction()
                if sug.option_count == 0:
                    return
                if sug.highlighted is None:
                    sug.highlighted = 0
                elif sug.highlighted < sug.option_count - 1:
                    sug.highlighted += 1

            def action_suggest_complete(self) -> None:
                """Tab: fill the highlighted slash command into the input."""
                sug = self._suggestions()
                if not sug.is_open:
                    raise SkipAction()
                cmd = sug.selected_command()
                if not cmd:
                    raise SkipAction()
                prompt = self._prompt_widget()
                prompt.value = cmd
                prompt.cursor_position = len(cmd)
                sug.show_for(cmd)

            def action_exit_shell(self) -> None:
                # App-level Esc is priority=True (shell exit). When a modal is
                # on top, forward Esc to dismiss it instead of exiting shell.
                from textual.screen import ModalScreen

                if isinstance(self.screen, ModalScreen):
                    cancel = getattr(self.screen, "action_cancel", None)
                    if callable(cancel):
                        cancel()
                    else:
                        self.screen.dismiss(None)
                    return
                if self._suggestions().is_open:
                    self._suggestions().hide()
                    return
                if self._shell_mode:
                    self._exit_shell_mode()

            def action_toggle_sidebar(self) -> None:
                self._sidebar().toggle()
                visible = self._sidebar().is_visible
                self._status().flash(
                    "Sidebar shown" if visible else "Sidebar hidden"
                )

            def action_open_models(self) -> None:
                if self._busy:
                    self._write_error(
                        "Cannot open Models while a turn is active"
                    )
                    return
                self._open_models_modal()

            def action_open_sessions(self) -> None:
                if self._busy:
                    self._write_error(
                        "Cannot open Sessions while a turn is active"
                    )
                    return
                self._open_sessions_modal()

            def _open_models_modal(self) -> None:
                """Push ModelsModal (callback-based; safe outside workers)."""
                cfg = getattr(self._host._backend, "cfg", None)
                current = getattr(cfg, "model", None) if cfg else None
                self.push_screen(
                    ModelsModal(current_model=current),
                    callback=self._on_models_modal_dismissed,
                )

            def _open_sessions_modal(self) -> None:
                store = self._host.session_store
                sessions = store.list_sessions() if store is not None else []

                def _delete(session_id: str) -> None:
                    if store is None:
                        raise RuntimeError("No session store attached.")
                    if not store.delete_session(session_id):
                        raise FileNotFoundError(
                            f"session not found: {session_id}"
                        )

                self.push_screen(
                    SessionsModal(
                        sessions,
                        current_session_id=self._host.session_id or "",
                        on_delete=_delete,
                    ),
                    callback=self._on_sessions_modal_dismissed,
                )

            def _open_directory_picker_modal(self) -> None:
                if self._busy:
                    self._write_error(
                        "Cannot add directories while a turn is active"
                    )
                    return
                reg = self._host.workdirs
                start = reg.primary or None
                from openjiuwen_icode.tui.screens.directory_picker_modal import (
                    DirectoryPickerModal,
                )

                self.push_screen(
                    DirectoryPickerModal(
                        start_path=start,
                        existing_dirs=list(reg.dirs),
                    ),
                    callback=self._on_directory_picker_dismissed,
                )

            def _on_directory_picker_dismissed(
                self, result: dict[str, Any] | None
            ) -> None:
                if not result or result.get("action") != "select":
                    return
                path = str(result.get("path") or "").strip()
                if not path:
                    return
                self.run_worker(
                    self._bus.publish(
                        UserCommand(
                            name="workdirs",
                            args=f"add {path}",
                            session_id=self._host.session_id,
                        )
                    ),
                    exclusive=False,
                )

            def _on_models_modal_dismissed(
                self, result: dict[str, Any] | None
            ) -> None:
                if not result:
                    return
                action = result.get("action")
                model_id = str(result.get("id") or "")
                if action == "use" and model_id:
                    self.run_worker(
                        self._switch_model_from_modal(model_id),
                        exclusive=False,
                    )

            def _on_sessions_modal_dismissed(
                self, result: dict[str, Any] | None
            ) -> None:
                if result and result.get("action") == "deleted_current":
                    self.run_worker(
                        self._bus.publish(
                            UserCommand(
                                name="new",
                                args="",
                                session_id=self._host.session_id,
                            )
                        ),
                        exclusive=False,
                    )
                    return
                if not result:
                    return
                action = result.get("action")
                session_id = str(result.get("id") or "")
                if action == "resume" and session_id:
                    if self._busy:
                        self._write_error(
                            "Cannot resume while a turn is active"
                        )
                        return
                    self.run_worker(
                        self._bus.publish(
                            UserCommand(
                                name="resume",
                                args=session_id,
                                session_id=self._host.session_id,
                            )
                        ),
                        exclusive=False,
                    )

            async def _switch_model_from_modal(self, model_id: str) -> None:
                await self._bus.publish(
                    UserCommand(
                        name="models",
                        args=model_id,
                        session_id=self._host.session_id,
                    )
                )

            def on_conversation_toc_turn_selected(
                self, event: ConversationToc.TurnSelected
            ) -> None:
                from textual.css.query import NoMatches

                try:
                    bubble = self.query_one(f"#{event.turn_id}", UserBubble)
                except NoMatches:
                    self._status().flash(
                        f"Turn {event.turn_id} not in transcript"
                    )
                    return
                self._transcript().scroll_to_widget(bubble, animate=True)
                try:
                    bubble.add_class("-toc-focus")
                    self.set_timer(
                        0.8, lambda: bubble.remove_class("-toc-focus")
                    )
                except Exception:  # noqa: BLE001
                    pass

            def action_copy_text(self) -> None:
                if not copy_screen_selection(self, self.screen, clear=False):
                    raise SkipAction()
                self._status().flash("Copied selection to clipboard")

            def on_mouse_down(self, event: Any) -> None:
                button = getattr(event, "button", None)
                if button != 3:
                    return
                if not copy_screen_selection(self, self.screen, clear=True):
                    return
                cancel_textual_mouse_chain(self.screen)
                prevent = getattr(event, "prevent_default", None)
                if callable(prevent):
                    prevent()
                stop = getattr(event, "stop", None)
                if callable(stop):
                    stop()
                self._status().flash("Copied selection to clipboard")

            async def action_interrupt(self) -> None:
                await self._bus.publish(
                    UserInterrupt(session_id=self._host.session_id)
                )
                self._write_system("Interrupt requested (Ctrl+B)")

            async def action_retry(self) -> None:
                if self._busy:
                    self._write_error("Cannot retry while turn is active")
                    return
                await self._bus.publish(
                    UserRetry(session_id=self._host.session_id)
                )

        return _App()


async def run_tui(
    cfg: CLIConfig | None,
    *,
    demo: bool = False,
) -> int:
    """Launch the Textual EventBus TUI."""
    bundle = build_host_bundle(cfg, demo=demo, auto_approve=False)
    app = CodingAssistantApp.create(
        bus=bundle.bus, host=bundle.host, title=bundle.title
    )
    await app.run_async()
    return 0

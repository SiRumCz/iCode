# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Minimal ACP (Agent Client Protocol) JSON-RPC server for editors (T-30).

Stdout carries **only** newline-delimited JSON-RPC 2.0 messages.
Logs and diagnostics must go to stderr.

Implements: ``initialize``, ``session/new``, ``session/load``,
``session/transcript``, ``session/list``, ``session/prompt``,
``session/cancel``, ``session/close``, ``session/approve``,
``session/diff``, ``session/delete``, ``shutdown``.
Streaming updates: agent message, thinking, tool call/result, usage,
permission requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from openjiuwen_icode import __version__
from openjiuwen_icode.events import (
    AgentMessage,
    AgentThinking,
    ApprovalRequest,
    EventBus,
    ToolCallResult,
    ToolCallStart,
    TurnFailed,
    TurnFinished,
    UsageUpdate,
    UserApproval,
    UserInterrupt,
    UserMessage,
)
from openjiuwen_icode.host.bootstrap import HostBundle, build_host_bundle
from openjiuwen_icode.storage.session_store import SessionStore

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
PRODUCT_NAME = "iCode"


@dataclass
class AcpSession:
    """One ACP-exposed session bound to a HostBundle."""

    session_id: str
    cwd: str
    bundle: HostBundle
    prompt_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AcpProtocolError(RuntimeError):
    """JSON-RPC application error."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class AcpServer:
    """Process-scoped ACP adapter over SessionHost."""

    def __init__(
        self,
        *,
        demo: bool = False,
        cfg: Any = None,
        auto_approve: bool = True,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self._demo = demo
        self._cfg = cfg
        self._auto_approve = auto_approve
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._sessions: dict[str, AcpSession] = {}
        self._default_store: SessionStore | None = None
        self._closed = False

    def _store(self) -> SessionStore:
        if self._default_store is None:
            from openjiuwen_icode.paths import IcodeProject

            project_path = (
                getattr(self._cfg, "project", None) if self._cfg else None
            )
            project = IcodeProject.open(project_path)
            self._default_store = SessionStore(store_dir=project.sessions_dir)
        return self._default_store

    def _write(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._stdout.write(line + "\n")
        self._stdout.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _reply(self, req_id: Any, result: Any) -> None:
        self._write({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _reply_error(
        self, req_id: Any, code: int, message: str, data: Any = None
    ) -> None:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        self._write({"jsonrpc": "2.0", "id": req_id, "error": err})

    def _session_update(self, sid: str, update: dict[str, Any]) -> None:
        self._notify(
            "session/update",
            {"sessionId": sid, "update": update},
        )

    async def handle_request(self, message: dict[str, Any]) -> None:
        """Dispatch one JSON-RPC request or notification."""
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        req_id = message.get("id", None)
        is_request = "id" in message

        try:
            result = await self._dispatch(method, params)
            if is_request:
                self._reply(req_id, result if result is not None else {})
        except AcpProtocolError as exc:
            if is_request:
                self._reply_error(req_id, exc.code, exc.message, exc.data)
            else:
                print(f"ACP error: {exc.message}", file=self._stderr)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ACP handler failed for %s", method)
            if is_request:
                self._reply_error(req_id, -32603, str(exc))

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method in {"initialize", "agent/initialize"}:
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "agentInfo": {
                    "name": PRODUCT_NAME,
                    "version": __version__,
                },
                "agentCapabilities": {
                    "loadSession": True,
                    "promptCapabilities": {"image": False, "audio": False},
                    "mcpCapabilities": False,
                },
            }
        if method in {"session/new", "newSession"}:
            return await self._session_new(params)
        if method in {"session/load", "loadSession"}:
            return await self._session_load(params)
        if method in {"session/transcript", "sessionTranscript"}:
            return await self._session_transcript(params)
        if method in {"session/list", "listSessions"}:
            return await self._session_list(params)
        if method in {"session/prompt", "prompt"}:
            return await self._session_prompt(params)
        if method in {"session/cancel", "cancel"}:
            return await self._session_cancel(params)
        if method in {"session/close", "closeSession"}:
            return await self._session_close(params)
        if method in {"session/approve", "approve"}:
            return await self._session_approve(params)
        if method in {"session/diff", "diff"}:
            return await self._session_diff(params)
        if method in {"session/delete", "deleteSession"}:
            return await self._session_delete(params)
        if method in {"shutdown", "exit"}:
            await self.close_all()
            return {}
        raise AcpProtocolError(-32601, f"Method not found: {method}")

    async def _session_new(self, params: dict[str, Any]) -> dict[str, Any]:
        cwd = str(params.get("cwd") or "").strip()
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        if not sid:
            sid = f"acp-{uuid4().hex[:10]}"
        if sid in self._sessions:
            raise AcpProtocolError(-32000, f"session already open: {sid}")
        bundle = build_host_bundle(
            self._cfg,
            demo=self._demo,
            auto_approve=self._auto_approve,
            session_id=sid,
        )
        await bundle.host.start()
        if cwd:
            try:
                from openjiuwen_icode.host.workdirs import (
                    apply_workdir_to_backend,
                )

                path = bundle.host.workdirs.add(cwd)
                bundle.host.workdirs.use(path)
                apply_workdir_to_backend(bundle.host._backend, path)
            except Exception:  # noqa: BLE001
                logger.debug("ACP workdir apply failed for %s", cwd, exc_info=True)
        self._sessions[sid] = AcpSession(
            session_id=sid, cwd=cwd, bundle=bundle
        )
        self._session_update(
            sid,
            {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [],
            },
        )
        return {"sessionId": sid}

    async def _session_load(self, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        if not sid:
            raise AcpProtocolError(-32602, "sessionId required")
        store = self._store()
        try:
            session = store.load_session(sid)
        except FileNotFoundError as exc:
            raise AcpProtocolError(-32001, str(exc)) from exc
        if sid not in self._sessions:
            bundle = build_host_bundle(
                self._cfg,
                demo=self._demo,
                auto_approve=self._auto_approve,
                session_id=sid,
            )
            await bundle.host.start()
            from openjiuwen_icode.features.session_resume import (
                align_backend_session_after_resume,
            )

            store.switch_session(sid)
            await align_backend_session_after_resume(bundle.host, session)
            self._sessions[sid] = AcpSession(
                session_id=sid,
                cwd=session.workdir or "",
                bundle=bundle,
            )
        return {
            "sessionId": sid,
            "title": session.title,
            "messageCount": len(session.messages),
            "model": session.model,
            "messages": self._session_messages_for_client(store, sid, session),
        }

    async def _session_transcript(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return chat timeline for a session without switching the active session."""
        sid = str(params.get("sessionId") or params.get("session_id") or "").strip()
        if not sid:
            raise AcpProtocolError(-32602, "sessionId required")
        store = self._store()
        try:
            session = store.load_session(sid)
        except FileNotFoundError as exc:
            raise AcpProtocolError(-32000, f"session not found: {sid}") from exc
        return {
            "sessionId": sid,
            "title": session.title,
            "model": session.model,
            "messages": self._session_messages_for_client(store, sid, session),
        }

    def _session_messages_for_client(
        self,
        store: SessionStore,
        sid: str,
        session: Any,
    ) -> list[dict[str, str]]:
        """Prefer event-log timeline (tools/thinking); fall back to stored messages."""
        from openjiuwen_icode.features.session_timeline import session_timeline

        return session_timeline(
            store.store_dir,
            sid,
            fallback_messages=list(session.messages),
        )

    async def _session_list(self, params: dict[str, Any]) -> dict[str, Any]:
        rows = self._store().list_sessions()
        return {
            "sessions": [
                {
                    "sessionId": r.get("id"),
                    "title": r.get("title"),
                    "updatedAt": r.get("updated_at"),
                    "cwd": r.get("directory"),
                    "model": r.get("model"),
                }
                for r in rows
            ]
        }

    async def _session_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        if not sid:
            raise AcpProtocolError(-32602, "sessionId required")
        session = self._sessions.get(sid)
        if session is None:
            await self._session_new(
                {"sessionId": sid, "cwd": params.get("cwd") or ""}
            )
            session = self._sessions[sid]
        prompt = _extract_prompt_text(params)
        if not prompt:
            raise AcpProtocolError(-32602, "prompt text required")

        async with session.prompt_lock:
            bus: EventBus = session.bundle.bus
            done = asyncio.get_running_loop().create_future()
            parts: list[str] = []

            async def on_agent(ev: AgentMessage) -> None:
                if ev.text:
                    parts.append(ev.text)
                    self._session_update(
                        sid,
                        {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": ev.text},
                        },
                    )

            async def on_thinking(ev: AgentThinking) -> None:
                if ev.text:
                    self._session_update(
                        sid,
                        {
                            "sessionUpdate": "agent_thought_chunk",
                            "content": {"type": "text", "text": ev.text},
                        },
                    )

            async def on_tool_start(ev: ToolCallStart) -> None:
                self._session_update(
                    sid,
                    {
                        "sessionUpdate": "tool_call",
                        "toolCallId": ev.tool_call_id,
                        "title": ev.tool_name,
                        "kind": "other",
                        "status": "pending",
                        "rawInput": ev.tool_args,
                    },
                )

            async def on_tool_result(ev: ToolCallResult) -> None:
                self._session_update(
                    sid,
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": ev.tool_call_id,
                        "title": ev.tool_name,
                        "status": (
                            "completed"
                            if ev.tool_success is not False
                            else "failed"
                        ),
                        "content": [
                            {
                                "type": "content",
                                "content": {
                                    "type": "text",
                                    "text": str(ev.result)[:2000],
                                },
                            }
                        ],
                    },
                )

            async def on_usage(ev: UsageUpdate) -> None:
                self._session_update(
                    sid,
                    {
                        "sessionUpdate": "usage_update",
                        "inputTokens": ev.input_tokens,
                        "outputTokens": ev.output_tokens,
                        "totalTokens": ev.total_tokens,
                        "modelCalls": ev.model_calls,
                    },
                )

            async def on_approval(ev: ApprovalRequest) -> None:
                self._session_update(
                    sid,
                    {
                        "sessionUpdate": "request_permission",
                        "interactionId": ev.interaction_id,
                        "toolName": ev.tool_name,
                        "toolArgs": ev.tool_args,
                        "message": ev.message
                        or f"Approve tool `{ev.tool_name}`?",
                    },
                )

            async def on_finished(ev: TurnFinished) -> None:
                if not done.done():
                    done.set_result({"stopReason": "end_turn", "ok": True})

            async def on_failed(ev: TurnFailed) -> None:
                if not done.done():
                    done.set_result(
                        {
                            "stopReason": "error",
                            "ok": False,
                            "error": ev.error,
                        }
                    )

            await bus.subscribe(AgentMessage, on_agent)
            await bus.subscribe(AgentThinking, on_thinking)
            await bus.subscribe(ToolCallStart, on_tool_start)
            await bus.subscribe(ToolCallResult, on_tool_result)
            await bus.subscribe(UsageUpdate, on_usage)
            await bus.subscribe(ApprovalRequest, on_approval)
            await bus.subscribe(TurnFinished, on_finished)
            await bus.subscribe(TurnFailed, on_failed)
            try:
                await bus.publish(UserMessage(text=prompt, session_id=sid))
                result = await asyncio.wait_for(done, timeout=600)
            except asyncio.TimeoutError as exc:
                raise AcpProtocolError(-32002, "prompt timed out") from exc
            finally:
                await bus.unsubscribe(AgentMessage, on_agent)
                await bus.unsubscribe(AgentThinking, on_thinking)
                await bus.unsubscribe(ToolCallStart, on_tool_start)
                await bus.unsubscribe(ToolCallResult, on_tool_result)
                await bus.unsubscribe(UsageUpdate, on_usage)
                await bus.unsubscribe(ApprovalRequest, on_approval)
                await bus.unsubscribe(TurnFinished, on_finished)
                await bus.unsubscribe(TurnFailed, on_failed)

            result["sessionId"] = sid
            result["text"] = "".join(parts)
            # Attach latest mutation summary for editor diff UI.
            result["diff"] = _mutation_payload(session.bundle.host)
            return result

    async def _session_approve(self, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        interaction_id = str(
            params.get("interactionId")
            or params.get("interaction_id")
            or ""
        ).strip()
        if not sid or not interaction_id:
            raise AcpProtocolError(
                -32602, "sessionId and interactionId required"
            )
        session = self._sessions.get(sid)
        if session is None:
            raise AcpProtocolError(-32001, f"unknown session: {sid}")
        approved = bool(params.get("approved", True))
        feedback = str(params.get("feedback") or "")
        await session.bundle.bus.publish(
            UserApproval(
                interaction_id=interaction_id,
                approved=approved,
                feedback=feedback,
                session_id=sid,
            )
        )
        return {
            "ok": True,
            "sessionId": sid,
            "interactionId": interaction_id,
            "approved": approved,
        }

    async def _session_diff(self, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        if not sid:
            raise AcpProtocolError(-32602, "sessionId required")
        session = self._sessions.get(sid)
        if session is None:
            raise AcpProtocolError(-32001, f"unknown session: {sid}")
        turn_id = params.get("turnId") or params.get("turn_id")
        payload = _mutation_payload(
            session.bundle.host,
            turn_id=str(turn_id) if turn_id else None,
        )
        return {"sessionId": sid, **payload}

    async def _session_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        if not sid:
            raise AcpProtocolError(-32602, "sessionId required")
        # Close in-memory session first if open.
        if sid in self._sessions:
            await self._session_close({"sessionId": sid})
        removed = self._store().delete_session(sid)
        if not removed:
            raise AcpProtocolError(-32001, f"session not found: {sid}")
        return {"deleted": True, "sessionId": sid}

    async def _session_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        session = self._sessions.get(sid)
        if session is None:
            return {"cancelled": False}
        await session.bundle.bus.publish(UserInterrupt(session_id=sid))
        return {"cancelled": True, "sessionId": sid}

    async def _session_close(self, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        session = self._sessions.pop(sid, None)
        if session is None:
            return {"closed": False}
        await session.bundle.host.stop()
        return {"closed": True, "sessionId": sid}

    async def close_all(self) -> None:
        for sid in list(self._sessions):
            await self._session_close({"sessionId": sid})
        self._closed = True

    async def serve_reader(self, reader: asyncio.StreamReader) -> int:
        """Read JSON-RPC lines from *reader* until EOF or shutdown."""
        while not self._closed:
            line = await reader.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                self._reply_error(None, -32700, "Parse error")
                continue
            if not isinstance(message, dict):
                continue
            await self.handle_request(message)
        await self.close_all()
        return 0

    async def serve_stdio(self) -> int:
        """Read JSON-RPC lines from stdin until EOF."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        return await self.serve_reader(reader)


def _mutation_payload(
    host: Any, *, turn_id: str | None = None
) -> dict[str, Any]:
    tracker = getattr(host, "mutations", None)
    if tracker is None:
        return {"files": [], "summary": ""}
    turns = tracker.list_turns()
    if turn_id:
        turns = [t for t in turns if t.turn_id == turn_id]
    files: list[dict[str, Any]] = []
    for turn in turns[-5:]:
        for mut in turn.files:
            entry: dict[str, Any] = {
                "path": mut.path,
                "kind": mut.kind,
                "turnId": turn.turn_id,
                "beforeHash": mut.before_hash,
                "afterHash": mut.after_hash,
            }
            before = _read_snapshot(tracker, mut.snapshot_before)
            after = _read_snapshot(tracker, mut.snapshot_after)
            if before is not None:
                entry["before"] = before
            if after is not None:
                entry["after"] = after
            files.append(entry)
    return {
        "files": files,
        "summary": tracker.format_diff(turn_id),
    }


def _read_snapshot(tracker: Any, rel: str) -> str | None:
    if not rel:
        return None
    path = Path(tracker.root) / rel
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:200_000]
    except OSError:
        return None


def _extract_prompt_text(params: dict[str, Any]) -> str:
    if isinstance(params.get("prompt"), str):
        return params["prompt"].strip()
    if isinstance(params.get("text"), str):
        return params["text"].strip()
    blocks = params.get("prompt") or params.get("content") or []
    if isinstance(blocks, list):
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif "text" in block:
                    parts.append(str(block["text"]))
                # Resource / file context from editors
                elif block.get("type") in {"resource", "resource_link"}:
                    uri = block.get("uri") or block.get("path") or ""
                    text = block.get("text") or block.get("content") or ""
                    if uri or text:
                        parts.append(f"\n[Attached: {uri}]\n{text}\n")
        return "".join(parts).strip()
    return ""


async def run_acp_server(
    *,
    demo: bool = False,
    cfg: Any = None,
    auto_approve: bool = True,
) -> int:
    """Entry used by ``icode acp``."""
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    server = AcpServer(
        demo=demo, cfg=cfg, auto_approve=auto_approve
    )
    return await server.serve_stdio()


__all__ = [
    "AcpProtocolError",
    "AcpServer",
    "PROTOCOL_VERSION",
    "run_acp_server",
]

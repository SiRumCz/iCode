# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Minimal ACP client for spawning external sub-agents (T-31)."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AcpClientConfig:
    """How to launch an external ACP agent process."""

    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    profile_id: str = ""


@dataclass
class AcpClientResult:
    """Outcome of one ACP client prompt."""

    session_id: str
    text: str
    ok: bool
    stop_reason: str = ""
    error: str = ""
    transport: str = "acp"


class AcpClient:
    """Stdio JSON-RPC client talking to an external ``openjiuwen acp`` (or Chrys)."""

    def __init__(self, config: AcpClientConfig) -> None:
        self.config = config
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._req_id = 0
        self._session_id = ""

    async def start(self) -> str:
        """Spawn the child and create a session. Returns session id."""
        env = None
        if self.config.env:
            import os

            env = {**os.environ, **self.config.env}
        self._proc = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.cwd,
            env=env,
        )
        assert self._proc.stdout is not None
        self._reader = self._proc.stdout
        await self._request("initialize", {})
        result = await self._request("session/new", {"cwd": self.config.cwd or ""})
        self._session_id = str(result.get("sessionId") or "")
        return self._session_id

    async def prompt(self, text: str) -> AcpClientResult:
        """Send a prompt to the child ACP session."""
        if not self._session_id:
            await self.start()
        result = await self._request(
            "session/prompt",
            {
                "sessionId": self._session_id,
                "prompt": [{"type": "text", "text": text}],
            },
        )
        return AcpClientResult(
            session_id=self._session_id,
            text=str(result.get("text") or ""),
            ok=bool(result.get("ok", True)),
            stop_reason=str(result.get("stopReason") or ""),
            error=str(result.get("error") or ""),
            transport="acp",
        )

    async def cancel(self) -> None:
        if self._session_id:
            try:
                await self._request(
                    "session/cancel", {"sessionId": self._session_id}
                )
            except Exception:  # noqa: BLE001
                logger.debug("ACP cancel failed", exc_info=True)

    async def close(self) -> None:
        if self._session_id and self._proc and self._proc.stdin:
            try:
                await self._request(
                    "session/close", {"sessionId": self._session_id}
                )
            except Exception:  # noqa: BLE001
                pass
        if self._proc is not None:
            if self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self._proc.kill()
            self._proc = None

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None or self._reader is None:
            raise RuntimeError("ACP client not started")
        self._req_id += 1
        req_id = self._req_id
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()
        # Read until matching response id (skip notifications).
        while True:
            raw = await asyncio.wait_for(self._reader.readline(), timeout=120)
            if not raw:
                raise RuntimeError("ACP child closed stdout")
            message = json.loads(raw.decode("utf-8"))
            if not isinstance(message, dict):
                continue
            if message.get("id") != req_id:
                continue
            if "error" in message:
                err = message["error"]
                raise RuntimeError(
                    f"ACP error {err.get('code')}: {err.get('message')}"
                )
            result = message.get("result")
            return result if isinstance(result, dict) else {}


def parse_acp_transport(profile: dict[str, Any] | None) -> AcpClientConfig | None:
    """Extract ACP transport config from an agent profile document."""
    if not profile:
        return None
    transport = str(profile.get("transport") or "").strip().lower()
    block = profile.get("acp")
    if transport != "acp" and not isinstance(block, dict):
        return None
    if not isinstance(block, dict):
        block = {}
    command = str(block.get("command") or "icode").strip()
    args_raw = block.get("args")
    if isinstance(args_raw, list):
        args = [str(a) for a in args_raw]
    else:
        args = ["acp", "--demo"]
    env = block.get("env") if isinstance(block.get("env"), dict) else {}
    return AcpClientConfig(
        command=command,
        args=args,
        env={str(k): str(v) for k, v in env.items()},
        cwd=str(block.get("cwd") or "") or None,
        profile_id=str(profile.get("id") or ""),
    )


async def run_acp_subagent_prompt(
    config: AcpClientConfig,
    prompt: str,
    *,
    bus: Any = None,
    session_id: str | None = None,
    invocation_id: str | None = None,
) -> AcpClientResult:
    """Run one ACP subagent turn and optionally emit SubAgent* EventBus events."""
    from uuid import uuid4

    from openjiuwen_icode.events import (
        SubAgentFailed,
        SubAgentFinished,
        SubAgentStarted,
    )

    inv = invocation_id or f"acp-{uuid4().hex[:8]}"
    client = AcpClient(config)
    if bus is not None:
        await bus.publish(
            SubAgentStarted(
                invocation_id=inv,
                agent_name=config.profile_id or "acp",
                task=prompt[:200],
                transport="acp",
                session_id=session_id,
            )
        )
    try:
        await client.start()
        result = await client.prompt(prompt)
        if bus is not None:
            if result.ok:
                await bus.publish(
                    SubAgentFinished(
                        invocation_id=inv,
                        agent_name=config.profile_id or "acp",
                        result=result.text[:2000],
                        transport="acp",
                        session_id=session_id,
                    )
                )
            else:
                await bus.publish(
                    SubAgentFailed(
                        invocation_id=inv,
                        agent_name=config.profile_id or "acp",
                        error=result.error or "acp failed",
                        transport="acp",
                        session_id=session_id,
                    )
                )
        return result
    except Exception as exc:
        if bus is not None:
            await bus.publish(
                SubAgentFailed(
                    invocation_id=inv,
                    agent_name=config.profile_id or "acp",
                    error=str(exc),
                    transport="acp",
                    session_id=session_id,
                )
            )
        raise
    finally:
        await client.close()


__all__ = [
    "AcpClient",
    "AcpClientConfig",
    "AcpClientResult",
    "parse_acp_transport",
    "run_acp_subagent_prompt",
]

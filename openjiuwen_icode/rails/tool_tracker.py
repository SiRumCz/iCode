"""Tool execution tracking rail.

Emits ``tool_call`` and ``tool_result`` chunks into the session
stream so the CLI renderer can display tool activity in Claude Code
style (``● ToolName(args)`` / ``⎿ result summary``).
"""

from __future__ import annotations

import json
from typing import Any

from openjiuwen.core.session.stream.base import OutputSchema
from openjiuwen.core.single_agent.rail.base import AgentRail


from openjiuwen.harness.tools.base_tool import ToolOutput


def _extract_tool_call_id(inputs: Any) -> str:
    """Best-effort tool call id from rail inputs / raw tool_call."""
    direct = getattr(inputs, "tool_call_id", None)
    if direct:
        return str(direct)
    tool_call = getattr(inputs, "tool_call", None)
    if tool_call is None:
        return ""
    for attr in ("id", "tool_call_id"):
        value = getattr(tool_call, attr, None)
        if value:
            return str(value)
    if isinstance(tool_call, dict):
        return str(
            tool_call.get("id") or tool_call.get("tool_call_id") or ""
        )
    return ""


class ToolTrackingRail(AgentRail):
    """Emit tool call/result chunks for UI rendering.

    This rail fires at low priority so that other rails (e.g.
    ``SecurityRail``) can modify or reject tool calls before
    the UI is notified.
    """

    priority = 5  # very low — run after everything else

    @staticmethod
    def _ensure_failed_tool_diagnostic(
        tool_name: str,
        tool_result: Any,
        tool_msg: Any,
    ) -> None:
        """Replace empty ToolOutput failures with actionable model feedback."""
        if (
            not isinstance(tool_result, ToolOutput)
            or tool_result.success
            or tool_result.error
            or tool_result.data is not None
        ):
            return
        detail = (
            f"Tool '{tool_name or 'unknown'}' failed without diagnostic output. "
            "Check the arguments and retry, or use an alternative tool."
        )
        tool_result.error = detail
        if tool_msg is not None and hasattr(tool_msg, "content"):
            tool_msg.content = detail

    @staticmethod
    def _build_tool_result_payload(
        tool_name: str,
        tool_result: Any,
    ) -> dict[str, Any]:
        """Build the UI payload for a completed tool call."""
        payload: dict[str, Any] = {}
        if isinstance(tool_result, ToolOutput):
            payload["tool_success"] = tool_result.success
            if tool_result.error:
                payload["tool_error"] = str(tool_result.error)
            if tool_result.data is not None:
                payload["tool_data"] = tool_result.data
            if tool_result.success:
                payload["tool_result"] = (
                    str(tool_result.data)
                    if tool_result.data is not None
                    else ""
                )
            else:
                payload["tool_result"] = str(
                    tool_result.error or tool_result.data or ""
                )
            return payload

        payload = {
            "tool_result": str(tool_result)
            if tool_result is not None
            else "",
        }
        if tool_name != "read_file" or tool_result is None:
            return payload

        data = getattr(tool_result, "data", None)
        if not isinstance(data, dict):
            return payload

        content = data.get("content")
        if content is not None:
            if isinstance(content, bytes):
                payload["tool_result"] = content.decode(
                    "utf-8", errors="replace"
                )
            else:
                payload["tool_result"] = str(content)

        line_count = data.get("line_count")
        if line_count is not None:
            try:
                payload["line_count"] = int(line_count)
            except (TypeError, ValueError):
                pass

        return payload

    async def before_tool_call(self, ctx: Any) -> None:
        """Write a ``tool_call`` chunk when a tool starts."""
        session = ctx.session
        if session is None:
            return

        inputs = ctx.inputs
        tool_name = getattr(inputs, "tool_name", "")
        tool_args = getattr(inputs, "tool_args", "")
        tool_call_id = _extract_tool_call_id(inputs)

        # Normalize args to a dict if it's a JSON string
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except (json.JSONDecodeError, TypeError):
                pass

        await session.write_stream(
            OutputSchema(
                type="tool_call",
                index=0,
                payload={
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "tool_call_id": tool_call_id,
                },
            )
        )

    async def after_tool_call(self, ctx: Any) -> None:
        """Write a ``tool_result`` chunk when a tool finishes."""
        session = ctx.session
        if session is None:
            return

        inputs = ctx.inputs
        tool_name = getattr(inputs, "tool_name", "")
        tool_result = getattr(inputs, "tool_result", None)
        tool_msg = getattr(inputs, "tool_msg", None)
        tool_args = getattr(inputs, "tool_args", "")
        tool_call_id = _extract_tool_call_id(inputs)
        self._ensure_failed_tool_diagnostic(
            tool_name, tool_result, tool_msg
        )

        # Normalize args
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except (json.JSONDecodeError, TypeError):
                pass

        await session.write_stream(
            OutputSchema(
                type="tool_result",
                index=0,
                payload={
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "tool_call_id": tool_call_id,
                    **self._build_tool_result_payload(
                        tool_name, tool_result
                    ),
                },
            )
        )

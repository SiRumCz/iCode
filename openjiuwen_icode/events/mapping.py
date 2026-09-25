# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Map ``OutputSchema`` stream chunks to app EventBus events."""

from __future__ import annotations

from typing import Any

from openjiuwen_icode.events.types import (
    AgentMessage,
    AgentThinking,
    ApprovalRequest,
    CompactionFinished,
    CompactionStarted,
    ErrorEvent,
    Event,
    QuestionToUser,
    SubAgentsAwaiting,
    SubAgentsIdle,
    SubAgentFailed,
    SubAgentFinished,
    SubAgentPaused,
    SubAgentProgress,
    SubAgentRetryAttempt,
    SubAgentStarted,
    SubAgentToolCallResult,
    SubAgentToolCallStart,
    TodoListUpdated,
    ToolCallResult,
    ToolCallStart,
    ModelUsage,
)

# Aligned with harness/cli/ui/renderer.py chunk types.
_CHUNK_LLM_OUTPUT = "llm_output"
_CHUNK_LLM_REASONING = "llm_reasoning"
_CHUNK_ANSWER = "answer"
_CHUNK_MESSAGE = "message"
_CHUNK_TOOL_CALL = "tool_call"
_CHUNK_TOOL_RESULT = "tool_result"
_CHUNK_MODEL_USAGE = "model_usage"
_CHUNK_CONTROLLER_OUTPUT = "controller_output"
_CHUNK_INTERACTION = "__interaction__"
_CHUNK_TODO_UPDATED = "todo.updated"
_CHUNK_COMPACTION_START = "compaction.started"
_CHUNK_COMPACTION_END = "compaction.finished"
_CHUNK_SUBAGENT_START = "subagent.started"
_CHUNK_SUBAGENT_PROGRESS = "subagent.progress"
_CHUNK_SUBAGENT_END = "subagent.finished"
_CHUNK_SUBAGENT_TOOL_CALL = "subagent.tool_call"
_CHUNK_SUBAGENT_TOOL_RESULT = "subagent.tool_result"
_CHUNK_SUBAGENT_AWAITING = "subagent.awaiting"
_CHUNK_SUBAGENT_IDLE = "subagent.idle"
_CHUNK_SUBAGENT_RETRY = "subagent.retry_attempt"

_ASK_USER_TOOL = "ask_user"
_SUBAGENT_TOOLS = frozenset(
    {"task", "task_tool", "sessions_spawn", "code_agent", "research_agent"}
)
_LIFECYCLE_CHUNK_TOOLS = frozenset({"task_tool", "sessions_spawn"})


def _subagent_event_fields(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "invocation_id": str(payload.get("invocation_id", "") or ""),
        "sub_session_id": str(payload.get("sub_session_id", "") or ""),
        "transport": str(payload.get("transport", "") or ""),
    }


def _task_text_from_args(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    return str(
        args.get("task_description")
        or args.get("task")
        or args.get("query")
        or args.get("prompt")
        or ""
    )


def _tool_result_ok(payload: dict[str, Any]) -> bool:
    if "tool_success" in payload:
        return bool(payload.get("tool_success"))
    tool_data = payload.get("tool_data")
    if isinstance(tool_data, dict) and tool_data.get("status") == "pending":
        return True
    return True


def _subagent_name_from_tool(tool_name: str, args: Any) -> str:
    if isinstance(args, dict):
        st = args.get("subagent_type")
        if st:
            return str(st)
    return tool_name


def _payload_text(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("content", "text", "message", "output"):
            value = payload.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                return str(value)
        return ""
    if payload is None:
        return ""
    # Avoid dumping SDK objects / EventType reprs into the chat transcript.
    if hasattr(payload, "content"):
        content = getattr(payload, "content", None)
        if isinstance(content, str):
            return content
    text = str(payload)
    if text.startswith("type=") or "EventType." in text or "DataFrame" in text:
        return ""
    return text


def _controller_error_text(payload: Any) -> str:
    """Match renderer: only surface task_failed controller payloads."""
    if isinstance(payload, dict):
        payload_type = str(payload.get("type", "")).lower()
        if "task_failed" not in payload_type:
            return ""
        data = payload.get("data", [])
        texts: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    text = str(item.get("text", "")).strip()
                    if text:
                        texts.append(text)
        return "\n".join(texts)
    raw = str(payload)
    if "task_failed" not in raw.lower():
        return ""
    return raw


def _interaction_parts(
    payload: Any,
) -> tuple[str, Any]:
    """Return ``(interaction_id, request)`` from an interaction payload."""
    if isinstance(payload, dict):
        iid = str(
            payload.get("interaction_id")
            or payload.get("id")
            or "unknown"
        )
        # InteractionOutput-as-dict: ``{"id": ..., "value": request}``.
        if (
            "tool_name" not in payload
            and isinstance(payload.get("value"), (dict, object))
            and "value" in payload
        ):
            return iid, payload["value"]
        return iid, payload

    if isinstance(payload, tuple) and len(payload) >= 2:
        return str(payload[0]), payload[1]

    iid = str(getattr(payload, "id", None) or "unknown")
    value = getattr(payload, "value", payload)
    return iid, value


def _request_field(request: Any, name: str, default: Any = None) -> Any:
    if isinstance(request, dict):
        return request.get(name, default)
    return getattr(request, name, default)


def _interaction_events(
    payload: Any,
    *,
    session_id: str | None,
) -> list[Event]:
    iid, request = _interaction_parts(payload)
    tool_name = str(_request_field(request, "tool_name", "") or "")
    message = str(_request_field(request, "message", "") or "")

    if tool_name == _ASK_USER_TOOL:
        questions = _request_field(request, "questions", None) or []
        if not isinstance(questions, list):
            questions = []
        return [
            QuestionToUser(
                interaction_id=iid,
                questions=questions,
                message=message,
                session_id=session_id,
            )
        ]

    return [
        ApprovalRequest(
            interaction_id=iid,
            tool_name=tool_name,
            tool_args=_request_field(request, "tool_args"),
            message=message,
            session_id=session_id,
        )
    ]


def chunk_to_events(
    chunk: Any,
    *,
    session_id: str | None = None,
) -> list[Event]:
    """Convert one stream chunk into zero or more EventBus events."""
    chunk_type = getattr(chunk, "type", None)
    if chunk_type is None and isinstance(chunk, dict):
        chunk_type = chunk.get("type")
        payload = chunk.get("payload")
    else:
        payload = getattr(chunk, "payload", None)

    if not chunk_type:
        return []

    if chunk_type == _CHUNK_LLM_OUTPUT:
        text = _payload_text(payload)
        if not text:
            return []
        return [
            AgentMessage(text=text, stream=True, session_id=session_id)
        ]

    if chunk_type == _CHUNK_ANSWER:
        # Fallback when provider emits only answer (no llm_output tokens).
        text = _payload_text(payload)
        if not text:
            return []
        return [
            AgentMessage(text=text, stream=False, session_id=session_id)
        ]

    if chunk_type == _CHUNK_MESSAGE:
        text = _payload_text(payload)
        if not text:
            return []
        return [
            AgentMessage(text=text, stream=False, session_id=session_id)
        ]

    if chunk_type == _CHUNK_CONTROLLER_OUTPUT:
        # Do not dump TASK_COMPLETION / JsonDataFrame into the chat.
        err = _controller_error_text(payload)
        if not err:
            return []
        return [ErrorEvent(message=err, session_id=session_id)]

    if chunk_type == _CHUNK_LLM_REASONING:
        text = _payload_text(payload)
        if not text:
            return []
        return [AgentThinking(text=text, session_id=session_id)]

    if chunk_type == _CHUNK_TOOL_CALL:
        if not isinstance(payload, dict):
            return []
        tool_name = str(payload.get("tool_name", ""))
        events: list[Event] = [
            ToolCallStart(
                tool_name=tool_name,
                tool_args=payload.get("tool_args"),
                tool_call_id=str(payload.get("tool_call_id") or ""),
                session_id=session_id,
            )
        ]
        if tool_name in _SUBAGENT_TOOLS or tool_name.endswith("_agent"):
            if tool_name not in _LIFECYCLE_CHUNK_TOOLS:
                args = payload.get("tool_args")
                task = _task_text_from_args(args)
                agent_name = _subagent_name_from_tool(tool_name, args)
                events.append(
                    SubAgentStarted(
                        agent_name=agent_name,
                        task=task,
                        session_id=session_id,
                    )
                )
        return events

    if chunk_type == _CHUNK_TOOL_RESULT:
        if not isinstance(payload, dict):
            return []
        tool_name = str(payload.get("tool_name", ""))
        result = payload.get("tool_result", "")
        result_text = "" if result is None else str(result)
        tool_success = payload.get("tool_success")
        events = [
            ToolCallResult(
                tool_name=tool_name,
                result=result_text,
                tool_call_id=str(payload.get("tool_call_id") or ""),
                tool_success=(
                    None if tool_success is None else bool(tool_success)
                ),
                session_id=session_id,
            )
        ]
        if tool_name in _SUBAGENT_TOOLS or tool_name.endswith("_agent"):
            if tool_name not in _LIFECYCLE_CHUNK_TOOLS:
                args = payload.get("tool_args")
                agent_name = _subagent_name_from_tool(tool_name, args)
                ok = _tool_result_ok(payload)
                if ok:
                    events.append(
                        SubAgentFinished(
                            agent_name=agent_name,
                            result=result_text[:500],
                            ok=True,
                            session_id=session_id,
                        )
                    )
                else:
                    err = str(payload.get("tool_error") or result_text)[:500]
                    events.append(
                        SubAgentFailed(
                            agent_name=agent_name,
                            error=err,
                            session_id=session_id,
                        )
                    )
            elif tool_name in _LIFECYCLE_CHUNK_TOOLS and not _tool_result_ok(
                payload
            ):
                err = str(payload.get("tool_error") or result_text)[:500]
                args = payload.get("tool_args")
                agent_name = _subagent_name_from_tool(tool_name, args)
                events.append(
                    SubAgentFailed(
                        agent_name=agent_name,
                        error=err,
                        session_id=session_id,
                    )
                )
        return events

    if chunk_type == _CHUNK_MODEL_USAGE:
        if not isinstance(payload, dict):
            return []
        return [
            ModelUsage(
                input_tokens=int(payload.get("input_tokens") or 0),
                output_tokens=int(payload.get("output_tokens") or 0),
                call_index=int(payload.get("call_index") or 0),
                session_id=session_id,
            )
        ]

    if chunk_type == _CHUNK_INTERACTION:
        return _interaction_events(payload, session_id=session_id)

    if chunk_type == _CHUNK_TODO_UPDATED:
        if isinstance(payload, dict):
            items = payload.get("items", payload)
        else:
            items = payload
        return [TodoListUpdated(items=items, session_id=session_id)]

    if chunk_type == _CHUNK_COMPACTION_START:
        reason = _payload_text(payload) if payload else ""
        return [CompactionStarted(reason=reason, session_id=session_id)]

    if chunk_type == _CHUNK_COMPACTION_END:
        summary = _payload_text(payload) if payload else ""
        ok = True
        if isinstance(payload, dict) and "ok" in payload:
            ok = bool(payload.get("ok"))
        return [
            CompactionFinished(
                summary=summary, ok=ok, session_id=session_id
            )
        ]

    if chunk_type == _CHUNK_SUBAGENT_START:
        if isinstance(payload, dict):
            fields = _subagent_event_fields(payload)
            return [
                SubAgentStarted(
                    agent_name=str(payload.get("agent_name", "")),
                    task=str(payload.get("task", "")),
                    session_id=session_id,
                    **fields,
                )
            ]
        return []

    if chunk_type == _CHUNK_SUBAGENT_PROGRESS:
        if isinstance(payload, dict):
            fields = _subagent_event_fields(payload)
            return [
                SubAgentProgress(
                    agent_name=str(payload.get("agent_name", "")),
                    text=str(payload.get("text", "")),
                    session_id=session_id,
                    invocation_id=fields["invocation_id"],
                    sub_session_id=fields["sub_session_id"],
                )
            ]
        return []

    if chunk_type == _CHUNK_SUBAGENT_END:
        if isinstance(payload, dict):
            fields = _subagent_event_fields(payload)
            ok = bool(payload.get("ok", True))
            agent_name = str(payload.get("agent_name", ""))
            if ok:
                return [
                    SubAgentFinished(
                        agent_name=agent_name,
                        result=str(payload.get("result", "")),
                        ok=True,
                        session_id=session_id,
                        **fields,
                    )
                ]
            err_text = str(payload.get("result", "") or payload.get("error", ""))
            events: list[Event] = [
                SubAgentFailed(
                    agent_name=agent_name,
                    error=err_text,
                    session_id=session_id,
                    invocation_id=fields["invocation_id"],
                    sub_session_id=fields["sub_session_id"],
                    transport=fields["transport"],
                )
            ]
            if fields.get("transport") == "async":
                events.append(
                    SubAgentPaused(
                        agent_name=agent_name,
                        invocation_id=fields["invocation_id"],
                        reason="spawn_failed",
                        last_error=err_text,
                        session_id=session_id,
                    )
                )
            return events
        return []

    if chunk_type == _CHUNK_SUBAGENT_TOOL_CALL:
        if isinstance(payload, dict):
            fields = _subagent_event_fields(payload)
            return [
                SubAgentToolCallStart(
                    agent_name=str(payload.get("agent_name", "")),
                    tool_name=str(payload.get("tool_name", "")),
                    tool_args=payload.get("tool_args"),
                    session_id=session_id,
                    **fields,
                )
            ]
        return []

    if chunk_type == _CHUNK_SUBAGENT_TOOL_RESULT:
        if isinstance(payload, dict):
            fields = _subagent_event_fields(payload)
            return [
                SubAgentToolCallResult(
                    agent_name=str(payload.get("agent_name", "")),
                    tool_name=str(payload.get("tool_name", "")),
                    result=str(payload.get("result", "")),
                    session_id=session_id,
                    **fields,
                )
            ]
        return []

    if chunk_type == _CHUNK_SUBAGENT_AWAITING:
        if isinstance(payload, dict):
            items = payload.get("items", [])
            if not isinstance(items, list):
                items = []
            return [
                SubAgentsAwaiting(
                    count=int(payload.get("count", len(items)) or 0),
                    items=items,
                    session_id=session_id,
                )
            ]
        return []

    if chunk_type == _CHUNK_SUBAGENT_IDLE:
        return [SubAgentsIdle(session_id=session_id)]

    if chunk_type == _CHUNK_SUBAGENT_RETRY:
        if isinstance(payload, dict):
            fields = _subagent_event_fields(payload)
            return [
                SubAgentRetryAttempt(
                    agent_name=str(payload.get("agent_name", "")),
                    message=str(payload.get("message", "")),
                    attempt=int(payload.get("attempt", 0) or 0),
                    max_attempts=int(payload.get("max_attempts", 0) or 0),
                    delay_seconds=int(payload.get("delay_seconds", 0) or 0),
                    session_id=session_id,
                    invocation_id=fields["invocation_id"],
                    sub_session_id=fields["sub_session_id"],
                    transport=fields["transport"],
                )
            ]
        return []

    return []

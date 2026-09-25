# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""App-layer events for CLI EventBus (Chrys-style)."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4


def _event_id() -> str:
    return uuid4().hex[:12]


@dataclass
class Event:
    """Base class for all app EventBus events."""

    event_id: str = field(default_factory=_event_id)
    timestamp: float = field(default_factory=time)
    session_id: str | None = None


# ---------------------------------------------------------------------------
# Frontend → backend
# ---------------------------------------------------------------------------


@dataclass
class UserMessage(Event):
    """User submits a turn."""

    text: str = ""


@dataclass
class UserInterrupt(Event):
    """User requests abort of the current turn."""


@dataclass
class UserApproval(Event):
    """User decision for an :class:`ApprovalRequest`."""

    interaction_id: str = ""
    approved: bool = False
    feedback: str = ""


@dataclass
class UserAskAnswer(Event):
    """User answers for a :class:`QuestionToUser`."""

    interaction_id: str = ""
    answers: dict[str, str] = field(default_factory=dict)
    answer: str = ""


@dataclass
class UserInject(Event):
    """Steer mid-turn (DeepAgent ``steer`` / task-loop injection)."""

    text: str = ""
    inject_id: str = ""


@dataclass
class UserInjectCancel(Event):
    """Cancel a pending inject before it is consumed."""

    inject_id: str = ""


@dataclass
class UserFollowUp(Event):
    """Queue a follow-up after the current iteration (DeepAgent ``follow_up``)."""

    text: str = ""


@dataclass
class UserRetry(Event):
    """Retry the last turn (optional continuation text)."""

    text: str = ""


@dataclass
class UserCommand(Event):
    """Slash-style UI command (e.g. ``/models``, ``/sessions``)."""

    name: str = ""
    args: str = ""


@dataclass
class UserSubAgentAbort(Event):
    """User aborts one sub-agent invocation (maps to Chrys ``SubAgentAbortRequested``)."""

    invocation_id: str = ""


@dataclass
class UserSubAgentRetry(Event):
    """User retries one failed sub-agent invocation."""

    invocation_id: str = ""


# ---------------------------------------------------------------------------
# Backend → frontend
# ---------------------------------------------------------------------------


@dataclass
class TurnStarted(Event):
    """A user turn has begun."""

    text: str = ""


@dataclass
class TurnFinished(Event):
    """A user turn completed successfully."""


@dataclass
class TurnFailed(Event):
    """A user turn failed."""

    error: str = ""


@dataclass
class AgentMessage(Event):
    """Streamed assistant text (token or chunk)."""

    text: str = ""
    stream: bool = True  # False for non-streaming answer fallbacks


@dataclass
class AgentThinking(Event):
    """Streamed reasoning / thinking text."""

    text: str = ""


@dataclass
class ToolCallStart(Event):
    """A tool invocation started."""

    tool_name: str = ""
    tool_args: Any = None
    tool_call_id: str = ""


@dataclass
class ToolCallResult(Event):
    """A tool invocation finished."""

    tool_name: str = ""
    result: str = ""
    tool_call_id: str = ""
    tool_success: bool | None = None


@dataclass
class ModelUsage(Event):
    """Per-model-call token usage (from TokenTrackingRail)."""

    input_tokens: int = 0
    output_tokens: int = 0
    call_index: int = 0


@dataclass
class ApprovalRequest(Event):
    """ConfirmInterruptRail / write-tool approval needed."""

    interaction_id: str = ""
    tool_name: str = ""
    tool_args: Any = None
    message: str = ""


@dataclass
class QuestionToUser(Event):
    """AskUserRail question(s) for the user."""

    interaction_id: str = ""
    questions: list[Any] = field(default_factory=list)
    message: str = ""


@dataclass
class TodoListUpdated(Event):
    """Todo list changed (``todo.updated`` chunk)."""

    items: Any = None


@dataclass
class UsageUpdate(Event):
    """Token usage snapshot from TokenTrackingRail.

    ``input_tokens`` / ``output_tokens`` / ``total_tokens`` are
    *session-cumulative*. ``last_input_tokens`` is the most recent
    prompt size (best proxy for current context-window fill).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_calls: int = 0
    last_input_tokens: int = 0
    last_output_tokens: int = 0


@dataclass
class UserInjectResult(Event):
    """Whether a :class:`UserInject` was consumed by the backend."""

    inject_id: str = ""
    consumed: bool = False


@dataclass
class ErrorEvent(Event):
    """Non-fatal or host-level error for the frontend."""

    message: str = ""


@dataclass
class SystemNotice(Event):
    """Host → UI informational text (slash command output, etc.)."""

    text: str = ""
    kind: str = "info"  # info | help | status | error


@dataclass
class SessionListed(Event):
    """Result of listing persisted sessions."""

    sessions: list[Any] = field(default_factory=list)


@dataclass
class SessionRestored(Event):
    """A session was loaded into the host (``session_id`` on :class:`Event`)."""

    model: str = ""
    message_count: int = 0
    title: str = ""
    agent_context: str = ""


@dataclass
class SessionCreated(Event):
    """A new session was created (``session_id`` on :class:`Event`)."""

    model: str = ""
    title: str = ""


@dataclass
class SessionTitleUpdated(Event):
    """Session display title changed (provisional / LLM / manual)."""

    title: str = ""
    source: str = ""  # provisional | llm | manual


@dataclass
class CompactionStarted(Event):
    """Context compaction began."""

    reason: str = ""


@dataclass
class CompactionFinished(Event):
    """Context compaction finished."""

    summary: str = ""
    ok: bool = True


@dataclass
class SubAgentStarted(Event):
    """A subagent / task tool run started."""

    agent_name: str = ""
    task: str = ""
    invocation_id: str = ""
    sub_session_id: str = ""
    transport: str = ""  # sync | async | acp


@dataclass
class SubAgentProgress(Event):
    """Incremental subagent progress."""

    agent_name: str = ""
    text: str = ""
    invocation_id: str = ""
    sub_session_id: str = ""


@dataclass
class SubAgentFinished(Event):
    """A subagent / task tool run finished."""

    agent_name: str = ""
    result: str = ""
    ok: bool = True
    invocation_id: str = ""
    sub_session_id: str = ""
    transport: str = ""


@dataclass
class SubAgentFailed(Event):
    """A subagent run failed (spawn rejected or execution error)."""

    agent_name: str = ""
    error: str = ""
    invocation_id: str = ""
    sub_session_id: str = ""
    transport: str = ""


@dataclass
class SubAgentToolCallStart(Event):
    """A tool call started inside a sub-agent (parent-visible)."""

    agent_name: str = ""
    tool_name: str = ""
    tool_args: Any = None
    invocation_id: str = ""
    sub_session_id: str = ""
    transport: str = ""


@dataclass
class SubAgentToolCallResult(Event):
    """A tool call finished inside a sub-agent (parent-visible)."""

    agent_name: str = ""
    tool_name: str = ""
    result: str = ""
    invocation_id: str = ""
    sub_session_id: str = ""
    transport: str = ""


@dataclass
class SubAgentPaused(Event):
    """Sub-agent waiting for user Retry/Abort (Chrys parity surface)."""

    agent_name: str = ""
    invocation_id: str = ""
    reason: str = ""
    last_error: str = ""
    retry_attempts: int = 0


@dataclass
class SubAgentRetryAttempt(Event):
    """Auto-retry loop is about to sleep before the next attempt."""

    agent_name: str = ""
    invocation_id: str = ""
    message: str = ""
    attempt: int = 0
    max_attempts: int = 0
    delay_seconds: int = 0
    sub_session_id: str = ""
    transport: str = ""


@dataclass
class SubAgentResumed(Event):
    """Sub-agent restarted after user Retry."""

    agent_name: str = ""
    invocation_id: str = ""


@dataclass
class SubAgentAborted(Event):
    """Sub-agent invocation ended by user abort or cancel."""

    agent_name: str = ""
    invocation_id: str = ""
    reason: str = ""


@dataclass
class SubAgentsIdle(Event):
    """No background sub-agents are running for this session."""

    pass


@dataclass
class SubAgentsAwaiting(Event):
    """Parent session is waiting on one or more async sub-agents."""

    count: int = 0
    items: list[Any] = field(default_factory=list)


@dataclass
class ProfileSwitched(Event):
    """Model or agent profile selection changed."""

    kind: str = "model"  # model | agent
    profile_id: str = ""
    detail: str = ""

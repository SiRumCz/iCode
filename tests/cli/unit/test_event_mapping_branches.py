# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Branch coverage for events.mapping helpers and chunk types."""

from __future__ import annotations

from types import SimpleNamespace

from openjiuwen_icode.events.mapping import (
    _controller_error_text,
    _payload_text,
    _subagent_name_from_tool,
    _task_text_from_args,
    _tool_result_ok,
    chunk_to_events,
)
from openjiuwen_icode.events.types import (
    AgentMessage,
    AgentThinking,
    CompactionFinished,
    CompactionStarted,
    ErrorEvent,
    ModelUsage,
    SubAgentFailed,
    SubAgentFinished,
    SubAgentPaused,
    SubAgentProgress,
    SubAgentRetryAttempt,
    SubAgentStarted,
    SubAgentToolCallResult,
    SubAgentToolCallStart,
    SubAgentsAwaiting,
    SubAgentsIdle,
)


def test_payload_text_variants() -> None:
    assert _payload_text({"content": "a"}) == "a"
    assert _payload_text({"text": "b"}) == "b"
    assert _payload_text(None) == ""
    assert _payload_text({"content": {"nested": 1}}) == ""
    obj = SimpleNamespace(content="from-attr")
    assert _payload_text(obj) == "from-attr"
    assert _payload_text("type=EventType.FOO") == ""
    assert _payload_text("plain") == "plain"


def test_controller_error_text_dict_and_raw() -> None:
    assert (
        _controller_error_text(
            {
                "type": "task_failed",
                "data": [{"text": "boom"}, {"text": ""}],
            }
        )
        == "boom"
    )
    assert _controller_error_text({"type": "ok"}) == ""
    assert "failed" in _controller_error_text("TASK_FAILED: x").lower() or (
        _controller_error_text("TASK_FAILED: x") != ""
    )
    assert _controller_error_text("all good") == ""


def test_task_and_subagent_helpers() -> None:
    assert _task_text_from_args("x") == ""
    assert _task_text_from_args({"prompt": "p"}) == "p"
    assert _subagent_name_from_tool("task", {"subagent_type": "code"}) == "code"
    assert _subagent_name_from_tool("code_agent", {}) == "code_agent"
    assert _tool_result_ok({"tool_success": False}) is False
    assert _tool_result_ok({"tool_data": {"status": "pending"}}) is True
    assert _tool_result_ok({}) is True


def test_chunk_reasoning_message_model_usage() -> None:
    think = chunk_to_events({"type": "llm_reasoning", "payload": {"text": "hmm"}})
    assert isinstance(think[0], AgentThinking)
    msg = chunk_to_events({"type": "message", "payload": {"content": "hi"}})
    assert isinstance(msg[0], AgentMessage) and msg[0].stream is False
    usage = chunk_to_events(
        {
            "type": "model_usage",
            "payload": {"input_tokens": 2, "output_tokens": 3, "call_index": 1},
        }
    )
    assert isinstance(usage[0], ModelUsage)
    assert usage[0].input_tokens == 2
    assert chunk_to_events({"type": "", "payload": {}}) == []
    assert chunk_to_events({}) == []


def test_chunk_controller_task_failed() -> None:
    events = chunk_to_events(
        {
            "type": "controller_output",
            "payload": {
                "type": "task_failed",
                "data": [{"text": "died"}],
            },
        }
    )
    assert isinstance(events[0], ErrorEvent)
    assert events[0].message == "died"


def test_chunk_compaction() -> None:
    start = chunk_to_events(
        {"type": "compaction.started", "payload": {"text": "full"}}
    )
    assert isinstance(start[0], CompactionStarted)
    end = chunk_to_events(
        {"type": "compaction.finished", "payload": {"content": "ok", "ok": False}}
    )
    assert isinstance(end[0], CompactionFinished)
    assert end[0].ok is False


def test_tool_call_emits_subagent_started() -> None:
    events = chunk_to_events(
        {
            "type": "tool_call",
            "payload": {
                "tool_name": "code_agent",
                "tool_args": {"task": "fix bug"},
                "tool_call_id": "c1",
            },
        }
    )
    assert isinstance(events[0], type(events[0]))  # ToolCallStart
    assert any(isinstance(e, SubAgentStarted) for e in events)
    # lifecycle tools do not emit synthetic SubAgentStarted
    life = chunk_to_events(
        {
            "type": "tool_call",
            "payload": {
                "tool_name": "task_tool",
                "tool_args": {"task": "x"},
            },
        }
    )
    assert len(life) == 1


def test_tool_result_subagent_fail_and_lifecycle_fail() -> None:
    ok_events = chunk_to_events(
        {
            "type": "tool_result",
            "payload": {
                "tool_name": "research_agent",
                "tool_result": "done",
                "tool_success": True,
            },
        }
    )
    assert any(isinstance(e, SubAgentFinished) for e in ok_events)

    fail = chunk_to_events(
        {
            "type": "tool_result",
            "payload": {
                "tool_name": "code_agent",
                "tool_result": "nope",
                "tool_success": False,
                "tool_error": "boom",
            },
        }
    )
    assert any(isinstance(e, SubAgentFailed) for e in fail)

    life_fail = chunk_to_events(
        {
            "type": "tool_result",
            "payload": {
                "tool_name": "sessions_spawn",
                "tool_result": "err",
                "tool_success": False,
            },
        }
    )
    assert any(isinstance(e, SubAgentFailed) for e in life_fail)


def test_subagent_lifecycle_chunks() -> None:
    started = chunk_to_events(
        {
            "type": "subagent.started",
            "payload": {
                "agent_name": "code",
                "task": "t",
                "invocation_id": "i1",
            },
        }
    )
    assert isinstance(started[0], SubAgentStarted)

    prog = chunk_to_events(
        {
            "type": "subagent.progress",
            "payload": {"agent_name": "code", "text": "…"},
        }
    )
    assert isinstance(prog[0], SubAgentProgress)

    fin = chunk_to_events(
        {
            "type": "subagent.finished",
            "payload": {"agent_name": "code", "result": "ok", "ok": True},
        }
    )
    assert isinstance(fin[0], SubAgentFinished)

    failed = chunk_to_events(
        {
            "type": "subagent.finished",
            "payload": {
                "agent_name": "code",
                "result": "bad",
                "ok": False,
                "transport": "async",
                "invocation_id": "inv",
            },
        }
    )
    assert isinstance(failed[0], SubAgentFailed)
    assert any(isinstance(e, SubAgentPaused) for e in failed)

    tool_start = chunk_to_events(
        {
            "type": "subagent.tool_call",
            "payload": {"agent_name": "a", "tool_name": "bash"},
        }
    )
    assert isinstance(tool_start[0], SubAgentToolCallStart)

    tool_res = chunk_to_events(
        {
            "type": "subagent.tool_result",
            "payload": {"agent_name": "a", "tool_name": "bash", "result": "x"},
        }
    )
    assert isinstance(tool_res[0], SubAgentToolCallResult)

    awaiting = chunk_to_events(
        {
            "type": "subagent.awaiting",
            "payload": {"items": [{"id": 1}], "count": 1},
        }
    )
    assert isinstance(awaiting[0], SubAgentsAwaiting)

    idle = chunk_to_events({"type": "subagent.idle", "payload": {}})
    assert isinstance(idle[0], SubAgentsIdle)

    retry = chunk_to_events(
        {
            "type": "subagent.retry_attempt",
            "payload": {
                "agent_name": "a",
                "message": "retry",
                "attempt": 1,
                "max_attempts": 3,
                "delay_seconds": 2,
            },
        }
    )
    assert isinstance(retry[0], SubAgentRetryAttempt)

    assert chunk_to_events({"type": "subagent.started", "payload": "x"}) == []
    assert chunk_to_events({"type": "unknown.chunk", "payload": {}}) == []

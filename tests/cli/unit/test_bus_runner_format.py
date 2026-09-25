# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Coverage for bus_runner.format_event and event_to_dict."""

from __future__ import annotations

from openjiuwen_icode.events import (
    AgentMessage,
    AgentThinking,
    ApprovalRequest,
    ErrorEvent,
    ModelUsage,
    QuestionToUser,
    TodoListUpdated,
    ToolCallResult,
    ToolCallStart,
    TurnFailed,
    TurnFinished,
    TurnStarted,
    UsageUpdate,
    UserInjectResult,
)
from openjiuwen_icode.host.bus_runner import event_to_dict, format_event


def test_format_event_all_watched_types() -> None:
    assert "hi" in format_event(TurnStarted(text="hi"))
    assert format_event(TurnFinished()) == "[TurnFinished]"
    assert "boom" in format_event(TurnFailed(error="boom"))
    assert "msg" in format_event(AgentMessage(text="msg"))
    assert "think" in format_event(AgentThinking(text="think"))
    assert "bash" in format_event(
        ToolCallStart(tool_name="bash", tool_args={"c": 1})
    )
    long = "x" * 200
    line = format_event(ToolCallResult(tool_name="bash", result=long))
    assert "..." in line
    assert "write" in format_event(
        ApprovalRequest(interaction_id="i", tool_name="write")
    )
    assert "i" in format_event(QuestionToUser(interaction_id="i", questions=[]))
    assert "items" in format_event(TodoListUpdated(items=[1]))
    assert "total=" in format_event(
        UsageUpdate(input_tokens=1, output_tokens=2, total_tokens=3)
    )
    assert "consumed=" in format_event(
        UserInjectResult(inject_id="j", consumed=True)
    )
    assert "err" in format_event(ErrorEvent(message="err"))
    # Unknown Event subclass fallback uses base Event fields via generic name.
    assert format_event(ModelUsage(input_tokens=1, output_tokens=1)).startswith(
        "[ModelUsage]"
    )


def test_event_to_dict_branches() -> None:
    base = event_to_dict(TurnStarted(text="t"))
    assert base["type"] == "TurnStarted" and base["text"] == "t"

    failed = event_to_dict(TurnFailed(error="e"))
    assert failed["error"] == "e"

    msg = event_to_dict(AgentMessage(text="a"))
    assert msg["text"] == "a"

    start = event_to_dict(
        ToolCallStart(tool_name="t", tool_args={}, tool_call_id="c")
    )
    assert start["tool_call_id"] == "c"

    result = event_to_dict(
        ToolCallResult(
            tool_name="t", result="r", tool_call_id="c", tool_success=True
        )
    )
    assert result["tool_success"] is True

    usage = event_to_dict(
        ModelUsage(input_tokens=1, output_tokens=2, call_index=3)
    )
    assert usage["call_index"] == 3

    appr = event_to_dict(
        ApprovalRequest(
            interaction_id="i",
            tool_name="w",
            tool_args={},
            message="m",
        )
    )
    assert appr["message"] == "m"

    q = event_to_dict(
        QuestionToUser(interaction_id="i", questions=[1], message="q")
    )
    assert q["questions"] == [1]

    todo = event_to_dict(TodoListUpdated(items=["x"]))
    assert todo["items"] == ["x"]

    uu = event_to_dict(
        UsageUpdate(
            input_tokens=1,
            output_tokens=2,
            total_tokens=3,
            model_calls=4,
        )
    )
    assert uu["model_calls"] == 4

    inj = event_to_dict(UserInjectResult(inject_id="j", consumed=False))
    assert inj["consumed"] is False

    err = event_to_dict(ErrorEvent(message="m"))
    assert err["message"] == "m"

    finished = event_to_dict(TurnFinished())
    assert finished["type"] == "TurnFinished"
    assert "text" not in finished

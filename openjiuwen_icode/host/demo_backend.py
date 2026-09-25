# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Demo backend that emits fake OutputSchema chunks (no LLM)."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Optional

from openjiuwen.core.session.stream.base import OutputSchema


class DemoBackend:
    """Deterministic backend for EventBus demos and tests."""

    def __init__(self) -> None:
        self._aborted = False
        self.steered: list[str] = []
        self.follow_ups: list[str] = []

    async def start(self) -> None:
        self._aborted = False

    async def stop(self) -> None:
        return None

    async def abort(self) -> None:
        self._aborted = True

    async def steer(self, msg: str) -> None:
        self.steered.append(msg)

    async def follow_up(self, msg: str) -> None:
        self.follow_ups.append(msg)

    def get_usage(self) -> Optional[Dict[str, Any]]:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
        }

    async def rebuild(self) -> None:
        """No-op rebuild for demos/tests."""
        return None

    async def run_streaming(
        self,
        query: Any,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Any]:
        _ = session_id
        if self._aborted:
            return

        # Resume after InteractiveInput (approval / ask).
        user_inputs = getattr(query, "user_inputs", None)
        if isinstance(user_inputs, dict) and user_inputs:
            yield OutputSchema(
                type="llm_output",
                index=0,
                payload={"content": "[demo] resumed after interaction\n"},
            )
            return

        text = query if isinstance(query, str) else str(query)

        # Deterministic interaction path for demos/tests.
        if text.startswith("NEED_APPROVAL:"):
            yield OutputSchema(
                type="llm_output",
                index=0,
                payload={"content": "[demo] need approval\n"},
            )
            yield OutputSchema(
                type="__interaction__",
                index=1,
                payload={
                    "interaction_id": "demo-approve-1",
                    "tool_name": "write_file",
                    "tool_args": {"path": "demo.txt"},
                    "message": "Approve write?",
                },
            )
            return

        if text.startswith("NEED_ASK:"):
            yield OutputSchema(
                type="__interaction__",
                index=0,
                payload={
                    "interaction_id": "demo-ask-1",
                    "tool_name": "ask_user",
                    "message": "Need input",
                    "questions": [
                        {
                            "header": "Q1",
                            "question": "Which option?",
                            "options": [],
                        }
                    ],
                },
            )
            return

        yield OutputSchema(
            type="llm_output",
            index=0,
            payload={"content": f"[demo] got: {text}\n"},
        )
        yield OutputSchema(
            type="tool_call",
            index=1,
            payload={
                "tool_name": "demo_echo",
                "tool_args": {"text": text},
            },
        )
        yield OutputSchema(
            type="tool_result",
            index=2,
            payload={
                "tool_name": "demo_echo",
                "tool_result": f"echoed {len(text)} chars",
            },
        )
        yield OutputSchema(
            type="llm_output",
            index=3,
            payload={"content": "[demo] done.\n"},
        )

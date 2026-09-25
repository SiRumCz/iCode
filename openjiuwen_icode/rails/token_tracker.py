"""Token usage tracking rail.

Hooks into ``after_model_call`` to accumulate token counts from the
LLM response.  Provides :meth:`get_summary` for ``/status`` and
``/cost`` commands. Also emits a ``model_usage`` stream chunk per call
so SessionHost can persist step-level usage for OpenCode export.
"""

from __future__ import annotations

from typing import Any, Dict

from openjiuwen.core.session.stream.base import OutputSchema
from openjiuwen.core.single_agent.rail.base import AgentRail


class TokenTrackingRail(AgentRail):
    """Accumulate token usage across model calls.

    This rail hooks into the SDK rail framework via
    ``after_model_call`` and tracks prompt / completion tokens.

    Attributes:
        total_input_tokens: Sum of prompt / input tokens.
        total_output_tokens: Sum of completion / output tokens.
        call_count: Number of model calls tracked.
        last_input_tokens: Tokens from the most recent model call.
        last_output_tokens: Tokens from the most recent model call.
    """

    priority = 10  # low priority — run after other rails

    def __init__(self) -> None:
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.call_count: int = 0
        self.last_input_tokens: int = 0
        self.last_output_tokens: int = 0

    async def after_model_call(self, ctx: Any) -> None:
        """Extract token usage from the model response.

        The response object is expected to carry a ``usage`` attribute
        with ``prompt_tokens`` and ``completion_tokens`` fields.
        """
        self.call_count += 1
        self.last_input_tokens = 0
        self.last_output_tokens = 0
        response = getattr(ctx.inputs, "response", None)
        if response is not None:
            usage = getattr(response, "usage", None) or getattr(
                response, "usage_metadata", None
            )
            if usage is not None:
                self.last_input_tokens = (
                    getattr(usage, "prompt_tokens", None)
                    or getattr(usage, "input_tokens", None)
                    or 0
                ) or 0
                self.last_output_tokens = (
                    getattr(usage, "completion_tokens", None)
                    or getattr(usage, "output_tokens", None)
                    or 0
                ) or 0
                self.total_input_tokens += int(self.last_input_tokens)
                self.total_output_tokens += int(self.last_output_tokens)

        session = getattr(ctx, "session", None)
        if session is None:
            return
        try:
            await session.write_stream(
                OutputSchema(
                    type="model_usage",
                    index=0,
                    payload={
                        "input_tokens": int(self.last_input_tokens),
                        "output_tokens": int(self.last_output_tokens),
                        "call_index": int(self.call_count),
                    },
                )
            )
        except Exception:
            # Never fail the agent turn because of usage telemetry.
            return

    def get_summary(self) -> Dict[str, Any]:
        """Return a dict suitable for ``/status`` and ``/cost``."""
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": (
                self.total_input_tokens + self.total_output_tokens
            ),
            "model_calls": self.call_count,
            "last_input_tokens": self.last_input_tokens,
            "last_output_tokens": self.last_output_tokens,
        }

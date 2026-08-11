# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""Compatibility helpers for older openjiuwen SDK builds (e.g. 0.1.16)."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable


def call_with_supported_kwargs(ctor: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Instantiate *ctor*, dropping kwargs not present in its signature."""
    try:
        params = inspect.signature(ctor).parameters
    except (TypeError, ValueError):
        return ctor(*args, **kwargs)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return ctor(*args, **kwargs)
    filtered = {k: v for k, v in kwargs.items() if k in params}
    return ctor(*args, **filtered)


@dataclass
class LocalSubagentConcurrencyConfig:
    """Fallback when ``openjiuwen.harness.subagents.concurrency`` is absent."""

    max_total: int = 2
    per_agent_default: int = 2
    per_agent: dict[str, int] = field(default_factory=dict)


def load_concurrency_types() -> tuple[type, type | None]:
    """Return ``(ConfigType, LimiterType|None)`` for subagent concurrency."""
    try:
        from openjiuwen.harness.subagents.concurrency import (
            SubagentConcurrencyConfig,
            SubagentConcurrencyLimiter,
        )

        return SubagentConcurrencyConfig, SubagentConcurrencyLimiter
    except ImportError:
        return LocalSubagentConcurrencyConfig, None

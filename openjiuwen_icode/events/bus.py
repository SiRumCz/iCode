# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""In-process EventBus — sole CLI frontend↔backend channel (MVP).

Semantics mirror Chrys ``foundation.events.bus``:

* ``subscribe`` handlers are awaited inline by ``publish`` (backpressured, never
  lossy).
* ``stream`` iterators use an unbounded per-consumer queue (lossless; a slow
  consumer grows memory rather than dropping events).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

from openjiuwen_icode.events.types import Event

E = TypeVar("E", bound=Event)
logger = logging.getLogger(__name__)

_STREAM_QUEUE_HIGH_WATER = 10_000


class EventBus:
    """In-process async event bus for the coding-assistant CLI shell."""

    def __init__(self) -> None:
        self._handlers: dict[
            type[Event], list[Callable[..., Awaitable[None]]]
        ] = defaultdict(list)
        self._streams: list[_EventStream] = []
        self._taps: list[Callable[[Event], Any]] = []

    def add_tap(self, tap: Callable[[Event], Any]) -> None:
        """Register a sync/async callback invoked for every published event."""
        self._taps.append(tap)

    def remove_tap(self, tap: Callable[[Event], Any]) -> None:
        """Remove a previously registered tap."""
        if tap in self._taps:
            self._taps.remove(tap)

    async def publish(
        self,
        event: Event,
        *,
        raise_handler_errors: bool = False,
    ) -> None:
        """Publish *event* to subscribers and active streams."""
        event_type = type(event)
        failures: list[Exception] = []
        for handler in list(self._handlers.get(event_type, [])):
            try:
                await handler(event)
            except Exception as exc:
                failures.append(exc)
                logger.exception(
                    "EventBus handler failed for %s",
                    event_type.__name__,
                )
        for tap in list(self._taps):
            try:
                result = tap(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                failures.append(exc)
                logger.exception(
                    "EventBus tap failed for %s",
                    event_type.__name__,
                )
        for stream in list(self._streams):
            stream.deliver(event)
        if raise_handler_errors and failures:
            if len(failures) == 1:
                raise failures[0]
            raise ExceptionGroup(
                f"EventBus handlers failed for {event_type.__name__}",
                failures,
            )

    async def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], Awaitable[None]],
    ) -> None:
        """Register an async callback for *event_type*."""
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]

    async def unsubscribe(
        self,
        event_type: type[E],
        handler: Callable[..., Awaitable[None]],
    ) -> None:
        """Remove a previously registered handler."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def stream(self, *event_types: type[Event]) -> _EventStream:
        """Return an async iterator over matching events."""
        return _EventStream(self, event_types)


class _EventStream:
    """Async iterator backed by an unbounded queue (never drops)."""

    def __init__(
        self,
        bus: EventBus,
        event_types: tuple[type[Event], ...],
    ) -> None:
        self._bus = bus
        self._event_types = event_types
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._warned_high_water = False
        self._closed = False

    def deliver(self, event: Event) -> None:
        """Enqueue *event* when it matches this stream's filter."""
        if self._closed:
            return
        if self._event_types and not isinstance(event, self._event_types):
            return
        self._queue.put_nowait(event)
        if (
            not self._warned_high_water
            and self._queue.qsize() >= _STREAM_QUEUE_HIGH_WATER
        ):
            self._warned_high_water = True
            logger.warning(
                "EventBus stream backlog exceeded %d events; "
                "consumer is falling behind (events retained)",
                _STREAM_QUEUE_HIGH_WATER,
            )

    def close(self) -> None:
        """Unblock waiters and stop accepting events."""
        if self._closed:
            return
        self._closed = True
        self._queue.put_nowait(None)

    async def __aenter__(self) -> _EventStream:
        self._bus._streams.append(self)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self in self._bus._streams:
            self._bus._streams.remove(self)
        self.close()

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

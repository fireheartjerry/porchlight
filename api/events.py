"""A tiny fan-out bus so ``ctx.emit`` can feed the ``/api/events`` SSE stream.

Trace events are produced on whatever thread the graph happens to be running on (the API
hands work to a threadpool so the event loop stays free), and consumed by any number of
browser tabs. :class:`EventBus` bridges the two: publishers call :meth:`publish` from any
thread, subscribers get an ``asyncio.Queue`` fed on the loop thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

QUEUE_MAXSIZE = 500
"""Per-subscriber backlog. A slow browser drops its oldest events rather than the newest."""

HISTORY_MAXLEN = 500
"""How many recent events a newly connected client can replay."""


def normalize(event: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw emit into the trace event shape from ``docs/CONTRACTS.md`` §7."""
    ts = event.get("ts")
    if isinstance(ts, datetime):
        ts = ts.isoformat()
    return {
        "type": str(event.get("type") or "log"),
        "ts": ts or datetime.now(UTC).isoformat(),
        "request_id": event.get("request_id"),
        "agent": event.get("agent"),
        "summary": str(event.get("summary") or ""),
        "detail": event.get("detail") or {},
    }


class EventBus:
    """Thread-safe publish/subscribe over ``asyncio.Queue``s."""

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Create a bus bound to ``loop`` (the loop the API runs on)."""
        self._loop = loop
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_MAXLEN)
        self.published = 0

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attach the bus to the running event loop (called from the app lifespan)."""
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        """How many streams are currently connected."""
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: dict[str, Any]) -> None:
        """Fan one event out to every subscriber. Safe to call from any thread."""
        payload = normalize(event)
        with self._lock:
            self.history.append(payload)
            self.published += 1
            targets = list(self._subscribers)
        if not targets:
            return
        loop = self._loop
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        for queue in targets:
            if on_loop or loop is None:
                self._offer(queue, payload)
            else:
                try:
                    loop.call_soon_threadsafe(self._offer, queue, payload)
                except RuntimeError:  # pragma: no cover - loop already closed
                    logger.debug("event loop closed; dropping trace event")

    @staticmethod
    def _offer(queue: asyncio.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
        """Enqueue, dropping the oldest event when a subscriber has fallen behind."""
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(payload)
            except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover - racy edge
                logger.debug("dropping trace event for a saturated subscriber")

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[dict[str, Any]]]:
        """Yield a queue that receives every event published while the context is open."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        with self._lock:
            self._subscribers.add(queue)
        try:
            yield queue
        finally:
            with self._lock:
                self._subscribers.discard(queue)

    def recent(self, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` of the most recent events, oldest first."""
        if limit <= 0:
            return []
        with self._lock:
            items = list(self.history)
        return items[-limit:]

    def __repr__(self) -> str:
        return f"EventBus(subscribers={self.subscriber_count}, published={self.published})"


__all__ = ["EventBus", "normalize"]

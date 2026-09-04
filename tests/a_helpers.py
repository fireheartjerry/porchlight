"""Shared helpers for the Builder-A test modules (tools, channels, memory, MCP, simulator)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from strands.types.tools import ToolContext

from porchlight.channels.sim import SimChannel
from porchlight.clock import Clock, FrozenClock
from porchlight.config import Settings
from porchlight.context import AppContext
from porchlight.memory.sqlite_store import SqliteMemoryStore
from porchlight.models import AidRequest, Category, RequestStatus, Source, Urgency
from porchlight.store.base import Store

FROZEN_NOW = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)
"""Tuesday 8 September 2026, 14:00 UTC — matches ``tests/conftest.py``."""

THURSDAY_MORNING = datetime(2026, 9, 10, 13, 0, 0, tzinfo=UTC)
"""Thursday 09:00 America/Toronto, inside most fixture volunteers' morning windows."""


def tool_ctx(ctx: AppContext, *, agent: Any = "test", tool_name: str = "tool") -> ToolContext:
    """A ``ToolContext`` for calling a decorated tool directly, outside an agent."""
    return ToolContext(
        tool_use={"toolUseId": "test-1", "name": tool_name, "input": {}},
        agent=agent,
        invocation_state={"ctx": ctx, "agent": agent},
        cancel_signal=threading.Event(),
    )


def make_ctx(
    store: Store,
    clock: Clock | None = None,
    *,
    settings: Settings | None = None,
    with_memory: bool = True,
    reply_fn: Any = None,
    auto_reply: bool = True,
) -> AppContext:
    """An :class:`AppContext` wired to a :class:`SimChannel` and (optionally) SQLite memory.

    The returned context carries an ``emitted`` list of every trace event, for assertions.
    """
    clock = clock or FrozenClock(FROZEN_NOW)
    settings = settings or Settings(
        mode="demo", model_provider="mock", store="sqlite", sqlite_path=":memory:"
    )
    events: list[dict] = []
    ctx = AppContext(
        settings=settings,
        store=store,
        channel=SimChannel(store, clock, reply_fn, auto_reply=auto_reply),
        memory=SqliteMemoryStore(":memory:", clock=clock) if with_memory else None,
        clock=clock,
        emit=events.append,
    )
    ctx.emitted = events  # type: ignore[attr-defined]
    return ctx


def make_request(
    store: Store,
    clock: Clock,
    *,
    request_id: str = "req_test",
    category: Category = Category.RIDE,
    zone: str | None = "Maple St",
    summary: str = "Ride to dialysis and back",
    window_start: datetime | None = THURSDAY_MORNING,
    window_hours: int = 3,
    status: RequestStatus = RequestStatus.MATCHING,
    **overrides: Any,
) -> AidRequest:
    """Create and persist a request shaped like the ones intake produces."""
    now = clock.now()
    request = AidRequest(
        id=request_id,
        source=Source.SMS,
        raw_text=summary,
        requester_id="rqr_okafor",
        category=category,
        summary=summary,
        window_start=window_start,
        window_end=window_start + timedelta(hours=window_hours) if window_start else None,
        location_zone=zone,
        urgency=Urgency.NORMAL,
        status=status,
        created_at=now,
        updated_at=now,
        **overrides,
    )
    store.put_request(request)
    return request

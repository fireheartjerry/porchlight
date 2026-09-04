"""Persisted trace events, and the two ways the porch reads them back.

When the API runs on Lambda and the agents run on AgentCore Runtime, no ``ctx.emit`` call the
graph makes ever reaches the API process — the in-memory bus is empty and the live trace goes
dark. So every trace event is also written to the store, and the API can either poll
``/api/events/poll`` or tail the store into the same SSE stream.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.events import EventBus
from api.main import attach_bus, create_app, cursor_of, read_trace, tail_trace
from porchlight.channels.email import EmailChannel
from porchlight.channels.sim import SimChannel
from porchlight.clock import FrozenClock
from porchlight.config import Settings
from porchlight.context import AppContext, build_context, persisting_emit
from porchlight.store.sqlite_store import SqliteStore

FROZEN_NOW = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)
"""Tuesday 8 September 2026, 14:00 UTC — matches ``tests/conftest.py``."""


# --------------------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------------------


def test_trace_cursors_are_strictly_increasing(empty_store: SqliteStore) -> None:
    cursors = [empty_store.append_trace({"type": "log", "summary": str(index)}) for index in range(5)]
    assert cursors == sorted(cursors)
    assert len(set(cursors)) == 5


def test_list_trace_returns_events_after_a_cursor_oldest_first(empty_store: SqliteStore) -> None:
    for summary in ("one", "two", "three"):
        empty_store.append_trace({"type": "log", "summary": summary})

    everything = empty_store.list_trace(0)
    assert [event["summary"] for event in everything] == ["one", "two", "three"]
    assert [event["cursor"] for event in everything] == [1, 2, 3]

    assert [event["summary"] for event in empty_store.list_trace(everything[0]["cursor"])] == [
        "two",
        "three",
    ]
    assert empty_store.list_trace(everything[-1]["cursor"]) == []


def test_list_trace_filters_by_request_and_honours_the_limit(empty_store: SqliteStore) -> None:
    for index in range(4):
        empty_store.append_trace(
            {"type": "tool_call", "summary": f"e{index}", "request_id": "req_a" if index % 2 else "req_b"}
        )

    mine = empty_store.list_trace(0, request_id="req_a")
    assert [event["summary"] for event in mine] == ["e1", "e3"]
    assert len(empty_store.list_trace(0, limit=2)) == 2


def test_persisted_events_carry_a_ttl_friendly_expiry(empty_store: SqliteStore) -> None:
    empty_store.append_trace({"type": "log", "summary": "keep me for a week"})
    event = empty_store.list_trace(0)[0]
    ts = datetime.fromisoformat(event["ts"])
    assert ts.tzinfo is not None
    assert event["expires_at"] > ts.timestamp()


def test_the_trace_survives_a_second_process_opening_the_same_database(tmp_path) -> None:
    path = str(tmp_path / "shared.db")
    writer = SqliteStore(path)
    writer.append_trace({"type": "node_start", "summary": "intake", "request_id": "req_1"})
    writer.close()

    reader = SqliteStore(path)
    try:
        events = reader.list_trace(0)
        assert [event["summary"] for event in events] == ["intake"]
    finally:
        reader.close()


def test_reset_clears_the_trace(empty_store: SqliteStore) -> None:
    empty_store.append_trace({"type": "log", "summary": "before"})
    empty_store.reset()
    assert empty_store.list_trace(0) == []


# --------------------------------------------------------------------------------------
# The context
# --------------------------------------------------------------------------------------


def test_build_context_persists_every_trace_event(tmp_path) -> None:
    seen: list[dict] = []
    ctx = build_context(
        Settings(mode="demo", model_provider="mock", sqlite_path=str(tmp_path / "ctx.db")),
        emit=seen.append,
    )
    ctx.emit({"type": "tool_call", "summary": "asked Maria", "request_id": "req_9"})

    stored = ctx.store.list_trace(0)
    assert [event["summary"] for event in stored] == ["asked Maria"]
    assert seen == [{"type": "tool_call", "summary": "asked Maria", "request_id": "req_9"}]


def test_persistence_can_be_turned_off(tmp_path) -> None:
    ctx = build_context(
        Settings(mode="demo", model_provider="mock", sqlite_path=str(tmp_path / "off.db")),
        persist_trace=False,
    )
    ctx.emit({"type": "log", "summary": "not stored"})
    assert ctx.store.list_trace(0) == []


def test_a_failing_store_or_sink_never_breaks_a_run(empty_store: SqliteStore) -> None:
    class Broken:
        def append_trace(self, event: dict) -> int:
            raise RuntimeError("disk full")

    def boom(event: dict) -> None:
        raise RuntimeError("browser gone")

    persisting_emit(Broken(), boom)({"type": "log", "summary": "still fine"})
    persisting_emit(empty_store, boom)({"type": "log", "summary": "persisted anyway"})
    assert [event["summary"] for event in empty_store.list_trace(0)] == ["persisted anyway"]


# --------------------------------------------------------------------------------------
# Settings and the email channel
# --------------------------------------------------------------------------------------


def test_settings_carry_a_sender_address_and_an_events_source() -> None:
    defaults = Settings()
    assert defaults.from_addr == "porchlight@example.org"
    assert defaults.events_source == "memory"

    configured = Settings(from_addr="hello@maplestreet.org", events_source="store")
    assert configured.from_addr == "hello@maplestreet.org"
    assert configured.events_source == "store"


def test_settings_read_both_fields_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("PORCHLIGHT_FROM_ADDR", "porch@maplestreet.org")
    monkeypatch.setenv("PORCHLIGHT_EVENTS_SOURCE", "store")
    settings = Settings()
    assert settings.from_addr == "porch@maplestreet.org"
    assert settings.events_source == "store"


def test_the_live_channel_sends_from_the_configured_address(empty_store: SqliteStore) -> None:
    from porchlight.channels import make_channel

    live = make_channel(
        Settings(mode="live", from_addr="hello@maplestreet.org"), empty_store, FrozenClock(FROZEN_NOW)
    )
    assert isinstance(live, EmailChannel)
    assert live.from_addr == "hello@maplestreet.org"

    demo = make_channel(Settings(mode="demo"), empty_store, FrozenClock(FROZEN_NOW))
    assert isinstance(demo, SimChannel)


# --------------------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------------------


def _client(store: SqliteStore) -> TestClient:
    """A test client over a context wired to ``store``, with a no-op orchestrator."""
    settings = Settings(mode="demo", model_provider="mock", sqlite_path=":memory:")
    clock = FrozenClock(FROZEN_NOW)

    def factory() -> AppContext:
        return AppContext(
            settings=settings,
            store=store,
            channel=SimChannel(store, clock),
            memory=None,
            clock=clock,
            emit=lambda event: store.append_trace(event),
        )

    return TestClient(create_app(context_factory=factory, orchestrator_factory=lambda ctx: object()))


def test_poll_returns_persisted_events_and_a_cursor_to_resume_from(store: SqliteStore) -> None:
    with _client(store) as client:
        assert client.get("/api/events/poll").json() == {"events": [], "cursor": 0}

        store.append_trace({"type": "node_start", "summary": "intake", "request_id": "req_1"})
        store.append_trace({"type": "tool_call", "summary": "asked Maria", "request_id": "req_1"})

        page = client.get("/api/events/poll").json()
        assert [event["summary"] for event in page["events"]] == ["intake", "asked Maria"]
        assert page["cursor"] == page["events"][-1]["cursor"]

        assert client.get("/api/events/poll", params={"since": page["cursor"]}).json() == {
            "events": [],
            "cursor": page["cursor"],
        }

        store.append_trace({"type": "log", "summary": "later"})
        page2 = client.get("/api/events/poll", params={"since": page["cursor"]}).json()
        assert [event["summary"] for event in page2["events"]] == ["later"]


def test_poll_filters_by_request_and_limit(store: SqliteStore) -> None:
    with _client(store) as client:
        store.append_trace({"type": "log", "summary": "mine", "request_id": "req_a"})
        store.append_trace({"type": "log", "summary": "theirs", "request_id": "req_b"})

        scoped = client.get("/api/events/poll", params={"request_id": "req_a"}).json()
        assert [event["summary"] for event in scoped["events"]] == ["mine"]
        assert len(client.get("/api/events/poll", params={"limit": 1}).json()["events"]) == 1


def test_poll_rejects_a_negative_cursor(store: SqliteStore) -> None:
    with _client(store) as client:
        assert client.get("/api/events/poll", params={"since": -1}).status_code == 422


def test_read_trace_swallows_a_broken_store() -> None:
    class Broken:
        def list_trace(self, *args, **kwargs):
            raise RuntimeError("no table")

    ctx = AppContext(
        settings=Settings(),
        store=Broken(),
        channel=None,
        memory=None,
        clock=FrozenClock(FROZEN_NOW),
    )
    assert read_trace(ctx, 0, 10) == []
    assert cursor_of([], 7) == 7
    assert cursor_of([{"cursor": 3}, {"cursor": 9}], 0) == 9


def test_sse_replays_the_in_process_bus(store: SqliteStore) -> None:
    with _client(store) as client:
        response = client.get("/api/events", params={"limit": 1})
        assert response.status_code == 200
        assert "Trace connected" in response.text


@pytest.mark.parametrize("direct", [True, False])
def test_attach_bus_can_stop_publishing_directly(direct: bool, empty_store: SqliteStore) -> None:
    bus = EventBus()
    ctx = AppContext(
        settings=Settings(),
        store=empty_store,
        channel=None,
        memory=None,
        clock=FrozenClock(FROZEN_NOW),
        emit=lambda event: empty_store.append_trace(event),
    )
    attach_bus(ctx, bus, direct=direct)
    ctx.emit({"type": "log", "summary": "hello"})

    assert bus.published == (1 if direct else 0)
    assert len(empty_store.list_trace(0)) == 1, "the wrapped sink always still runs"


def test_the_tailer_turns_persisted_events_into_bus_events(store: SqliteStore) -> None:
    """The split-deployment path: nothing emits in this process, yet the stream still moves."""

    async def scenario() -> list[dict]:
        client_app = create_app()
        client_app.state.bus = EventBus()
        client_app.state.bus.bind(asyncio.get_running_loop())
        client_app.state.ctx = AppContext(
            settings=Settings(events_source="store"),
            store=store,
            channel=None,
            memory=None,
            clock=FrozenClock(FROZEN_NOW),
        )
        store.append_trace({"type": "log", "summary": "backlog, before anyone was watching"})

        task = asyncio.create_task(tail_trace(client_app, interval=0.01))
        await asyncio.sleep(0.05)
        store.append_trace({"type": "tool_call", "summary": "asked Maria", "request_id": "req_1"})
        await asyncio.sleep(0.1)
        task.cancel()
        return list(client_app.state.bus.history)

    published = asyncio.run(scenario())
    summaries = [event["summary"] for event in published]
    assert "asked Maria" in summaries
    assert "backlog, before anyone was watching" not in summaries


def test_the_store_backed_stream_reaches_a_subscriber(store: SqliteStore) -> None:
    """End to end: an event written to the store arrives on an SSE subscriber's queue."""

    async def scenario() -> list[dict]:
        app = create_app()
        app.state.bus = EventBus()
        app.state.bus.bind(asyncio.get_running_loop())
        app.state.ctx = AppContext(
            settings=Settings(events_source="store"),
            store=store,
            channel=None,
            memory=None,
            clock=FrozenClock(FROZEN_NOW),
        )
        task = asyncio.create_task(tail_trace(app, interval=0.01))
        received: list[dict] = []
        with app.state.bus.subscribe() as queue:
            await asyncio.sleep(0.05)
            store.append_trace({"type": "decision", "summary": "Nobody free", "request_id": "req_z"})
            received.append(await asyncio.wait_for(queue.get(), timeout=2.0))
        task.cancel()
        return received

    received = asyncio.run(scenario())
    assert [event["summary"] for event in received] == ["Nobody free"]
    assert json.loads(json.dumps(received[0]))["type"] == "decision"

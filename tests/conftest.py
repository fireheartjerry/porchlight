"""Shared pytest fixtures: mock model provider, in-memory store, frozen clock."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from porchlight.clock import FrozenClock
from porchlight.config import Settings, reset_settings
from porchlight.context import AppContext, NullChannel
from porchlight.sim.fixtures import seed_store
from porchlight.store.sqlite_store import SqliteStore

FROZEN_NOW = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)
"""Tuesday 8 September 2026, 14:00 UTC — the instant every test runs at."""


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Keep the cached settings from leaking between tests."""
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def settings() -> Settings:
    """Demo settings: mock model provider, in-memory SQLite."""
    return Settings(
        mode="demo",
        model_provider="mock",
        store="sqlite",
        sqlite_path=":memory:",
        session_dir="data/sessions",
    )


@pytest.fixture
def clock() -> FrozenClock:
    """A clock frozen at :data:`FROZEN_NOW`."""
    return FrozenClock(FROZEN_NOW)


@pytest.fixture
def empty_store() -> Iterator[SqliteStore]:
    """An in-memory store with schema but no rows."""
    store = SqliteStore(":memory:")
    yield store
    store.close()


@pytest.fixture
def store(clock: FrozenClock) -> Iterator[SqliteStore]:
    """An in-memory store seeded with the Maple Street fixtures."""
    seeded = SqliteStore(":memory:")
    seed_store(seeded, clock)
    yield seeded
    seeded.close()


@pytest.fixture
def channel() -> NullChannel:
    """A channel that only records what would have been sent."""
    return NullChannel()


@pytest.fixture
def ctx(settings: Settings, store: SqliteStore, clock: FrozenClock, channel: NullChannel) -> AppContext:
    """An :class:`AppContext` wired to the seeded in-memory store and frozen clock."""
    events: list[dict] = []
    context = AppContext(
        settings=settings,
        store=store,
        channel=channel,
        memory=None,
        clock=clock,
        emit=events.append,
    )
    context.emitted = events  # type: ignore[attr-defined]
    return context

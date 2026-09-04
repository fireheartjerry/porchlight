"""Time source abstraction so the whole system is testable with a frozen clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Something that can tell the current timezone-aware UTC time."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    """Wall-clock time, always timezone-aware UTC."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)

    def __repr__(self) -> str:
        return "SystemClock()"


class FrozenClock:
    """A clock stopped at a fixed instant; move it forward with :meth:`advance`."""

    def __init__(self, now: datetime) -> None:
        """Create a clock frozen at ``now`` (naive datetimes are assumed to be UTC)."""
        self._now = now if now.tzinfo else now.replace(tzinfo=UTC)

    def now(self) -> datetime:
        """Return the frozen time."""
        return self._now

    def advance(self, delta: timedelta | None = None, **kwargs: float) -> datetime:
        """Move the clock forward.

        Args:
            delta: Explicit offset. When omitted, ``kwargs`` are passed to ``timedelta``
                (e.g. ``advance(hours=2)``).
            **kwargs: ``timedelta`` keyword arguments.

        Returns:
            The new current time.
        """
        self._now = self._now + (delta if delta is not None else timedelta(**kwargs))
        return self._now

    def set(self, now: datetime) -> datetime:
        """Jump the clock to ``now`` and return it."""
        self._now = now if now.tzinfo else now.replace(tzinfo=UTC)
        return self._now

    def __repr__(self) -> str:
        return f"FrozenClock({self._now.isoformat()})"

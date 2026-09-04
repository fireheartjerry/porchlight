"""The storage contract every backend implements."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from ..models import (
    AidRequest,
    Attempt,
    Decision,
    DecisionStatus,
    GroupSettings,
    LogEvent,
    MessageStatus,
    OutboundMessage,
    Requester,
    RequestStatus,
    Volunteer,
    jsonable,
)

TRACE_TTL_DAYS = 7
"""How long persisted trace events are kept; written as an epoch-second ``expires_at``."""


class StaleVersionError(RuntimeError):
    """Raised when an optimistic-concurrency write lost the race.

    The caller holds a stale copy of the row: reload it and try again. Both
    :class:`~porchlight.store.sqlite_store.SqliteStore` and
    :class:`~porchlight.store.dynamo_store.DynamoStore` raise this and nothing else when a
    conditional write is rejected, so retry logic is backend-agnostic.
    """

    def __init__(self, request_id: str, expected: int | None = None, actual: int | None = None) -> None:
        """Record which row lost, and the versions involved."""
        super().__init__(
            f"request {request_id} changed underneath this write"
            + (f" (expected version {expected}, found {actual})" if expected is not None else "")
        )
        self.request_id = request_id
        self.expected = expected
        self.actual = actual


@runtime_checkable
class Store(Protocol):
    """Persistence for every Porchlight entity.

    Implementations are expected to be safe to share across threads. List methods return
    newest-first unless documented otherwise.
    """

    # --- volunteers ---------------------------------------------------------
    def put_volunteer(self, v: Volunteer) -> Volunteer:
        """Insert or replace a volunteer and return it."""
        ...

    def get_volunteer(self, id: str) -> Volunteer | None:
        """Return the volunteer with this id, or ``None``."""
        ...

    def list_volunteers(
        self, zone: str | None = None, skill: str | None = None, vetted: bool | None = None
    ) -> list[Volunteer]:
        """List volunteers, optionally filtered by zone, skill, and vetted flag."""
        ...

    # --- requesters ---------------------------------------------------------
    def put_requester(self, r: Requester) -> Requester:
        """Insert or replace a requester and return it."""
        ...

    def get_requester(self, id: str) -> Requester | None:
        """Return the requester with this id, or ``None``."""
        ...

    def find_requester_by_contact(self, contact: str) -> Requester | None:
        """Return the requester whose contact matches (case-insensitive), or ``None``."""
        ...

    def list_requesters(self) -> list[Requester]:
        """List every requester, newest first."""
        ...

    # --- requests -----------------------------------------------------------
    def put_request(self, req: AidRequest) -> AidRequest:
        """Insert or replace an aid request and return it."""
        ...

    def get_request(self, id: str) -> AidRequest | None:
        """Return the aid request with this id, or ``None``."""
        ...

    def list_requests(self, status: RequestStatus | None = None, limit: int = 200) -> list[AidRequest]:
        """List aid requests, newest first, optionally filtered by status."""
        ...

    def requests_for_volunteer(self, volunteer_id: str, since: datetime) -> list[AidRequest]:
        """Requests created since ``since`` that this volunteer was asked about or assigned."""
        ...

    def update_request_fields(
        self, request_id: str, *, expected_version: int | None = None, **fields: Any
    ) -> AidRequest | None:
        """Atomically write a few fields of one request, leaving every other field alone.

        This is the write every tool should use. ``put_request`` replaces the whole row, so two
        threads that each read-modify-write lose one another's changes; this one touches only the
        named fields and bumps :attr:`~porchlight.models.AidRequest.version`.

        Args:
            request_id: The request to update.
            expected_version: When given, the write only lands if the stored version still
                matches; otherwise the current version is used (last writer wins per field).
            **fields: ``AidRequest`` field names and their new values. Values are validated
                against the model, so an invalid status raises rather than corrupting the row.

        Returns:
            The updated request, or ``None`` when there is no such request.

        Raises:
            StaleVersionError: When ``expected_version`` no longer matches the stored row.
            ValueError: When a field name is unknown or a value fails validation.
        """
        ...

    def append_attempt(self, request_id: str, attempt: Attempt) -> AidRequest | None:
        """Atomically append one outreach attempt without rewriting any other field.

        Args:
            request_id: The request the attempt belongs to.
            attempt: The attempt to append.

        Returns:
            The updated request, or ``None`` when there is no such request.
        """
        ...

    def resolve_attempt(self, request_id: str, attempt: Attempt) -> AidRequest | None:
        """Settle this volunteer's open attempt, or append ``attempt`` when there is none.

        The outreach flow asks a volunteer (a ``pending`` attempt), then records what they said.
        This settles the open attempt in place rather than appending a second row for the same
        ask, and is atomic in the same way as :meth:`append_attempt`.

        Args:
            request_id: The request the attempt belongs to.
            attempt: The settled attempt — its ``volunteer_id`` selects the open attempt, and its
                ``outcome`` and ``note`` are what get written.

        Returns:
            The updated request, or ``None`` when there is no such request.
        """
        ...

    # --- decisions ----------------------------------------------------------
    def put_decision(self, d: Decision) -> Decision:
        """Insert or replace a decision card and return it."""
        ...

    def get_decision(self, id: str) -> Decision | None:
        """Return the decision card with this id, or ``None``."""
        ...

    def list_decisions(self, status: DecisionStatus | None = None) -> list[Decision]:
        """List decision cards, newest first, optionally filtered by status."""
        ...

    # --- messages -----------------------------------------------------------
    def put_message(self, m: OutboundMessage) -> OutboundMessage:
        """Insert or replace an outbound message and return it."""
        ...

    def list_messages(
        self,
        request_id: str | None = None,
        status: MessageStatus | None = None,
        due_before: datetime | None = None,
    ) -> list[OutboundMessage]:
        """List outbound messages, newest first; ``due_before`` filters on ``scheduled_for``."""
        ...

    # --- log ----------------------------------------------------------------
    def append_log(self, e: LogEvent) -> LogEvent:
        """Append a quiet-log event and return it."""
        ...

    def list_log(
        self, request_id: str | None = None, limit: int = 200, since: datetime | None = None
    ) -> list[LogEvent]:
        """List quiet-log events, newest first."""
        ...

    # --- trace --------------------------------------------------------------
    def append_trace(self, event: dict[str, Any]) -> int:
        """Persist one trace event and return its cursor.

        Cursors are strictly increasing integers within a store, so a poller can ask for
        "everything after N" without timestamps or de-duplication. The event is stored as given
        plus a ``ts`` (ISO-8601 UTC) and an ``expires_at`` epoch-second field, which is what a
        DynamoDB TTL attribute needs.

        Args:
            event: A trace event dict (``docs/CONTRACTS.md`` §7).

        Returns:
            The cursor assigned to this event.
        """
        ...

    def list_trace(
        self, since_cursor: int = 0, limit: int = 500, request_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Read trace events after ``since_cursor``, oldest first.

        Args:
            since_cursor: Return only events with a cursor strictly greater than this.
            limit: Maximum number of events.
            request_id: Only events for this request.

        Returns:
            Trace event dicts, each carrying its ``cursor``, oldest first.
        """
        ...

    # --- settings -----------------------------------------------------------
    def get_group_settings(self) -> GroupSettings:
        """Return the stored group settings, or defaults when none were saved."""
        ...

    def put_group_settings(self, gs: GroupSettings) -> GroupSettings:
        """Persist the group settings and return them."""
        ...

    # --- util ---------------------------------------------------------------
    def reset(self) -> None:
        """Wipe every table (tests and demo reseeding)."""
        ...

    def stats(self, day: date) -> dict[str, Any]:
        """Counters for one UTC day.

        Returns:
            ``{"handled_autonomously": int, "decisions_open": int, "decisions_resolved": int,
            "requests_by_status": dict[str, int]}``.
        """
        ...


IMMUTABLE_REQUEST_FIELDS: frozenset[str] = frozenset({"id", "version"})
"""Fields no field-level update may set: identity, and the concurrency counter itself."""


def apply_fields(request: AidRequest, fields: Mapping[str, Any]) -> AidRequest:
    """Return a validated copy of ``request`` with ``fields`` applied.

    Shared by both store backends so a bad field name or value fails the same way everywhere.

    Args:
        request: The request as it currently stands.
        fields: ``AidRequest`` field names mapped to new values.

    Returns:
        A new :class:`~porchlight.models.AidRequest` with the fields applied.

    Raises:
        ValueError: When a field is unknown, immutable, or fails model validation.
    """
    unknown = [key for key in fields if key not in AidRequest.model_fields]
    if unknown:
        raise ValueError(f"unknown request field(s) {sorted(unknown)}")
    frozen = [key for key in fields if key in IMMUTABLE_REQUEST_FIELDS]
    if frozen:
        raise ValueError(f"field(s) {sorted(frozen)} cannot be updated")
    payload = request.model_dump(mode="json")
    payload.update({key: jsonable(value) for key, value in fields.items()})
    return AidRequest.model_validate(payload)


def trace_row(event: Mapping[str, Any], now: datetime, ttl_days: int = TRACE_TTL_DAYS) -> dict[str, Any]:
    """Normalize one trace event for storage, stamping a ``ts`` and a TTL-friendly expiry.

    Args:
        event: The raw trace event.
        now: Current time, used when the event carries no ``ts``.
        ttl_days: How long the event should be kept.

    Returns:
        A JSON-safe dict with ``ts`` (ISO-8601 UTC) and ``expires_at`` (epoch seconds) set.
    """
    row = {key: jsonable(value) for key, value in dict(event).items()}
    ts = row.get("ts")
    if not isinstance(ts, str) or not ts:
        row["ts"] = now.astimezone(UTC).isoformat()
    row["expires_at"] = int((now + timedelta(days=ttl_days)).timestamp())
    row.pop("cursor", None)
    return row

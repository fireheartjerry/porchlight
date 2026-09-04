"""The storage contract every backend implements."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from ..models import (
    AidRequest,
    Decision,
    DecisionStatus,
    GroupSettings,
    LogEvent,
    MessageStatus,
    OutboundMessage,
    Requester,
    RequestStatus,
    Volunteer,
)


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

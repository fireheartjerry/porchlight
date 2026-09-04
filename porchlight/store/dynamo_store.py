"""DynamoDB-backed :class:`~porchlight.store.base.Store` (single-table design, used on AWS).

Table layout::

    pk      = "<ENTITY>#<id>"        e.g. "REQUEST#req_9f3a1c04bd"
    sk      = "<ENTITY>"             e.g. "REQUEST"
    gsi1pk  = "<ENTITY>"             partition for "all requests"
    gsi1sk  = "<status>#<created_at>"  sorts by status then time
    body    = JSON string of the Pydantic model

The GSI is named ``GSI1``. Boto3 is imported and the resource created lazily, so importing this
module never touches AWS.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, TypeVar

from pydantic import BaseModel

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

M = TypeVar("M", bound=BaseModel)

GSI1 = "GSI1"

VOLUNTEER = "VOLUNTEER"
REQUESTER = "REQUESTER"
REQUEST = "REQUEST"
DECISION = "DECISION"
MESSAGE = "MESSAGE"
LOG = "LOG"
SETTINGS = "SETTINGS"

_ENTITIES = (VOLUNTEER, REQUESTER, REQUEST, DECISION, MESSAGE, LOG, SETTINGS)


def _iso(value: datetime | None) -> str:
    """Normalize a datetime to a sortable UTC ISO string (empty string for ``None``)."""
    if value is None:
        return ""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


class DynamoStore:
    """Single-table DynamoDB store with the same API as :class:`SqliteStore`.

    Args:
        table: DynamoDB table name.
        region: AWS region; falls back to the boto3 default chain when ``None``.
    """

    def __init__(self, table: str = "porchlight", region: str | None = None) -> None:
        self.table_name = table
        self.region = region
        self._lock = threading.RLock()
        self._table: Any | None = None

    # --- plumbing -----------------------------------------------------------

    @property
    def table(self) -> Any:
        """Lazily created ``boto3`` Table resource."""
        with self._lock:
            if self._table is None:
                import boto3

                resource = boto3.resource("dynamodb", region_name=self.region)
                self._table = resource.Table(self.table_name)
            return self._table

    @staticmethod
    def _key(entity: str, id: str) -> dict[str, str]:
        return {"pk": f"{entity}#{id}", "sk": entity}

    def _put(self, entity: str, id: str, model: BaseModel, status: str, created_at: datetime | None) -> None:
        item: dict[str, Any] = {
            **self._key(entity, id),
            "gsi1pk": entity,
            "gsi1sk": f"{status}#{_iso(created_at)}#{id}",
            "entity": entity,
            "id": id,
            "status": status,
            "created_at": _iso(created_at),
            "body": model.model_dump_json(),
        }
        self.table.put_item(Item=item)

    def _get(self, model: type[M], entity: str, id: str) -> M | None:
        response = self.table.get_item(Key=self._key(entity, id))
        item = response.get("Item")
        return model.model_validate_json(item["body"]) if item else None

    def _query(
        self, model: type[M], entity: str, status: str | None = None, limit: int | None = None
    ) -> list[M]:
        """Query GSI1 for one entity, newest first, optionally narrowed to one status."""
        from boto3.dynamodb.conditions import Key

        condition = Key("gsi1pk").eq(entity)
        if status is not None:
            condition = condition & Key("gsi1sk").begins_with(f"{status}#")

        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "IndexName": GSI1,
            "KeyConditionExpression": condition,
            "ScanIndexForward": False,
        }
        while True:
            response = self.table.query(**kwargs)
            items.extend(response.get("Items", []))
            token = response.get("LastEvaluatedKey")
            if not token or (limit is not None and len(items) >= limit):
                break
            kwargs["ExclusiveStartKey"] = token

        loaded = [model.model_validate_json(item["body"]) for item in items]
        loaded.sort(key=lambda m: _iso(_created_at(m)), reverse=True)
        return loaded[:limit] if limit is not None else loaded

    def _delete_entity(self, entity: str) -> None:
        from boto3.dynamodb.conditions import Key

        kwargs: dict[str, Any] = {"IndexName": GSI1, "KeyConditionExpression": Key("gsi1pk").eq(entity)}
        keys: list[dict[str, str]] = []
        while True:
            response = self.table.query(**kwargs)
            keys.extend({"pk": item["pk"], "sk": item["sk"]} for item in response.get("Items", []))
            token = response.get("LastEvaluatedKey")
            if not token:
                break
            kwargs["ExclusiveStartKey"] = token
        with self.table.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key=key)

    # --- volunteers ---------------------------------------------------------

    def put_volunteer(self, v: Volunteer) -> Volunteer:
        """Insert or replace a volunteer and return it."""
        self._put(VOLUNTEER, v.id, v, "vetted" if v.vetted else "unvetted", v.created_at)
        return v

    def get_volunteer(self, id: str) -> Volunteer | None:
        """Return the volunteer with this id, or ``None``."""
        return self._get(Volunteer, VOLUNTEER, id)

    def list_volunteers(
        self, zone: str | None = None, skill: str | None = None, vetted: bool | None = None
    ) -> list[Volunteer]:
        """List volunteers, optionally filtered by zone, skill, and vetted flag."""
        status = None if vetted is None else ("vetted" if vetted else "unvetted")
        volunteers = self._query(Volunteer, VOLUNTEER, status)
        volunteers.sort(key=lambda v: _iso(v.created_at))
        if zone is not None:
            volunteers = [v for v in volunteers if zone in v.zones]
        if skill is not None:
            needle = skill.lower()
            volunteers = [v for v in volunteers if any(s.lower().startswith(needle) for s in v.skills)]
        return volunteers

    # --- requesters ---------------------------------------------------------

    def put_requester(self, r: Requester) -> Requester:
        """Insert or replace a requester and return it."""
        self._put(REQUESTER, r.id, r, r.contact.lower(), r.first_seen)
        return r

    def get_requester(self, id: str) -> Requester | None:
        """Return the requester with this id, or ``None``."""
        return self._get(Requester, REQUESTER, id)

    def find_requester_by_contact(self, contact: str) -> Requester | None:
        """Return the requester whose contact matches (case-insensitive), or ``None``."""
        matches = self._query(Requester, REQUESTER, contact.lower())
        return matches[0] if matches else None

    def list_requesters(self) -> list[Requester]:
        """List every requester, newest first."""
        return self._query(Requester, REQUESTER)

    # --- requests -----------------------------------------------------------

    def put_request(self, req: AidRequest) -> AidRequest:
        """Insert or replace an aid request and return it."""
        self._put(REQUEST, req.id, req, str(req.status), req.created_at)
        return req

    def get_request(self, id: str) -> AidRequest | None:
        """Return the aid request with this id, or ``None``."""
        return self._get(AidRequest, REQUEST, id)

    def list_requests(self, status: RequestStatus | None = None, limit: int = 200) -> list[AidRequest]:
        """List aid requests, newest first, optionally filtered by status."""
        return self._query(AidRequest, REQUEST, None if status is None else str(status), limit=limit)

    def requests_for_volunteer(self, volunteer_id: str, since: datetime) -> list[AidRequest]:
        """Requests created since ``since`` that this volunteer was asked about or assigned."""
        cutoff = _iso(since)
        return [
            req
            for req in self._query(AidRequest, REQUEST)
            if _iso(req.created_at) >= cutoff
            and (req.assigned_volunteer_id == volunteer_id or volunteer_id in req.attempted_volunteer_ids())
        ]

    # --- decisions ----------------------------------------------------------

    def put_decision(self, d: Decision) -> Decision:
        """Insert or replace a decision card and return it."""
        self._put(DECISION, d.id, d, str(d.status), d.created_at)
        return d

    def get_decision(self, id: str) -> Decision | None:
        """Return the decision card with this id, or ``None``."""
        return self._get(Decision, DECISION, id)

    def list_decisions(self, status: DecisionStatus | None = None) -> list[Decision]:
        """List decision cards, newest first, optionally filtered by status."""
        return self._query(Decision, DECISION, None if status is None else str(status))

    # --- messages -----------------------------------------------------------

    def put_message(self, m: OutboundMessage) -> OutboundMessage:
        """Insert or replace an outbound message and return it."""
        self._put(MESSAGE, m.id, m, str(m.status), m.created_at)
        return m

    def list_messages(
        self,
        request_id: str | None = None,
        status: MessageStatus | None = None,
        due_before: datetime | None = None,
    ) -> list[OutboundMessage]:
        """List outbound messages, newest first; ``due_before`` filters on ``scheduled_for``."""
        messages = self._query(OutboundMessage, MESSAGE)
        if request_id is not None:
            messages = [m for m in messages if m.request_id == request_id]
        if status is not None:
            messages = [m for m in messages if m.status == status]
        if due_before is not None:
            cutoff = _iso(due_before)
            messages = [
                m for m in messages if m.scheduled_for is not None and _iso(m.scheduled_for) <= cutoff
            ]
        return messages

    # --- log ----------------------------------------------------------------

    def append_log(self, e: LogEvent) -> LogEvent:
        """Append a quiet-log event and return it."""
        self._put(LOG, e.id, e, str(e.kind), e.ts)
        return e

    def list_log(
        self, request_id: str | None = None, limit: int = 200, since: datetime | None = None
    ) -> list[LogEvent]:
        """List quiet-log events, newest first."""
        events = self._query(LogEvent, LOG)
        events.sort(key=lambda e: _iso(e.ts), reverse=True)
        if request_id is not None:
            events = [e for e in events if e.request_id == request_id]
        if since is not None:
            cutoff = _iso(since)
            events = [e for e in events if _iso(e.ts) >= cutoff]
        return events[:limit]

    # --- settings -----------------------------------------------------------

    def get_group_settings(self) -> GroupSettings:
        """Return the stored group settings, or defaults when none were saved."""
        stored = self._get(GroupSettings, SETTINGS, "singleton")
        return stored or GroupSettings()

    def put_group_settings(self, gs: GroupSettings) -> GroupSettings:
        """Persist the group settings and return them."""
        self._put(SETTINGS, "singleton", gs, "singleton", None)
        return gs

    # --- util ---------------------------------------------------------------

    def reset(self) -> None:
        """Delete every Porchlight item in the table (demo reseeding only)."""
        for entity in _ENTITIES:
            self._delete_entity(entity)

    def stats(self, day: date) -> dict[str, Any]:
        """Counters for the UTC day ``day`` (see :meth:`SqliteStore.stats`)."""
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)
        touched = [req for req in self._query(AidRequest, REQUEST) if start <= _aware(req.updated_at) < end]

        requests_by_status: dict[str, int] = {}
        for req in touched:
            key = str(req.status)
            requests_by_status[key] = requests_by_status.get(key, 0) + 1

        decisions = self._query(Decision, DECISION)
        flagged = {d.request_id for d in decisions if d.request_id}
        settled = {RequestStatus.CONFIRMED, RequestStatus.IN_PROGRESS, RequestStatus.COMPLETED}

        return {
            "handled_autonomously": sum(
                1 for req in touched if req.status in settled and req.id not in flagged
            ),
            "decisions_open": sum(1 for d in decisions if d.status == DecisionStatus.OPEN),
            "decisions_resolved": sum(
                1
                for d in decisions
                if d.status == DecisionStatus.RESOLVED
                and d.resolved_at is not None
                and start <= _aware(d.resolved_at) < end
            ),
            "requests_by_status": requests_by_status,
        }

    def __repr__(self) -> str:
        return f"DynamoStore(table={self.table_name!r}, region={self.region!r})"


def _aware(value: datetime) -> datetime:
    """Return ``value`` as a UTC-aware datetime."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _created_at(model: BaseModel) -> datetime | None:
    """Best-effort creation timestamp used to sort query results newest-first."""
    for attr in ("created_at", "ts", "first_seen"):
        value = getattr(model, attr, None)
        if isinstance(value, datetime):
            return value
    return None

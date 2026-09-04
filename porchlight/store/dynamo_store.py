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

import json
import threading
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, TypeVar

from pydantic import BaseModel

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
)
from .base import StaleVersionError, apply_fields, trace_row

M = TypeVar("M", bound=BaseModel)

GSI1 = "GSI1"

TRACE_COUNTER_ID = "counter"
"""Id of the single item holding the monotonic trace cursor."""

CURSOR_WIDTH = 20
"""Zero-padding for trace cursors, so the GSI sort key orders them numerically."""

MAX_CONDITIONAL_RETRIES = 5
"""How many times an unconditional field update re-reads and retries after losing a race."""

VOLUNTEER = "VOLUNTEER"
REQUESTER = "REQUESTER"
REQUEST = "REQUEST"
DECISION = "DECISION"
MESSAGE = "MESSAGE"
LOG = "LOG"
TRACE = "TRACE"
SETTINGS = "SETTINGS"

_ENTITIES = (VOLUNTEER, REQUESTER, REQUEST, DECISION, MESSAGE, LOG, TRACE, SETTINGS)


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

    def _items(
        self, entity: str, status: str | None = None, limit: int | None = None, ascending: bool = False
    ) -> list[dict[str, Any]]:
        """Query GSI1 for one entity and return the raw items."""
        from boto3.dynamodb.conditions import Key

        condition = Key("gsi1pk").eq(entity)
        if status is not None:
            condition = condition & Key("gsi1sk").begins_with(f"{status}#")

        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "IndexName": GSI1,
            "KeyConditionExpression": condition,
            "ScanIndexForward": ascending,
        }
        while True:
            response = self.table.query(**kwargs)
            items.extend(response.get("Items", []))
            token = response.get("LastEvaluatedKey")
            if not token or (limit is not None and len(items) >= limit):
                break
            kwargs["ExclusiveStartKey"] = token
        return items

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
        """Insert or replace an aid request and return it.

        Requests carry two attributes the other entities do not: a numeric ``version`` for
        optimistic concurrency, and ``attempts`` as a real DynamoDB list of JSON strings so
        :meth:`append_attempt` can use ``list_append`` instead of rewriting the row.
        """
        self.table.put_item(Item=_request_item(req))
        return req

    def get_request(self, id: str) -> AidRequest | None:
        """Return the aid request with this id, or ``None``."""
        response = self.table.get_item(Key=self._key(REQUEST, id))
        item = response.get("Item")
        return _hydrate_request(item) if item else None

    def list_requests(self, status: RequestStatus | None = None, limit: int = 200) -> list[AidRequest]:
        """List aid requests, newest first, optionally filtered by status."""
        items = self._items(REQUEST, None if status is None else str(status), limit=limit)
        requests = [_hydrate_request(item) for item in items]
        requests.sort(key=lambda r: _iso(r.created_at), reverse=True)
        return requests[:limit]

    def requests_for_volunteer(self, volunteer_id: str, since: datetime) -> list[AidRequest]:
        """Requests created since ``since`` that this volunteer was asked about or assigned."""
        cutoff = _iso(since)
        return [
            req
            for req in self.list_requests(limit=10_000)
            if _iso(req.created_at) >= cutoff
            and (req.assigned_volunteer_id == volunteer_id or volunteer_id in req.attempted_volunteer_ids())
        ]

    def update_request_fields(
        self, request_id: str, *, expected_version: int | None = None, **fields: Any
    ) -> AidRequest | None:
        """Atomically write a few fields of one request (see :class:`.base.Store`).

        The body is rewritten but the write is guarded by ``ConditionExpression version = :expected``,
        so a concurrent writer never silently loses its change: either the condition holds, or the
        row is re-read and the update replayed on top of the newer version.
        """
        for _ in range(MAX_CONDITIONAL_RETRIES):
            current = self.get_request(request_id)
            if current is None:
                return None
            expected = current.version if expected_version is None else expected_version
            if expected_version is not None and current.version != expected_version:
                raise StaleVersionError(request_id, expected_version, current.version)
            updated = apply_fields(current, fields)
            updated.version = expected + 1
            names = {"#status": "status", "#version": "version"}
            sets = ["body = :body", "#status = :status", "gsi1sk = :gsi1sk", "#version = :next"]
            values: dict[str, Any] = {
                ":body": updated.model_dump_json(),
                ":status": str(updated.status),
                ":gsi1sk": _sort_key(updated),
                ":next": updated.version,
                ":expected": expected,
            }
            if "attempts" in fields:
                names["#attempts"] = "attempts"
                sets.append("#attempts = :attempts")
                values[":attempts"] = _encode_attempts(updated.attempts)
            try:
                self.table.update_item(
                    Key=self._key(REQUEST, request_id),
                    UpdateExpression="SET " + ", ".join(sets),
                    ConditionExpression="#version = :expected",
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                )
            except Exception as exc:
                if not _is_conditional_failure(exc):
                    raise
                if expected_version is not None:
                    raise StaleVersionError(request_id, expected_version) from exc
                continue
            return updated
        raise StaleVersionError(request_id)  # pragma: no cover - five lost races in a row

    def append_attempt(self, request_id: str, attempt: Attempt) -> AidRequest | None:
        """Atomically append one outreach attempt (see :class:`.base.Store`).

        This is a single ``list_append`` on the ``attempts`` attribute, so it never rewrites — or
        loses — any other field, however many writers are working on the request at once.
        """
        try:
            response = self.table.update_item(
                Key=self._key(REQUEST, request_id),
                UpdateExpression=(
                    "SET #attempts = list_append(if_not_exists(#attempts, :empty), :one) ADD #version :bump"
                ),
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeNames={"#attempts": "attempts", "#version": "version"},
                ExpressionAttributeValues={
                    ":empty": [],
                    ":one": _encode_attempts([attempt]),
                    ":bump": 1,
                },
                ReturnValues="ALL_NEW",
            )
        except Exception as exc:
            if _is_conditional_failure(exc):
                return None
            raise
        item = response.get("Attributes")
        return _hydrate_request(item) if item else self.get_request(request_id)

    def resolve_attempt(self, request_id: str, attempt: Attempt) -> AidRequest | None:
        """Settle this volunteer's open attempt, or append it (see :class:`.base.Store`)."""
        for _ in range(MAX_CONDITIONAL_RETRIES):
            current = self.get_request(request_id)
            if current is None:
                return None
            attempts = _settled(current, attempt)
            if attempts == list(current.attempts):
                return current
            try:
                response = self.table.update_item(
                    Key=self._key(REQUEST, request_id),
                    UpdateExpression="SET #attempts = :attempts ADD #version :bump",
                    ConditionExpression="#version = :expected",
                    ExpressionAttributeNames={"#attempts": "attempts", "#version": "version"},
                    ExpressionAttributeValues={
                        ":attempts": _encode_attempts(attempts),
                        ":bump": 1,
                        ":expected": current.version,
                    },
                    ReturnValues="ALL_NEW",
                )
            except Exception as exc:
                if not _is_conditional_failure(exc):
                    raise
                continue
            item = response.get("Attributes")
            return _hydrate_request(item) if item else self.get_request(request_id)
        raise StaleVersionError(request_id)  # pragma: no cover - five lost races in a row

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

    # --- trace --------------------------------------------------------------

    def append_trace(self, event: dict[str, Any]) -> int:
        """Persist one trace event and return its cursor (see :class:`.base.Store`).

        The cursor comes from an atomic ``ADD`` on a single counter item, so cursors stay
        strictly increasing across processes. ``expires_at`` doubles as the table's TTL
        attribute, which is what keeps the trace partition from growing without bound.
        """
        row = trace_row(event, datetime.now(UTC))
        cursor = self._next_cursor()
        sort_key = f"{cursor:0{CURSOR_WIDTH}d}"
        request_id = row.get("request_id")
        self.table.put_item(
            Item={
                **self._key(TRACE, sort_key),
                "gsi1pk": TRACE,
                "gsi1sk": sort_key,
                "entity": TRACE,
                "id": sort_key,
                "cursor": cursor,
                "status": "trace",
                "created_at": str(row["ts"]),
                "request_id": request_id if isinstance(request_id, str) else "",
                "expires_at": int(row["expires_at"]),
                "body": json.dumps(row),
            }
        )
        return cursor

    def list_trace(
        self, since_cursor: int = 0, limit: int = 500, request_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Read trace events after ``since_cursor``, oldest first (see :class:`.base.Store`)."""
        from boto3.dynamodb.conditions import Key

        after = f"{max(0, int(since_cursor)):0{CURSOR_WIDTH}d}"
        condition = Key("gsi1pk").eq(TRACE) & Key("gsi1sk").gt(after)
        kwargs: dict[str, Any] = {
            "IndexName": GSI1,
            "KeyConditionExpression": condition,
            "ScanIndexForward": True,
        }
        events: list[dict[str, Any]] = []
        while True:
            response = self.table.query(**kwargs)
            for item in response.get("Items", []):
                if request_id is not None and item.get("request_id") != request_id:
                    continue
                events.append({**json.loads(item["body"]), "cursor": int(item["cursor"])})
            token = response.get("LastEvaluatedKey")
            if not token or len(events) >= limit:
                break
            kwargs["ExclusiveStartKey"] = token
        return events[: max(0, int(limit))]

    def _next_cursor(self) -> int:
        """Atomically increment and return the shared trace counter."""
        response = self.table.update_item(
            Key=self._key(TRACE, TRACE_COUNTER_ID),
            UpdateExpression="ADD #seq :one",
            ExpressionAttributeNames={"#seq": "seq"},
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(response.get("Attributes", {}).get("seq", 0))

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


def _sort_key(req: AidRequest) -> str:
    """The GSI1 sort key for one request: status, then creation time, then id."""
    return f"{req.status}#{_iso(req.created_at)}#{req.id}"


def _encode_attempts(attempts: list[Attempt]) -> list[str]:
    """Attempts as a DynamoDB list of JSON strings, which ``list_append`` can extend."""
    return [attempt.model_dump_json() for attempt in attempts]


def _request_item(req: AidRequest) -> dict[str, Any]:
    """The full DynamoDB item for one request."""
    return {
        "pk": f"{REQUEST}#{req.id}",
        "sk": REQUEST,
        "gsi1pk": REQUEST,
        "gsi1sk": _sort_key(req),
        "entity": REQUEST,
        "id": req.id,
        "status": str(req.status),
        "created_at": _iso(req.created_at),
        "version": int(req.version),
        "attempts": _encode_attempts(list(req.attempts)),
        "body": req.model_dump_json(),
    }


def _hydrate_request(item: dict[str, Any]) -> AidRequest:
    """Rebuild a request from its item, preferring the live ``attempts`` and ``version`` columns.

    ``append_attempt`` extends the ``attempts`` attribute without rewriting ``body``, so the
    attribute — not the body — is the authority on what has been asked.
    """
    request = AidRequest.model_validate_json(item["body"])
    attempts = item.get("attempts")
    if isinstance(attempts, list):
        request.attempts = [Attempt.model_validate_json(raw) for raw in attempts]
    version = item.get("version")
    if version is not None:
        request.version = int(version)
    return request


def _settled(req: AidRequest, attempt: Attempt) -> list[Attempt]:
    """``req.attempts`` with this volunteer's open attempt settled, or ``attempt`` appended."""
    attempts = list(req.attempts)
    for index in range(len(attempts) - 1, -1, -1):
        candidate = attempts[index]
        if candidate.volunteer_id == attempt.volunteer_id and candidate.outcome == "pending":
            attempts[index] = candidate.model_copy(update={"outcome": attempt.outcome, "note": attempt.note})
            return attempts
    attempts.append(attempt)
    return attempts


def _is_conditional_failure(exc: Exception) -> bool:
    """True when a boto3 error is DynamoDB rejecting a ``ConditionExpression``."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None
    return code == "ConditionalCheckFailedException" or type(exc).__name__ == (
        "ConditionalCheckFailedException"
    )

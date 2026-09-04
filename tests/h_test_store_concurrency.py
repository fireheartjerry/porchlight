"""Concurrent writes to one request must not lose an attempt or an assignment.

Before the store grew field-level writes, every tool did a read-modify-write of the whole
``AidRequest`` row: ``assign_volunteer`` and ``record_attempt`` running on two threads would each
load the request, change one part of it, and write the whole thing back — so whichever finished
second silently reverted the other. These tests hammer that exact race.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import pytest
from a_helpers import FROZEN_NOW, make_ctx

from porchlight.clock import FrozenClock
from porchlight.models import AidRequest, Attempt, Category, RequestStatus, Volunteer
from porchlight.store.base import StaleVersionError, apply_fields, trace_row
from porchlight.store.sqlite_store import SqliteStore
from porchlight.tools.records import assign_volunteer_impl, record_attempt_impl

RACES = 50
"""How many times each race is re-run; one lost write in fifty is still a lost write."""


@pytest.fixture
def racy_store(tmp_path) -> SqliteStore:
    """A store on disk, so the two threads really share one SQLite connection."""
    store = SqliteStore(str(tmp_path / "race.db"))
    for index in range(4):
        store.put_volunteer(Volunteer(id=f"vol_{index}", name=f"Volunteer {index}"))
    yield store
    store.close()


def _fresh_request(store: SqliteStore, request_id: str) -> AidRequest:
    """A request in the state outreach leaves behind: asked, waiting to hear back."""
    return store.put_request(
        AidRequest(
            id=request_id,
            summary="Ride to dialysis",
            category=Category.RIDE,
            status=RequestStatus.AWAITING_REPLY,
            attempts=[Attempt(volunteer_id="vol_0", outcome="pending")],
        )
    )


# --------------------------------------------------------------------------------------
# The race the tools used to lose
# --------------------------------------------------------------------------------------


def test_assign_and_record_attempt_racing_never_lose_a_write(racy_store: SqliteStore) -> None:
    """One volunteer accepts while another declines, fifty times, on two threads at once."""
    ctx = make_ctx(racy_store, FrozenClock(FROZEN_NOW), with_memory=False)

    for round_number in range(RACES):
        request_id = f"req_race_{round_number}"
        _fresh_request(racy_store, request_id)
        start = threading.Barrier(2)

        def assign(gate: threading.Barrier, rid: str) -> None:
            gate.wait(timeout=5)
            assign_volunteer_impl(ctx, rid, "vol_1")

        def decline(gate: threading.Barrier, rid: str) -> None:
            gate.wait(timeout=5)
            record_attempt_impl(ctx, rid, "vol_2", "declined", "busy")

        with ThreadPoolExecutor(max_workers=2) as pool:
            running = [pool.submit(assign, start, request_id), pool.submit(decline, start, request_id)]
            for future in running:
                future.result(timeout=10)

        settled = racy_store.get_request(request_id)
        assert settled is not None
        outcomes = {attempt.volunteer_id: attempt.outcome for attempt in settled.attempts}
        assert outcomes["vol_1"] == "accepted", f"assignment lost on round {round_number}"
        assert outcomes["vol_2"] == "declined", f"attempt lost on round {round_number}"
        assert outcomes["vol_0"] == "pending", f"the open ask was clobbered on round {round_number}"
        assert settled.assigned_volunteer_id == "vol_1"
        assert settled.status is RequestStatus.CONFIRMED


def test_many_threads_recording_attempts_keep_every_one(racy_store: SqliteStore) -> None:
    """Twenty volunteers answering at once produce twenty attempts, not one."""
    ctx = make_ctx(racy_store, FrozenClock(FROZEN_NOW), with_memory=False)
    racy_store.put_request(AidRequest(id="req_many", status=RequestStatus.AWAITING_REPLY))
    for index in range(20):
        racy_store.put_volunteer(Volunteer(id=f"vol_many_{index}", name=f"V{index}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(record_attempt_impl, ctx, "req_many", f"vol_many_{index}", "declined")
            for index in range(20)
        ]
        for future in futures:
            future.result(timeout=10)

    settled = racy_store.get_request("req_many")
    assert settled is not None
    assert len(settled.attempts) == 20
    assert len({attempt.volunteer_id for attempt in settled.attempts}) == 20


def test_field_updates_on_different_fields_do_not_overwrite_each_other(racy_store: SqliteStore) -> None:
    """Two writers touching two fields both keep their change."""
    racy_store.put_request(AidRequest(id="req_fields", summary="before"))
    start = threading.Barrier(2)

    def set_summary() -> None:
        start.wait(timeout=5)
        racy_store.update_request_fields("req_fields", summary="after")

    def set_zone() -> None:
        start.wait(timeout=5)
        racy_store.update_request_fields("req_fields", location_zone="Riverside")

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(set_summary), pool.submit(set_zone)]:
            future.result(timeout=10)

    settled = racy_store.get_request("req_fields")
    assert settled is not None
    assert settled.summary == "after"
    assert settled.location_zone == "Riverside"


# --------------------------------------------------------------------------------------
# The store contract
# --------------------------------------------------------------------------------------


def test_version_starts_at_zero_and_climbs_with_every_atomic_write(empty_store: SqliteStore) -> None:
    empty_store.put_request(AidRequest(id="req_v"))
    assert empty_store.get_request("req_v").version == 0

    first = empty_store.update_request_fields("req_v", summary="one")
    assert first is not None and first.version == 1
    second = empty_store.append_attempt("req_v", Attempt(volunteer_id="vol_a"))
    assert second is not None and second.version == 2
    assert empty_store.get_request("req_v").version == 2


def test_expected_version_rejects_a_stale_write(empty_store: SqliteStore) -> None:
    empty_store.put_request(AidRequest(id="req_stale"))
    empty_store.update_request_fields("req_stale", expected_version=0, summary="mine")

    with pytest.raises(StaleVersionError) as caught:
        empty_store.update_request_fields("req_stale", expected_version=0, summary="theirs")
    assert caught.value.request_id == "req_stale"
    assert caught.value.expected == 0
    assert empty_store.get_request("req_stale").summary == "mine"


def test_field_updates_leave_untouched_fields_and_attempts_alone(empty_store: SqliteStore) -> None:
    empty_store.put_request(
        AidRequest(
            id="req_keep",
            summary="keep me",
            constraints=["no stairs"],
            attempts=[Attempt(volunteer_id="vol_a", outcome="declined")],
        )
    )
    updated = empty_store.update_request_fields("req_keep", status=RequestStatus.MATCHING)
    assert updated is not None
    assert updated.summary == "keep me"
    assert updated.constraints == ["no stairs"]
    assert [a.volunteer_id for a in updated.attempts] == ["vol_a"]


def test_unknown_request_returns_none_rather_than_raising(empty_store: SqliteStore) -> None:
    assert empty_store.update_request_fields("req_nope", summary="x") is None
    assert empty_store.append_attempt("req_nope", Attempt(volunteer_id="vol_a")) is None
    assert empty_store.resolve_attempt("req_nope", Attempt(volunteer_id="vol_a")) is None


@pytest.mark.parametrize("field", ["id", "version"])
def test_identity_and_the_version_counter_cannot_be_written_as_fields(
    empty_store: SqliteStore, field: str
) -> None:
    empty_store.put_request(AidRequest(id="req_frozen"))
    with pytest.raises(ValueError, match="cannot be updated"):
        empty_store.update_request_fields("req_frozen", **{field: "nope"})


def test_unknown_and_invalid_fields_raise_value_error(empty_store: SqliteStore) -> None:
    empty_store.put_request(AidRequest(id="req_bad"))
    with pytest.raises(ValueError, match="unknown request field"):
        empty_store.update_request_fields("req_bad", nonsense=1)
    with pytest.raises(ValueError):
        empty_store.update_request_fields("req_bad", status="not-a-status")


def test_resolve_attempt_settles_the_open_ask_instead_of_appending(empty_store: SqliteStore) -> None:
    empty_store.put_request(
        AidRequest(id="req_settle", attempts=[Attempt(volunteer_id="vol_a", outcome="pending")])
    )
    settled = empty_store.resolve_attempt(
        "req_settle", Attempt(volunteer_id="vol_a", outcome="accepted", note="yes please")
    )
    assert settled is not None
    assert len(settled.attempts) == 1
    assert settled.attempts[0].outcome == "accepted"
    assert settled.attempts[0].note == "yes please"


def test_resolve_attempt_appends_when_nobody_was_asked(empty_store: SqliteStore) -> None:
    empty_store.put_request(AidRequest(id="req_unasked"))
    settled = empty_store.resolve_attempt("req_unasked", Attempt(volunteer_id="vol_z", outcome="declined"))
    assert settled is not None
    assert [(a.volunteer_id, a.outcome) for a in settled.attempts] == [("vol_z", "declined")]


def test_apply_fields_validates_against_the_model() -> None:
    request = AidRequest(id="req_apply")
    updated = apply_fields(request, {"status": "matching", "window_start": "2026-09-10T13:00:00Z"})
    assert updated.status is RequestStatus.MATCHING
    assert updated.window_start == datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
    assert request.status is RequestStatus.NEW, "the original must not be mutated"


def test_trace_row_stamps_a_ts_and_a_ttl_friendly_expiry() -> None:
    now = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)
    row = trace_row({"type": "log", "summary": "hi", "cursor": 99}, now)
    assert row["ts"] == now.isoformat()
    assert row["expires_at"] == int(now.timestamp()) + 7 * 24 * 3600
    assert "cursor" not in row, "the store assigns the cursor, never the caller"

    kept = trace_row({"type": "log", "ts": "2026-01-01T00:00:00+00:00"}, now)
    assert kept["ts"] == "2026-01-01T00:00:00+00:00"


def test_an_older_database_file_gains_the_version_column(tmp_path) -> None:
    """A database written before optimistic concurrency existed still opens and writes."""
    import sqlite3

    path = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(path)
    legacy.executescript(
        "CREATE TABLE requests (id TEXT PRIMARY KEY, status TEXT NOT NULL, requester_id TEXT,"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL, body TEXT NOT NULL);"
    )
    legacy.execute(
        "INSERT INTO requests (id, status, requester_id, created_at, updated_at, body)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            "req_old",
            "new",
            None,
            FROZEN_NOW.isoformat(),
            FROZEN_NOW.isoformat(),
            AidRequest(id="req_old", summary="from before").model_dump_json(),
        ),
    )
    legacy.commit()
    legacy.close()

    store = SqliteStore(path)
    try:
        assert store.get_request("req_old").summary == "from before"
        updated = store.update_request_fields("req_old", status=RequestStatus.MATCHING)
        assert updated is not None and updated.version == 1
    finally:
        store.close()


# --------------------------------------------------------------------------------------
# DynamoDB: the same contract, expressed as conditional updates
# --------------------------------------------------------------------------------------


class FakeTable:
    """Just enough DynamoDB to exercise the expressions ``DynamoStore`` actually writes.

    It understands the handful of ``UpdateExpression`` shapes the store emits — ``SET`` with
    plain values or ``list_append(if_not_exists(...))``, and ``ADD`` on a counter — plus the two
    ``ConditionExpression`` forms, raising a boto3-shaped conditional failure when one fails.
    """

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.updates: list[dict[str, Any]] = []

    # --- api ---------------------------------------------------------------
    def put_item(self, Item: dict[str, Any]) -> dict[str, Any]:  # noqa: N803 - boto3 spelling
        self.items[(Item["pk"], Item["sk"])] = dict(Item)
        return {}

    def get_item(self, Key: dict[str, str]) -> dict[str, Any]:  # noqa: N803 - boto3 spelling
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        key = (kwargs["Key"]["pk"], kwargs["Key"]["sk"])
        item = self.items.get(key, {**kwargs["Key"]})
        names = kwargs.get("ExpressionAttributeNames", {})
        values = kwargs.get("ExpressionAttributeValues", {})
        condition = kwargs.get("ConditionExpression")
        if condition and not self._holds(condition, item, names, values, key):
            raise ConditionalCheckFailed()
        self._apply(kwargs["UpdateExpression"], item, names, values)
        self.items[key] = item
        return {"Attributes": dict(item)}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        condition = kwargs["KeyConditionExpression"]
        rows = [item for item in self.items.values() if _matches(condition, item)]
        rows.sort(
            key=lambda item: str(item.get("gsi1sk")),
            reverse=not kwargs.get("ScanIndexForward", True),
        )
        return {"Items": rows}

    # --- expression evaluation ----------------------------------------------
    def _holds(
        self,
        condition: str,
        item: dict[str, Any],
        names: dict[str, str],
        values: dict[str, Any],
        key: tuple[str, str],
    ) -> bool:
        if condition == "attribute_exists(pk)":
            return key in self.items
        left, _, right = condition.partition(" = ")
        return item.get(names.get(left.strip(), left.strip())) == values[right.strip()]

    @staticmethod
    def _apply(expression: str, item: dict[str, Any], names: dict[str, str], values: dict[str, Any]) -> None:
        sets, adds = _sections(expression)
        for clause in sets:
            target, _, source = clause.partition(" = ")
            field = names.get(target.strip(), target.strip())
            source = source.strip()
            if source.startswith("list_append("):
                inner = source[len("list_append(") : -1]
                base, _, extra = inner.rpartition(", ")
                current = item.get(field) if "if_not_exists" in base else values.get(base.strip())
                item[field] = list(current or []) + list(values[extra.strip()])
            else:
                item[field] = values[source]
        for clause in adds:
            target, _, amount = clause.strip().partition(" ")
            field = names.get(target.strip(), target.strip())
            item[field] = int(item.get(field, 0)) + int(values[amount.strip()])


def _split_clauses(section: str) -> list[str]:
    """Split an update section on the commas that are not inside a function call."""
    clauses: list[str] = []
    depth = 0
    current = ""
    for character in section:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            clauses.append(current.strip())
            current = ""
            continue
        current += character
    if current.strip():
        clauses.append(current.strip())
    return clauses


def _sections(expression: str) -> tuple[list[str], list[str]]:
    """Split an ``UpdateExpression`` into its SET clauses and its ADD clauses."""
    if expression.startswith("ADD "):
        return [], _split_clauses(expression.removeprefix("ADD "))
    head, marker, tail = expression.partition(" ADD ")
    return _split_clauses(head.removeprefix("SET ")), _split_clauses(tail) if marker else []


def _matches(condition: Any, item: dict[str, Any]) -> bool:
    """Evaluate a boto3 ``Key`` condition tree against one fake item."""
    expression = condition.get_expression()
    operator = expression["operator"]
    values = expression["values"]
    if operator == "AND":
        return all(_matches(part, item) for part in values)
    actual = item.get(values[0].name)
    target = values[1]
    if operator == "=":
        return actual == target
    if operator == ">":
        return actual is not None and str(actual) > str(target)
    if operator == "begins_with":
        return str(actual or "").startswith(str(target))
    raise AssertionError(f"the fake table does not implement {operator!r}")


class ConditionalCheckFailed(Exception):
    """A boto3-shaped ``ConditionalCheckFailedException``."""

    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


@pytest.fixture
def dynamo():
    """A :class:`DynamoStore` bound to the fake table, plus the table itself."""
    from porchlight.store.dynamo_store import DynamoStore

    store = DynamoStore(table="porchlight-test")
    table = FakeTable()
    store._table = table
    return store, table


def test_dynamo_append_attempt_uses_list_append_and_never_rewrites_the_body(dynamo) -> None:
    store, table = dynamo
    store.put_request(AidRequest(id="req_dyn", summary="original"))

    for index in range(3):
        store.append_attempt("req_dyn", Attempt(volunteer_id=f"vol_{index}", outcome="pending"))

    expression = table.updates[-1]["UpdateExpression"]
    assert "list_append" in expression, "attempts must be appended, not read-modify-written"
    assert "body" not in expression, "appending an attempt must not rewrite the whole record"

    settled = store.get_request("req_dyn")
    assert [a.volunteer_id for a in settled.attempts] == ["vol_0", "vol_1", "vol_2"]
    assert settled.summary == "original"
    assert settled.version == 3


def test_dynamo_field_update_is_guarded_by_a_condition_expression(dynamo) -> None:
    store, table = dynamo
    store.put_request(AidRequest(id="req_dyn2"))
    updated = store.update_request_fields("req_dyn2", status=RequestStatus.MATCHING)

    assert updated is not None and updated.status is RequestStatus.MATCHING
    call = table.updates[-1]
    assert call["ConditionExpression"] == "#version = :expected"
    assert call["ExpressionAttributeValues"][":expected"] == 0
    assert store.get_request("req_dyn2").version == 1


def test_dynamo_field_update_raises_on_a_stale_expected_version(dynamo) -> None:
    store, _table = dynamo
    store.put_request(AidRequest(id="req_dyn3"))
    store.update_request_fields("req_dyn3", summary="mine")
    with pytest.raises(StaleVersionError):
        store.update_request_fields("req_dyn3", expected_version=0, summary="theirs")


def test_dynamo_attempts_and_assignment_survive_each_other(dynamo) -> None:
    store, _table = dynamo
    store.put_request(AidRequest(id="req_dyn4", attempts=[Attempt(volunteer_id="vol_a", outcome="pending")]))
    store.resolve_attempt("req_dyn4", Attempt(volunteer_id="vol_a", outcome="accepted"))
    store.update_request_fields("req_dyn4", assigned_volunteer_id="vol_a", status=RequestStatus.CONFIRMED)
    store.append_attempt("req_dyn4", Attempt(volunteer_id="vol_b", outcome="declined"))

    settled = store.get_request("req_dyn4")
    assert settled.assigned_volunteer_id == "vol_a"
    assert settled.status is RequestStatus.CONFIRMED
    assert [(a.volunteer_id, a.outcome) for a in settled.attempts] == [
        ("vol_a", "accepted"),
        ("vol_b", "declined"),
    ]


def test_dynamo_append_attempt_on_a_missing_request_returns_none(dynamo) -> None:
    store, _table = dynamo
    assert store.append_attempt("req_missing", Attempt(volunteer_id="vol_a")) is None


def test_dynamo_trace_cursors_increase_and_page(dynamo) -> None:
    store, _table = dynamo
    first = store.append_trace({"type": "log", "summary": "one", "request_id": "req_x"})
    second = store.append_trace({"type": "log", "summary": "two", "request_id": "req_y"})
    assert (first, second) == (1, 2)

    everything = store.list_trace(0)
    assert [event["summary"] for event in everything] == ["one", "two"]
    assert [event["cursor"] for event in everything] == [1, 2]
    assert store.list_trace(1)[0]["summary"] == "two"
    assert [e["summary"] for e in store.list_trace(0, request_id="req_y")] == ["two"]
    assert all(event["expires_at"] > 0 for event in everything)

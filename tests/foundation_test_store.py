"""Every :class:`~porchlight.store.base.Store` method, exercised against SqliteStore."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from porchlight.config import Settings
from porchlight.models import (
    AidRequest,
    Attempt,
    Category,
    Decision,
    DecisionKind,
    DecisionStatus,
    GroupSettings,
    LogEvent,
    LogKind,
    MessageStatus,
    OutboundMessage,
    Recipient,
    Requester,
    RequestStatus,
    Volunteer,
)
from porchlight.store import DynamoStore, SqliteStore, Store, make_store

NOW = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)


def test_sqlite_store_satisfies_the_protocol(empty_store: SqliteStore) -> None:
    assert isinstance(empty_store, Store)


def test_make_store_picks_backend_from_settings() -> None:
    sqlite = make_store(Settings(store="sqlite", sqlite_path=":memory:"))
    assert isinstance(sqlite, SqliteStore)
    dynamo = make_store(Settings(store="dynamo", dynamo_table="t", aws_region="us-east-1"))
    assert isinstance(dynamo, DynamoStore)
    assert dynamo.table_name == "t"


# --- volunteers ------------------------------------------------------------------------


def test_volunteer_round_trip_and_filters(empty_store: SqliteStore) -> None:
    a = Volunteer(id="vol_a", name="Ann", zones=["Riverside"], skills=["drive"], vetted=True)
    b = Volunteer(id="vol_b", name="Bo", zones=["Northgate"], skills=["cook", "translate:es"])
    empty_store.put_volunteer(a)
    empty_store.put_volunteer(b)

    assert empty_store.get_volunteer("vol_a") == a
    assert empty_store.get_volunteer("missing") is None
    assert {v.id for v in empty_store.list_volunteers()} == {"vol_a", "vol_b"}
    assert [v.id for v in empty_store.list_volunteers(vetted=True)] == ["vol_a"]
    assert [v.id for v in empty_store.list_volunteers(vetted=False)] == ["vol_b"]
    assert [v.id for v in empty_store.list_volunteers(zone="Northgate")] == ["vol_b"]
    assert [v.id for v in empty_store.list_volunteers(skill="translate")] == ["vol_b"]
    assert empty_store.list_volunteers(zone="Nowhere") == []


def test_put_volunteer_replaces(empty_store: SqliteStore) -> None:
    volunteer = Volunteer(id="vol_a", name="Ann")
    empty_store.put_volunteer(volunteer)
    volunteer.name = "Annette"
    empty_store.put_volunteer(volunteer)
    assert len(empty_store.list_volunteers()) == 1
    stored = empty_store.get_volunteer("vol_a")
    assert stored is not None and stored.name == "Annette"


# --- requesters ------------------------------------------------------------------------


def test_requester_round_trip_and_contact_lookup(empty_store: SqliteStore) -> None:
    requester = Requester(id="rqr_a", name="Ezra", contact="+1-555-0201")
    empty_store.put_requester(requester)
    assert empty_store.get_requester("rqr_a") == requester
    assert empty_store.find_requester_by_contact("+1-555-0201") == requester
    assert empty_store.find_requester_by_contact("+1-555-9999") is None
    assert [r.id for r in empty_store.list_requesters()] == ["rqr_a"]


def test_find_requester_by_contact_is_case_insensitive(empty_store: SqliteStore) -> None:
    empty_store.put_requester(Requester(id="rqr_a", name="Lucía", contact="Lucia@Example.org"))
    assert empty_store.find_requester_by_contact("lucia@example.org") is not None


# --- requests --------------------------------------------------------------------------


def _request(rid: str, status: RequestStatus, created: datetime) -> AidRequest:
    return AidRequest(
        id=rid,
        status=status,
        category=Category.RIDE,
        created_at=created,
        updated_at=created,
        requester_id="rqr_a",
    )


def test_request_round_trip_and_listing(empty_store: SqliteStore) -> None:
    older = _request("req_1", RequestStatus.NEW, NOW - timedelta(days=1))
    newer = _request("req_2", RequestStatus.COMPLETED, NOW)
    empty_store.put_request(older)
    empty_store.put_request(newer)

    assert empty_store.get_request("req_1") == older
    assert empty_store.get_request("nope") is None
    assert [r.id for r in empty_store.list_requests()] == ["req_2", "req_1"]
    assert [r.id for r in empty_store.list_requests(RequestStatus.NEW)] == ["req_1"]
    assert [r.id for r in empty_store.list_requests(limit=1)] == ["req_2"]


def test_requests_for_volunteer_matches_attempts_and_assignment(empty_store: SqliteStore) -> None:
    assigned = _request("req_assigned", RequestStatus.CONFIRMED, NOW)
    assigned.assigned_volunteer_id = "vol_a"
    attempted = _request("req_attempted", RequestStatus.AWAITING_REPLY, NOW)
    attempted.attempts = [Attempt(volunteer_id="vol_a", sent_at=NOW, outcome="declined")]
    unrelated = _request("req_other", RequestStatus.NEW, NOW)
    stale = _request("req_stale", RequestStatus.COMPLETED, NOW - timedelta(days=30))
    stale.assigned_volunteer_id = "vol_a"
    for request in (assigned, attempted, unrelated, stale):
        empty_store.put_request(request)

    found = empty_store.requests_for_volunteer("vol_a", NOW - timedelta(days=7))
    assert {r.id for r in found} == {"req_assigned", "req_attempted"}
    assert empty_store.requests_for_volunteer("vol_zzz", NOW - timedelta(days=7)) == []


# --- decisions -------------------------------------------------------------------------


def test_decision_round_trip_and_status_filter(empty_store: SqliteStore) -> None:
    open_card = Decision(id="dec_1", kind=DecisionKind.SAFETY, title="Child alone", created_at=NOW)
    resolved = Decision(
        id="dec_2",
        kind=DecisionKind.MONEY,
        title="Bill help",
        created_at=NOW - timedelta(hours=1),
        status=DecisionStatus.RESOLVED,
        resolved_option="approve",
        resolved_at=NOW,
    )
    empty_store.put_decision(open_card)
    empty_store.put_decision(resolved)

    assert empty_store.get_decision("dec_1") == open_card
    assert empty_store.get_decision("nope") is None
    assert [d.id for d in empty_store.list_decisions()] == ["dec_1", "dec_2"]
    assert [d.id for d in empty_store.list_decisions(DecisionStatus.OPEN)] == ["dec_1"]
    assert [d.id for d in empty_store.list_decisions(DecisionStatus.RESOLVED)] == ["dec_2"]


# --- messages --------------------------------------------------------------------------


def test_message_round_trip_and_filters(empty_store: SqliteStore) -> None:
    sent = OutboundMessage(
        id="msg_1",
        request_id="req_1",
        to=Recipient.VOLUNTEER,
        status=MessageStatus.SENT,
        created_at=NOW,
    )
    due = OutboundMessage(
        id="msg_2",
        request_id="req_1",
        to=Recipient.REQUESTER,
        status=MessageStatus.SCHEDULED,
        scheduled_for=NOW + timedelta(hours=1),
        created_at=NOW - timedelta(minutes=5),
    )
    later = OutboundMessage(
        id="msg_3",
        request_id="req_2",
        status=MessageStatus.SCHEDULED,
        scheduled_for=NOW + timedelta(days=2),
        created_at=NOW - timedelta(minutes=10),
    )
    for message in (sent, due, later):
        empty_store.put_message(message)

    assert [m.id for m in empty_store.list_messages()] == ["msg_1", "msg_2", "msg_3"]
    assert [m.id for m in empty_store.list_messages(request_id="req_1")] == ["msg_1", "msg_2"]
    assert [m.id for m in empty_store.list_messages(status=MessageStatus.SENT)] == ["msg_1"]
    assert [m.id for m in empty_store.list_messages(due_before=NOW + timedelta(hours=2))] == ["msg_2"]


# --- log -------------------------------------------------------------------------------


def test_log_append_and_filters(empty_store: SqliteStore) -> None:
    first = LogEvent(id="log_1", ts=NOW - timedelta(hours=2), request_id="req_1", summary="one")
    second = LogEvent(id="log_2", ts=NOW, request_id="req_2", kind=LogKind.DECISION, summary="two")
    empty_store.append_log(first)
    empty_store.append_log(second)

    assert [e.id for e in empty_store.list_log()] == ["log_2", "log_1"]
    assert [e.id for e in empty_store.list_log(request_id="req_1")] == ["log_1"]
    assert [e.id for e in empty_store.list_log(since=NOW - timedelta(minutes=30))] == ["log_2"]
    assert [e.id for e in empty_store.list_log(limit=1)] == ["log_2"]


# --- settings --------------------------------------------------------------------------


def test_group_settings_default_then_persisted(empty_store: SqliteStore) -> None:
    assert empty_store.get_group_settings() == GroupSettings()
    custom = GroupSettings(name="Elm Ave Aid", zones=["Elm"], max_candidates=5)
    empty_store.put_group_settings(custom)
    assert empty_store.get_group_settings() == custom


# --- util ------------------------------------------------------------------------------


def test_reset_wipes_every_table(store: SqliteStore) -> None:
    assert store.list_volunteers()
    store.append_log(LogEvent(summary="before reset"))
    store.reset()
    assert store.list_volunteers() == []
    assert store.list_requesters() == []
    assert store.list_requests() == []
    assert store.list_decisions() == []
    assert store.list_messages() == []
    assert store.list_log() == []
    assert store.get_group_settings() == GroupSettings()


def test_stats_counts_handled_open_and_resolved(empty_store: SqliteStore) -> None:
    quiet = _request("req_quiet", RequestStatus.COMPLETED, NOW)
    flagged = _request("req_flagged", RequestStatus.CONFIRMED, NOW)
    pending = _request("req_pending", RequestStatus.AWAITING_REPLY, NOW)
    yesterday = _request("req_old", RequestStatus.COMPLETED, NOW - timedelta(days=1))
    for request in (quiet, flagged, pending, yesterday):
        empty_store.put_request(request)

    empty_store.put_decision(
        Decision(id="dec_open", request_id="req_flagged", created_at=NOW, status=DecisionStatus.OPEN)
    )
    empty_store.put_decision(
        Decision(
            id="dec_done",
            request_id="req_quiet_other",
            created_at=NOW,
            status=DecisionStatus.RESOLVED,
            resolved_at=NOW,
        )
    )

    stats = empty_store.stats(NOW.date())
    assert stats["handled_autonomously"] == 1
    assert stats["decisions_open"] == 1
    assert stats["decisions_resolved"] == 1
    assert stats["requests_by_status"] == {"completed": 1, "confirmed": 1, "awaiting_reply": 1}


def test_stats_on_a_quiet_day(empty_store: SqliteStore) -> None:
    stats = empty_store.stats(NOW.date())
    assert stats == {
        "handled_autonomously": 0,
        "decisions_open": 0,
        "decisions_resolved": 0,
        "requests_by_status": {},
    }


def test_store_is_usable_from_several_threads(empty_store: SqliteStore) -> None:
    def worker(index: int) -> None:
        for offset in range(10):
            empty_store.put_volunteer(Volunteer(id=f"vol_{index}_{offset}", name=f"V{index}{offset}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(empty_store.list_volunteers()) == 40


def test_dynamo_store_does_not_touch_aws_on_construction() -> None:
    store = DynamoStore(table="porchlight", region="us-east-1")
    assert store._table is None
    assert "porchlight" in repr(store)

"""Inbound messages that are not requests: thank-you notes, chatter, and duplicates.

Every one of these used to be pushed through matching and outreach like any other job, so a
neighbour saying "thank you for the lasagne" eventually produced a "nobody free" decision card,
and a second message chasing a ride already in hand booked a second volunteer for the same trip.
Intake now says so, and the graph hands straight to the steward, who closes it politely.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from a_helpers import make_request

from porchlight.agents.outputs import IntakeResult
from porchlight.channels.sim import SimChannel
from porchlight.clock import FrozenClock
from porchlight.config import Settings
from porchlight.context import AppContext
from porchlight.graph import run_request
from porchlight.intake_ingest import create_request_from_inbox
from porchlight.memory.sqlite_store import SqliteMemoryStore
from porchlight.models import AidRequest, Category, Recipient, RequestStatus
from porchlight.sim.fixtures import sample_by_id, seed_store
from porchlight.sim.mock_scenarios import SAMPLE_PLANS
from porchlight.store.sqlite_store import SqliteStore
from porchlight.tools.intake import find_similar_open_requests_impl

DEMO_NOW = datetime.fromisoformat("2026-09-08T18:00:00+00:00")
"""Tuesday afternoon in America/Toronto, so quiet hours never change the expected path."""


@pytest.fixture
def demo_ctx(tmp_path, settings: Settings) -> AppContext:
    """A demo context on disk: SQLite store, SimChannel, SQLite memory, frozen daytime clock."""
    clock = FrozenClock(DEMO_NOW)
    store = SqliteStore(str(tmp_path / "porchlight.db"))
    seed_store(store, clock)
    events: list[dict] = []
    ctx = AppContext(
        settings=settings.model_copy(
            update={
                "sqlite_path": str(tmp_path / "porchlight.db"),
                "session_dir": str(tmp_path / "sessions"),
            }
        ),
        store=store,
        channel=SimChannel(store, clock),
        memory=SqliteMemoryStore(str(tmp_path / "memory.db"), clock=clock),
        clock=clock,
        emit=events.append,
    )
    ctx.emitted = events  # type: ignore[attr-defined]
    yield ctx
    store.close()


def _run_sample(ctx: AppContext, sample_id: str) -> tuple[AidRequest, object]:
    """Push one fixture message through the real graph."""
    sample = sample_by_id(sample_id)
    assert sample is not None
    request = create_request_from_inbox(ctx, sample["text"], sample["source"], sample["contact"])
    return request, run_request(ctx, request.id)


def _volunteer_messages(ctx: AppContext, request_id: str) -> list:
    return [m for m in ctx.store.list_messages(request_id=request_id) if m.to == Recipient.VOLUNTEER]


# --------------------------------------------------------------------------------------
# The intake result and the request flag it sets
# --------------------------------------------------------------------------------------


def test_intake_result_reports_whether_there_is_a_job_in_the_message() -> None:
    assert IntakeResult(summary="Ride to dialysis").is_actionable()
    assert not IntakeResult(summary="Thank you!", is_request=False).is_actionable()
    assert not IntakeResult(summary="Me again", duplicate_of="req_abc").is_actionable()


def test_intake_result_copies_both_flags_onto_the_request() -> None:
    request = AidRequest(id="req_flags")
    IntakeResult(summary="thanks", is_request=False, duplicate_of="req_first").apply_to(request)
    assert request.is_request is False
    assert request.duplicate_of == "req_first"
    assert not request.needs_outreach()


def test_a_plain_request_still_needs_outreach() -> None:
    assert AidRequest(id="req_plain").needs_outreach()


# --------------------------------------------------------------------------------------
# find_similar_open_requests
# --------------------------------------------------------------------------------------


def test_find_similar_open_requests_finds_the_neighbours_open_ride(ctx, store, clock) -> None:
    original = make_request(
        store, clock, request_id="req_original", category=Category.RIDE, status=RequestStatus.AWAITING_REPLY
    )
    original.requester_id = "rqr_okafor"
    store.put_request(original)

    found = find_similar_open_requests_impl(ctx, "rqr_okafor", "ride")
    assert [row["request_id"] for row in found] == ["req_original"]
    assert found[0]["status"] == "awaiting_reply"
    assert found[0]["summary"] == original.summary


def test_find_similar_open_requests_ignores_other_people_categories_and_closed_jobs(
    ctx, store, clock
) -> None:
    for index, (requester, category, status) in enumerate(
        [
            ("rqr_other", Category.RIDE, RequestStatus.AWAITING_REPLY),
            ("rqr_okafor", Category.MEAL, RequestStatus.AWAITING_REPLY),
            ("rqr_okafor", Category.RIDE, RequestStatus.COMPLETED),
        ]
    ):
        request = make_request(store, clock, request_id=f"req_no_{index}", category=category, status=status)
        request.requester_id = requester
        request.category = category
        store.put_request(request)

    assert find_similar_open_requests_impl(ctx, "rqr_okafor", "ride") == []


def test_find_similar_open_requests_excludes_the_message_being_read(ctx, store, clock) -> None:
    mine = make_request(store, clock, request_id="req_self", category=Category.RIDE)
    mine.requester_id = "rqr_okafor"
    store.put_request(mine)

    assert find_similar_open_requests_impl(ctx, "rqr_okafor", "ride") != []
    assert find_similar_open_requests_impl(ctx, "rqr_okafor", "ride", exclude_request_id="req_self") == []


def test_find_similar_open_requests_respects_the_window(ctx, store, clock) -> None:
    stale = make_request(store, clock, request_id="req_stale", category=Category.RIDE)
    stale.requester_id = "rqr_okafor"
    stale.created_at = clock.now() - timedelta(days=30)
    store.put_request(stale)

    assert find_similar_open_requests_impl(ctx, "rqr_okafor", "ride", 72) == []
    assert find_similar_open_requests_impl(ctx, "rqr_okafor", "ride", 24 * 40) != []


def test_find_similar_open_requests_ignores_a_bad_category_rather_than_failing(ctx, store, clock) -> None:
    request = make_request(store, clock, request_id="req_any", category=Category.RIDE)
    request.requester_id = "rqr_okafor"
    store.put_request(request)

    assert [row["request_id"] for row in find_similar_open_requests_impl(ctx, "rqr_okafor", "nonsense")] == [
        "req_any"
    ]


def test_find_similar_open_requests_skips_messages_that_were_not_requests(ctx, store, clock) -> None:
    note = make_request(store, clock, request_id="req_thanks", category=Category.RIDE)
    note.requester_id = "rqr_okafor"
    note.is_request = False
    store.put_request(note)

    assert find_similar_open_requests_impl(ctx, "rqr_okafor", "ride") == []


def test_find_similar_open_requests_traces_what_it_looked_at(ctx, store, clock) -> None:
    find_similar_open_requests_impl(ctx, "rqr_okafor", "ride", agent="intake")
    trace = [event for event in ctx.emitted if event["type"] == "tool_call"]
    assert trace and trace[-1]["detail"]["requester_id"] == "rqr_okafor"


# --------------------------------------------------------------------------------------
# End to end through the real graph
# --------------------------------------------------------------------------------------


def test_a_thank_you_note_is_closed_politely_without_asking_anybody(demo_ctx: AppContext) -> None:
    request, outcome = _run_sample(demo_ctx, "sm_thank_you")

    settled = demo_ctx.store.get_request(request.id)
    assert settled is not None
    assert settled.is_request is False
    assert settled.status is RequestStatus.CANCELLED
    assert outcome.interrupted is False
    assert outcome.decisions_created == []
    assert settled.attempts == [], "nobody should have been asked about a thank-you note"
    assert _volunteer_messages(demo_ctx, request.id) == []

    to_requester = [
        m for m in demo_ctx.store.list_messages(request_id=request.id) if m.to == Recipient.REQUESTER
    ]
    assert to_requester, "the neighbour should still get a warm reply"


def test_the_duplicate_dialysis_message_is_closed_against_the_original(demo_ctx: AppContext) -> None:
    original, first = _run_sample(demo_ctx, "sm_dialysis_ride")
    assert first.status is RequestStatus.CONFIRMED

    chase, outcome = _run_sample(demo_ctx, "sm_duplicate_dialysis")
    settled = demo_ctx.store.get_request(chase.id)
    assert settled is not None
    assert settled.duplicate_of == original.id
    assert settled.status is RequestStatus.CANCELLED
    assert settled.attempts == [], "a chase must not book a second volunteer"
    assert outcome.decisions_created == []
    assert _volunteer_messages(demo_ctx, chase.id) == []

    # The original is untouched and still confirmed.
    assert demo_ctx.store.get_request(original.id).status is RequestStatus.CONFIRMED


def test_the_short_circuit_is_written_to_the_quiet_log(demo_ctx: AppContext) -> None:
    request, _outcome = _run_sample(demo_ctx, "sm_thank_you")
    summaries = [event.summary for event in demo_ctx.store.list_log(request_id=request.id)]
    assert any("no outreach needed" in summary for summary in summaries)


def test_an_ordinary_request_still_goes_all_the_way_through(demo_ctx: AppContext) -> None:
    request, outcome = _run_sample(demo_ctx, "sm_grocery_run")
    settled = demo_ctx.store.get_request(request.id)
    assert settled is not None
    assert settled.needs_outreach()
    assert settled.status is RequestStatus.CONFIRMED
    assert settled.attempts, "a real request still gets somebody asked"
    assert outcome.interrupted is False


def test_the_fixture_plans_mark_the_two_non_jobs(demo_ctx: AppContext) -> None:
    assert SAMPLE_PLANS["sm_thank_you"].is_request is False
    assert SAMPLE_PLANS["sm_duplicate_dialysis"].duplicate is True
    others = {
        sample_id: plan
        for sample_id, plan in SAMPLE_PLANS.items()
        if sample_id not in ("sm_thank_you", "sm_duplicate_dialysis")
    }
    assert all(plan.is_request and not plan.duplicate for plan in others.values())

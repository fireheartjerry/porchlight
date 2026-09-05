"""The Quiet Log has to read like a colleague's notes, not a stack trace.

These tests pin the wording rules that make that true: names instead of ids, the reply itself
instead of an outcome enum, no raw tool names anywhere on the porch, and bookkeeping marked
invisible so the coordinator reads the story rather than the mechanics.
"""

from __future__ import annotations

import re

import pytest
from a_helpers import THURSDAY_MORNING, make_ctx, make_request

from porchlight.context import AppContext
from porchlight.models import Category, LogKind, Volunteer
from porchlight.tools.messaging import schedule_message_impl, send_message_impl
from porchlight.tools.records import assign_volunteer_impl, record_attempt_impl, remember_impl
from porchlight.tools.summaries import SUMMARIZERS, call_phrase, describe_tool, display_name, first_name

RAW_NAME = re.compile(r"[a-z]+_[a-z]+")
"""A snake_case token — what a tool name looks like, and what must never reach the porch."""


@pytest.fixture
def actx(store, clock) -> AppContext:
    """A context with the simulated channel and SQLite long-term memory."""
    return make_ctx(store, clock)


def test_first_name_skips_honorifics() -> None:
    assert first_name("Mrs. Chen") == "Chen"
    assert first_name("Maria Alvarez") == "Maria"
    assert first_name(None) == "them"


def test_display_name_refuses_to_print_a_phone_number() -> None:
    assert display_name("+1-555-0299") == "a new neighbour"
    assert display_name("nobody@example.org") == "a new neighbour"
    assert display_name("Femi Adeyemi") == "Femi Adeyemi"


def test_intake_reads_like_someone_opened_the_message(actx: AppContext) -> None:
    note = describe_tool(
        actx,
        "IntakeResult",
        {
            "requester_name": "Femi Adeyemi",
            "source": "email",
            "summary": "$180 short on an electric bill due Monday",
            "money_involved": True,
        },
    )
    assert note.summary == (
        "Read Femi Adeyemi's email: $180 short on an electric bill due Monday "
        "— the group's money is involved."
    )
    assert note.visible


def test_a_lookup_names_the_person_and_stays_off_the_porch(actx: AppContext) -> None:
    requester = actx.store.list_requesters()[0]
    note = describe_tool(
        actx,
        "lookup_requester_history",
        {"contact_or_name": requester.contact},
        {"requester": {"name": requester.name}, "recent_requests": []},
    )
    assert requester.name in note.summary
    assert note.visible is False, "a bare lookup is bookkeeping"


def test_the_shortlist_says_why_that_person(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock, zone="Riverside", category=Category.RIDE)
    maria = actx.store.get_volunteer("vol_maria")
    assert isinstance(maria, Volunteer)
    note = describe_tool(
        actx,
        "MatchPlan",
        {
            "request_id": request.id,
            "candidates": [
                {"volunteer_id": "vol_maria", "score": 0.9, "rationale": "has drive for ride"},
                {"volunteer_id": "vol_devon", "score": 0.7, "rationale": "covers Riverside"},
            ],
        },
    )
    assert note.summary.startswith("Shortlisted Maria Alvarez (")
    assert "drives" in note.summary
    assert note.summary.endswith("then Devon Clarke.")


def test_asking_a_volunteer_says_who_and_what(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock, summary="Ride to dialysis", window_start=THURSDAY_MORNING)
    send_message_impl(actx, request.id, "volunteer", "vol_maria", "Hi Maria, are you free?")
    # The simulated channel answers straight away, so the ask is not the newest row.
    entry = next(e for e in actx.store.list_log(request_id=request.id) if e.summary.startswith("Asked"))
    assert entry.summary == "Asked Maria: Ride to dialysis Thursday 9am."
    assert entry.visible and entry.kind is LogKind.MESSAGE_SENT
    assert entry.detail["body"] == "Hi Maria, are you free?"


def test_a_decline_quotes_the_reply_the_volunteer_actually_sent(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock)
    record_attempt_impl(
        actx, request.id, "vol_maria", "declined", "Sorry, not after four — I have my grandson."
    )
    entry = actx.store.list_log(request_id=request.id)[0]
    assert entry.summary.startswith("Maria can't — “Sorry, not after four")
    assert "Trying the next person." in entry.summary
    assert entry.detail["reply"].startswith("Sorry, not after four")


def test_an_acceptance_is_told_once_by_the_confirmation(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock, summary="Ride to dialysis")
    record_attempt_impl(actx, request.id, "vol_maria", "accepted", "Yes of course.")
    assign_volunteer_impl(actx, request.id, "vol_maria")

    rows = {event.summary: event for event in actx.store.list_log(request_id=request.id)}
    assert rows["Maria said yes — “Yes of course.”."].visible is False, "the confirmation says it better"
    confirmed = rows["Maria Alvarez said yes — confirmed for: Ride to dialysis"]
    assert confirmed.visible


def test_a_message_held_for_quiet_hours_says_so(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock)
    morning = clock.now().replace(hour=12, minute=0, second=0, microsecond=0)  # 08:00 in Toronto
    schedule_message_impl(actx, request.id, "volunteer", "vol_maria", "Morning Maria…", morning.isoformat())
    entry = actx.store.list_log(request_id=request.id)[0]
    assert entry.summary == "Held the message to Maria until Tuesday 8am — quiet hours here."


def test_a_reminder_says_when_it_will_land(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock)
    when = THURSDAY_MORNING.replace(hour=22)  # 18:00 in Toronto, well outside quiet hours
    schedule_message_impl(
        actx, request.id, "volunteer", "vol_maria", "Reminder: the ride is tomorrow", when.isoformat()
    )
    entry = actx.store.list_log(request_id=request.id)[0]
    assert entry.summary == "Set a reminder for Maria on Thursday 6pm."


def test_a_memory_note_is_quoted_as_written(actx: AppContext) -> None:
    remember_impl(actx, "Ezra prefers Maria when she is free.", "vol_maria", "preference")
    entry = actx.store.list_log()[0]
    assert entry.summary == "Remembered: Ezra prefers Maria when she is free."
    assert entry.kind is LogKind.MEMORY and entry.visible


def test_an_unknown_tool_never_puts_its_own_name_on_the_porch(actx: AppContext) -> None:
    note = describe_tool(actx, "some_new_tool", {"whatever": 1})
    assert note.visible is False
    assert note.summary == "Ran some new tool."


def test_a_stopped_call_says_what_it_was_about_to_do(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock)
    note = describe_tool(
        actx,
        "send_message",
        {"request_id": request.id, "to": "volunteer"},
        cancelled=True,
        cancel_message="DENIED: this looks like an emergency",
        card={"title": "Money is involved ($180)"},
    )
    assert note.summary == "Paused before sending that message — Money is involved ($180). Card raised."


def test_every_summarizer_writes_a_sentence_without_a_tool_name(actx: AppContext, clock) -> None:
    """Whatever the inputs, nothing snake_case reaches a visible summary."""
    request = make_request(actx.store, clock)
    for name in SUMMARIZERS:
        note = describe_tool(actx, name, {"request_id": request.id}, None)
        assert note.summary and note.summary[0].isupper(), name
        if note.visible:
            assert not RAW_NAME.search(note.summary), f"{name}: {note.summary}"


def test_the_trace_says_what_an_agent_is_doing_not_which_function(actx: AppContext) -> None:
    assert call_phrase("send_message", "outreach") == "Outreach is sending a message…"
    assert call_phrase("MatchPlan", "matcher") == "Matcher is settling on a shortlist…"
    assert call_phrase("SomethingNew", "matcher") == "Matcher is finishing up (SomethingNew)…"


def test_a_volunteer_who_says_yes_appears_once_with_their_reply(actx: AppContext, clock) -> None:
    """The drawer used to show the same person accepting twice — once without their words."""
    request = make_request(actx.store, clock)
    record_attempt_impl(actx, request.id, "vol_maria", "accepted", "Yes of course, Thursday works.")
    assign_volunteer_impl(actx, request.id, "vol_maria")

    settled = actx.store.get_request(request.id)
    assert settled is not None
    accepted = [a for a in settled.attempts if a.volunteer_id == "vol_maria"]
    assert len(accepted) == 1
    assert accepted[0].note == "Yes of course, Thursday works."


def test_policy_guidance_never_shows_its_machinery(actx: AppContext, clock) -> None:
    """A guidance verdict is a nudge at the model, not a line for the porch."""
    request = make_request(actx.store, clock)
    note = describe_tool(
        actx,
        "send_message",
        {"request_id": request.id, "to": "volunteer", "recipient_id": "vol_maria", "body": "Hi"},
        None,
        cancelled=True,
        cancel_message=(
            "GUIDANCE: [porchlight-policy] It is quiet hours for Maple Street Mutual Aid. "
            "Do not send this now. Call schedule_message with the same body and "
            "send_at_iso='2026-09-05T12:00:00+00:00' so it lands first thing in the morning."
        ),
    )
    assert "GUIDANCE" not in note.summary
    assert "porchlight-policy" not in note.summary
    assert "schedule_message" not in note.summary
    assert note.summary == "Held off sending that message — it is quiet hours for Maple Street Mutual Aid."
    # The schedule_message row a beat later tells this better, so this one is bookkeeping.
    assert note.visible is False


def test_a_denial_still_reaches_the_porch_in_plain_words(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock)
    note = describe_tool(
        actx,
        "assign_volunteer",
        {"request_id": request.id, "volunteer_id": "vol_maria"},
        None,
        cancelled=True,
        cancel_message="DENIED: [porchlight-policy] Nobody has agreed to this yet.",
    )
    assert note.summary == "Stopped before confirming anyone — Nobody has agreed to this yet."
    assert note.visible is True


def test_close_out_note_never_carries_a_request_id(actx: AppContext, clock) -> None:
    request = make_request(actx.store, clock)
    note = describe_tool(
        actx,
        "close_request",
        {"request_id": request.id, "outcome": "cancelled", "note": f"duplicate of {request.id}"},
        None,
    )
    assert request.id not in note.summary
    assert "the earlier one" in note.summary

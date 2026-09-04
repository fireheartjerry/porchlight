"""The Maple Street fixtures must be coherent, seedable, and cover the policy table."""

from __future__ import annotations

from porchlight.clock import FrozenClock
from porchlight.models import Category, RequestStatus, Volunteer
from porchlight.sim import fixtures
from porchlight.sim.fixtures import (
    REQUESTERS,
    SAMPLE_MESSAGES,
    SCRIPTED_REPLIES,
    VOLUNTEERS,
    ZONES,
    reply_for,
    sample_by_id,
    sample_payloads,
    samples_expecting,
    seed_store,
)
from porchlight.store.sqlite_store import SqliteStore


def test_roster_shape() -> None:
    assert len(VOLUNTEERS) == 14
    assert len(REQUESTERS) == 8
    assert len(ZONES) == 5
    assert len({v.id for v in VOLUNTEERS}) == 14
    assert len({v.name for v in VOLUNTEERS}) == 14


def test_every_volunteer_is_well_formed() -> None:
    for volunteer in VOLUNTEERS:
        assert volunteer.id.startswith("vol_")
        assert volunteer.zones and set(volunteer.zones) <= set(ZONES)
        assert volunteer.skills
        assert volunteer.availability
        assert volunteer.max_per_week >= 1
        assert volunteer.persona, f"{volunteer.name} needs a simulator persona"


def test_every_requester_is_well_formed() -> None:
    for requester in REQUESTERS:
        assert requester.id.startswith("rqr_")
        assert requester.contact
        assert requester.zone in ZONES
        assert requester.history_count >= 0


def test_roster_covers_every_category() -> None:
    for category in Category:
        assert any(v.can_do(category) for v in VOLUNTEERS), f"nobody can do {category}"


def test_roster_covers_every_zone() -> None:
    covered = {zone for volunteer in VOLUNTEERS for zone in volunteer.zones}
    assert covered == set(ZONES)


def test_roster_includes_vetted_and_unvetted() -> None:
    assert any(v.vetted for v in VOLUNTEERS)
    assert any(not v.vetted for v in VOLUNTEERS)


def test_sample_messages_shape() -> None:
    assert len(SAMPLE_MESSAGES) == 24
    ids = [message["id"] for message in SAMPLE_MESSAGES]
    assert len(set(ids)) == len(ids)
    for message in SAMPLE_MESSAGES:
        assert message["expected"] in {"quiet", "card"}
        assert message["text"].strip()
        assert message["contact"]
        assert message["source"] in {"form", "email", "sms", "voicemail", "paper", "api"}
        if message["expected"] == "card":
            assert message["expected_kind"] in {
                "safety",
                "money",
                "vetting",
                "unmatched",
                "concern",
                "policy",
            }
        else:
            assert message["expected_kind"] is None


def test_sample_messages_cover_the_policy_table() -> None:
    kinds = {m["expected_kind"] for m in SAMPLE_MESSAGES if m["expected"] == "card"}
    assert {"safety", "money", "vetting", "concern", "unmatched"} <= kinds
    assert len(samples_expecting("quiet")) >= 15
    assert len(samples_expecting("card")) >= 6


def test_named_scenarios_from_the_demo_script_exist() -> None:
    for sample_id in (
        "sm_dialysis_ride",
        "sm_child_home_alone",
        "sm_electric_bill",
        "sm_first_time_in_home",
        "sm_volunteer_concern",
        "sm_chest_pain",
        "sm_duplicate_dialysis",
        "sm_conflicting_times",
        "sm_thank_you",
        "sm_spanish_request",
        "sm_garbled_voicemail",
        "sm_flexible_window",
        "sm_urgent_ride",
    ):
        assert sample_by_id(sample_id) is not None, sample_id
    assert sample_by_id("nope") is None


def test_sample_payloads_are_plain_dicts() -> None:
    payloads = sample_payloads()
    assert len(payloads) == len(SAMPLE_MESSAGES)
    assert all(isinstance(payload, dict) for payload in payloads)


def test_scripted_replies_exist_for_every_volunteer() -> None:
    assert set(SCRIPTED_REPLIES) == {v.id for v in VOLUNTEERS}
    for volunteer_id, replies in SCRIPTED_REPLIES.items():
        assert len(replies) >= 3, volunteer_id
        assert all(reply.strip() for reply in replies)


def test_reply_for_cycles_and_falls_back() -> None:
    first = reply_for("vol_maria", 0)
    assert first == reply_for("vol_maria", len(SCRIPTED_REPLIES["vol_maria"]))
    assert reply_for("vol_unknown", 1) in fixtures.DEFAULT_REPLIES


def test_seed_store_populates_everything(clock: FrozenClock) -> None:
    store = SqliteStore(":memory:")
    counts = seed_store(store, clock)

    assert counts == {"volunteers": 14, "requesters": 8, "requests": 4}
    assert len(store.list_volunteers()) == 14
    assert len(store.list_requesters()) == 8
    assert len(store.list_requests()) == 4
    assert store.get_group_settings().name == "Maple Street Mutual Aid"
    assert store.get_group_settings().zones == ZONES

    maria = store.get_volunteer("vol_maria")
    assert isinstance(maria, Volunteer)
    assert maria.stats.last_active is not None
    assert maria.created_at < clock.now()

    history = store.list_requests(RequestStatus.COMPLETED)
    assert len(history) == 4
    assert all(request.assigned_volunteer_id for request in history)
    store.close()


def test_seed_store_is_idempotent(clock: FrozenClock) -> None:
    store = SqliteStore(":memory:")
    seed_store(store, clock)
    seed_store(store, clock)
    assert len(store.list_volunteers()) == 14
    store.close()


def test_seeded_history_links_to_real_people(store: SqliteStore) -> None:
    for request in store.list_requests():
        assert store.get_requester(request.requester_id or "") is not None
        assert store.get_volunteer(request.assigned_volunteer_id or "") is not None

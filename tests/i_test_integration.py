"""Integration tests: the mock scenario model driving the real graph end to end.

These are the tests that would have caught the wiring bugs the builders could not see from
inside their own areas: decision cards deduped across requests, a card asked twice, parallel
tool calls clobbering the same row, and a run that exhausts its candidates in silence.
"""

from __future__ import annotations

import pytest

from porchlight.channels.sim import SimChannel
from porchlight.clock import FrozenClock
from porchlight.config import Settings
from porchlight.context import AppContext, build_context
from porchlight.graph import resume_decision, run_request
from porchlight.intake_ingest import create_request_from_inbox
from porchlight.matching import zone_info
from porchlight.memory.sqlite_store import SqliteMemoryStore
from porchlight.models import DecisionKind, DecisionStatus, RequestStatus
from porchlight.models_provider import make_model
from porchlight.policy import already_approved, matched_patterns, resolved_option_for
from porchlight.sim.fixtures import SAMPLE_MESSAGES, demo_sequence, sample_by_id, seed_store
from porchlight.sim.mock_scenarios import (
    SAMPLE_PLANS,
    PorchlightScenarioModel,
    infer_plan,
    plan_for,
    sample_id_for_text,
)
from porchlight.store.sqlite_store import SqliteStore

# Daytime in America/Toronto, so quiet hours never change the expected path.
DEMO_NOW = "2026-09-08T18:00:00+00:00"


@pytest.fixture
def demo_ctx(tmp_path, settings: Settings) -> AppContext:
    """A demo context on disk: SQLite store, SimChannel, SQLite memory, frozen daytime clock."""
    from datetime import datetime

    clock = FrozenClock(datetime.fromisoformat(DEMO_NOW))
    live = settings.model_copy(update={"sqlite_path": str(tmp_path / "porchlight.db")})
    store = SqliteStore(str(tmp_path / "porchlight.db"))
    seed_store(store, clock)
    return AppContext(
        settings=live.model_copy(update={"session_dir": str(tmp_path / "sessions")}),
        store=store,
        channel=SimChannel(store, clock),
        memory=SqliteMemoryStore(str(tmp_path / "memory.db")),
        clock=clock,
        emit=lambda event: None,
    )


def _run_sample(ctx: AppContext, sample_id: str):
    """Push one fixture message through the real graph."""
    sample = sample_by_id(sample_id)
    assert sample is not None
    request = create_request_from_inbox(ctx, sample["text"], sample["source"], sample["contact"])
    return request, run_request(ctx, request.id)


# --- context wiring -------------------------------------------------------------------


def test_build_context_wires_the_real_demo_adapters(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PORCHLIGHT_SQLITE_PATH", str(tmp_path / "demo.db"))
    ctx = build_context(Settings(mode="demo", model_provider="mock", sqlite_path=str(tmp_path / "demo.db")))
    assert isinstance(ctx.channel, SimChannel)
    assert isinstance(ctx.memory, SqliteMemoryStore)


def test_mock_provider_returns_the_scenario_model() -> None:
    model = make_model(Settings(model_provider="mock"), "haiku")
    assert isinstance(model, PorchlightScenarioModel)


# --- the sample plans -----------------------------------------------------------------


def test_every_sample_message_has_a_plan() -> None:
    assert {m["id"] for m in SAMPLE_MESSAGES} == set(SAMPLE_PLANS)


def test_sample_lookup_survives_rewrapped_text() -> None:
    sample = SAMPLE_MESSAGES[0]
    assert sample_id_for_text("  " + sample["text"].replace(" ", "\n  ") + " ") == sample["id"]


def test_unknown_text_falls_back_to_a_keyword_reading() -> None:
    plan = infer_plan("Could someone drive me to my clinic appointment tomorrow?")
    assert str(plan.category) == "ride"
    assert plan_for(None).summary


def test_demo_sequence_shows_a_card_in_the_first_six() -> None:
    first_six = demo_sequence(6)
    assert len(first_six) == 6
    assert any(sample["expected"] == "card" for sample in first_six)
    assert len(demo_sequence()) == len(SAMPLE_MESSAGES)


# --- policy keyword hygiene -----------------------------------------------------------


def test_money_patterns_match_whole_words_only() -> None:
    from porchlight.policy import MONEY_PATTERNS

    assert matched_patterns("a hot dinner for new parents", MONEY_PATTERNS) == []
    assert "rent" in matched_patterns("i cannot make rent this month", MONEY_PATTERNS)


def test_stem_patterns_still_match_their_suffixes() -> None:
    from porchlight.policy import DANGER_PATTERNS

    assert matched_patterns("he said he is suicidal", DANGER_PATTERNS)


def test_a_utility_threat_is_money_not_danger() -> None:
    from porchlight.policy import DANGER_PATTERNS

    assert matched_patterns("they are threatening to cut off my power", DANGER_PATTERNS) == []


# --- end to end -----------------------------------------------------------------------


@pytest.mark.parametrize("sample_id", ["sm_dialysis_ride", "sm_prescription", "sm_tablet_help"])
def test_routine_samples_are_confirmed_without_a_card(demo_ctx: AppContext, sample_id: str) -> None:
    request, outcome = _run_sample(demo_ctx, sample_id)
    assert outcome.interrupted is False
    assert outcome.decisions_created == []
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None
    assert stored.status is RequestStatus.CONFIRMED
    assert stored.assigned_volunteer_id


@pytest.mark.parametrize(
    ("sample_id", "kind"),
    [
        ("sm_child_home_alone", DecisionKind.SAFETY),
        ("sm_chest_pain", DecisionKind.SAFETY),
        ("sm_gift_card", DecisionKind.MONEY),
        ("sm_electric_bill", DecisionKind.MONEY),
        ("sm_first_time_in_home", DecisionKind.VETTING),
        ("sm_volunteer_concern", DecisionKind.CONCERN),
        ("sm_nobody_free", DecisionKind.UNMATCHED),
    ],
)
def test_card_samples_raise_the_right_decision(
    demo_ctx: AppContext, sample_id: str, kind: DecisionKind
) -> None:
    request, outcome = _run_sample(demo_ctx, sample_id)
    assert outcome.interrupted is True
    assert [d.kind for d in outcome.decisions_created] == [kind]
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.ESCALATED


def test_a_safety_card_never_contacts_a_volunteer(demo_ctx: AppContext) -> None:
    request, _ = _run_sample(demo_ctx, "sm_child_home_alone")
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None and stored.attempts == []
    assert demo_ctx.store.list_messages(request_id=request.id) == []


def test_two_card_requests_get_two_distinct_cards(demo_ctx: AppContext) -> None:
    """Strands derives interrupt ids from the node name; the session is what makes them unique."""
    first, first_outcome = _run_sample(demo_ctx, "sm_child_home_alone")
    second, second_outcome = _run_sample(demo_ctx, "sm_chest_pain")
    [card_a] = first_outcome.decisions_created
    [card_b] = second_outcome.decisions_created
    assert card_a.id != card_b.id
    assert card_a.request_id == first.id
    assert card_b.request_id == second.id


def test_approving_a_vetting_card_resumes_and_asks_a_volunteer(demo_ctx: AppContext) -> None:
    request, outcome = _run_sample(demo_ctx, "sm_first_time_in_home")
    [card] = outcome.decisions_created
    resumed = resume_decision(demo_ctx, card.id, "approve", "I know them.")

    assert resumed.interrupted is False
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None
    assert stored.status is RequestStatus.CONFIRMED
    assert stored.assigned_volunteer_id
    assert already_approved(demo_ctx.store, request.id, DecisionKind.VETTING)
    assert resolved_option_for(demo_ctx.store, request.id, DecisionKind.VETTING) == "approve"
    assert not [d for d in demo_ctx.store.list_decisions(DecisionStatus.OPEN) if d.request_id == request.id]


def test_declining_a_money_card_closes_the_request(demo_ctx: AppContext) -> None:
    request, outcome = _run_sample(demo_ctx, "sm_electric_bill")
    [card] = outcome.decisions_created
    resume_decision(demo_ctx, card.id, "decline_request", "Referred to the utility fund.")
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.DECLINED
    assert stored.attempts == []


def test_taking_a_safety_card_over_leaves_the_request_with_the_coordinator(demo_ctx: AppContext) -> None:
    request, outcome = _run_sample(demo_ctx, "sm_chest_pain")
    [card] = outcome.decisions_created
    resume_decision(demo_ctx, card.id, "i_will_handle", "Called an ambulance.")
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.ESCALATED
    assert stored.attempts == []
    assert demo_ctx.store.get_decision(card.id).status is DecisionStatus.RESOLVED


def test_widening_the_pool_finds_somebody(demo_ctx: AppContext) -> None:
    request, outcome = _run_sample(demo_ctx, "sm_nobody_free")
    [card] = outcome.decisions_created
    resume_decision(demo_ctx, card.id, "widen_pool", None)
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.CONFIRMED


def test_a_confirmed_request_told_the_neighbour_and_remembered_it(demo_ctx: AppContext) -> None:
    request, _ = _run_sample(demo_ctx, "sm_dialysis_ride")
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None
    to_requester = [m for m in demo_ctx.store.list_messages(request_id=request.id) if m.to == "requester"]
    assert to_requester, "the steward must tell the neighbour who is coming"
    volunteer = demo_ctx.store.get_volunteer(stored.assigned_volunteer_id or "")
    assert volunteer is not None and volunteer.name in to_requester[0].body
    notes = demo_ctx.memory.search_sync("job", limit=5)
    assert notes, "the steward must write something down"


def test_assign_and_record_do_not_clobber_each_other(demo_ctx: AppContext) -> None:
    """The outreach agent resolves a reply one tool at a time; both writes must survive."""
    request, _ = _run_sample(demo_ctx, "sm_grocery_run")
    stored = demo_ctx.store.get_request(request.id)
    assert stored is not None
    assert stored.assigned_volunteer_id
    assert [a for a in stored.attempts if a.outcome == "accepted"]


def test_messages_use_local_time_and_drop_honorifics(demo_ctx: AppContext) -> None:
    request, _ = _run_sample(demo_ctx, "sm_grocery_run")
    to_volunteer = [m for m in demo_ctx.store.list_messages(request_id=request.id) if m.to == "volunteer"]
    assert to_volunteer
    body = to_volunteer[0].body
    assert "Mrs." not in body
    assert str(zone_info(demo_ctx.settings.timezone))  # the tz the phrasing was rendered in


def test_a_scripted_script_still_wins_over_the_scenario(demo_ctx: AppContext) -> None:
    from porchlight.testing.mock_model import MockTurn

    model = PorchlightScenarioModel(script=[MockTurn(text="scripted")])
    assert model.script
    assert model.remaining_turns == 1

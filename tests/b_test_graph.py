"""End-to-end graph behaviour, driven by scripted models — no AWS, no network.

Four scenarios, matching the demo script: a routine request that never needs the coordinator,
a safety request that raises a decision card and is resumed, a bounded retry cycle across
declining volunteers, and an interrupt that survives being rebuilt from the session directory.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from porchlight.agents.outputs import IntakeResult, OutreachStep, StewardResult
from porchlight.clock import FrozenClock
from porchlight.config import Settings
from porchlight.context import AppContext, NullChannel
from porchlight.graph import (
    RunOutcome,
    build_graph,
    resume_decision,
    run_brief,
    run_request,
    run_sweep,
)
from porchlight.models import (
    AidRequest,
    Category,
    DecisionKind,
    DecisionStatus,
    MatchCandidate,
    MatchPlan,
    MessageStatus,
    OutboundMessage,
    Recipient,
    RequestStatus,
    Source,
    Urgency,
)
from porchlight.sim.fixtures import seed_store
from porchlight.store.sqlite_store import SqliteStore
from porchlight.testing.mock_model import MockTurn, ScenarioModel

FROZEN_NOW = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture
def gclock() -> FrozenClock:
    """A clock frozen at Tuesday midday, well outside quiet hours."""
    return FrozenClock(FROZEN_NOW)


@pytest.fixture
def gctx(tmp_path: Path, gclock: FrozenClock) -> Iterator[AppContext]:
    """A context whose sessions land in a temp directory, so graphs can be rebuilt."""
    settings = Settings(
        mode="demo",
        model_provider="mock",
        store="sqlite",
        sqlite_path=":memory:",
        session_dir=str(tmp_path / "sessions"),
        max_candidates=3,
        confidence_threshold=0.55,
    )
    store = SqliteStore(":memory:")
    seed_store(store, gclock)
    events: list[dict] = []
    ctx = AppContext(
        settings=settings,
        store=store,
        channel=NullChannel(),
        memory=None,
        clock=gclock,
        emit=events.append,
    )
    ctx.emitted = events  # type: ignore[attr-defined]
    yield ctx
    store.close()


def use_scenario(monkeypatch: pytest.MonkeyPatch, scenarios: dict[str, list[MockTurn]]) -> ScenarioModel:
    """Route every agent's model through one scripted :class:`ScenarioModel`."""
    model = ScenarioModel(scenarios)
    monkeypatch.setattr("porchlight.agents.base.make_model", lambda settings, tier: model)
    return model


def new_request(ctx: AppContext, text: str, **fields: Any) -> AidRequest:
    """Persist a fresh inbound request."""
    request = AidRequest(raw_text=text, source=Source.SMS, **fields)
    ctx.store.put_request(request)
    return request


def volunteer_ids(ctx: AppContext, category: Category, count: int) -> list[str]:
    """Ids of volunteers who can actually do ``category``."""
    matching = [v for v in ctx.store.list_volunteers() if v.active and v.can_do(category)]
    assert len(matching) >= count, "the fixture roster is too small for this test"
    return [v.id for v in matching[:count]]


def plan(request_id: str, volunteer_id: str, confidence: float = 0.86) -> MatchPlan:
    """A confident single-candidate plan."""
    return MatchPlan(
        request_id=request_id,
        candidates=[MatchCandidate(volunteer_id=volunteer_id, score=0.9, rationale="free and nearby")],
        confidence=confidence,
        notes="",
    )


def accept_turns(request_id: str, volunteer_id: str) -> list[MockTurn]:
    """Outreach turns that assign a volunteer and report an acceptance."""
    return [
        MockTurn(tool_calls=[("assign_volunteer", {"request_id": request_id, "volunteer_id": volunteer_id})]),
        MockTurn(structured=OutreachStep(action="accepted", volunteer_id=volunteer_id, note="said yes")),
    ]


def decline_turns(request_id: str, volunteer_id: str) -> list[MockTurn]:
    """Outreach turns that record a decline and ask the graph for the next candidate."""
    return [
        MockTurn(
            tool_calls=[
                (
                    "record_attempt",
                    {
                        "request_id": request_id,
                        "volunteer_id": volunteer_id,
                        "outcome": "declined",
                        "note": "busy this week",
                    },
                )
            ]
        ),
        MockTurn(structured=OutreachStep(action="declined", volunteer_id=volunteer_id, note="a no")),
    ]


# --------------------------------------------------------------------------------------
# 1. Routine request — nobody is interrupted
# --------------------------------------------------------------------------------------


def test_routine_request_is_handled_without_the_coordinator(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = new_request(gctx, "Hi it's Ezra. I need a ride to dialysis Thursday at 9am, back around 1.")
    volunteer = volunteer_ids(gctx, Category.RIDE, 1)[0]
    use_scenario(
        monkeypatch,
        {
            "intake": [
                MockTurn(
                    structured=IntakeResult(
                        summary="Ride to dialysis Thursday 9am",
                        category=Category.RIDE,
                        urgency=Urgency.NORMAL,
                        location_zone="Riverside",
                    )
                )
            ],
            "matcher": [MockTurn(structured=plan(request.id, volunteer))],
            "outreach": accept_turns(request.id, volunteer),
            "steward": [
                MockTurn(structured=StewardResult(confirmed=True, outcome="confirmed", summary="Told Ezra"))
            ],
        },
    )

    outcome = run_request(gctx, request.id)

    assert isinstance(outcome, RunOutcome)
    assert outcome.interrupted is False
    assert outcome.decisions_created == []
    assert outcome.status is RequestStatus.CONFIRMED
    assert gctx.store.list_decisions(DecisionStatus.OPEN) == []

    stored = gctx.store.get_request(request.id)
    assert stored is not None
    assert stored.assigned_volunteer_id == volunteer
    assert stored.summary == "Ride to dialysis Thursday 9am"
    assert outcome.log_events > 0

    nodes = [event["detail"].get("node") for event in gctx.emitted if event["type"] == "node_start"]  # type: ignore[attr-defined]
    assert nodes == ["intake", "matcher", "outreach", "steward"]


def test_unknown_request_is_reported_not_raised(gctx: AppContext) -> None:
    outcome = run_request(gctx, "req_missing")
    assert outcome.interrupted is False
    assert "unknown request" in outcome.summary


# --------------------------------------------------------------------------------------
# 2. Safety request — a decision card, then a resume
# --------------------------------------------------------------------------------------


def _safety_scenario(request: AidRequest, volunteer: str) -> dict[str, list[MockTurn]]:
    return {
        "intake": [
            MockTurn(
                structured=IntakeResult(
                    summary="Child alone next door, stove on",
                    category=Category.OTHER,
                    urgency=Urgency.EMERGENCY,
                    safety_flags=["kid is home alone", "the stove is on"],
                )
            )
        ],
        "matcher": [MockTurn(structured=plan(request.id, volunteer))] * 3,
        "outreach": accept_turns(request.id, volunteer),
        "steward": [MockTurn(structured=StewardResult(outcome="pending"))],
    }


def test_safety_request_raises_a_card_and_escalates(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = new_request(gctx, "My neighbour's kid is home alone next door and I can smell the stove is on.")
    volunteer = volunteer_ids(gctx, Category.RIDE, 1)[0]
    use_scenario(monkeypatch, _safety_scenario(request, volunteer))

    outcome = run_request(gctx, request.id)

    assert outcome.interrupted is True
    assert len(outcome.decisions_created) == 1
    card = outcome.decisions_created[0]
    assert card.kind is DecisionKind.SAFETY
    assert card.node == "matcher"
    assert card.interrupt_id and card.session_id == request.id
    assert "i_will_handle" in card.option_ids()
    assert outcome.status is RequestStatus.ESCALATED

    stored = gctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.ESCALATED
    assert stored.assigned_volunteer_id is None
    assert [event for event in gctx.emitted if event["type"] == "decision"]  # type: ignore[attr-defined]


def test_resume_with_i_will_handle_resolves_the_card(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = new_request(gctx, "My neighbour's kid is home alone next door and I can smell the stove is on.")
    volunteer = volunteer_ids(gctx, Category.RIDE, 1)[0]
    use_scenario(monkeypatch, _safety_scenario(request, volunteer))
    card = run_request(gctx, request.id).decisions_created[0]

    resumed = resume_decision(gctx, card.id, "i_will_handle", "I'm walking over now")

    assert resumed.interrupted is False
    assert resumed.status is RequestStatus.ESCALATED
    stored_card = gctx.store.get_decision(card.id)
    assert stored_card is not None
    assert stored_card.status is DecisionStatus.RESOLVED
    assert stored_card.resolved_option == "i_will_handle"
    assert stored_card.resolved_note == "I'm walking over now"
    # The coordinator took it: no volunteer was ever asked.
    stored = gctx.store.get_request(request.id)
    assert stored is not None and stored.assigned_volunteer_id is None


def test_resuming_an_already_resolved_card_is_a_no_op(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = new_request(gctx, "the stove is on and the kid is home alone")
    volunteer = volunteer_ids(gctx, Category.RIDE, 1)[0]
    use_scenario(monkeypatch, _safety_scenario(request, volunteer))
    card = run_request(gctx, request.id).decisions_created[0]
    resume_decision(gctx, card.id, "i_will_handle")

    again = resume_decision(gctx, card.id, "approve")
    assert "already resolved" in again.summary


def test_resume_of_an_unknown_decision_is_reported(gctx: AppContext) -> None:
    assert "unknown decision" in resume_decision(gctx, "dec_nope", "approve").summary


# --------------------------------------------------------------------------------------
# 3. Two declines, then an acceptance — the bounded outreach cycle
# --------------------------------------------------------------------------------------


def test_two_declines_then_an_accept(gctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    request = new_request(gctx, "Could someone drive my mother to the eye doctor on Friday at 11?")
    first, second, third = volunteer_ids(gctx, Category.RIDE, 3)
    use_scenario(
        monkeypatch,
        {
            "intake": [
                MockTurn(structured=IntakeResult(summary="Ride to eye doctor", category=Category.RIDE))
            ],
            "matcher": [
                MockTurn(structured=plan(request.id, first)),
                MockTurn(structured=plan(request.id, second)),
                MockTurn(structured=plan(request.id, third)),
            ],
            "outreach": [
                *decline_turns(request.id, first),
                *decline_turns(request.id, second),
                *accept_turns(request.id, third),
            ],
            "steward": [MockTurn(structured=StewardResult(confirmed=True, outcome="confirmed"))],
        },
    )

    outcome = run_request(gctx, request.id)

    assert outcome.interrupted is False
    assert outcome.status is RequestStatus.CONFIRMED
    stored = gctx.store.get_request(request.id)
    assert stored is not None
    assert stored.assigned_volunteer_id == third
    outcomes = [attempt.outcome for attempt in stored.attempts]
    assert outcomes.count("declined") == 2
    assert "accepted" in outcomes

    nodes = [event["detail"].get("node") for event in gctx.emitted if event["type"] == "node_start"]  # type: ignore[attr-defined]
    assert nodes == ["intake", "matcher", "outreach", "matcher", "outreach", "matcher", "outreach", "steward"]


def test_a_thin_match_plan_raises_an_unmatched_card(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = new_request(gctx, "Long shot: a lift to Riverside at 4am on Sunday.")
    use_scenario(
        monkeypatch,
        {
            "intake": [MockTurn(structured=IntakeResult(summary="4am lift", category=Category.RIDE))],
            "matcher": [MockTurn(structured=MatchPlan(request_id=request.id, candidates=[], confidence=0.1))],
        },
    )

    outcome = run_request(gctx, request.id)

    assert outcome.interrupted is True
    card = outcome.decisions_created[0]
    assert card.kind is DecisionKind.UNMATCHED
    assert card.node == "outreach"
    assert {"widen_pool", "reschedule", "i_will_handle", "decline_request"} <= set(card.option_ids())


def test_declining_an_unmatched_card_closes_the_request(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = new_request(gctx, "Long shot: a lift to Riverside at 4am on Sunday.")
    use_scenario(
        monkeypatch,
        {
            "intake": [MockTurn(structured=IntakeResult(summary="4am lift", category=Category.RIDE))],
            "matcher": [MockTurn(structured=MatchPlan(request_id=request.id, candidates=[], confidence=0.1))],
            "outreach": [MockTurn(structured=OutreachStep(action="escalate", note="nobody free"))],
        },
    )
    card = run_request(gctx, request.id).decisions_created[0]

    resumed = resume_decision(gctx, card.id, "decline_request", "we couldn't cover it")

    assert resumed.status is RequestStatus.DECLINED
    stored = gctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.DECLINED


# --------------------------------------------------------------------------------------
# 4. The interrupt survives a fresh process
# --------------------------------------------------------------------------------------


def test_interrupt_is_restored_from_the_session_directory(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = new_request(gctx, "The kid is home alone and the stove is on next door.")
    volunteer = volunteer_ids(gctx, Category.RIDE, 1)[0]
    use_scenario(monkeypatch, _safety_scenario(request, volunteer))
    card = run_request(gctx, request.id).decisions_created[0]

    # A fresh process: same durable store and session directory, brand-new context and graph.
    later = AppContext(
        settings=gctx.settings,
        store=gctx.store,
        channel=NullChannel(),
        memory=None,
        clock=gctx.clock,
        emit=lambda event: None,
    )
    rebuilt = build_graph(later, session_id=request.id)

    assert {node.node_id for node in rebuilt.state.completed_nodes} == {"intake"}
    assert {node.node_id for node in rebuilt.state.interrupted_nodes} == {"matcher"}
    assert card.interrupt_id in rebuilt._interrupt_state.interrupts  # type: ignore[attr-defined]

    resumed = resume_decision(later, card.id, "i_will_handle", "picked it up the next morning")

    assert resumed.interrupted is False
    reloaded = later.store.get_decision(card.id)
    assert reloaded is not None and reloaded.status is DecisionStatus.RESOLVED


def test_session_files_are_written_under_the_configured_directory(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = new_request(gctx, "Ride to the pharmacy tomorrow.")
    volunteer = volunteer_ids(gctx, Category.RIDE, 1)[0]
    use_scenario(
        monkeypatch,
        {
            "intake": [MockTurn(structured=IntakeResult(summary="Pharmacy run", category=Category.ERRAND))],
            "matcher": [MockTurn(structured=plan(request.id, volunteer))],
            "outreach": accept_turns(request.id, volunteer),
            "steward": [MockTurn(structured=StewardResult(outcome="confirmed"))],
        },
    )
    run_request(gctx, request.id)

    root = Path(gctx.settings.session_dir)
    assert (root / f"session_{request.id}").is_dir()


# --------------------------------------------------------------------------------------
# Sweep and brief
# --------------------------------------------------------------------------------------


def test_sweep_sends_due_messages(gctx: AppContext) -> None:
    request = new_request(gctx, "ride")
    due = OutboundMessage(
        request_id=request.id,
        to=Recipient.VOLUNTEER,
        recipient_id="vol_maria",
        body="Reminder: Ezra's ride is tomorrow at 9.",
        scheduled_for=FROZEN_NOW - timedelta(hours=1),
        status=MessageStatus.SCHEDULED,
    )
    gctx.store.put_message(due)

    outcome = run_sweep(gctx)

    assert outcome.messages_sent == 1
    assert gctx.channel.sent[0].body.startswith("Reminder")  # type: ignore[attr-defined]


def test_sweep_escalates_a_request_running_out_of_time(gctx: AppContext) -> None:
    request = new_request(
        gctx,
        "ride to the clinic",
        status=RequestStatus.AWAITING_REPLY,
        window_start=FROZEN_NOW + timedelta(hours=2),
    )

    outcome = run_sweep(gctx)

    assert outcome.requests_escalated == 1
    assert outcome.decisions_created[0].kind is DecisionKind.UNMATCHED
    stored = gctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.ESCALATED


def test_sweep_leaves_a_healthy_request_alone(gctx: AppContext) -> None:
    new_request(
        gctx,
        "ride next week",
        status=RequestStatus.AWAITING_REPLY,
        window_start=FROZEN_NOW + timedelta(days=4),
    )
    outcome = run_sweep(gctx)
    assert outcome.requests_escalated == 0
    assert outcome.requests_checked == 1


def test_brief_returns_markdown(gctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    from porchlight.agents.outputs import BriefResult

    use_scenario(
        monkeypatch,
        {"brief": [MockTurn(structured=BriefResult(markdown="# Tuesday\n\nNothing needs you."))]},
    )
    markdown = run_brief(gctx, FROZEN_NOW.date())
    assert markdown.startswith("# Tuesday")


def test_brief_falls_back_to_the_store(gctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    from porchlight.agents.outputs import BriefResult

    use_scenario(monkeypatch, {"brief": [MockTurn(structured=BriefResult(markdown=""))]})
    markdown = run_brief(gctx, FROZEN_NOW.date())
    assert gctx.settings.group_name in markdown
    assert "Needs you" in markdown


def test_widening_the_pool_lets_outreach_continue(gctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    request = new_request(gctx, "Ride to the clinic on Sunday morning.")
    volunteer = volunteer_ids(gctx, Category.RIDE, 1)[0]
    use_scenario(
        monkeypatch,
        {
            "intake": [MockTurn(structured=IntakeResult(summary="Sunday lift", category=Category.RIDE))],
            "matcher": [MockTurn(structured=MatchPlan(request_id=request.id, candidates=[], confidence=0.2))],
            "outreach": accept_turns(request.id, volunteer),
            "steward": [MockTurn(structured=StewardResult(confirmed=True, outcome="confirmed"))],
        },
    )
    card = run_request(gctx, request.id).decisions_created[0]

    resumed = resume_decision(gctx, card.id, "widen_pool", "try the next zone over")

    assert resumed.interrupted is False
    assert resumed.status is RequestStatus.CONFIRMED
    stored = gctx.store.get_request(request.id)
    assert stored is not None and stored.assigned_volunteer_id == volunteer


def test_i_will_handle_stops_outreach_reaching_a_volunteer(
    gctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unmatched card runs before outreach, so the policy must also refuse the tool calls."""
    request = new_request(gctx, "Ride to the clinic on Sunday morning.")
    volunteer = volunteer_ids(gctx, Category.RIDE, 1)[0]
    use_scenario(
        monkeypatch,
        {
            "intake": [MockTurn(structured=IntakeResult(summary="Sunday lift", category=Category.RIDE))],
            "matcher": [MockTurn(structured=MatchPlan(request_id=request.id, candidates=[], confidence=0.2))],
            "outreach": [
                MockTurn(
                    tool_calls=[
                        (
                            "send_message",
                            {
                                "request_id": request.id,
                                "to": "volunteer",
                                "recipient_id": volunteer,
                                "body": "Any chance you are free?",
                            },
                        )
                    ]
                ),
                MockTurn(structured=OutreachStep(action="escalate", note="coordinator has it")),
            ],
        },
    )
    card = run_request(gctx, request.id).decisions_created[0]

    resumed = resume_decision(gctx, card.id, "i_will_handle")

    assert resumed.status is RequestStatus.ESCALATED
    assert gctx.channel.sent == []  # type: ignore[attr-defined]
    denied = [entry for entry in gctx.store.list_log(request_id=request.id) if not entry.autonomous]
    assert denied, "the refused send should show up in the quiet log"

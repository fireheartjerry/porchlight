"""Safety beats the not-a-request short-circuit (``docs/LIVE-FIXES.md`` A).

The first live run on Bedrock produced the one intake result the graph had no answer for: the
"child home alone, stove on" message came back with ``is_request=false`` **and** two safety
flags **and** ``needs_human=true``. The graph read only ``is_request``, took the
intake → steward edge meant for thank-you notes, and the steward closed the request as
*cancelled* — no decision card, no coordinator, nothing on the porch.

Every test here scripts that exact intake result, or one of its siblings, and drives the real
graph. The steward is deliberately scripted to close things out the way it did live, so a
regression in the routing shows up as a cancelled request rather than as a missing assertion.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from porchlight.agents.outputs import IntakeResult, OutreachStep, StewardResult
from porchlight.agents.prompts import intake_prompt, steward_prompt
from porchlight.clock import FrozenClock
from porchlight.config import Settings
from porchlight.context import AppContext, NullChannel
from porchlight.graph import needs_coordinator, resume_decision, run_request
from porchlight.models import (
    AidRequest,
    Category,
    DecisionKind,
    MatchCandidate,
    MatchPlan,
    RequestStatus,
    Source,
    Urgency,
)
from porchlight.sim.fixtures import seed_store
from porchlight.store.sqlite_store import SqliteStore
from porchlight.testing.mock_model import MockTurn, ScenarioModel

FROZEN_NOW = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)
"""Tuesday midday: outside quiet hours, so nothing here is explained by the clock."""

CHILD_ALONE = "My neighbour's kid is home alone next door and I can smell the stove is on."

LIVE_INTAKE = IntakeResult(
    summary="Neighbour reports a child alone next door with the stove on",
    category=Category.OTHER,
    safety_flags=["kid is home alone", "the stove is on"],
    is_request=False,
    needs_human=True,
    reasoning="Read as a report rather than a request for help.",
)
"""What Claude Haiku actually returned on the live stack — ``urgency`` was never raised.

Kept at the default ``normal`` urgency on purpose: the safety flags alone have to be enough.
"""


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture
def lctx(tmp_path: Path) -> Iterator[AppContext]:
    """A graph context with sessions on disk, so an interrupt can be resumed."""
    clock = FrozenClock(FROZEN_NOW)
    store = SqliteStore(":memory:")
    seed_store(store, clock)
    events: list[dict] = []
    ctx = AppContext(
        settings=Settings(
            mode="demo",
            model_provider="mock",
            store="sqlite",
            sqlite_path=":memory:",
            session_dir=str(tmp_path / "sessions"),
            max_candidates=3,
            confidence_threshold=0.55,
        ),
        store=store,
        channel=NullChannel(),
        memory=None,
        clock=clock,
        emit=events.append,
    )
    ctx.emitted = events  # type: ignore[attr-defined]
    yield ctx
    store.close()


def _volunteer(ctx: AppContext) -> str:
    """Any active volunteer, so the matcher script is a real id."""
    return next(v.id for v in ctx.store.list_volunteers() if v.active)


def _script(ctx: AppContext, request: AidRequest, parsed: IntakeResult) -> dict[str, list[MockTurn]]:
    """Script every agent, including the two that must never run for a flagged message.

    The steward's turn is the live bug in miniature: given the chance, it closes the request as
    *cancelled*. If the graph ever hands a flagged message to it again, these tests fail.
    """
    volunteer = _volunteer(ctx)
    return {
        "intake": [MockTurn(structured=parsed)],
        "matcher": [
            MockTurn(
                structured=MatchPlan(
                    request_id=request.id,
                    candidates=[MatchCandidate(volunteer_id=volunteer, score=0.9, rationale="free")],
                    confidence=0.9,
                )
            )
        ]
        * 3,
        "outreach": [MockTurn(structured=OutreachStep(action="asked", volunteer_id=volunteer))] * 3,
        "steward": [MockTurn(structured=StewardResult(outcome="cancelled", summary="nothing to arrange"))]
        * 2,
    }


def _run(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch, parsed: IntakeResult, text: str = CHILD_ALONE
) -> tuple[AidRequest, Any]:
    """Push one message through the real graph with a scripted intake result."""
    request = AidRequest(raw_text=text, source=Source.SMS)
    ctx.store.put_request(request)
    model = ScenarioModel(_script(ctx, request, parsed))
    monkeypatch.setattr("porchlight.agents.base.make_model", lambda settings, tier: model)
    return request, run_request(ctx, request.id)


def _summaries(ctx: AppContext, request_id: str) -> list[str]:
    return [event.summary for event in ctx.store.list_log(request_id=request_id)]


# --------------------------------------------------------------------------------------
# The regression: the exact live intake result
# --------------------------------------------------------------------------------------


def test_the_live_intake_result_raises_a_safety_card_instead_of_cancelling(
    lctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, outcome = _run(lctx, monkeypatch, LIVE_INTAKE)

    assert outcome.interrupted is True
    [card] = outcome.decisions_created
    assert card.kind is DecisionKind.SAFETY
    assert card.node == "matcher"
    assert card.request_id == request.id
    assert "i_will_handle" in card.option_ids()

    stored = lctx.store.get_request(request.id)
    assert stored is not None
    assert stored.status is RequestStatus.ESCALATED
    assert stored.status is not RequestStatus.CANCELLED, "the live defect: closed as cancelled"
    assert stored.is_request is False, "intake's own reading is preserved, it just no longer decides"


def test_the_live_intake_result_asks_nobody_and_sends_nothing(
    lctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _ = _run(lctx, monkeypatch, LIVE_INTAKE)

    stored = lctx.store.get_request(request.id)
    assert stored is not None
    assert stored.attempts == [], "no volunteer may be asked about an emergency"
    assert stored.assigned_volunteer_id is None
    assert lctx.store.list_messages(request_id=request.id) == [], (
        "nothing goes out — not to a volunteer, and not the 'call 911' reply to the requester"
    )


def test_the_quiet_log_says_it_went_to_the_coordinator_not_that_it_was_ignored(
    lctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _ = _run(lctx, monkeypatch, LIVE_INTAKE)
    summaries = _summaries(lctx, request.id)

    assert any("goes to you" in summary for summary in summaries)
    assert not any("isn't asking for help" in summary for summary in summaries)
    assert any("emergency" in summary for summary in summaries)


def test_the_emergency_reply_waits_for_the_coordinator(
    lctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``docs/DESIGN.md`` §3: deny outreach, raise the red card, hold the reply."""
    request, outcome = _run(lctx, monkeypatch, LIVE_INTAKE)
    [card] = outcome.decisions_created
    assert lctx.store.list_messages(request_id=request.id) == []
    assert "emergency services" in card.context
    assert "waits until you have decided" in card.context

    resumed = resume_decision(lctx, card.id, "i_will_handle", "Called 911 myself.")

    assert resumed.interrupted is False
    stored = lctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.ESCALATED
    assert stored.attempts == []
    assert lctx.store.list_messages(request_id=request.id) == [], (
        "the coordinator took it: Porchlight still sends nothing on its own"
    )


# --------------------------------------------------------------------------------------
# The other three signals, each on its own
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("parsed", "kind"),
    [
        pytest.param(
            IntakeResult(summary="Chest pain", urgency=Urgency.EMERGENCY, is_request=False),
            DecisionKind.SAFETY,
            id="emergency-urgency-alone",
        ),
        pytest.param(
            IntakeResult(summary="Asks for a gift card", money_involved=True, is_request=False),
            DecisionKind.MONEY,
            id="money-alone",
        ),
        pytest.param(
            IntakeResult(summary="Half a sentence about Thursday", needs_human=True, is_request=False),
            DecisionKind.POLICY,
            id="needs-human-alone",
        ),
    ],
)
def test_each_signal_beats_the_short_circuit_on_its_own(
    lctx: AppContext, monkeypatch: pytest.MonkeyPatch, parsed: IntakeResult, kind: DecisionKind
) -> None:
    request, outcome = _run(lctx, monkeypatch, parsed, text="A message the model read as no request.")

    assert outcome.interrupted is True
    assert [card.kind for card in outcome.decisions_created] == [kind]
    stored = lctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.ESCALATED
    assert stored.attempts == []


def test_needs_human_on_an_ordinary_request_still_raises_a_card(
    lctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escalate rather than guess: an ambiguous request is a card, not a coin toss."""
    parsed = IntakeResult(summary="Something about Thursday", needs_human=True, reasoning="Half audible.")
    request, outcome = _run(lctx, monkeypatch, parsed, text="…thursday… the usual… thanks love")

    [card] = outcome.decisions_created
    assert card.kind is DecisionKind.POLICY
    assert "Half audible." in card.context
    stored = lctx.store.get_request(request.id)
    assert stored is not None and stored.attempts == []


# --------------------------------------------------------------------------------------
# The short-circuit itself still works
# --------------------------------------------------------------------------------------


def test_a_plain_thank_you_is_still_closed_quietly(lctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fix must not turn every thank-you note into a decision card."""
    parsed = IntakeResult(summary="Thanks for the lasagne", is_request=False, category=Category.OTHER)
    request, outcome = _run(lctx, monkeypatch, parsed, text="Thank you so much for the lasagne!")

    assert outcome.interrupted is False
    assert outcome.decisions_created == []
    stored = lctx.store.get_request(request.id)
    assert stored is not None and stored.status is RequestStatus.CANCELLED
    assert stored.attempts == []
    assert any("isn't asking for help" in summary for summary in _summaries(lctx, request.id))


def test_a_routine_request_is_untouched(lctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = IntakeResult(summary="Ride to dialysis Thursday 9am", category=Category.RIDE)
    request, outcome = _run(lctx, monkeypatch, parsed, text="Could someone drive me to dialysis Thursday?")

    assert outcome.interrupted is False
    assert outcome.decisions_created == []
    stored = lctx.store.get_request(request.id)
    assert stored is not None
    assert stored.status is RequestStatus.AWAITING_REPLY, "it went matcher → outreach as usual"


# --------------------------------------------------------------------------------------
# The rule, unit by unit
# --------------------------------------------------------------------------------------


def test_intake_result_knows_when_it_must_reach_a_person() -> None:
    assert LIVE_INTAKE.needs_coordinator() is True
    assert IntakeResult(summary="thanks").needs_coordinator() is False
    assert IntakeResult(summary="x", safety_flags=["gas"]).needs_coordinator() is True
    assert IntakeResult(summary="x", urgency=Urgency.EMERGENCY).needs_coordinator() is True
    assert IntakeResult(summary="x", money_involved=True).needs_coordinator() is True
    assert IntakeResult(summary="x", needs_human=True).needs_coordinator() is True


def test_needs_coordinator_reads_the_request_when_there_is_no_intake_result() -> None:
    """The sweep and a resumed run see the stored request, not intake's output."""
    assert needs_coordinator(None) is False
    assert needs_coordinator(AidRequest(raw_text="thanks")) is False
    assert needs_coordinator(AidRequest(raw_text="x", safety_flags=["stove on"])) is True
    assert needs_coordinator(AidRequest(raw_text="x", urgency=Urgency.EMERGENCY)) is True
    assert needs_coordinator(AidRequest(raw_text="x", money_involved=True)) is True
    # ``needs_human`` lives only on the intake result, so the parsed argument carries it.
    plain = AidRequest(raw_text="x")
    assert needs_coordinator(plain, IntakeResult(summary="x", needs_human=True)) is True
    assert needs_coordinator(plain, IntakeResult(summary="x")) is False


# --------------------------------------------------------------------------------------
# The prompt half of the fix
# --------------------------------------------------------------------------------------


def test_the_intake_prompt_says_a_flagged_message_is_a_request(settings: Settings) -> None:
    prompt = intake_prompt(settings)
    assert "request for the coordinator's attention" in prompt
    assert "`is_request` must be true" in prompt
    assert "Never use `is_request=false` to make something go away quietly." in prompt


def test_the_steward_prompt_refuses_to_close_a_flagged_message(settings: Settings) -> None:
    prompt = steward_prompt(settings)
    assert "not yours to close" in prompt
    assert "emergency services goes out when they say so" in prompt

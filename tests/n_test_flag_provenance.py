"""An intake safety flag is a model's opinion, and it is ranked like one.

Found on the live stack, not in a fixture. The electric-bill sample went to Bedrock and came
back with ``money_involved=true`` *and* ``safety_flags=["utility cutoff threat", "financial
hardship"]`` — the intake prompt tells the model to over-flag rather than under-flag, and it
obliged. Because :func:`card_for` ranked safety above everything, the coordinator got a red
card titled "Possible emergency — needs you now" recommending they tell a neighbour who is
$180 short on a bill to *dial emergency services*.

The rule that came out of it: a safety flag whose only source is intake ranks below every rule
that actually matched, and it travels inside the winning card so nothing is hidden. A flag that
a deterministic rule corroborates — danger language, or ``urgency=emergency`` — still wins
outright, and still says "call 911".
"""

from __future__ import annotations

import pytest

from porchlight.config import Settings
from porchlight.models import AidRequest, Category, DecisionKind, Source, Urgency
from porchlight.policy import card_for, evaluate_request, safety_card


@pytest.fixture
def settings() -> Settings:
    return Settings(mode="demo", model_provider="mock", store="sqlite", sqlite_path=":memory:")


def _request(**kwargs: object) -> AidRequest:
    base: dict[str, object] = {
        "source": Source.EMAIL,
        "raw_text": "placeholder",
        "requester_id": "rqr_novak",
        "category": Category.OTHER,
        "summary": "placeholder",
        "urgency": Urgency.NORMAL,
    }
    base.update(kwargs)
    return AidRequest(**base)  # type: ignore[arg-type]


ELECTRIC_BILL = (
    "I am $180 short on my electric bill and they are threatening to cut it off Monday. "
    "Can the group help with money?"
)


def test_the_live_electric_bill_gets_a_money_card_not_an_emergency(settings: Settings) -> None:
    """The exact shape the deployed stack produced on 2026-09-05."""
    request = _request(
        raw_text=ELECTRIC_BILL,
        category=Category.OTHER,
        summary="Requester is $180 short on their electric bill.",
        money_involved=True,
        safety_flags=["utility cutoff threat", "financial hardship"],
    )
    spec = card_for(request, evaluate_request(request, settings), settings)

    assert spec is not None
    assert spec.kind is DecisionKind.MONEY
    assert "emergency services" not in spec.recommendation


def test_the_money_card_still_carries_what_intake_was_worried_about(settings: Settings) -> None:
    """Demoted is not discarded: the coordinator reads the flag inside the card that won."""
    request = _request(
        raw_text=ELECTRIC_BILL,
        summary="Requester is $180 short on their electric bill.",
        money_involved=True,
        safety_flags=["utility cutoff threat"],
    )
    spec = card_for(request, evaluate_request(request, settings), settings)

    assert spec is not None
    assert "utility cutoff threat" in spec.context


def test_danger_language_still_wins_outright(settings: Settings) -> None:
    """A rule matched, so this is the call-911 card even though money is in the message too."""
    request = _request(
        raw_text="Dad is having chest pain and we cannot pay for the ambulance, please help",
        summary="Chest pain, and the family cannot pay for an ambulance.",
        money_involved=True,
        safety_flags=["chest pain"],
    )
    spec = card_for(request, evaluate_request(request, settings), settings)

    assert spec is not None
    assert spec.kind is DecisionKind.SAFETY
    assert spec.title == "Possible emergency — needs you now"
    assert "emergency services" in spec.recommendation


def test_an_emergency_urgency_corroborates_an_intake_flag(settings: Settings) -> None:
    """``urgency=emergency`` is a deliberate call, not the over-flagging field."""
    request = _request(
        raw_text="something is very wrong next door and I do not know what to do",
        summary="Neighbour reports something wrong next door.",
        urgency=Urgency.EMERGENCY,
        safety_flags=["something is very wrong"],
        money_involved=True,
    )
    spec = card_for(request, evaluate_request(request, settings), settings)

    assert spec is not None
    assert spec.kind is DecisionKind.SAFETY
    assert "emergency services" in spec.recommendation


def test_an_uncorroborated_flag_alone_still_stops_everything(settings: Settings) -> None:
    """Nothing else fired, so intake's unease is the card — worded as unease, not as a 911 call."""
    request = _request(
        raw_text="my neighbour has been shouting at the wall all week and I am not sure what to do",
        summary="Neighbour shouting at the wall all week.",
        safety_flags=["shouting at the wall all week"],
    )
    flags = evaluate_request(request, settings)
    spec = card_for(request, flags, settings)

    assert spec is not None
    assert spec.kind is DecisionKind.SAFETY
    assert spec.title == "Porchlight would not act on this alone"
    assert "emergency services" not in spec.recommendation
    assert "shouting at the wall" in spec.context


def test_evaluate_request_records_where_each_safety_flag_came_from(settings: Settings) -> None:
    request = _request(
        raw_text="he is bleeding badly",
        summary="Bleeding badly.",
        safety_flags=["bleeding"],
    )
    safety = [f for f in evaluate_request(request, settings) if f.kind is DecisionKind.SAFETY]
    sources = {flag.source for flag in safety}

    assert sources == {"intake", "rule"}


def test_the_safety_card_shape_follows_the_flag_source(settings: Settings) -> None:
    """Same builder, two shapes — the only difference is whether a rule backed the flag up."""
    request = _request(raw_text="x", summary="x", safety_flags=["x"])
    flags = evaluate_request(request, settings)
    assert safety_card(request, flags).title == "Porchlight would not act on this alone"

    rule_backed = [flag.model_copy(update={"source": "rule"}) for flag in flags]
    assert safety_card(request, rule_backed).title == "Possible emergency — needs you now"


def test_the_intake_prompt_keeps_hardship_out_of_the_safety_field(settings: Settings) -> None:
    """The root cause was the prompt, not only the ranking."""
    from porchlight.agents.prompts import intake_prompt

    prompt = intake_prompt(settings)
    assert "Hardship is not a safety flag" in prompt
    assert "utility cutoff" in prompt


# --------------------------------------------------------------------------------------
# The porch must not advertise a rule nobody enforces
# --------------------------------------------------------------------------------------


def test_the_seeded_group_mirrors_the_deployments_settings() -> None:
    """``/api/porch`` reads the stored group row; the policy reads ``Settings``. One source."""
    from porchlight.sim.fixtures import group_settings

    configured = Settings(
        mode="demo",
        model_provider="mock",
        store="sqlite",
        sqlite_path=":memory:",
        quiet_hours=(0, 0),
        petty_cash_limit=75.0,
        group_name="Riverbend Aid",
        timezone="Europe/Lisbon",
    )
    group = group_settings(configured)

    assert group.quiet_hours == (0, 0)
    assert group.petty_cash_limit == 75.0
    assert group.name == "Riverbend Aid"
    assert group.timezone == "Europe/Lisbon"


def test_the_seeded_group_still_defaults_to_maple_street() -> None:
    from porchlight.sim.fixtures import group_settings

    group = group_settings(Settings())
    assert group.name == "Maple Street Mutual Aid"
    assert group.quiet_hours == (21, 8)
    assert group.zones

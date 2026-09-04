"""Every row of the policy table in ``docs/DESIGN.md`` §3, plus the audit and trace hooks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from strands.hooks import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeToolCallEvent,
    HookRegistry,
    MessageAddedEvent,
)
from strands.interventions import Confirm, Deny, Guide, Proceed, Transform

from porchlight.clock import FrozenClock
from porchlight.config import Settings
from porchlight.context import AppContext
from porchlight.models import (
    AidRequest,
    Category,
    DecisionKind,
    ReplyIntent,
    RequestStatus,
    Source,
    Urgency,
    VolunteerReply,
)
from porchlight.policy import (
    AuditHook,
    PorchlightPolicy,
    TraceHook,
    contains_pii,
    decode_decision,
    evaluate_option,
    evaluate_reply,
    evaluate_request,
    extract_amount,
    is_quiet_hours,
    money_card,
    next_send_time,
    redact_pii,
    safety_card,
)

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


class _Agent:
    """Minimal stand-in for a Strands agent in hand-built hook events."""

    name = "outreach"
    event_loop_metrics = None


def make_request(store: Any, **fields: Any) -> AidRequest:
    """Persist and return a request built from ``fields``."""
    request = AidRequest(source=Source.SMS, **fields)
    store.put_request(request)
    return request


def tool_event(
    ctx: AppContext, name: str, args: dict[str, Any], request_id: str | None = None
) -> BeforeToolCallEvent:
    """Build a ``BeforeToolCallEvent`` for one tool call."""
    return BeforeToolCallEvent(
        agent=_Agent(),
        selected_tool=None,
        tool_use={"name": name, "input": dict(args), "toolUseId": "tu_1"},
        invocation_state={"ctx": ctx, "request_id": request_id},
    )


def decide(ctx: AppContext, name: str, args: dict[str, Any], request_id: str | None = None) -> Any:
    """Run the policy over one tool call and return the intervention action."""
    return PorchlightPolicy(ctx).before_tool_call(tool_event(ctx, name, args, request_id))


# --------------------------------------------------------------------------------------
# evaluate_request
# --------------------------------------------------------------------------------------


def test_routine_request_has_no_flags(settings: Settings) -> None:
    request = AidRequest(
        raw_text="Could someone give Ezra a ride to dialysis Thursday at 9am?",
        summary="Ride to dialysis",
        category=Category.RIDE,
    )
    assert evaluate_request(request, settings) == []


def test_danger_language_blocks(settings: Settings) -> None:
    request = AidRequest(
        raw_text="My neighbour's kid is home alone next door and I can smell the stove is on."
    )
    flags = evaluate_request(request, settings)
    assert flags[0].kind is DecisionKind.SAFETY
    assert flags[0].blocks()


def test_emergency_urgency_blocks(settings: Settings) -> None:
    request = AidRequest(raw_text="please help", urgency=Urgency.EMERGENCY)
    flags = evaluate_request(request, settings)
    assert any(flag.kind is DecisionKind.SAFETY and flag.blocks() for flag in flags)


def test_intake_safety_flags_block(settings: Settings) -> None:
    request = AidRequest(raw_text="something is wrong", safety_flags=["arm feels heavy"])
    flags = evaluate_request(request, settings)
    assert flags[0].kind is DecisionKind.SAFETY
    assert "arm feels heavy" in flags[0].reason


def test_gift_card_is_a_money_flag(settings: Settings) -> None:
    request = AidRequest(raw_text="Could the group get me a grocery gift card instead of a shopping run?")
    flags = [flag for flag in evaluate_request(request, settings) if flag.kind is DecisionKind.MONEY]
    assert flags and flags[0].severity == "warn"


def test_amount_over_petty_cash_blocks(settings: Settings) -> None:
    request = AidRequest(raw_text="I am $180 short on my electric bill and they will cut it off.")
    flags = [flag for flag in evaluate_request(request, settings) if flag.kind is DecisionKind.MONEY]
    assert flags and flags[0].blocks()
    assert "180" in flags[0].reason


def test_small_amount_stays_a_warning(settings: Settings) -> None:
    request = AidRequest(raw_text="Could someone spot me $12 cash for the bus?")
    flags = [flag for flag in evaluate_request(request, settings) if flag.kind is DecisionKind.MONEY]
    assert flags and flags[0].severity == "warn"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("$180 short", 180.0), ("about 45 dollars", 45.0), ("$1,200 rent", 1200.0), ("no numbers", None)],
)
def test_extract_amount(text: str, expected: float | None) -> None:
    assert extract_amount(text) == expected


def test_first_time_requester_in_home_needs_vetting(settings: Settings) -> None:
    request = AidRequest(
        raw_text="I'm new here. I need someone to come inside and help me move a wardrobe.",
        first_time_requester=True,
    )
    assert any(flag.kind is DecisionKind.VETTING for flag in evaluate_request(request, settings))


def test_known_requester_in_home_is_fine(settings: Settings) -> None:
    request = AidRequest(raw_text="Could someone come inside and help me with the tablet?")
    assert not [flag for flag in evaluate_request(request, settings) if flag.kind is DecisionKind.VETTING]


def test_evaluate_reply_flags_a_concern() -> None:
    flag = evaluate_reply(VolunteerReply(intent=ReplyIntent.CONCERN, concern_text="man shouting inside"))
    assert flag is not None and flag.kind is DecisionKind.CONCERN
    assert evaluate_reply(VolunteerReply(intent=ReplyIntent.ACCEPT)) is None


# --------------------------------------------------------------------------------------
# Quiet hours and PII
# --------------------------------------------------------------------------------------


def test_quiet_hours_wrap_midnight(settings: Settings) -> None:
    late = datetime(2026, 9, 9, 2, 30, tzinfo=UTC)  # 22:30 in Toronto
    midday = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)  # 12:00 in Toronto
    assert is_quiet_hours(late, settings)
    assert not is_quiet_hours(midday, settings)


def test_next_send_time_lands_at_the_opening_hour(settings: Settings) -> None:
    late = datetime(2026, 9, 9, 2, 30, tzinfo=UTC)
    when = next_send_time(late, settings)
    assert when > late
    assert not is_quiet_hours(when, settings)


def test_next_send_time_is_a_no_op_outside_quiet_hours(settings: Settings) -> None:
    midday = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
    assert next_send_time(midday, settings) == midday


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("call her on 555-123-4567", "555-123-4567"),
        ("she is at 12 Riverbend Lane", "Riverbend"),
        ("email ezra@example.com", "ezra@example.com"),
        ("reach him on +1 (416) 555-0199 any time", "555-0199"),
    ],
)
def test_redact_pii_removes_contact_details(text: str, secret: str) -> None:
    assert contains_pii(text)
    redacted = redact_pii(text)
    assert secret not in redacted
    assert "once you accept" in redacted


def test_redact_pii_leaves_ordinary_text_alone() -> None:
    text = "Ezra needs a ride to dialysis Thursday at 9am in Riverside."
    assert redact_pii(text) == text


# --------------------------------------------------------------------------------------
# Decision payload plumbing
# --------------------------------------------------------------------------------------


def test_decision_prompt_round_trips(settings: Settings) -> None:
    request = AidRequest(raw_text="I am $180 short on my electric bill")
    spec = money_card(request, evaluate_request(request, settings), settings)
    payload = decode_decision(spec.prompt())
    assert payload is not None
    assert payload["kind"] == "money"
    assert {option["id"] for option in payload["options"]} >= {"approve", "i_will_handle"}
    assert decode_decision(spec.reason()) == payload


def test_decode_decision_tolerates_junk() -> None:
    assert decode_decision("just some prose") is None
    assert decode_decision(None) is None
    assert decode_decision({"kind": "safety"}) == {"kind": "safety"}


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"option": "approve"}, True),
        ({"option": "widen_pool"}, True),
        ({"option": "decline_request"}, False),
        ({"option": "i_will_handle"}, False),
        ({"option": "something_unknown"}, False),
        ("yes", True),
        (True, True),
        (None, False),
    ],
)
def test_evaluate_option(response: Any, expected: bool) -> None:
    assert evaluate_option(response) is expected


def test_safety_card_names_the_reasons(settings: Settings) -> None:
    request = AidRequest(raw_text="the stove is on and the kid is home alone")
    spec = safety_card(request, evaluate_request(request, settings))
    assert spec.kind is DecisionKind.SAFETY
    assert "emergency services" in spec.context


# --------------------------------------------------------------------------------------
# The intervention handler
# --------------------------------------------------------------------------------------


def test_ungated_tool_proceeds(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="ride to dialysis")
    assert isinstance(decide(ctx, "find_candidates", {"request_id": request.id}), Proceed)


def test_routine_message_proceeds(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="ride to dialysis Thursday", category=Category.RIDE)
    action = decide(
        ctx,
        "send_message",
        {"request_id": request.id, "to": "volunteer", "recipient_id": "vol_maria", "body": "Free Thursday?"},
    )
    assert isinstance(action, Proceed)


def test_safety_denies_volunteer_outreach(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="kid is home alone and the stove is on")
    action = decide(
        ctx,
        "send_message",
        {"request_id": request.id, "to": "volunteer", "recipient_id": "vol_maria", "body": "Can you go?"},
    )
    assert isinstance(action, Deny)
    assert "emergency services" in action.reason


def test_safety_denies_assignment(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="he has chest pain and his arm feels heavy")
    action = decide(ctx, "assign_volunteer", {"request_id": request.id, "volunteer_id": "vol_maria"})
    assert isinstance(action, Deny)


def test_safety_still_lets_the_requester_be_answered(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="kid is home alone and the stove is on")
    action = decide(
        ctx,
        "send_message",
        {
            "request_id": request.id,
            "to": "requester",
            "recipient_id": "rqr_okafor",
            "body": "Please call 911 right now.",
        },
    )
    assert isinstance(action, Proceed)


def test_money_asks_the_coordinator(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="could the group buy me a $50 grocery gift card")
    action = decide(
        ctx,
        "send_message",
        {"request_id": request.id, "to": "volunteer", "recipient_id": "vol_maria", "body": "Can you help?"},
    )
    assert isinstance(action, Confirm)
    payload = decode_decision(action.prompt)
    assert payload is not None and payload["kind"] == "money"


def test_vetting_asks_the_coordinator(ctx: AppContext) -> None:
    request = make_request(
        ctx.store,
        raw_text="I'm new to the neighbourhood, could someone come inside and help me?",
        first_time_requester=True,
    )
    action = decide(
        ctx,
        "send_message",
        {"request_id": request.id, "to": "volunteer", "recipient_id": "vol_maria", "body": "Free tomorrow?"},
    )
    assert isinstance(action, Confirm)
    assert (decode_decision(action.prompt) or {})["kind"] == "vetting"


def test_concern_on_record_attempt_asks_the_coordinator(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="grocery drop")
    action = decide(
        ctx,
        "record_attempt",
        {
            "request_id": request.id,
            "volunteer_id": "vol_maria",
            "outcome": "concern",
            "note": "a man was shouting inside",
        },
    )
    assert isinstance(action, Confirm)
    payload = decode_decision(action.prompt) or {}
    assert payload["kind"] == "concern"
    assert "shouting" in payload["context"]


def test_quiet_hours_guides_towards_scheduling(ctx: AppContext, clock: FrozenClock) -> None:
    request = make_request(ctx.store, raw_text="bins to the curb, no rush")
    clock.set(datetime(2026, 9, 9, 3, 40, tzinfo=UTC))  # 23:40 local
    action = decide(
        ctx,
        "send_message",
        {"request_id": request.id, "to": "volunteer", "recipient_id": "vol_maria", "body": "Free tomorrow?"},
    )
    assert isinstance(action, Guide)
    assert "schedule_message" in action.feedback


def test_quiet_hours_does_not_block_the_coordinator(ctx: AppContext, clock: FrozenClock) -> None:
    request = make_request(ctx.store, raw_text="bins to the curb")
    clock.set(datetime(2026, 9, 9, 3, 40, tzinfo=UTC))
    action = decide(
        ctx,
        "send_message",
        {"request_id": request.id, "to": "coordinator", "recipient_id": "dana", "body": "heads up"},
    )
    assert isinstance(action, Proceed)


def test_pii_is_redacted_before_acceptance(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="ride to dialysis", category=Category.RIDE)
    event = tool_event(
        ctx,
        "send_message",
        {
            "request_id": request.id,
            "to": "volunteer",
            "recipient_id": "vol_maria",
            "body": "Pick him up at 12 Riverbend Lane, call 555-123-4567.",
        },
    )
    action = PorchlightPolicy(ctx).before_tool_call(event)
    assert isinstance(action, Transform)
    action.apply(event)
    body = event.tool_use["input"]["body"]
    assert "Riverbend" not in body
    assert "555-123-4567" not in body


def test_pii_flows_to_a_vetted_volunteer_who_accepted(ctx: AppContext) -> None:
    volunteer = next(v for v in ctx.store.list_volunteers() if v.vetted)
    request = make_request(
        ctx.store,
        raw_text="ride to dialysis",
        category=Category.RIDE,
        assigned_volunteer_id=volunteer.id,
        status=RequestStatus.CONFIRMED,
    )
    action = decide(
        ctx,
        "send_message",
        {
            "request_id": request.id,
            "to": "volunteer",
            "recipient_id": volunteer.id,
            "body": "He is at 12 Riverbend Lane.",
        },
    )
    assert isinstance(action, Proceed)


def test_policy_without_a_request_proceeds(ctx: AppContext) -> None:
    assert isinstance(decide(ctx, "remember", {"content": "Maria prefers mornings"}), Proceed)


# --------------------------------------------------------------------------------------
# Hooks
# --------------------------------------------------------------------------------------


def test_audit_hook_writes_the_quiet_log(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="ride")
    hook = AuditHook(ctx)
    registry = HookRegistry()
    hook.register_hooks(registry)

    tool_use = {"name": "send_message", "input": {"request_id": request.id}, "toolUseId": "tu_1"}
    registry.invoke_callbacks(
        BeforeToolCallEvent(agent=_Agent(), selected_tool=None, tool_use=tool_use, invocation_state={})
    )
    registry.invoke_callbacks(
        AfterToolCallEvent(
            agent=_Agent(),
            selected_tool=None,
            tool_use=tool_use,
            invocation_state={},
            result={"status": "success", "content": []},
            duration=0.01,
        )
    )

    entries = ctx.store.list_log(request_id=request.id)
    assert entries and entries[0].summary.startswith("send_message")
    assert entries[0].agent == "outreach"
    types = [event["type"] for event in ctx.emitted]  # type: ignore[attr-defined]
    assert "tool_call" in types and "tool_result" in types


def test_audit_hook_marks_a_cancelled_call_as_not_autonomous(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="ride")
    hook = AuditHook(ctx)
    registry = HookRegistry()
    hook.register_hooks(registry)
    tool_use = {"name": "assign_volunteer", "input": {"request_id": request.id}, "toolUseId": "tu_2"}
    registry.invoke_callbacks(
        AfterToolCallEvent(
            agent=_Agent(),
            selected_tool=None,
            tool_use=tool_use,
            invocation_state={},
            result={"status": "error", "content": []},
            cancel_message="DENIED: emergency",
        )
    )
    entry = ctx.store.list_log(request_id=request.id)[0]
    assert entry.autonomous is False
    assert entry.detail["cancel_message"] == "DENIED: emergency"


def test_trace_hook_emits_messages_and_model_calls(ctx: AppContext) -> None:
    registry = HookRegistry()
    TraceHook(ctx).register_hooks(registry)
    registry.invoke_callbacks(
        MessageAddedEvent(agent=_Agent(), message={"role": "user", "content": [{"text": "hello"}]})
    )
    registry.invoke_callbacks(
        AfterModelCallEvent(
            agent=_Agent(),
            stop_response=AfterModelCallEvent.ModelStopResponse(
                message={"role": "assistant", "content": []}, stop_reason="end_turn"
            ),
        )
    )
    kinds = [event["type"] for event in ctx.emitted]  # type: ignore[attr-defined]
    assert "message" in kinds and "model_call" in kinds


def test_a_halted_request_never_reaches_a_volunteer(ctx: AppContext) -> None:
    """Once the coordinator owns a request, Porchlight stops asking volunteers about it."""
    request = make_request(ctx.store, raw_text="ride to dialysis", status=RequestStatus.ESCALATED)
    action = decide(
        ctx,
        "send_message",
        {"request_id": request.id, "to": "volunteer", "recipient_id": "vol_maria", "body": "Free Thursday?"},
    )
    assert isinstance(action, Deny)
    assert "taken it over" in action.reason


def test_a_halted_request_can_still_be_answered_and_closed(ctx: AppContext) -> None:
    request = make_request(ctx.store, raw_text="ride to dialysis", status=RequestStatus.ESCALATED)
    reply = decide(
        ctx,
        "send_message",
        {"request_id": request.id, "to": "requester", "recipient_id": "rqr_1", "body": "Dana will call you."},
    )
    assert isinstance(reply, Proceed)
    close = decide(ctx, "close_request", {"request_id": request.id, "outcome": "declined"})
    assert isinstance(close, Proceed)

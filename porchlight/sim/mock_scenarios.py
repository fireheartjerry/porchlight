"""Scripted model behaviour that makes ``PORCHLIGHT_MODEL_PROVIDER=mock`` a real demo.

Plain :class:`~porchlight.testing.mock_model.MockModel` answers an unscripted structured-output
request by synthesizing a *schema-valid but empty* instance. For Porchlight that means every
``MatchPlan`` comes back with no candidates and confidence ``0.0``, so the outreach gate fires on
every request and the offline demo degenerates into twenty-four identical "nobody free" cards.

:class:`PorchlightScenarioModel` plays each agent's part instead. It is a simulator, not a
language model: every turn is derived from the request in the store, the group's real roster, and
the tool results already in the conversation. Intake classifies the fixture message, the matcher
ranks the roster and reports an honest confidence, outreach actually texts volunteers through
``SimChannel`` and reads their replies, and the steward confirms the neighbour and writes a
memory note. The same day therefore runs the same way every time, through the real Strands
graph, tools, hooks, and policy interventions.

Unknown text (anything typed into the demo inbox) falls back to :func:`infer_plan`, a keyword
reading of the message, so the mock provider is useful beyond the twenty-four fixtures.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

from ..context import AppContext
from ..matching import rank_candidates, zone_info
from ..models import AidRequest, Category, ReplyIntent, Requester, RequestStatus, Urgency, Volunteer
from ..testing.mock_model import MockModel, ScenarioModel, _structured_output_spec, emit_message
from .fixtures import SAMPLE_MESSAGES
from .volunteer_sim import guess_intent

logger = logging.getLogger(__name__)

__all__ = [
    "SAMPLE_PLANS",
    "PorchlightScenarioModel",
    "SamplePlan",
    "infer_plan",
    "plan_for",
    "sample_id_for_text",
]

REMINDER_HOURS_BEFORE = 12
"""How long before a job the steward schedules the volunteer's reminder."""

DEFAULT_CONFIDENCE_BONUS = 0.05
"""Nudge per extra candidate on the bench, matching ``matching.plan_confidence``."""


# --------------------------------------------------------------------------------------
# Per-sample plans
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SamplePlan:
    """What intake should understand from one inbound message.

    Attributes:
        summary: The one-line summary a neighbour would recognise.
        category: The request category.
        urgency: How soon it matters.
        window: ``(start, end)`` hours from now, or ``None`` when no time was given.
        flexible: True when the timing can move.
        constraints: Dietary needs, mobility needs, allergies.
        money_involved: True when the group's money, not just its time, is asked for.
        safety_flags: Danger signals worth quoting to the coordinator.
        zone: Neighbourhood zone named in the message.
        confidence: Matcher confidence override; ``None`` derives it from the scores.
        is_request: False when the message asks for nothing (a thank-you note, chatter, spam).
        duplicate: True when the message chases a request the same neighbour already has open.
        reasoning: Two lines on how intake read the message.
    """

    summary: str
    category: Category = Category.OTHER
    urgency: Urgency = Urgency.NORMAL
    window: tuple[int, int] | None = None
    flexible: bool = False
    constraints: tuple[str, ...] = ()
    money_involved: bool = False
    safety_flags: tuple[str, ...] = ()
    zone: str | None = None
    confidence: float | None = None
    is_request: bool = True
    duplicate: bool = False
    reasoning: str = ""


SAMPLE_PLANS: dict[str, SamplePlan] = {
    "sm_dialysis_ride": SamplePlan(
        summary="Ride to dialysis Thursday 9am and home again around 1pm",
        category=Category.RIDE,
        window=(18, 22),
        zone="Riverside",
        reasoning="A standing dialysis run he has asked for before. Routine, and he named the time.",
    ),
    "sm_grocery_run": SamplePlan(
        summary="Milk, bread and her usual tea picked up sometime this week",
        category=Category.GROCERIES,
        urgency=Urgency.LOW,
        window=(24, 120),
        flexible=True,
        zone="Riverside",
        reasoning="No deadline and she says there is no rush, so this can wait for a spare hour.",
    ),
    "sm_new_parent_meal": SamplePlan(
        summary="A hot dinner one evening this week for new parents",
        category=Category.MEAL,
        window=(6, 54),
        flexible=True,
        constraints=("no dairy",),
        reasoning="Any evening works and the only hard constraint is dairy.",
    ),
    "sm_prescription": SamplePlan(
        summary="Collect blood pressure pills from the Old Mill pharmacy before Friday",
        category=Category.PRESCRIPTION,
        window=(12, 72),
        flexible=True,
        zone="Old Mill",
        reasoning="Medication, so it has a real deadline, but any day before Friday is fine.",
    ),
    "sm_snow_shovel": SamplePlan(
        summary="Clear the front walk before the nurse visits Wednesday morning",
        category=Category.YARD_WORK,
        window=(12, 40),
        reasoning="The nurse visit is the deadline; his knee rules out doing it himself.",
    ),
    "sm_tablet_help": SamplePlan(
        summary="Half an hour of patient help with the photo app on her tablet",
        category=Category.TECH_HELP,
        urgency=Urgency.LOW,
        window=(12, 96),
        flexible=True,
        reasoning="Small and not urgent, but it matters to her; patience is the real requirement.",
    ),
    "sm_clinic_translation": SamplePlan(
        summary="Spanish interpreting at a clinic appointment Monday 2pm on Northgate",
        category=Category.TRANSLATION,
        window=(24, 28),
        zone="Northgate",
        constraints=("Spanish speaker",),
        reasoning="Fixed appointment time and a hard language requirement.",
    ),
    "sm_companionship": SamplePlan(
        summary="A friendly visit Friday afternoon; the days are long",
        category=Category.COMPANIONSHIP,
        urgency=Urgency.LOW,
        window=(48, 56),
        flexible=True,
        reasoning="She underplays it, but loneliness is the actual ask. Worth taking seriously.",
    ),
    "sm_spanish_request": SamplePlan(
        summary="Ride to the pharmacy Friday morning; no car",
        category=Category.RIDE,
        window=(40, 46),
        zone="Northgate",
        constraints=("requester speaks Spanish",),
        reasoning="Written in Spanish: a lift to the pharmacy on Friday morning.",
    ),
    "sm_garbled_voicemail": SamplePlan(
        summary="Unclear voicemail, probably the usual Thursday ride her daughter arranges",
        category=Category.RIDE,
        urgency=Urgency.LOW,
        window=(18, 26),
        flexible=True,
        reasoning="Half the transcript is inaudible. Matched to the standing Thursday pattern.",
    ),
    "sm_flexible_window": SamplePlan(
        summary="A lift to the library any afternoon next week",
        category=Category.RIDE,
        urgency=Urgency.LOW,
        window=(72, 168),
        flexible=True,
        reasoning="Completely flexible, so this is the one to give to whoever has a spare hour.",
    ),
    "sm_urgent_ride": SamplePlan(
        summary="Same-day ride to a clinic appointment moved to 3pm today",
        category=Category.RIDE,
        urgency=Urgency.HIGH,
        window=(2, 5),
        reasoning="Today, short notice, and a medical appointment. Urgent but not an emergency.",
    ),
    "sm_child_home_alone": SamplePlan(
        summary="Neighbour reports a child alone next door with the stove on",
        category=Category.OTHER,
        urgency=Urgency.EMERGENCY,
        safety_flags=("child home alone", "stove is on"),
        reasoning="A child alone and a lit stove. This is emergency services, not a volunteer.",
    ),
    "sm_electric_bill": SamplePlan(
        summary="$180 short on an electric bill due Monday",
        category=Category.PAPERWORK,
        urgency=Urgency.HIGH,
        money_involved=True,
        window=(24, 72),
        reasoning="A money ask well over the petty-cash limit. The coordinator decides, not me.",
    ),
    "sm_first_time_in_home": SamplePlan(
        summary="New neighbour asking for help moving furniture inside their home",
        category=Category.REPAIR,
        window=(24, 120),
        flexible=True,
        reasoning="First time we have heard from them, and the help is indoors and alone.",
    ),
    "sm_volunteer_concern": SamplePlan(
        summary="Volunteer reports feeling unsafe after a delivery at 9 Riverbend",
        category=Category.GROCERIES,
        urgency=Urgency.HIGH,
        zone="Riverbend",
        reasoning="This is a volunteer telling us something is wrong. Not a job to dispatch.",
    ),
    "sm_chest_pain": SamplePlan(
        summary="Chest pain and a heavy arm since this morning; asking for a lift to hospital",
        category=Category.RIDE,
        urgency=Urgency.EMERGENCY,
        safety_flags=("chest pain", "arm feels heavy"),
        reasoning="Textbook cardiac symptoms. Nobody drives them anywhere; they call an ambulance.",
    ),
    "sm_duplicate_dialysis": SamplePlan(
        summary="Follow-up on the Thursday 9am dialysis ride already in hand",
        category=Category.RIDE,
        urgency=Urgency.LOW,
        window=(18, 22),
        zone="Riverside",
        duplicate=True,
        reasoning="Same person, same Thursday ride. Chasing, not a second job.",
    ),
    "sm_conflicting_times": SamplePlan(
        summary="A visit next week; three times were suggested, Wednesday reads as the preference",
        category=Category.COMPANIONSHIP,
        urgency=Urgency.LOW,
        window=(48, 96),
        flexible=True,
        reasoning="Three times in one message. Taking the last clear preference and staying flexible.",
    ),
    "sm_thank_you": SamplePlan(
        summary="Thank-you note about the lasagne; no help needed",
        category=Category.OTHER,
        urgency=Urgency.LOW,
        flexible=True,
        is_request=False,
        reasoning="Not a request at all. Worth passing the thanks on to whoever cooked.",
    ),
    "sm_paper_slip": SamplePlan(
        summary="Ride to the eye doctor Friday 11am, from the Riverside paper slip",
        category=Category.RIDE,
        window=(40, 44),
        zone="Riverside",
        reasoning="A photographed paper slip: name, need, time and zone are all legible.",
    ),
    "sm_gift_card": SamplePlan(
        summary="Asks for a $50 grocery gift card instead of a shopping run",
        category=Category.GROCERIES,
        money_involved=True,
        flexible=True,
        reasoning="Gift cards are group money. That is the coordinator's call every time.",
    ),
    "sm_night_send": SamplePlan(
        summary="Bins out Thursday morning; message arrived late at night",
        category=Category.YARD_WORK,
        urgency=Urgency.LOW,
        window=(30, 38),
        flexible=True,
        reasoning="Small and not urgent. They apologised for the hour; nothing goes out tonight.",
    ),
    "sm_nobody_free": SamplePlan(
        summary="Lift to Riverside at 4am Sunday for a hospital transfer",
        category=Category.RIDE,
        urgency=Urgency.HIGH,
        window=(60, 64),
        zone="Riverside",
        confidence=0.28,
        reasoning="4am on a Sunday is outside everyone's availability. They know it is a big ask.",
    ),
}
"""Intake plans for the twenty-four fixture messages, keyed by sample id."""


_CATEGORY_HINTS: tuple[tuple[Category, tuple[str, ...]], ...] = (
    (Category.PRESCRIPTION, ("prescription", "pharmac", "pills", "medication", "refill")),
    (Category.RIDE, ("ride", "lift", "drive", "drop me", "appointment", "clinic", "hospital")),
    (Category.GROCERIES, ("grocer", "shop", "milk", "bread", "food bank", "supermarket")),
    (Category.MEAL, ("meal", "dinner", "cook", "lasagne", "casserole", "hot food")),
    (Category.YARD_WORK, ("snow", "shovel", "lawn", "garden", "leaves", "bins", "walk cleared")),
    (Category.TECH_HELP, ("tablet", "computer", "phone", "wifi", "internet", "password", "laptop")),
    (Category.TRANSLATION, ("translat", "interpret", "spanish", "portuguese", "language")),
    (Category.COMPANIONSHIP, ("company", "visit", "lonely", "chat", "companion")),
    (Category.CHILDCARE, ("babysit", "childcare", "watch my kid", "school pickup")),
    (Category.REPAIR, ("fix", "repair", "leak", "broken", "furniture", "shelf")),
    (Category.PAPERWORK, ("form", "paperwork", "bill", "letter", "application", "benefits")),
    (Category.ERRAND, ("errand", "post office", "drop off", "pick up")),
)

_URGENT_HINTS = ("today", "urgent", "right now", "asap", "this morning", "short notice")


def _normalise(text: str) -> str:
    """Collapse whitespace and lower-case, so fixture text matches however it was re-wrapped."""
    return " ".join(str(text).split()).strip().lower()


_TEXT_TO_SAMPLE: dict[str, str] = {_normalise(m["text"]): m["id"] for m in SAMPLE_MESSAGES}


def sample_id_for_text(text: str) -> str | None:
    """Return the fixture sample id whose text this is, or ``None`` for anything else."""
    return _TEXT_TO_SAMPLE.get(_normalise(text))


def infer_plan(text: str) -> SamplePlan:
    """Read an unknown message with keywords, so typed-in demo text still behaves sensibly."""
    from ..policy import DANGER_PATTERNS, MONEY_PATTERNS, matched_patterns

    lowered = _normalise(text)
    category = Category.OTHER
    for candidate, hints in _CATEGORY_HINTS:
        if any(hint in lowered for hint in hints):
            category = candidate
            break
    danger = matched_patterns(lowered, DANGER_PATTERNS)
    money = bool(matched_patterns(lowered, MONEY_PATTERNS))
    urgency = Urgency.NORMAL
    if danger:
        urgency = Urgency.EMERGENCY
    elif any(hint in lowered for hint in _URGENT_HINTS):
        urgency = Urgency.HIGH
    summary = " ".join(str(text).split())[:140] or "An inbound message with no text"
    return SamplePlan(
        summary=summary,
        category=category,
        urgency=urgency,
        window=None if urgency is Urgency.EMERGENCY else (12, 72),
        flexible=urgency is Urgency.NORMAL,
        money_involved=money,
        safety_flags=tuple(danger[:3]),
        reasoning="Read from keywords: no scripted plan matched this message.",
    )


def plan_for(request: AidRequest | None) -> SamplePlan:
    """The plan for one request: the scripted fixture plan, or a keyword reading."""
    if request is None:
        return infer_plan("")
    sample_id = sample_id_for_text(request.raw_text)
    if sample_id and sample_id in SAMPLE_PLANS:
        return SAMPLE_PLANS[sample_id]
    return infer_plan(request.raw_text)


# --------------------------------------------------------------------------------------
# Reading the conversation so far
# --------------------------------------------------------------------------------------


@dataclass
class ToolCall:
    """One tool the agent already asked for, with the result it got back."""

    name: str
    args: dict[str, Any]
    result: Any = None


def _blocks(messages: Messages) -> list[tuple[str, dict[str, Any]]]:
    """Flatten ``messages`` into ``(role, content_block)`` pairs."""
    flat: list[tuple[str, dict[str, Any]]] = []
    for message in messages or []:
        role = str(message.get("role", ""))
        for block in message.get("content") or []:
            if isinstance(block, dict):
                flat.append((role, block))
    return flat


def _decode(payload: Any) -> Any:
    """Decode a tool result body, which Strands serializes to JSON text."""
    if not isinstance(payload, str):
        return payload
    try:
        return json.loads(payload)
    except (TypeError, ValueError):
        return payload


def _result_body(block: dict[str, Any]) -> Any:
    """Pull the useful part out of a ``toolResult`` block."""
    for part in block.get("content") or []:
        if not isinstance(part, dict):
            continue
        if "json" in part:
            return part["json"]
        if "text" in part:
            return _decode(part["text"])
    return None


def tool_calls(messages: Messages) -> list[ToolCall]:
    """Every tool this agent has already called in this conversation, oldest first."""
    pending: dict[str, ToolCall] = {}
    ordered: list[ToolCall] = []
    for _role, block in _blocks(messages):
        use = block.get("toolUse")
        if isinstance(use, dict):
            call = ToolCall(name=str(use.get("name", "")), args=dict(use.get("input") or {}))
            pending[str(use.get("toolUseId"))] = call
            ordered.append(call)
            continue
        result = block.get("toolResult")
        if isinstance(result, dict):
            call = pending.get(str(result.get("toolUseId")))
            if call is not None:
                call.result = _result_body(result)
    return ordered


def called(messages: Messages) -> set[str]:
    """Names of the tools already called in this conversation."""
    return {call.name for call in tool_calls(messages)}


def last_result(messages: Messages, name: str) -> Any:
    """The most recent result for one tool name, or ``None``."""
    for call in reversed(tool_calls(messages)):
        if call.name == name:
            return call.result
    return None


def prompt_text(messages: Messages) -> str:
    """All user-supplied text in the conversation, joined."""
    parts = [
        str(block.get("text", "")) for role, block in _blocks(messages) if role == "user" and "text" in block
    ]
    return "\n".join(part for part in parts if part)


# --------------------------------------------------------------------------------------
# The turn planners
# --------------------------------------------------------------------------------------


@dataclass
class Turn:
    """One planned model response."""

    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    structured: dict[str, Any] | None = None
    text: str | None = None


def _iso(moment: datetime | None) -> str | None:
    """ISO-8601 or ``None``."""
    return moment.isoformat() if moment else None


HONORIFICS = frozenset({"mr", "mrs", "ms", "miss", "dr", "mx", "prof", "rev", "sr", "sra"})


def _first_name(name: str | None) -> str:
    """The part of a name you would actually text, skipping any honorific."""
    parts = [part for part in (name or "").split() if part]
    for part in parts:
        if part.rstrip(".").lower() not in HONORIFICS:
            return part
    return parts[-1] if parts else "there"


def _local(moment: datetime, timezone: str) -> datetime:
    """The group's local time for a UTC moment."""
    return moment.astimezone(zone_info(timezone))


def _clock_phrase(moment: datetime) -> str:
    """``Thursday at 9am`` — the way a neighbour writes a time."""
    return moment.strftime("%A at %-I%p").replace("AM", "am").replace("PM", "pm")


def _when_phrase(request: AidRequest, timezone: str) -> str:
    """A short, human way to say when a job is, in the group's local time."""
    if request.window_start is None:
        return "whenever suits you this week"
    start = _local(request.window_start, timezone)
    if not request.flexible:
        return f"on {_clock_phrase(start)}"
    if request.window_end is not None:
        return f"any time before {_local(request.window_end, timezone).strftime('%A')}"
    return "whenever suits you"


def _intake_turn(ctx: AppContext, request: AidRequest | None, messages: Messages) -> Turn:
    """Look the requester up once, check for a duplicate, then read the message."""
    plan = plan_for(request)
    done = called(messages)
    if "lookup_requester_history" not in done and request is not None:
        requester = ctx.store.get_requester(request.requester_id) if request.requester_id else None
        needle = (requester.contact if requester else None) or request.requester_id or plan.summary
        return Turn(tool_calls=[("lookup_requester_history", {"contact_or_name": needle})])

    now = ctx.now()
    window = plan.window
    requester = ctx.store.get_requester(request.requester_id) if request and request.requester_id else None
    if plan.duplicate and requester is not None and "find_similar_open_requests" not in done:
        return Turn(
            tool_calls=[
                (
                    "find_similar_open_requests",
                    {"requester_id": requester.id, "category": str(plan.category)},
                )
            ]
        )
    return Turn(
        structured={
            "summary": plan.summary,
            "category": str(plan.category),
            "urgency": str(plan.urgency),
            "source": str(request.source) if request else "form",
            "requester_name": requester.name if requester else None,
            "requester_contact": requester.contact if requester else None,
            "location_zone": plan.zone or (requester.zone if requester else None),
            "window_start": _iso(now + timedelta(hours=window[0])) if window else None,
            "window_end": _iso(now + timedelta(hours=window[1])) if window else None,
            "flexible": plan.flexible,
            "constraints": list(plan.constraints),
            "money_involved": plan.money_involved,
            "safety_flags": list(plan.safety_flags),
            "first_time_requester": bool(request.first_time_requester) if request else False,
            "is_request": plan.is_request,
            "duplicate_of": _duplicate_of(
                messages, plan.summary, now + timedelta(hours=window[0]) if window else None
            )
            if plan.duplicate
            else None,
            "needs_human": bool(plan.safety_flags) or plan.money_involved,
            "reasoning": plan.reasoning,
        }
    )


def _duplicate_of(messages: Messages, summary: str, window_start: datetime | None) -> str | None:
    """Which open request this message is chasing, out of what the lookup turned up.

    The same neighbour can easily have three open rides — a standing Thursday appointment, a
    same-day clinic change, and a half-audible voicemail — so the match is the one whose summary
    this message actually echoes, with the nearest window breaking a tie.
    """
    found = last_result(messages, "find_similar_open_requests") or []
    rows = [row for row in found if isinstance(row, dict) and row.get("request_id")]
    if not rows:
        return None
    wanted = _words(summary)
    rows.sort(
        key=lambda row: (
            -len(wanted & _words(str(row.get("summary") or ""))),
            _window_gap(row.get("window_start"), window_start),
        )
    )
    return str(rows[0]["request_id"])


STOPWORDS = frozenset(
    {"a", "an", "and", "the", "to", "for", "of", "on", "in", "at", "already", "hand", "again"}
)
"""Words too common to say two summaries are about the same job."""


def _words(text: str) -> set[str]:
    """The distinctive words in a summary, lower-cased."""
    return {
        word.strip(".,;:!?'\"").lower()
        for word in text.split()
        if word.strip(".,;:!?'\"").lower() not in STOPWORDS and len(word) > 2
    }


def _window_gap(candidate: Any, wanted: datetime | None) -> float:
    """Seconds between a candidate's window and the one this message is about."""
    if wanted is None or not isinstance(candidate, str) or not candidate:
        return float("inf")
    try:
        return abs((datetime.fromisoformat(candidate) - wanted).total_seconds())
    except ValueError:  # pragma: no cover - the store always writes ISO-8601
        return float("inf")


def _confidence(plan: SamplePlan, candidates: Sequence[dict[str, Any]]) -> float:
    """Honest confidence: the best score, nudged up when there is a bench behind them."""
    if plan.confidence is not None:
        return plan.confidence
    if not candidates:
        return 0.0
    best = float(candidates[0].get("score") or 0.0)
    depth = min(len(candidates), 3) - 1
    return round(min(1.0, best + DEFAULT_CONFIDENCE_BONUS * depth), 3)


def _matcher_turn(ctx: AppContext, request: AidRequest | None, messages: Messages) -> Turn:
    """Rank the real roster, check memory on the front-runner, then commit to a plan."""
    if request is None:
        return Turn(structured={"request_id": "", "candidates": [], "confidence": 0.0})
    done = called(messages)
    limit = max(1, ctx.settings.max_candidates)
    if "find_candidates" not in done:
        return Turn(tool_calls=[("find_candidates", {"request_id": request.id, "limit": limit})])

    found = last_result(messages, "find_candidates")
    candidates = [c for c in found if isinstance(c, dict) and c.get("volunteer_id")] if found else []
    if candidates and "recall_memory" not in done:
        return Turn(
            tool_calls=[
                (
                    "recall_memory",
                    {
                        "query": request.summary or str(request.category),
                        "about": candidates[0]["volunteer_id"],
                    },
                )
            ]
        )

    plan = plan_for(request)
    confidence = _confidence(plan, candidates)
    ranked = [
        {
            "volunteer_id": c["volunteer_id"],
            "score": float(c.get("score") or 0.0),
            "rationale": "; ".join(list(c.get("reasons") or [])[:2]) or "available and able",
        }
        for c in candidates[:limit]
    ]
    if confidence < ctx.settings.confidence_threshold:
        notes = "Nobody on the roster really fits this one; the coordinator should see it."
    else:
        notes = f"Asking {candidates[0]['name']} first; {max(0, len(ranked) - 1)} more on the bench."
    return Turn(
        structured={
            "request_id": request.id,
            "candidates": ranked,
            "confidence": confidence,
            "notes": notes,
        }
    )


def _next_volunteer(ctx: AppContext, request: AidRequest) -> Volunteer | None:
    """The best-scoring volunteer who has not been asked about this request yet."""
    volunteers = ctx.store.list_volunteers()
    from ..tools._common import load_for

    ranked = rank_candidates(
        volunteers,
        request,
        loads={v.id: load_for(ctx, v.id) for v in volunteers},
        now=ctx.now(),
        timezone=ctx.settings.timezone,
        limit=1,
        exclude=request.attempted_volunteer_ids(),
    )
    return ctx.store.get_volunteer(ranked[0].volunteer_id) if ranked else None


def _ask_body(request: AidRequest, volunteer: Volunteer, requester: Requester | None, timezone: str) -> str:
    """The text Porchlight sends a volunteer, written the way a neighbour would."""
    who = _first_name(requester.name if requester else None)
    return (
        f"Hi {_first_name(volunteer.name)} — {who} needs {request.summary or 'a hand'}, "
        f"{_when_phrase(request, timezone)}. Are you free? Completely fine to say no, "
        "just let me know either way and I'll ask someone else."
    )


def _outreach_turn(ctx: AppContext, request: AidRequest | None, messages: Messages) -> Turn:
    """Ask one volunteer, read their reply, and record what it meant."""
    if request is None:
        return Turn(structured={"action": "escalate", "note": "no request to work on", "done": True})

    done = called(messages)
    requester = ctx.store.get_requester(request.requester_id) if request.requester_id else None

    if not {"send_message", "schedule_message"} & done:
        volunteer = _next_volunteer(ctx, request)
        if volunteer is None:
            return Turn(
                structured={
                    "action": "escalate",
                    "note": "everybody who could take this has already been asked",
                    "done": True,
                }
            )
        body = _ask_body(request, volunteer, requester, ctx.settings.timezone)
        from ..policy import is_quiet_hours, next_send_time

        if is_quiet_hours(ctx.now(), ctx.settings):
            when = next_send_time(ctx.now(), ctx.settings)
            return Turn(
                tool_calls=[
                    (
                        "schedule_message",
                        {
                            "request_id": request.id,
                            "to": "volunteer",
                            "recipient_id": volunteer.id,
                            "body": body,
                            "send_at_iso": when.isoformat(),
                        },
                    )
                ]
            )
        return Turn(
            tool_calls=[
                (
                    "send_message",
                    {
                        "request_id": request.id,
                        "to": "volunteer",
                        "recipient_id": volunteer.id,
                        "body": body,
                    },
                )
            ]
        )

    asked_id = _asked_volunteer_id(messages)
    if "read_replies" not in done:
        return Turn(tool_calls=[("read_replies", {"request_id": request.id})])

    replies = last_result(messages, "read_replies") or []
    reply = _reply_from(replies, asked_id)
    if reply is None:
        return Turn(
            structured={
                "action": "waiting",
                "volunteer_id": asked_id,
                "note": "message queued for the morning; nothing to read yet",
                "done": False,
            }
        )

    if "interpret_reply" not in done:
        volunteer = ctx.store.get_volunteer(str(reply.get("from_volunteer_id") or asked_id or ""))
        return Turn(
            tool_calls=[
                (
                    "interpret_reply",
                    {
                        "reply_text": str(reply.get("text") or ""),
                        "volunteer_name": volunteer.name if volunteer else None,
                    },
                )
            ]
        )

    parsed = last_result(messages, "interpret_reply") or {}
    intent = str(parsed.get("intent") or ReplyIntent.UNCLEAR)
    volunteer_id = str(reply.get("from_volunteer_id") or asked_id or "")
    text = str(reply.get("text") or "")

    resolve = _resolve_calls(request.id, volunteer_id, intent, text)
    for name, args in resolve:
        if name not in done:
            # One tool per turn: assign_volunteer and record_attempt both rewrite the whole
            # request row, so asking for them together would let one clobber the other.
            return Turn(tool_calls=[(name, args)])

    return Turn(structured=_outreach_result(ctx, volunteer_id, intent, text))


def _asked_volunteer_id(messages: Messages) -> str | None:
    """Which volunteer this pass texted."""
    for call in reversed(tool_calls(messages)):
        if call.name in ("send_message", "schedule_message") and call.args.get("to") == "volunteer":
            return str(call.args.get("recipient_id") or "") or None
    return None


def _reply_from(replies: Any, volunteer_id: str | None) -> dict[str, Any] | None:
    """The newest reply from the volunteer we just asked."""
    rows = [r for r in replies if isinstance(r, dict)]
    if volunteer_id:
        mine = [r for r in rows if r.get("from_volunteer_id") == volunteer_id]
        if mine:
            return mine[-1]
    return rows[-1] if rows else None


def _resolve_calls(
    request_id: str, volunteer_id: str, intent: str, text: str
) -> list[tuple[str, dict[str, Any]]]:
    """The tool calls that write one volunteer's answer down, in the order they must run."""
    if intent == ReplyIntent.ACCEPT:
        return [
            ("assign_volunteer", {"request_id": request_id, "volunteer_id": volunteer_id}),
            (
                "record_attempt",
                {
                    "request_id": request_id,
                    "volunteer_id": volunteer_id,
                    "outcome": "accepted",
                    "note": text[:200],
                },
            ),
        ]
    outcome = {
        ReplyIntent.DECLINE: "declined",
        ReplyIntent.COUNTER: "counter",
        ReplyIntent.CONCERN: "concern",
    }.get(ReplyIntent(intent) if intent in set(ReplyIntent) else ReplyIntent.UNCLEAR, "declined")
    return [
        (
            "record_attempt",
            {
                "request_id": request_id,
                "volunteer_id": volunteer_id,
                "outcome": outcome,
                "note": text[:200],
            },
        )
    ]


def _outreach_result(ctx: AppContext, volunteer_id: str, intent: str, text: str) -> dict[str, Any]:
    """The structured summary of this outreach pass."""
    volunteer = ctx.store.get_volunteer(volunteer_id)
    who = volunteer.name if volunteer else "the volunteer"
    if intent == ReplyIntent.ACCEPT:
        return {
            "action": "accepted",
            "volunteer_id": volunteer_id,
            "reply_intent": str(ReplyIntent.ACCEPT),
            "note": f"{who} said yes",
            "done": True,
        }
    if intent == ReplyIntent.CONCERN:
        return {
            "action": "concern",
            "volunteer_id": volunteer_id,
            "reply_intent": str(ReplyIntent.CONCERN),
            "note": f"{who} raised a concern: {text[:120]}",
            "done": True,
        }
    if intent == ReplyIntent.COUNTER:
        return {
            "action": "countered",
            "volunteer_id": volunteer_id,
            "reply_intent": str(ReplyIntent.COUNTER),
            "note": f"{who} proposed a different time",
            "done": False,
        }
    return {
        "action": "declined",
        "volunteer_id": volunteer_id,
        "reply_intent": str(ReplyIntent.DECLINE),
        "note": f"{who} cannot make it; trying the next person",
        "done": False,
    }


def _close_out_reply(ctx: AppContext, request: AidRequest, requester: Requester | None) -> str:
    """The one warm line a thank-you note or a duplicate gets back."""
    who = _first_name(requester.name if requester else None)
    if not request.duplicate_of:
        return (
            f"Thank you {who} — that has been passed on to the neighbour who cooked, and it will "
            "make their week. Nothing needed from us."
        )
    original = ctx.store.get_request(request.duplicate_of)
    when = _when_phrase(original, ctx.settings.timezone) if original else "as arranged"
    return (
        f"Got it {who} — your earlier message came through and it is in hand {when}. "
        "You will hear from us as soon as someone is confirmed."
    )


def _close_out_turn(ctx: AppContext, request: AidRequest, messages: Messages) -> Turn:
    """Reply politely and close a message that needs no outreach at all."""
    done = called(messages)
    requester = ctx.store.get_requester(request.requester_id) if request.requester_id else None
    reason = (
        f"duplicate of {request.duplicate_of}" if request.duplicate_of else "thank-you note, no help needed"
    )
    if "send_message" not in done and request.requester_id:
        return Turn(
            tool_calls=[
                (
                    "send_message",
                    {
                        "request_id": request.id,
                        "to": "requester",
                        "recipient_id": request.requester_id,
                        "body": _close_out_reply(ctx, request, requester),
                    },
                )
            ]
        )
    if "close_request" not in done:
        return Turn(
            tool_calls=[("close_request", {"request_id": request.id, "outcome": "cancelled", "note": reason})]
        )
    return Turn(
        structured={
            "confirmed": False,
            "requester_message": _close_out_reply(ctx, request, requester),
            "reminder_at": None,
            "memory_notes": [],
            "outcome": "cancelled",
            "summary": f"Closed without asking anybody: {reason}.",
        }
    )


def _steward_turn(ctx: AppContext, request: AidRequest | None, messages: Messages) -> Turn:
    """Tell the neighbour who is coming, set a reminder, and write down what was learned."""
    if request is not None and not request.needs_outreach():
        return _close_out_turn(ctx, request, messages)
    if request is None or not request.assigned_volunteer_id:
        return Turn(structured={"outcome": "pending", "summary": "nothing to confirm yet"})

    done = called(messages)
    tz = ctx.settings.timezone
    volunteer = ctx.store.get_volunteer(request.assigned_volunteer_id)
    requester = ctx.store.get_requester(request.requester_id) if request.requester_id else None
    who = volunteer.name if volunteer else "a volunteer"

    if "send_message" not in done and request.requester_id:
        body = (
            f"Good news {_first_name(requester.name if requester else None)} — {who} is coming "
            f"for {request.summary or 'your request'} {_when_phrase(request, tz)}. "
            "They'll be in touch if anything changes."
        )
        return Turn(
            tool_calls=[
                (
                    "send_message",
                    {
                        "request_id": request.id,
                        "to": "requester",
                        "recipient_id": request.requester_id,
                        "body": body,
                    },
                )
            ]
        )

    reminder = _reminder_time(request.window_start, ctx.now())
    if "schedule_message" not in done and reminder is not None:
        return Turn(
            tool_calls=[
                (
                    "schedule_message",
                    {
                        "request_id": request.id,
                        "to": "volunteer",
                        "recipient_id": request.assigned_volunteer_id,
                        "body": (
                            f"Reminder: {request.summary or 'the job'} "
                            f"{_when_phrase(request, tz)}. Thanks again for taking it on."
                        ),
                        "send_at_iso": reminder.isoformat(),
                    },
                )
            ]
        )

    note = f"{who} took a {request.category} job in {request.location_zone or 'the neighbourhood'}"
    if "remember" not in done:
        return Turn(
            tool_calls=[
                (
                    "remember",
                    {
                        "content": f"{note} and said yes on the first ask.",
                        "about_id": request.assigned_volunteer_id,
                        "kind": "fact",
                    },
                )
            ]
        )

    return Turn(
        structured={
            "confirmed": True,
            "requester_message": f"{who} is confirmed for {request.summary or 'the request'}.",
            "reminder_at": _iso(reminder),
            "memory_notes": [note],
            "outcome": "confirmed",
            "summary": f"{who} confirmed; the neighbour has been told and a reminder is set.",
        }
    )


def _reminder_time(window_start: datetime | None, now: datetime) -> datetime | None:
    """When to nudge the volunteer, or ``None`` when the job has no window."""
    if window_start is None:
        return None
    candidate = window_start - timedelta(hours=REMINDER_HOURS_BEFORE)
    return candidate if candidate > now else now


def _interpret_reply_turn(messages: Messages) -> Turn:
    """Classify one volunteer reply with the same keyword read the simulator uses."""
    text = prompt_text(messages)
    marker = "verbatim:"
    body = text.split(marker, 1)[1] if marker in text else text
    body = body.split("Classify it.")[0].strip()
    intent = guess_intent(body)
    concern = body[:200] if intent is ReplyIntent.CONCERN else None
    confidence = 0.9 if intent is not ReplyIntent.UNCLEAR else 0.35
    return Turn(
        structured={
            "intent": str(intent),
            "proposed_time": None,
            "concern_text": concern,
            "confidence": confidence,
        }
    )


def _brief_turn(ctx: AppContext, messages: Messages) -> Turn:
    """Read the day out of the store, then write the digest."""
    done = called(messages)
    if "query_requests" not in done:
        return Turn(tool_calls=[("query_requests", {})])
    if "query_log" not in done:
        return Turn(tool_calls=[("query_log", {"limit": 100})])

    day = ctx.now().date()
    stats = ctx.store.stats(day)
    open_cards = [d for d in ctx.store.list_decisions() if d.open()]
    handled = int(stats.get("handled_autonomously", 0))
    by_status = stats.get("requests_by_status", {}) or {}
    lines = [
        f"# {ctx.settings.group_name} — {day.isoformat()}",
        "",
        f"{handled} handled quietly · {len(open_cards)} need you.",
        "",
        "## Needs you",
        *([f"- {card.title}" for card in open_cards] or ["- Nothing. Enjoy your evening."]),
        "",
        "## Where everything stands",
        *[f"- {status}: {count}" for status, count in sorted(by_status.items())],
    ]
    return Turn(
        structured={
            "headline": f"{handled} handled quietly, {len(open_cards)} waiting on you.",
            "markdown": "\n".join(lines),
            "handled_count": handled,
            "pending_count": int(by_status.get(str(RequestStatus.AWAITING_REPLY), 0)),
            "decisions_open": len(open_cards),
            "patterns": _patterns(by_status),
        }
    )


def _patterns(by_status: dict[str, Any]) -> list[str]:
    """A couple of honest observations about the day."""
    notes: list[str] = []
    escalated = int(by_status.get(str(RequestStatus.ESCALATED), 0))
    confirmed = int(by_status.get(str(RequestStatus.CONFIRMED), 0))
    if confirmed:
        notes.append(f"{confirmed} request(s) found a volunteer without you being asked.")
    if escalated:
        notes.append(f"{escalated} request(s) needed a person; worth reading those cards first.")
    return notes


# --------------------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------------------


class PorchlightScenarioModel(MockModel):
    """A :class:`MockModel` whose turns are computed from live Porchlight state.

    Routing works exactly like :class:`~porchlight.testing.mock_model.ScenarioModel`: the agent
    name comes from ``invocation_state["agent"].name``, falling back to the ``[[agent:...]]``
    marker each Porchlight prompt ends with. An agent this model has no part for — or any
    instance constructed with an explicit ``script`` — falls back to ordinary ``MockModel``
    behaviour, so tests can still script turns by hand.

    Args:
        tier: Which model tier this stands in for; cosmetic, but it shows up in traces.
        **kwargs: Passed through to :class:`MockModel`.
    """

    PLAYS = frozenset({"intake", "matcher", "outreach", "steward", "brief", "interpret_reply"})

    def __init__(self, tier: str = "sonnet", **kwargs: Any) -> None:
        kwargs.setdefault("model_id", f"mock-scenario-{tier}")
        super().__init__(**kwargs)
        self.tier = tier

    def _turn_for(
        self, name: str, ctx: AppContext, request: AidRequest | None, messages: Messages
    ) -> Turn | None:
        """Plan this agent's next move, or ``None`` when there is no part for it."""
        if name == "intake":
            return _intake_turn(ctx, request, messages)
        if name == "matcher":
            return _matcher_turn(ctx, request, messages)
        if name == "outreach":
            return _outreach_turn(ctx, request, messages)
        if name == "steward":
            return _steward_turn(ctx, request, messages)
        if name == "brief":
            return _brief_turn(ctx, messages)
        if name == "interpret_reply":
            return _interpret_reply_turn(messages)
        return None

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        invocation_state: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        """Plan one turn from live state, or fall back to scripted ``MockModel`` behaviour."""
        state = invocation_state or {}
        ctx = state.get("ctx")
        name = ScenarioModel.resolve_agent_name(state, system_prompt)
        turn: Turn | None = None
        if isinstance(ctx, AppContext) and not self.script and name in self.PLAYS:
            request_id = state.get("request_id")
            request = ctx.store.get_request(request_id) if isinstance(request_id, str) else None
            try:
                turn = self._turn_for(name, ctx, request, messages)
            except Exception:  # pragma: no cover - a planner bug must not kill the demo
                logger.exception("mock scenario planner failed for %s; falling back", name)
                turn = None

        if turn is None:
            async for event in super().stream(
                messages,
                tool_specs,
                system_prompt,
                tool_choice=tool_choice,
                invocation_state=invocation_state,
                **kwargs,
            ):
                yield event
            return

        self.calls.append(
            {
                "messages": messages,
                "tool_names": [spec.get("name") for spec in tool_specs or []],
                "system_prompt": system_prompt,
                "tool_choice": tool_choice,
                "agent": name,
            }
        )
        calls = list(turn.tool_calls)
        spec = _structured_output_spec(tool_specs)
        if not calls and turn.structured is not None and spec is not None:
            calls = [(str(spec["name"]), turn.structured)]
        text = turn.text if (turn.text or calls) else "Done."
        async for event in emit_message(text, calls, self._ids):
            yield event

    def __repr__(self) -> str:
        return f"PorchlightScenarioModel(tier={self.tier!r})"

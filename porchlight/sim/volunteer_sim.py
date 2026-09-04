"""The volunteer simulator: a tiny Strands agent that answers texts as a neighbour would.

Real SMS in a hackathon demo is a bad idea, and canned replies are boring. So the demo has one
more agent: it is handed a volunteer's persona ("busy contractor, terse texter, only free
weekends") and the message Porchlight just sent, and it replies in one or two casual sentences
with a structured ``intent`` so the outreach agent has something honest to interpret.

With ``PORCHLIGHT_MODEL_PROVIDER=mock`` the scripted fixture reply is loaded into the mock model
as the turn it plays back, so the same code path runs in tests with no AWS account.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from strands import Agent

from ..context import AppContext
from ..matching import zone_info
from ..models import AidRequest, ReplyIntent, Volunteer
from ..models_provider import make_model
from .fixtures import reply_for

logger = logging.getLogger(__name__)

ReplyFn = Callable[[Volunteer, AidRequest, str], str]

SYSTEM_PROMPT = """You are role-playing ONE volunteer in a neighbourhood mutual-aid group, \
replying to a text message from the group's coordinator.

You are {name}. Your persona: {persona}
You cover: {zones}. You can help with: {skills}.
Your usual availability (local time): {availability}
Notes the group keeps about you: {notes}

Reply exactly as this person would text: one or two short, casual sentences. No greeting \
boilerplate, no sign-off, no emoji unless it fits the persona. Stay in character even when that \
means saying no or proposing a different time. Never invent facts about the neighbour who needs \
help. Set `intent` to what your reply actually means: accept, decline, counter (you propose \
another time), concern (something worries you), or unclear."""

USER_PROMPT = """The coordinator just sent you this message:
\"\"\"{message}\"\"\"

It is about: {summary} ({category}) in {zone}, {when}.

Reply as {name}."""

ACCEPT_HINTS = ("yes", "sure", "happy to", "count me in", "i'll", "on it", "confirmed", "i can do")
DECLINE_HINTS = ("sorry", "can't", "cannot", "no,", "not this", "booked", "away", "i'm not")
COUNTER_HINTS = ("instead", "works better", "could we", "how about", "rather", "if that helps")
CONCERN_HINTS = (
    "how old",
    "is it safe",
    "worried",
    "concerned",
    "a concern",
    "felt off",
    "made me uncomfortable",
    "rather not go alone",
)
"""Phrases that mean the volunteer is uneasy — not merely unavailable."""


class SimReply(BaseModel):
    """What the simulated volunteer said, and what it means."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The reply as the volunteer would text it, 1-2 sentences")
    intent: ReplyIntent = Field(
        default=ReplyIntent.UNCLEAR, description="accept | decline | counter | concern | unclear"
    )


def guess_intent(text: str) -> ReplyIntent:
    """Cheap keyword read of a reply, used to label scripted fixture lines."""
    lowered = text.lower()
    if any(hint in lowered for hint in CONCERN_HINTS):
        return ReplyIntent.CONCERN
    if any(hint in lowered for hint in COUNTER_HINTS):
        return ReplyIntent.COUNTER
    if any(hint in lowered for hint in DECLINE_HINTS):
        return ReplyIntent.DECLINE
    if any(hint in lowered for hint in ACCEPT_HINTS):
        return ReplyIntent.ACCEPT
    return ReplyIntent.UNCLEAR


def _availability_text(volunteer: Volunteer) -> str:
    """Human summary of a volunteer's weekly windows."""
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    if not volunteer.availability:
        return "no fixed windows on file"
    return ", ".join(
        f"{days[w.weekday]} {w.start_hour:02d}:00-{w.end_hour:02d}:00" for w in volunteer.availability
    )


def _when_text(request: AidRequest, timezone: str = "UTC") -> str:
    """Human summary of when the request needs doing, in the group's local time."""
    if request.window_start is None:
        return "no time fixed yet"
    local = request.window_start.astimezone(zone_info(timezone))
    when = f"{local:%A %d %b at %H:%M}"
    return f"{when} (flexible)" if request.flexible else when


def build_system_prompt(volunteer: Volunteer) -> str:
    """The persona prompt for one volunteer."""
    return SYSTEM_PROMPT.format(
        name=volunteer.name,
        persona=volunteer.persona or "an ordinary, friendly neighbour who helps when they can",
        zones=", ".join(volunteer.zones) or "anywhere nearby",
        skills=", ".join(volunteer.skills) or "general help",
        availability=_availability_text(volunteer),
        notes="; ".join(volunteer.notes) or "none",
    )


def build_user_prompt(
    volunteer: Volunteer, request: AidRequest, message_text: str, timezone: str = "UTC"
) -> str:
    """The turn prompt for one incoming message."""
    return USER_PROMPT.format(
        message=message_text.strip(),
        summary=request.summary or request.raw_text[:120] or "a neighbour needs a hand",
        category=request.category,
        zone=request.location_zone or "the neighbourhood",
        when=_when_text(request, timezone),
        name=volunteer.name,
    )


def make_volunteer_sim(ctx: AppContext, *, tier: str = "haiku") -> ReplyFn:
    """Build the reply function :class:`~porchlight.channels.sim.SimChannel` calls.

    Args:
        ctx: The app context; supplies settings (which model provider) and the trace sink.
        tier: Model tier to role-play with; the simulator is deliberately the cheap one.

    Returns:
        ``(volunteer, request, message_text) -> str`` — the volunteer's reply. It never raises:
        if the model misbehaves, the scripted fixture line for that volunteer is returned instead,
        so a demo can't die on stage.
    """
    counters: dict[str, int] = {}

    def reply(volunteer: Volunteer, request: AidRequest, message_text: str) -> str:
        index = counters.get(volunteer.id, 0)
        counters[volunteer.id] = index + 1
        scripted = reply_for(volunteer.id, index)
        try:
            agent = _build_agent(ctx, volunteer, scripted, tier=tier)
            result = agent(
                build_user_prompt(volunteer, request, message_text, ctx.settings.timezone),
                invocation_state={"ctx": ctx, "agent": "volunteer_sim", "request_id": request.id},
            )
            answer = result.structured_output
        except Exception:  # pragma: no cover - the demo must survive a model hiccup
            logger.warning("volunteer simulator failed for %s", volunteer.id, exc_info=True)
            return scripted
        text = (getattr(answer, "text", "") or "").strip()
        chosen = text or scripted
        ctx.emit(
            {
                "type": "message",
                "ts": ctx.clock.now().isoformat(),
                "request_id": request.id,
                "agent": "volunteer_sim",
                "summary": f"{volunteer.name} replied: {chosen[:120]}",
                "detail": {
                    "volunteer_id": volunteer.id,
                    "intent": str(getattr(answer, "intent", guess_intent(chosen))),
                    "simulated": True,
                },
            }
        )
        return chosen

    return reply


def _build_agent(ctx: AppContext, volunteer: Volunteer, scripted: str, *, tier: str = "haiku") -> Agent:
    """One throwaway agent per reply, so personas never bleed into each other."""
    model: Any = make_model(ctx.settings, tier)  # type: ignore[arg-type]
    add_turn = getattr(model, "add_turn", None)
    if callable(add_turn):
        from ..testing.mock_model import MockTurn

        add_turn(MockTurn(structured=SimReply(text=scripted, intent=guess_intent(scripted))))
    return Agent(
        model=model,
        system_prompt=build_system_prompt(volunteer),
        structured_output_model=SimReply,
        name="volunteer_sim",
        description=f"Role-plays {volunteer.name} replying to the coordinator",
        callback_handler=None,
    )


def attach_volunteer_sim(ctx: AppContext, *, tier: str = "haiku") -> ReplyFn | None:
    """Wire the simulator into ``ctx.channel`` when the channel can use one.

    Returns:
        The reply function that was attached, or ``None`` for a channel that does not simulate.
    """
    setter = getattr(ctx.channel, "set_reply_fn", None)
    if not callable(setter):
        return None
    reply_fn = make_volunteer_sim(ctx, tier=tier)
    setter(reply_fn)
    return reply_fn

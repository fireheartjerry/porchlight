"""Structured output models — one per agent, so no agent ever answers in free prose.

Every field carries a default so a model that returns a partial object still validates; the
agents' system prompts, not the schema, are what push for completeness.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models import AidRequest, Category, ReplyIntent, Source, Urgency

__all__ = [
    "AGENT_OUTPUT_MODELS",
    "OutreachAction",
    "BriefResult",
    "IntakeResult",
    "OutreachStep",
    "StewardResult",
]


class _Out(BaseModel):
    """Shared config for agent outputs: tolerant of extra keys the model invents."""

    model_config = ConfigDict(extra="ignore")


class IntakeResult(_Out):
    """What the intake agent understood from one inbound message."""

    summary: str = Field(default="", description="One sentence a neighbour would recognise")
    category: Category = Category.OTHER
    urgency: Urgency = Urgency.NORMAL
    source: Source = Source.FORM
    requester_name: str | None = Field(default=None, description="Name given in the message")
    requester_contact: str | None = Field(default=None, description="Phone, email, or handle")
    location_zone: str | None = Field(default=None, description="Neighbourhood zone, if stated")
    window_start: datetime | None = Field(default=None, description="Earliest useful time, UTC")
    window_end: datetime | None = Field(default=None, description="Latest useful time, UTC")
    flexible: bool = Field(default=False, description="True when the timing can move")
    constraints: list[str] = Field(default_factory=list, description="Wheelchair, no stairs, cat allergy…")
    money_involved: bool = Field(default=False, description="True if the group's money is asked for")
    safety_flags: list[str] = Field(default_factory=list, description="Danger signals, verbatim if possible")
    first_time_requester: bool = Field(default=False)
    is_request: bool = Field(
        default=True,
        description="False when the message asks for nothing: thanks, chit-chat, spam, an update",
    )
    duplicate_of: str | None = Field(
        default=None,
        description="Request id this plainly repeats, from find_similar_open_requests; else null",
    )
    needs_human: bool = Field(default=False, description="True when you are not confident enough to proceed")
    reasoning: str = Field(default="", description="Two lines on how you read the message")

    def is_actionable(self) -> bool:
        """False when this message needs no outreach: it asks for nothing, or repeats a job."""
        return self.is_request and not self.duplicate_of

    def needs_coordinator(self) -> bool:
        """True when this message must reach the coordinator whatever else intake decided.

        Safety beats the not-a-request short-circuit. On the live stack a "the kid next door is
        home alone and the stove is on" message came back with ``is_request=false`` *and* two
        safety flags *and* ``needs_human=true``; the graph read only ``is_request`` and closed it
        as cancelled. Any one of these four signals now routes the message to the decision-card
        path instead, whatever ``is_request`` says.
        """
        return bool(
            self.safety_flags or self.urgency is Urgency.EMERGENCY or self.money_involved or self.needs_human
        )

    def apply_to(self, request: AidRequest) -> AidRequest:
        """Copy the understood fields onto an existing request, leaving ids and status alone."""
        request.summary = self.summary or request.summary
        request.category = self.category
        request.urgency = self.urgency
        request.location_zone = self.location_zone or request.location_zone
        request.window_start = self.window_start or request.window_start
        request.window_end = self.window_end or request.window_end
        request.flexible = self.flexible or request.flexible
        if self.constraints:
            request.constraints = list(self.constraints)
        request.money_involved = request.money_involved or self.money_involved
        merged = list(dict.fromkeys([*request.safety_flags, *self.safety_flags]))
        request.safety_flags = merged
        request.first_time_requester = request.first_time_requester or self.first_time_requester
        request.is_request = self.is_request
        request.duplicate_of = self.duplicate_of or request.duplicate_of
        return request


OutreachAction = Literal["asked", "accepted", "declined", "countered", "concern", "waiting", "escalate"]
"""What outreach did on this pass; drives the graph's retry / hand-off edges."""


class OutreachStep(_Out):
    """What the outreach agent did on this pass, and what should happen next."""

    action: OutreachAction = "waiting"
    volunteer_id: str | None = Field(default=None, description="Volunteer this pass was about")
    message: str = Field(default="", description="The message that was sent, or is proposed")
    reply_intent: ReplyIntent | None = Field(default=None, description="How their reply was read")
    note: str = Field(default="", description="One line for the quiet log")
    done: bool = Field(default=False, description="True when this request no longer needs outreach")


class StewardResult(_Out):
    """The steward's close-out: who was told what, and what is worth remembering."""

    confirmed: bool = Field(default=False, description="True when the requester has been told who is coming")
    requester_message: str = Field(default="", description="What was sent to the requester")
    reminder_at: datetime | None = Field(default=None, description="When a reminder was scheduled, UTC")
    memory_notes: list[str] = Field(default_factory=list, description="Durable facts worth keeping")
    outcome: Literal["confirmed", "completed", "pending", "declined", "cancelled"] = "pending"
    summary: str = Field(default="", description="One line for the coordinator")


class BriefResult(_Out):
    """The nightly digest the coordinator actually reads."""

    headline: str = Field(default="", description="One line: how the day went")
    markdown: str = Field(default="", description="The full digest, in markdown")
    handled_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    decisions_open: int = Field(default=0, ge=0)
    patterns: list[str] = Field(default_factory=list, description="Trends worth noticing")


AGENT_OUTPUT_MODELS: tuple[type[BaseModel], ...] = (
    IntakeResult,
    OutreachStep,
    StewardResult,
    BriefResult,
)
"""Registered with the mock model so unscripted test flows still produce valid output."""

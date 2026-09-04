"""Porchlight domain model (Pydantic v2).

Every entity is JSON-serializable: use :func:`jsonable` (or ``model_dump_json``) when a plain
dict is needed, so ``datetime`` values come out as ISO-8601 strings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .ids import new_id

# --------------------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------------------


class Category(StrEnum):
    """Kind of help being asked for."""

    RIDE = "ride"
    GROCERIES = "groceries"
    MEAL = "meal"
    PRESCRIPTION = "prescription"
    YARD_WORK = "yard_work"
    TECH_HELP = "tech_help"
    TRANSLATION = "translation"
    COMPANIONSHIP = "companionship"
    CHILDCARE = "childcare"
    ERRAND = "errand"
    REPAIR = "repair"
    PAPERWORK = "paperwork"
    OTHER = "other"


class Urgency(StrEnum):
    """How soon the request needs attention."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EMERGENCY = "emergency"


class RequestStatus(StrEnum):
    """Lifecycle of an aid request."""

    NEW = "new"
    TRIAGING = "triaging"
    MATCHING = "matching"
    AWAITING_REPLY = "awaiting_reply"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class Source(StrEnum):
    """Where an inbound message came from."""

    FORM = "form"
    EMAIL = "email"
    SMS = "sms"
    VOICEMAIL = "voicemail"
    PAPER = "paper"
    API = "api"


class ReplyIntent(StrEnum):
    """What a volunteer's reply means."""

    ACCEPT = "accept"
    DECLINE = "decline"
    COUNTER = "counter"
    CONCERN = "concern"
    UNCLEAR = "unclear"


class DecisionKind(StrEnum):
    """Why the coordinator is being asked."""

    SAFETY = "safety"
    MONEY = "money"
    VETTING = "vetting"
    UNMATCHED = "unmatched"
    CONCERN = "concern"
    POLICY = "policy"


class DecisionStatus(StrEnum):
    """Whether a decision card still needs the coordinator."""

    OPEN = "open"
    RESOLVED = "resolved"


class LogKind(StrEnum):
    """Category of a quiet-log entry."""

    TOOL_CALL = "tool_call"
    MESSAGE_SENT = "message_sent"
    DECISION = "decision"
    MEMORY = "memory"
    POLICY = "policy"
    MODEL = "model"


class MessageStatus(StrEnum):
    """Delivery state of an outbound message."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Recipient(StrEnum):
    """Who an outbound message is addressed to."""

    VOLUNTEER = "volunteer"
    REQUESTER = "requester"
    COORDINATOR = "coordinator"


AttemptOutcome = Literal["pending", "accepted", "declined", "counter", "concern", "timeout"]

OPEN_STATUSES: frozenset[RequestStatus] = frozenset(
    {
        RequestStatus.NEW,
        RequestStatus.TRIAGING,
        RequestStatus.MATCHING,
        RequestStatus.AWAITING_REPLY,
        RequestStatus.CONFIRMED,
        RequestStatus.IN_PROGRESS,
        RequestStatus.ESCALATED,
    }
)
"""Statuses where the request still needs work from Porchlight or the coordinator."""

TERMINAL_STATUSES: frozenset[RequestStatus] = frozenset(
    {RequestStatus.COMPLETED, RequestStatus.DECLINED, RequestStatus.CANCELLED}
)

CATEGORY_SKILLS: dict[Category, tuple[str, ...]] = {
    Category.RIDE: ("drive",),
    Category.GROCERIES: ("drive", "shop"),
    Category.MEAL: ("cook",),
    Category.PRESCRIPTION: ("drive", "errands"),
    Category.YARD_WORK: ("lift", "yard"),
    Category.TECH_HELP: ("tech",),
    Category.TRANSLATION: ("translate",),
    Category.COMPANIONSHIP: ("companionship",),
    Category.CHILDCARE: ("childcare-cleared",),
    Category.ERRAND: ("drive", "errands"),
    Category.REPAIR: ("handy", "lift"),
    Category.PAPERWORK: ("paperwork", "tech"),
    Category.OTHER: (),
}
"""Skills that qualify a volunteer for a category (any one of them is enough)."""


def utcnow() -> datetime:
    """Current timezone-aware UTC time (default for ``created_at`` style fields)."""
    return datetime.now(UTC)


def jsonable(value: Any) -> Any:
    """Return a JSON-safe representation (datetimes as ISO strings) of a model or collection."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class _Base(BaseModel):
    """Shared config: reject unknown fields so contract drift fails loudly."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# --------------------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------------------


class AvailabilityWindow(_Base):
    """A recurring weekly window during which a volunteer can help."""

    weekday: int = Field(ge=0, le=6, description="0 = Monday .. 6 = Sunday")
    start_hour: int = Field(ge=0, le=23, description="Local start hour, inclusive")
    end_hour: int = Field(ge=1, le=24, description="Local end hour, exclusive")

    def covers(self, moment: datetime) -> bool:
        """True when ``moment`` (treated as local time) falls inside this window."""
        return moment.weekday() == self.weekday and self.start_hour <= moment.hour < self.end_hour


class VolunteerStats(_Base):
    """Running counters used for fairness and reliability signals."""

    accepted: int = 0
    declined: int = 0
    completed: int = 0
    no_show: int = 0
    last_active: datetime | None = None


class Volunteer(_Base):
    """Someone who can take jobs."""

    id: str = Field(default_factory=lambda: new_id("vol"))
    name: str
    phone: str | None = None
    email: str | None = None
    zones: list[str] = Field(default_factory=list)
    skills: list[str] = Field(
        default_factory=list,
        description="e.g. drive, lift, cook, tech, shop, errands, yard, handy, paperwork, "
        "companionship, childcare-cleared, translate:es",
    )
    availability: list[AvailabilityWindow] = Field(default_factory=list)
    max_per_week: int = 2
    vetted: bool = False
    notes: list[str] = Field(default_factory=list, description="Durable memory notes about this person")
    stats: VolunteerStats = Field(default_factory=VolunteerStats)
    persona: str | None = Field(
        default=None,
        description="Demo-only: how the volunteer simulator should role-play this person",
    )
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)

    def can_do(self, category: Category | str) -> bool:
        """True when this volunteer has a skill that qualifies them for ``category``."""
        cat = Category(category)
        required = CATEGORY_SKILLS.get(cat, ())
        if not required:
            return True
        skills = {skill.lower() for skill in self.skills}
        for want in required:
            if want == "translate":
                if any(skill.startswith("translate") for skill in skills):
                    return True
            elif want in skills:
                return True
        return False

    def serves_zone(self, zone: str | None) -> bool:
        """True when the volunteer covers ``zone`` (or when no zone is specified)."""
        return zone is None or not self.zones or zone in self.zones


class Requester(_Base):
    """Someone asking for help."""

    id: str = Field(default_factory=lambda: new_id("rqr"))
    name: str
    contact: str = Field(description="Phone, email, or handle the request arrived from")
    zone: str | None = None
    address: str | None = Field(default=None, description="Redacted from unvetted volunteers")
    first_seen: datetime = Field(default_factory=utcnow)
    notes: list[str] = Field(default_factory=list)
    history_count: int = Field(default=0, description="Number of prior requests")

    @property
    def is_first_time(self) -> bool:
        """True when this requester has no prior completed requests."""
        return self.history_count == 0


# --------------------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------------------


class Attempt(_Base):
    """One outreach attempt to one volunteer."""

    volunteer_id: str
    sent_at: datetime = Field(default_factory=utcnow)
    outcome: AttemptOutcome = "pending"
    note: str | None = None


class AidRequest(_Base):
    """A structured job derived from an inbound message."""

    id: str = Field(default_factory=lambda: new_id("req"))
    source: Source = Source.FORM
    raw_text: str = ""
    requester_id: str | None = None
    category: Category = Category.OTHER
    summary: str = ""
    window_start: datetime | None = None
    window_end: datetime | None = None
    flexible: bool = False
    location_zone: str | None = None
    constraints: list[str] = Field(default_factory=list)
    urgency: Urgency = Urgency.NORMAL
    money_involved: bool = False
    safety_flags: list[str] = Field(default_factory=list)
    first_time_requester: bool = False
    status: RequestStatus = RequestStatus.NEW
    assigned_volunteer_id: str | None = None
    attempts: list[Attempt] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def is_open(self) -> bool:
        """True while the request still needs work (not completed/declined/cancelled)."""
        return self.status in OPEN_STATUSES

    def hours_until_window(self, now: datetime) -> float | None:
        """Hours until ``window_start``; negative once it has passed, ``None`` when unscheduled."""
        if self.window_start is None:
            return None
        start = self.window_start if self.window_start.tzinfo else self.window_start.replace(tzinfo=UTC)
        reference = now if now.tzinfo else now.replace(tzinfo=UTC)
        return (start - reference).total_seconds() / 3600.0

    def attempted_volunteer_ids(self) -> list[str]:
        """Volunteer ids already contacted about this request, in order."""
        return [attempt.volunteer_id for attempt in self.attempts]

    def touch(self, now: datetime | None = None) -> None:
        """Set ``updated_at`` (defaults to now)."""
        self.updated_at = now or utcnow()


class MatchCandidate(_Base):
    """One ranked volunteer in a match plan."""

    volunteer_id: str
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class MatchPlan(_Base):
    """The matcher's ranked shortlist for one request."""

    request_id: str
    candidates: list[MatchCandidate] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = ""

    def top(self) -> MatchCandidate | None:
        """Highest-scoring candidate, if any."""
        return max(self.candidates, key=lambda c: c.score, default=None)


class VolunteerReply(_Base):
    """Interpretation of a volunteer's free-text reply."""

    intent: ReplyIntent = ReplyIntent.UNCLEAR
    proposed_time: datetime | None = None
    concern_text: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# --------------------------------------------------------------------------------------
# Coordinator surface
# --------------------------------------------------------------------------------------


class DecisionOption(_Base):
    """One tappable option on a decision card."""

    id: str = Field(description="Short snake_case id, e.g. approve / widen_pool / i_will_handle")
    label: str
    description: str = ""


class Decision(_Base):
    """A decision card: the moment the porch light turns on."""

    id: str = Field(default_factory=lambda: new_id("dec"))
    request_id: str | None = None
    kind: DecisionKind = DecisionKind.POLICY
    title: str = ""
    context: str = Field(default="", description="Markdown shown to the coordinator")
    recommendation: str = ""
    options: list[DecisionOption] = Field(default_factory=list)
    interrupt_id: str | None = None
    session_id: str | None = None
    node: str | None = None
    status: DecisionStatus = DecisionStatus.OPEN
    resolved_option: str | None = None
    resolved_note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None

    def open(self) -> bool:
        """True while this card still needs the coordinator."""
        return self.status == DecisionStatus.OPEN

    def option_ids(self) -> list[str]:
        """Ids of the available options."""
        return [option.id for option in self.options]

    def resolve(self, option_id: str, note: str | None = None, now: datetime | None = None) -> None:
        """Mark the card resolved with the chosen option."""
        self.status = DecisionStatus.RESOLVED
        self.resolved_option = option_id
        self.resolved_note = note
        self.resolved_at = now or utcnow()


class LogEvent(_Base):
    """One line of the quiet log."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("log"))
    ts: datetime = Field(default_factory=utcnow)
    request_id: str | None = None
    agent: str | None = None
    kind: LogKind = LogKind.TOOL_CALL
    summary: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    autonomous: bool = True


class OutboundMessage(_Base):
    """A message Porchlight sends (or has scheduled) on the group's behalf."""

    id: str = Field(default_factory=lambda: new_id("msg"))
    request_id: str | None = None
    to: Recipient = Recipient.VOLUNTEER
    recipient_id: str | None = None
    channel: str = Field(default="sim", description="sim | email | sms")
    body: str = ""
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    status: MessageStatus = MessageStatus.DRAFT
    created_at: datetime = Field(default_factory=utcnow)

    def is_due(self, now: datetime) -> bool:
        """True when a scheduled message should now be sent."""
        return (
            self.status == MessageStatus.SCHEDULED
            and self.scheduled_for is not None
            and self.scheduled_for <= now
        )


class InboundReply(_Base):
    """A reply received from a volunteer (produced by the channel)."""

    id: str = Field(default_factory=lambda: new_id("msg"))
    request_id: str | None = None
    from_volunteer_id: str | None = None
    text: str = ""
    received_at: datetime = Field(default_factory=utcnow)


class GroupSettings(_Base):
    """Per-group policy knobs, editable by the coordinator."""

    name: str = "Maple Street Mutual Aid"
    timezone: str = "America/Toronto"
    quiet_hours: tuple[int, int] = (21, 8)
    petty_cash_limit: float = 40.0
    max_candidates: int = 3
    escalate_hours_before_window: int = 6
    confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    zones: list[str] = Field(default_factory=list)


ALL_MODELS: tuple[type[BaseModel], ...] = (
    AvailabilityWindow,
    VolunteerStats,
    Volunteer,
    Requester,
    Attempt,
    AidRequest,
    MatchCandidate,
    MatchPlan,
    VolunteerReply,
    DecisionOption,
    Decision,
    LogEvent,
    OutboundMessage,
    InboundReply,
    GroupSettings,
)
"""Every entity in the domain model; used by tests and the synthetic-instance builder."""

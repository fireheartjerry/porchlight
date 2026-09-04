"""Request and response bodies for the Porchlight API.

Domain entities (``AidRequest``, ``Decision``, ``LogEvent``, …) are returned as-is from
``porchlight.models``; this module only adds the API-shaped wrappers around them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from porchlight.models import (
    AidRequest,
    Attempt,
    Decision,
    GroupSettings,
    LogEvent,
    OutboundMessage,
    Volunteer,
)

SourceLiteral = Literal["form", "email", "sms", "voicemail", "paper", "api"]


class HealthResponse(BaseModel):
    """Liveness plus enough wiring detail to debug a deploy."""

    status: Literal["ok"] = "ok"
    mode: str
    version: str
    model_provider: str
    store: str
    orchestrator: str
    graph_available: bool


class PorchStats(BaseModel):
    """The four numbers on the Porch screen's stat tiles."""

    model_config = ConfigDict(extra="allow")

    handled_autonomously: int = 0
    decisions_open: int = 0
    decisions_resolved: int = 0
    requests_by_status: dict[str, int] = Field(default_factory=dict)
    confirmed_this_week: int = 0
    volunteers_active: int = 0


class PorchResponse(BaseModel):
    """Everything the home screen needs in one call."""

    status_line: str
    light_on: bool
    open_decisions: list[Decision]
    quiet_log: list[LogEvent]
    stats: PorchStats
    group: GroupSettings


class RequestDetail(BaseModel):
    """One request with its attempts, messages, and log."""

    request: AidRequest
    attempts: list[Attempt]
    messages: list[OutboundMessage]
    log: list[LogEvent]


class VolunteerLoad(BaseModel):
    """This week's workload for one volunteer."""

    this_week: int = 0
    max_per_week: int = 0
    last_active: datetime | None = None


class VolunteerView(Volunteer):
    """A volunteer plus the load bar the roster screen draws."""

    load: VolunteerLoad


class InboxIn(BaseModel):
    """A message the group received, pasted or forwarded into Porchlight."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", description="The message exactly as it arrived")
    source: SourceLiteral = "form"
    contact: str | None = Field(default=None, description="Phone, email, or handle it came from")
    image_base64: str | None = Field(default=None, description="Photo of a paper request slip")


class ResolveIn(BaseModel):
    """The coordinator's answer to a decision card."""

    model_config = ConfigDict(extra="forbid")

    option_id: str
    note: str | None = None


class RunDayIn(BaseModel):
    """Parameters for the "Run a Tuesday" demo."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=12, ge=1, le=48)
    reset: bool = Field(default=False, description="Reseed the fixtures before running")


class RunDayStarted(BaseModel):
    """Acknowledgement that the demo day is running in the background."""

    started: bool
    count: int
    detail: str = ""


class ResetResponse(BaseModel):
    """Counts written by a demo reseed."""

    ok: bool = True
    volunteers: int = 0
    requesters: int = 0
    requests: int = 0


class BriefResponse(BaseModel):
    """The daily coordinator digest."""

    day: str
    markdown: str


class SampleMessage(BaseModel):
    """One canned inbound message for the demo inbox."""

    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    source: str
    contact: str | None = None
    text: str
    expected: str
    expected_kind: str | None = None


class TraceEvent(BaseModel):
    """The shape every SSE frame uses (``docs/CONTRACTS.md`` §7)."""

    model_config = ConfigDict(extra="ignore")

    type: str
    ts: str
    request_id: str | None = None
    agent: str | None = None
    summary: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    cursor: int | None = Field(
        default=None, description="Position in the persisted trace; null for in-process events"
    )


class EventsPage(BaseModel):
    """One page of persisted trace events, for clients that poll instead of streaming."""

    events: list[TraceEvent] = Field(default_factory=list)
    cursor: int = Field(default=0, description="Pass this back as ?since= to get the next page")


__all__ = [
    "BriefResponse",
    "EventsPage",
    "HealthResponse",
    "InboxIn",
    "PorchResponse",
    "PorchStats",
    "RequestDetail",
    "ResetResponse",
    "ResolveIn",
    "RunDayIn",
    "RunDayStarted",
    "SampleMessage",
    "TraceEvent",
    "VolunteerLoad",
    "VolunteerView",
]

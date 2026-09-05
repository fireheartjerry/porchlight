"""Porchlight's autonomy boundary: deterministic rules, interventions, and audit hooks.

This module is the executable form of ``docs/DESIGN.md`` §3. Three things live here:

* :func:`evaluate_request` — pure, keyword-and-field based rules that turn an
  :class:`~porchlight.models.AidRequest` into a list of :class:`PolicyFlag`\\ s.
* :class:`PorchlightPolicy` — a Strands ``InterventionHandler`` that turns those flags into
  ``Deny`` / ``Confirm`` / ``Guide`` / ``Transform`` / ``Proceed`` decisions at the tool boundary.
* :class:`AuditHook` and :class:`TraceHook` — ``HookProvider``\\ s that write the Quiet Log and
  push live trace events to ``ctx.emit``.

Contract note: Strands' intervention registry forwards only ``Confirm.prompt`` to
``event.interrupt(...)`` — ``Confirm.reason`` never reaches the interrupt. So every decision card
is encoded **twice**: as JSON in ``Confirm.reason`` (per ``docs/CONTRACTS.md`` §7) and as a
``<porchlight-decision>`` block appended to ``Confirm.prompt``, which is what
:mod:`porchlight.graph` actually parses. :func:`decode_decision` accepts either form.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from strands.hooks import (
    AfterModelCallEvent,
    AfterNodeCallEvent,
    AfterToolCallEvent,
    BeforeNodeCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
    MessageAddedEvent,
)
from strands.interventions import Confirm, Deny, Guide, InterventionHandler, Proceed, Transform

from .config import Settings
from .context import AppContext
from .models import (
    AidRequest,
    Category,
    DecisionKind,
    LogEvent,
    LogKind,
    MatchPlan,
    ReplyIntent,
    RequestStatus,
    Urgency,
    VolunteerReply,
    jsonable,
)
from .tools.summaries import AGENT_ROLES, call_phrase, describe_tool

logger = logging.getLogger(__name__)

Severity = Literal["info", "warn", "block"]
"""``block`` = never do it autonomously; ``warn`` = ask the coordinator; ``info`` = log only."""


# --------------------------------------------------------------------------------------
# Flags
# --------------------------------------------------------------------------------------


class PolicyFlag(BaseModel):
    """One reason Porchlight should not act entirely on its own."""

    model_config = ConfigDict(extra="forbid")

    kind: DecisionKind
    reason: str
    severity: Severity = "warn"

    def blocks(self) -> bool:
        """True when this flag forbids autonomous outreach outright."""
        return self.severity == "block"

    def needs_card(self) -> bool:
        """True when this flag should surface a decision card."""
        return self.severity in ("warn", "block")


DANGER_PATTERNS: tuple[str, ...] = (
    "chest pain",
    "can't breathe",
    "cant breathe",
    "not breathing",
    "unconscious",
    "passed out",
    "heart attack",
    "stroke",
    "overdose",
    "bleed*",
    "suicid*",
    "kill myself",
    "hurt myself",
    "self-harm",
    "self harm",
    "abus*",
    "hitting me",
    "threatening me",
    "threatened me",
    "threatens me",
    "threatening to hurt",
    "threatening to kill",
    "weapon",
    "gun",
    "knife",
    "gas leak",
    "smell gas",
    "smoke",
    "on fire",
    "stove is on",
    "stove on",
    "home alone",
    "alone in the house",
    "child alone",
    "kid is home alone",
    "locked in",
    "911",
    "ambulance",
    "emergency room",
)
"""Substrings that mean a human — usually emergency services — must be involved right now."""

MONEY_PATTERNS: tuple[str, ...] = (
    "gift card",
    "giftcard",
    "cash",
    "money",
    "e-transfer",
    "etransfer",
    "venmo",
    "paypal",
    "zelle",
    "interac",
    "loan",
    "lend me",
    "pay my",
    "pay the",
    "bill",
    "rent",
    "utilities",
    "electric bill",
    "hydro",
    "fundrais*",
    "donation",
    "reimburse",
)
"""Substrings that mean the group's money — not just its time — is being asked for."""

CONCERN_PATTERNS: tuple[str, ...] = (
    "something felt off",
    "felt unsafe",
    "did not feel safe",
    "didn't feel safe",
    "rather not go alone",
    "not go back alone",
    "won't go back",
    "will not go back",
    "told me to leave",
    "made me uncomfortable",
    "shouting at me",
    "yelled at me",
)
"""Substrings that mean a volunteer is reporting something wrong about a visit."""

IN_HOME_PATTERNS: tuple[str, ...] = (
    "inside",
    "in my home",
    "in my house",
    "come in",
    "in-home",
    "in home",
    "into my house",
    "into my home",
    "my apartment",
    "my bedroom",
    "bathroom",
    "shower",
    "bathe",
    "help me dress",
    "lift me",
)
"""Substrings that mean a volunteer would be alone indoors with the requester."""

IN_HOME_CATEGORIES: frozenset[Category] = frozenset(
    {
        Category.CHILDCARE,
        Category.COMPANIONSHIP,
        Category.REPAIR,
        Category.TECH_HELP,
        Category.PAPERWORK,
    }
)
"""Categories that normally happen inside someone's home."""

_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
_AMOUNT_RE = re.compile(
    rf"\$\s?({_NUMBER})|\b({_NUMBER})\s*(?:dollars|bucks|cad|usd)\b",
    re.IGNORECASE,
)


def _text_of(req: AidRequest) -> str:
    """All free text on a request, lower-cased, for keyword matching."""
    parts = [req.raw_text, req.summary, *req.constraints, *req.safety_flags]
    return " ".join(part for part in parts if part).lower()


@lru_cache(maxsize=256)
def _pattern_re(pattern: str) -> re.Pattern[str]:
    """Compile one keyword pattern.

    Patterns match on word boundaries, so "rent" does not fire on "parents". A trailing ``*``
    means "this is a stem": ``"suicid*"`` matches *suicidal* and *suicide*.
    """
    stem = pattern.endswith("*")
    body = re.escape(pattern.rstrip("*"))
    tail = "" if stem else r"\b"
    return re.compile(rf"\b{body}{tail}", re.IGNORECASE)


def matched_patterns(text: str, patterns: tuple[str, ...]) -> list[str]:
    """Return the patterns present in ``text``, as whole words."""
    return [pattern for pattern in patterns if _pattern_re(pattern).search(text)]


def extract_amount(text: str) -> float | None:
    """Return the largest dollar amount mentioned in ``text``, if any."""
    amounts: list[float] = []
    for match in _AMOUNT_RE.finditer(text):
        raw = match.group(1) or match.group(2) or ""
        try:
            amounts.append(float(raw.replace(",", "")))
        except ValueError:  # pragma: no cover - regex already constrains the shape
            continue
    return max(amounts) if amounts else None


def evaluate_request(req: AidRequest, settings: Settings) -> list[PolicyFlag]:
    """Apply the deterministic policy rules to one request.

    The rules are intentionally boring and keyword-driven so they can be read, tested, and
    argued with. The model never decides whether something is an emergency; this function does.

    Args:
        req: The request to evaluate.
        settings: Group policy knobs (petty-cash limit and friends).

    Returns:
        Every flag that applies, most severe first. An empty list means "handle it quietly".
    """
    text = _text_of(req)
    flags: list[PolicyFlag] = []

    danger = matched_patterns(text, DANGER_PATTERNS)
    if req.safety_flags:
        flags.append(
            PolicyFlag(
                kind=DecisionKind.SAFETY,
                reason="intake flagged: " + "; ".join(req.safety_flags),
                severity="block",
            )
        )
    if req.urgency is Urgency.EMERGENCY:
        flags.append(
            PolicyFlag(
                kind=DecisionKind.SAFETY,
                reason="marked as an emergency during intake",
                severity="block",
            )
        )
    if danger:
        flags.append(
            PolicyFlag(
                kind=DecisionKind.SAFETY,
                reason="danger language in the message: " + ", ".join(sorted(set(danger))[:4]),
                severity="block",
            )
        )

    money_hits = matched_patterns(text, MONEY_PATTERNS)
    amount = extract_amount(text)
    over_limit = amount is not None and amount > settings.petty_cash_limit
    if req.money_involved or money_hits or over_limit:
        if over_limit:
            reason = (
                f"asks for ${amount:,.0f}, above the group's ${settings.petty_cash_limit:,.0f} "
                "petty-cash limit"
            )
            severity: Severity = "block"
        else:
            detail = ", ".join(sorted(set(money_hits))[:3]) or "flagged during intake"
            reason = f"involves the group's money ({detail})"
            severity = "warn"
        flags.append(PolicyFlag(kind=DecisionKind.MONEY, reason=reason, severity=severity))

    in_home = bool(matched_patterns(text, IN_HOME_PATTERNS)) or req.category in IN_HOME_CATEGORIES
    if req.first_time_requester and in_home:
        flags.append(
            PolicyFlag(
                kind=DecisionKind.VETTING,
                reason="first-time requester asking for help inside their home",
                severity="warn",
            )
        )

    concern_hits = matched_patterns(text, CONCERN_PATTERNS)
    if concern_hits:
        flags.append(
            PolicyFlag(
                kind=DecisionKind.CONCERN,
                reason="someone reported feeling unsafe: " + ", ".join(sorted(set(concern_hits))[:3]),
                severity="warn",
            )
        )

    order = {"block": 0, "warn": 1, "info": 2}
    flags.sort(key=lambda flag: order[flag.severity])
    return flags


def evaluate_reply(reply: VolunteerReply) -> PolicyFlag | None:
    """Return a concern flag when a volunteer's reply reports something wrong."""
    if reply.intent is not ReplyIntent.CONCERN:
        return None
    return PolicyFlag(
        kind=DecisionKind.CONCERN,
        reason=reply.concern_text or "a volunteer raised a concern",
        severity="warn",
    )


def has_kind(flags: list[PolicyFlag], kind: DecisionKind) -> list[PolicyFlag]:
    """Flags of one kind."""
    return [flag for flag in flags if flag.kind is kind]


def blocking(flags: list[PolicyFlag]) -> list[PolicyFlag]:
    """Flags that forbid autonomous action."""
    return [flag for flag in flags if flag.blocks()]


# --------------------------------------------------------------------------------------
# Quiet hours
# --------------------------------------------------------------------------------------


def _zone(settings: Settings) -> ZoneInfo:
    """The group's local timezone, falling back to UTC when it is unknown."""
    try:
        return ZoneInfo(settings.timezone)
    except Exception:  # pragma: no cover - depends on the host tz database
        logger.warning("unknown timezone %r; using UTC", settings.timezone)
        return ZoneInfo("UTC")


def to_local(moment: datetime, settings: Settings) -> datetime:
    """Convert a UTC instant to the group's local time."""
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(_zone(settings))


def is_quiet_hours(moment: datetime, settings: Settings) -> bool:
    """True when ``moment`` falls inside the group's quiet hours (default 21:00–08:00 local)."""
    start, end = settings.quiet_hours
    hour = to_local(moment, settings).hour
    if start == end:
        return False
    if start > end:  # window wraps midnight, e.g. 21 -> 8
        return hour >= start or hour < end
    return start <= hour < end


def next_send_time(moment: datetime, settings: Settings) -> datetime:
    """The next moment (UTC) at which it is polite to send a message.

    Returns ``moment`` itself when it is already outside quiet hours.
    """
    if not is_quiet_hours(moment, settings):
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    local = to_local(moment, settings)
    _, end = settings.quiet_hours
    target = local.replace(hour=end % 24, minute=0, second=0, microsecond=0)
    if target <= local:
        target = target + timedelta(days=1)
    return target.astimezone(UTC)


# --------------------------------------------------------------------------------------
# PII redaction
# --------------------------------------------------------------------------------------

PHONE_RE = re.compile(r"(?:\+?\d{1,2}[\s.‑-]?)?\(?\d{3}\)?[\s.‑-]?\d{3}[\s.‑-]?\d{4}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_STREET_WORDS = (
    "street|st|avenue|ave|road|rd|lane|ln|drive|dr|boulevard|blvd|court|ct|way|place|pl|"
    "terrace|terr|crescent|cres|close|circle|cir|trail|parkway|pkwy"
)
ADDRESS_RE = re.compile(
    rf"\b\d{{1,5}}[a-z]?\s+(?:[A-Za-z][\w'.-]*\s+){{0,3}}(?:{_STREET_WORDS})\b\.?",
    re.IGNORECASE,
)

PHONE_MASK = "[phone shared once you accept]"
ADDRESS_MASK = "[address shared once you accept]"
EMAIL_MASK = "[email shared once you accept]"


def redact_pii(text: str) -> str:
    """Strip a requester's phone number, street address, and email from a draft message.

    Deliberately blunt: it is better to withhold an address from a volunteer who has not yet
    said yes than to leak one. The full details are sent again after acceptance.
    """
    if not text:
        return text
    redacted = ADDRESS_RE.sub(ADDRESS_MASK, text)
    redacted = PHONE_RE.sub(PHONE_MASK, redacted)
    return EMAIL_RE.sub(EMAIL_MASK, redacted)


def contains_pii(text: str) -> bool:
    """True when ``text`` still holds a phone number, address, or email."""
    return redact_pii(text) != text


# --------------------------------------------------------------------------------------
# Decision cards
# --------------------------------------------------------------------------------------

DECISION_MARKER = "<porchlight-decision>"
DECISION_END = "</porchlight-decision>"

APPROVING_OPTIONS: frozenset[str] = frozenset(
    {"approve", "approve_once", "proceed", "continue", "send_anyway", "widen_pool", "yes"}
)
"""Option ids that mean "go ahead" — the gated tool runs."""

DENYING_OPTIONS: frozenset[str] = frozenset(
    {"decline_request", "i_will_handle", "reschedule", "hold", "cancel", "deny", "no", "escalate"}
)
"""Option ids that mean "stop" — the gated tool is cancelled and a human takes over."""


def resolved_option_for(store: Any, request_id: str | None, kind: DecisionKind) -> str | None:
    """The option the coordinator already chose for this kind of card on this request.

    A decision card is asked **once**: the graph gate raises it before any outreach happens, and
    the tool-level policy would otherwise ask the same question again the moment the agent tries
    to message a volunteer. Both consult this, so an answered card stays answered.

    Args:
        store: The application store.
        request_id: Request the card was about; ``None`` means nothing was decided.
        kind: Which card to look for.

    Returns:
        The chosen option id, or ``None`` when this card has not been answered.
    """
    if not request_id:
        return None
    try:
        decisions = store.list_decisions()
    except Exception:  # pragma: no cover - a store hiccup must not block the policy
        logger.exception("could not read decisions while checking policy history")
        return None
    for decision in decisions:
        if decision.request_id == request_id and decision.kind is kind and decision.resolved_option:
            return str(decision.resolved_option)
    return None


def already_approved(store: Any, request_id: str | None, kind: DecisionKind) -> bool:
    """True when the coordinator has already said "go ahead" to this card on this request."""
    option = resolved_option_for(store, request_id, kind)
    return option is not None and option.lower() in APPROVING_OPTIONS


@dataclass(frozen=True)
class DecisionSpec:
    """Everything the coordinator needs to make one call, and the graph needs to render it."""

    kind: DecisionKind
    title: str
    context: str
    recommendation: str
    options: tuple[tuple[str, str, str], ...]
    request_id: str | None = None

    def payload(self) -> dict[str, Any]:
        """JSON-safe dict form used both in ``Confirm.reason`` and inside the prompt."""
        return {
            "kind": str(self.kind),
            "title": self.title,
            "context": self.context,
            "recommendation": self.recommendation,
            "request_id": self.request_id,
            "options": [
                {"id": option_id, "label": label, "description": description}
                for option_id, label, description in self.options
            ],
        }

    def reason(self) -> str:
        """The JSON blob carried on ``Confirm.reason``."""
        return json.dumps(self.payload(), separators=(",", ":"))

    def prompt(self) -> str:
        """Human-readable prompt with the machine-readable payload appended."""
        lines = [self.title, "", self.context, "", f"Recommended: {self.recommendation}", "", "Options:"]
        lines += [f"  - {oid}: {label} — {desc}" for oid, label, desc in self.options]
        lines += ["", DECISION_MARKER + self.reason() + DECISION_END]
        return "\n".join(lines)

    def confirm(self) -> Confirm:
        """Build the Strands ``Confirm`` action that raises this card as an interrupt."""
        return Confirm(prompt=self.prompt(), reason=self.reason(), evaluate=evaluate_option)


def evaluate_option(response: Any) -> bool:
    """Decide whether a coordinator's answer lets the gated tool run.

    Accepts ``{"option": "<id>", "note": ...}`` (what the UI sends), a bare option id, or the
    plain ``True``/``"yes"`` that Strands' default evaluator understands. Unknown option ids are
    treated as a refusal — the safe direction.
    """
    option: Any = response
    if isinstance(response, dict):
        option = response.get("option", response.get("option_id"))
    if isinstance(option, bool):
        return option
    if isinstance(option, str):
        normalised = option.strip().lower()
        if normalised in APPROVING_OPTIONS:
            return True
        if normalised in DENYING_OPTIONS:
            return False
        return normalised in {"y", "true"}
    return False


def option_id_of(response: Any) -> str | None:
    """Pull the option id out of an interrupt response, if it has one."""
    if isinstance(response, dict):
        value = response.get("option", response.get("option_id"))
        return str(value) if value is not None else None
    if isinstance(response, str):
        return response.strip().lower()
    return None


def decode_decision(reason: Any) -> dict[str, Any] | None:
    """Recover a decision payload from an interrupt reason.

    Handles the three shapes a reason can take: an already-decoded dict, a bare JSON string,
    or a human-readable prompt with a ``<porchlight-decision>`` block appended.
    """
    if isinstance(reason, dict):
        return reason if "kind" in reason else None
    if not isinstance(reason, str) or not reason:
        return None
    text = reason
    if DECISION_MARKER in text:
        start = text.index(DECISION_MARKER) + len(DECISION_MARKER)
        end = text.find(DECISION_END, start)
        text = text[start:end] if end > start else text[start:]
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) and "kind" in payload else None


def _summary(req: AidRequest | None) -> str:
    """One line describing a request, for card context."""
    if req is None:
        return "an unidentified request"
    return req.summary or (req.raw_text[:160] if req.raw_text else req.id)


def safety_card(req: AidRequest | None, flags: list[PolicyFlag]) -> DecisionSpec:
    """Red card: the message hints at danger, so no volunteer goes out on autopilot."""
    reasons = "\n".join(f"- {flag.reason}" for flag in flags) or "- danger language in the message"
    return DecisionSpec(
        kind=DecisionKind.SAFETY,
        title="Possible emergency — needs you now",
        context=(
            f"**{_summary(req)}**\n\n"
            f"Porchlight stopped before contacting anyone because:\n{reasons}\n\n"
            "No volunteer has been messaged. The draft reply to the requester points them at "
            "emergency services."
        ),
        recommendation="Call the requester yourself, and tell them to dial emergency services now.",
        options=(
            ("i_will_handle", "I'll handle this", "You take it personally; Porchlight stands down."),
            ("approve", "Send a volunteer anyway", "Only if you have confirmed it is not an emergency."),
            ("decline_request", "Not something we can help with", "Close it with a kind explanation."),
        ),
        request_id=req.id if req else None,
    )


def money_card(req: AidRequest | None, flags: list[PolicyFlag], settings: Settings) -> DecisionSpec:
    """Money is being asked for, so a person commits the group's funds, not an agent."""
    reasons = "\n".join(f"- {flag.reason}" for flag in flags) or "- the request involves money"
    return DecisionSpec(
        kind=DecisionKind.MONEY,
        title="Money is involved — your call",
        context=(
            f"**{_summary(req)}**\n\n"
            f"{reasons}\n\n"
            f"The group's petty-cash limit is ${settings.petty_cash_limit:,.0f}. Porchlight will "
            "not promise money to anyone without you."
        ),
        recommendation="Approve only if this fits the group's petty cash rules; otherwise refer them on.",
        options=(
            ("approve", "Approve the spend", "Porchlight continues and arranges the help."),
            ("i_will_handle", "I'll handle this", "You take the money side yourself."),
            ("decline_request", "Decline", "Close it with a referral to a fund that can help."),
        ),
        request_id=req.id if req else None,
    )


def vetting_card(req: AidRequest | None, flags: list[PolicyFlag]) -> DecisionSpec:
    """A new requester asking for in-home help: a human decides who goes inside."""
    reasons = "\n".join(f"- {flag.reason}" for flag in flags) or "- new requester, in-home help"
    return DecisionSpec(
        kind=DecisionKind.VETTING,
        title="New requester wants in-home help",
        context=(
            f"**{_summary(req)}**\n\n{reasons}\n\n"
            "Nobody in the group has met this person yet, and this job happens inside their home."
        ),
        recommendation="Approve if you can vouch for them, or pair a vetted volunteer with a second person.",
        options=(
            ("approve", "Approve — send a vetted volunteer", "Porchlight only asks vetted volunteers."),
            ("i_will_handle", "I'll visit first", "You meet them before anyone is dispatched."),
            ("decline_request", "Decline for now", "Close it politely until we know them."),
        ),
        request_id=req.id if req else None,
    )


def unmatched_card(req: AidRequest | None, plan: MatchPlan | None, settings: Settings) -> DecisionSpec:
    """Nobody good is free: widen the pool, move it, take it, or say no."""
    if plan is None or not plan.candidates:
        detail = "No volunteer in the roster matches this job."
    else:
        names = ", ".join(candidate.volunteer_id for candidate in plan.candidates[:3])
        detail = (
            f"Best available: {names} (confidence {plan.confidence:.2f}, below the "
            f"{settings.confidence_threshold:.2f} threshold)."
        )
    attempts = len(req.attempts) if req else 0
    return DecisionSpec(
        kind=DecisionKind.UNMATCHED,
        title="Nobody free — needs a nudge",
        context=(
            f"**{_summary(req)}**\n\n{detail}\n\n"
            f"{attempts} volunteer(s) asked so far, limit {settings.max_candidates}."
        ),
        recommendation="Widen the pool to volunteers outside the zone before asking anyone to reschedule.",
        options=(
            ("widen_pool", "Widen the pool", "Ask volunteers outside the zone or over their usual cap."),
            ("reschedule", "Ask to reschedule", "Offer the requester a different time."),
            ("i_will_handle", "I'll cover it", "You take this one."),
            ("decline_request", "Decline", "Tell them we could not cover it this time."),
        ),
        request_id=req.id if req else None,
    )


def concern_card(req: AidRequest | None, note: str) -> DecisionSpec:
    """A volunteer reported something off — always a person's call."""
    return DecisionSpec(
        kind=DecisionKind.CONCERN,
        title="A volunteer raised a concern",
        context=f"**{_summary(req)}**\n\nThey said:\n\n> {note or 'something felt off'}",
        recommendation="Call the volunteer, then decide whether to keep this requester on the roster.",
        options=(
            ("approve", "Noted — carry on", "Log the concern and continue with the job."),
            ("i_will_handle", "I'll follow up", "You call the volunteer and the requester."),
            ("decline_request", "Pause this requester", "Close the request while you look into it."),
        ),
        request_id=req.id if req else None,
    )


def card_for(req: AidRequest | None, flags: list[PolicyFlag], settings: Settings) -> DecisionSpec | None:
    """Pick the card that matches the most severe flag, or ``None`` when nothing applies."""
    for kind, builder in (
        (DecisionKind.SAFETY, lambda f: safety_card(req, f)),
        (DecisionKind.MONEY, lambda f: money_card(req, f, settings)),
        (DecisionKind.VETTING, lambda f: vetting_card(req, f)),
        (DecisionKind.CONCERN, lambda f: concern_card(req, f[0].reason)),
    ):
        matching = [flag for flag in flags if flag.kind is kind and flag.needs_card()]
        if matching:
            return builder(matching)
    return None


# --------------------------------------------------------------------------------------
# The intervention handler
# --------------------------------------------------------------------------------------

GATED_TOOLS: frozenset[str] = frozenset(
    {"send_message", "schedule_message", "assign_volunteer", "close_request", "remember"}
)
"""Tools with real-world side effects; every one passes through the policy."""

MESSAGE_TOOLS: frozenset[str] = frozenset({"send_message", "schedule_message"})
COMMIT_TOOLS: frozenset[str] = frozenset({"assign_volunteer"})

HALTED_STATUSES: frozenset[RequestStatus] = frozenset(
    {
        RequestStatus.ESCALATED,
        RequestStatus.DECLINED,
        RequestStatus.CANCELLED,
        RequestStatus.COMPLETED,
    }
)
"""Statuses where a person owns the request; Porchlight stops asking volunteers about it."""


class PorchlightPolicy(InterventionHandler):
    """The autonomy boundary, enforced at the tool call.

    Implements the table in ``docs/DESIGN.md`` §3 in this order: deny outright, ask the
    coordinator, steer away from quiet hours, redact private details, otherwise proceed.
    """

    name = "porchlight-policy"

    def __init__(self, ctx: AppContext) -> None:
        """Bind the handler to an application context (store, settings, clock, trace sink)."""
        self.ctx = ctx

    # --- helpers ---------------------------------------------------------------

    def _ctx(self, event: BeforeToolCallEvent) -> AppContext:
        """Prefer the context on the live invocation, fall back to the bound one."""
        candidate = (event.invocation_state or {}).get("ctx")
        return candidate if isinstance(candidate, AppContext) else self.ctx

    def _request(
        self, ctx: AppContext, event: BeforeToolCallEvent, args: dict[str, Any]
    ) -> AidRequest | None:
        """Resolve the request this tool call is about."""
        request_id = args.get("request_id") or (event.invocation_state or {}).get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return None
        return ctx.store.get_request(request_id)

    def _note(self, ctx: AppContext, spec: DecisionSpec, tool_name: str) -> None:
        """Record that the porch light is about to come on."""
        ctx.emit(
            {
                "type": "decision",
                "ts": ctx.now().isoformat(),
                "request_id": spec.request_id,
                "agent": None,
                "summary": spec.title,
                "detail": {"kind": str(spec.kind), "tool": tool_name, "stage": "requested"},
            }
        )

    def _trusted_with_details(self, ctx: AppContext, req: AidRequest | None, volunteer_id: str) -> bool:
        """True when this volunteer has both been vetted and already accepted this job."""
        if req is None or req.assigned_volunteer_id != volunteer_id:
            return False
        volunteer = ctx.store.get_volunteer(volunteer_id)
        return bool(volunteer and volunteer.vetted)

    # --- lifecycle -------------------------------------------------------------

    def before_tool_call(
        self, event: BeforeToolCallEvent, **kwargs: Any
    ) -> Proceed | Deny | Guide | Confirm | Transform:
        """Gate one tool call. See ``docs/DESIGN.md`` §3 for the rule table."""
        tool_name = str(event.tool_use.get("name", ""))
        args: dict[str, Any] = dict(event.tool_use.get("input") or {})
        ctx = self._ctx(event)
        request = self._request(ctx, event, args)

        # A volunteer reporting something wrong is always a person's call.
        if tool_name == "record_attempt" and args.get("outcome") == "concern":
            spec = concern_card(request, str(args.get("note") or ""))
            self._note(ctx, spec, tool_name)
            return spec.confirm()

        if tool_name not in GATED_TOOLS:
            return Proceed()

        flags = evaluate_request(request, ctx.settings) if request else []
        recipient = str(args.get("to") or "")
        to_volunteer = recipient == "volunteer" or tool_name in COMMIT_TOOLS

        if request is not None and request.status in HALTED_STATUSES and to_volunteer:
            return Deny(
                reason=(
                    f"This request is {request.status}: the coordinator has taken it over or it is "
                    "closed. Do not contact any volunteer about it. Stop and report."
                )
            )

        safety = [flag for flag in has_kind(flags, DecisionKind.SAFETY) if flag.blocks()]
        if safety and to_volunteer:
            return Deny(
                reason=(
                    "This request looks like an emergency, so Porchlight does not dispatch "
                    "volunteers for it. Reply to the requester telling them to call emergency "
                    "services now, and stop: the coordinator has already been alerted."
                )
            )

        request_id = request.id if request else None
        money = [flag for flag in has_kind(flags, DecisionKind.MONEY) if flag.needs_card()]
        if (
            money
            and (to_volunteer or tool_name in MESSAGE_TOOLS or tool_name == "close_request")
            and not already_approved(ctx.store, request_id, DecisionKind.MONEY)
        ):
            spec = money_card(request, money, ctx.settings)
            self._note(ctx, spec, tool_name)
            return spec.confirm()

        vetting = [flag for flag in has_kind(flags, DecisionKind.VETTING) if flag.needs_card()]
        if vetting and to_volunteer and not already_approved(ctx.store, request_id, DecisionKind.VETTING):
            spec = vetting_card(request, vetting)
            self._note(ctx, spec, tool_name)
            return spec.confirm()

        quiet = tool_name == "send_message" and recipient != "coordinator"
        if quiet and is_quiet_hours(ctx.now(), ctx.settings):
            when = next_send_time(ctx.now(), ctx.settings)
            return Guide(
                feedback=(
                    f"It is quiet hours for {ctx.settings.group_name}. Do not send this now. "
                    f"Call schedule_message with the same body and send_at_iso='{when.isoformat()}' "
                    "so it lands first thing in the morning."
                ),
                reason="quiet-hours",
            )

        if tool_name in MESSAGE_TOOLS and recipient == "volunteer":
            body = str(args.get("body") or "")
            recipient_id = str(args.get("recipient_id") or "")
            if contains_pii(body) and not self._trusted_with_details(ctx, request, recipient_id):
                return Transform(apply=_redact_body, reason="pii-before-acceptance")

        return Proceed()


def _redact_body(event: Any) -> None:
    """Strip private contact details from a tool call's ``body`` argument, in place."""
    tool_use = getattr(event, "tool_use", None)
    if not isinstance(tool_use, dict):  # pragma: no cover - defensive
        return
    args = tool_use.get("input")
    if isinstance(args, dict) and isinstance(args.get("body"), str):
        args["body"] = redact_pii(args["body"])


# --------------------------------------------------------------------------------------
# Hooks
# --------------------------------------------------------------------------------------


def _agent_name(event: Any) -> str | None:
    """Best-effort agent name for a hook event."""
    agent = getattr(event, "agent", None)
    name = getattr(agent, "name", None)
    return name if isinstance(name, str) else None


def _request_id(event: Any, ctx: AppContext) -> str | None:
    """Request id from the event's invocation state, if it carries one."""
    state = getattr(event, "invocation_state", None) or {}
    value = state.get("request_id") if isinstance(state, dict) else None
    return value if isinstance(value, str) else None


NODE_STARTED: dict[str, str] = {
    "intake": "Intake is reading the message.",
    "matcher": "Matcher is looking for someone who can help.",
    "outreach": "Outreach is asking a volunteer.",
    "steward": "Steward is confirming and tidying up.",
    "brief": "Brief is writing the evening digest.",
}
"""What each graph node is about to do, for the Trace drawer."""


def _role(name: str | None) -> str:
    """A readable name for an agent or graph node."""
    if not name:
        return "Porchlight"
    return AGENT_ROLES.get(name, name.replace("_", " ").capitalize())


def _short(value: Any, limit: int = 160) -> str:
    """Compact one-line rendering of a tool argument blob."""
    try:
        text = json.dumps(jsonable(value), default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


SELF_LOGGING_TOOLS: frozenset[str] = frozenset(
    {
        "send_message",
        "schedule_message",
        "assign_volunteer",
        "record_attempt",
        "update_request",
        "close_request",
        "remember",
    }
)
"""Tools that write their own quiet-log row, so the hook's copy is bookkeeping."""


@dataclass
class AuditHook(HookProvider):
    """Writes the Quiet Log: one row per tool call, with its arguments and outcome.

    Every autonomous side effect ends up here, which is what makes the coordinator able to
    skim what happened rather than having to supervise it. The wording comes from
    :func:`porchlight.tools.summaries.describe_tool` — the tool itself knows best what it did —
    and anything that is pure bookkeeping is written with ``visible=False`` so the porch shows
    the story rather than the mechanics.
    """

    ctx: AppContext

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Attach to the tool lifecycle."""
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        name = str(event.tool_use.get("name", "tool"))
        args = event.tool_use.get("input") or {}
        request_id = str(args.get("request_id") or "") or _request_id(event, self.ctx)
        self.ctx.emit(
            {
                "type": "tool_call",
                "ts": self.ctx.now().isoformat(),
                "request_id": request_id,
                "agent": _agent_name(event),
                "summary": call_phrase(name, _agent_name(event)),
                "detail": {"tool": name, "input": jsonable(event.tool_use.get("input") or {})},
            }
        )

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        name = str(event.tool_use.get("name", "tool"))
        args = dict(event.tool_use.get("input") or {})
        request_id = str(args.get("request_id") or "") or _request_id(event, self.ctx)
        status = str((event.result or {}).get("status", "unknown"))
        cancelled = bool(event.cancel_message)
        kind = LogKind.MESSAGE_SENT if name in MESSAGE_TOOLS else LogKind.TOOL_CALL
        if name == "remember":
            kind = LogKind.MEMORY
        note = describe_tool(
            self.ctx,
            name,
            args,
            event.result,
            cancelled=cancelled,
            cancel_message=event.cancel_message,
            card=decode_decision(event.cancel_message),
        )
        entry = LogEvent(
            ts=self.ctx.now(),
            request_id=request_id or None,
            agent=_agent_name(event),
            kind=LogKind.POLICY if cancelled else kind,
            summary=note.summary,
            detail={
                "tool": name,
                "input": jsonable(args),
                "status": status,
                "cancel_message": event.cancel_message,
                "duration_ms": round((event.duration or 0.0) * 1000),
            },
            autonomous=not cancelled,
            # A tool that already wrote its own line says it better; this row stays as the
            # audit trail behind ``?all=1`` rather than repeating it on the porch.
            visible=note.visible and (cancelled or name not in SELF_LOGGING_TOOLS),
        )
        try:
            self.ctx.store.append_log(entry)
        except Exception:  # pragma: no cover - the log must never break a run
            logger.exception("failed to append audit log for tool %s", name)
        self.ctx.emit(
            {
                "type": "tool_result",
                "ts": entry.ts.isoformat(),
                "request_id": entry.request_id,
                "agent": entry.agent,
                "summary": note.summary,
                "detail": {"tool": name, "status": status, "cancelled": cancelled},
            }
        )


@dataclass
class TraceHook(HookProvider):
    """Streams node, message, and model events to ``ctx.emit`` for the live Trace drawer."""

    ctx: AppContext
    tokens: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0, "total": 0})
    _last_request_id: str | None = field(default=None, repr=False)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Attach to graph-node, message, and model lifecycle events."""
        registry.add_callback(BeforeNodeCallEvent, self._node_start)
        registry.add_callback(AfterNodeCallEvent, self._node_end)
        registry.add_callback(MessageAddedEvent, self._message)
        registry.add_callback(AfterModelCallEvent, self._model)

    def _emit(self, kind: str, summary: str, detail: dict[str, Any], **extra: Any) -> None:
        request_id = extra.get("request_id") or self._last_request_id
        self._last_request_id = request_id
        event = {
            "type": kind,
            "ts": self.ctx.now().isoformat(),
            "request_id": request_id,
            "agent": extra.get("agent"),
            "summary": summary,
            "detail": detail,
        }
        self.ctx.emit(event)

    def _node_start(self, event: BeforeNodeCallEvent) -> None:
        self._emit(
            "node_start",
            NODE_STARTED.get(event.node_id, f"{_role(event.node_id)} started."),
            {"node": event.node_id},
            agent=event.node_id,
            request_id=_request_id(event, self.ctx),
        )

    def _node_end(self, event: AfterNodeCallEvent) -> None:
        self._emit(
            "node_end",
            f"{_role(event.node_id)} is done.",
            {"node": event.node_id},
            agent=event.node_id,
            request_id=_request_id(event, self.ctx),
        )

    def _message(self, event: MessageAddedEvent) -> None:
        message = event.message or {}
        role = str(message.get("role", "?"))
        blocks = message.get("content") or []
        text = " ".join(block.get("text", "") for block in blocks if isinstance(block, dict)).strip()
        tools = [
            block["toolUse"].get("name")
            for block in blocks
            if isinstance(block, dict) and isinstance(block.get("toolUse"), dict)
        ]
        named = [str(name) for name in tools if name]
        who = _role(_agent_name(event))
        if text:
            summary = f"{who}: {text[:140]}"
        elif named:
            summary = call_phrase(named[0], _agent_name(event))
        elif role == "user":
            summary = f"The tool's answer came back to {who}."
        else:
            summary = f"{who} added an empty turn."
        self._emit(
            "message",
            summary,
            {"role": role, "tools": tools, "text": text[:2000]},
            agent=_agent_name(event),
        )

    def _model(self, event: AfterModelCallEvent) -> None:
        usage = self._usage(event)
        fields = (("input", "inputTokens"), ("output", "outputTokens"), ("total", "totalTokens"))
        for key, field_name in fields:
            self.tokens[key] = int(usage.get(field_name, 0) or 0)
        stop = getattr(event.stop_response, "stop_reason", None) if event.stop_response else None
        who = _role(_agent_name(event))
        if event.exception:
            summary = f"{who} hit a model error."
        elif stop == "tool_use":
            summary = f"{who} decided to use a tool."
        else:
            summary = f"{who} finished thinking."
        self._emit(
            "model_call",
            summary,
            {"stop_reason": stop, "usage": usage, "error": str(event.exception) if event.exception else None},
            agent=_agent_name(event),
            request_id=_request_id(event, self.ctx),
        )

    @staticmethod
    def _usage(event: AfterModelCallEvent) -> dict[str, int]:
        """Pull cumulative token usage off the agent's metrics, when the provider reports it."""
        agent = getattr(event, "agent", None)
        metrics = getattr(agent, "event_loop_metrics", None)
        usage = getattr(metrics, "accumulated_usage", None)
        if isinstance(usage, dict):
            return {key: int(value) for key, value in usage.items() if isinstance(value, int)}
        return {}

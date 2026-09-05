"""Plain-English descriptions of what a tool call just did.

The Quiet Log is the coordinator's view of the evening, not a debugger. Every row has to read
like a note a colleague left — "Asked Maria: ride to dialysis, Thursday 9am." — which means the
wording has to come from somewhere that knows the tool's arguments, its result, and the request
they belong to. That is this module.

:func:`describe_tool` is used twice for every call:

* the tools themselves (:mod:`porchlight.tools.messaging`, :mod:`porchlight.tools.records`) call
  it when they write their own quiet-log row, so the MCP surface and the in-process surface word
  things identically;
* :class:`~porchlight.policy.AuditHook` calls it for everything else — the structured-output
  "tools" the agents finish with, and the read-only lookups — so nothing ever falls back to a
  raw tool name.

A note also says whether it belongs on the porch at all: :attr:`ToolNote.visible` is ``False``
for pure bookkeeping (lookups, reads, and the rows another line already tells better), and the
API hides those from ``/api/porch`` unless ``?all=1`` is passed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..context import AppContext
from ..models import AidRequest, Requester, Volunteer

__all__ = [
    "AGENT_ROLES",
    "ToolNote",
    "call_phrase",
    "clip",
    "describe_tool",
    "display_name",
    "first_name",
    "scrub_ids",
    "when_phrase",
]

MAX_QUOTE = 90
"""How much of a message or a reply a summary quotes before trailing off."""

TIME_WORDS = re.compile(
    r"\b(mon|tues|wednes|thurs|fri|satur|sun)day\b|\b\d{1,2}\s?[ap]m\b|\b(morning|afternoon|evening|"
    r"tonight|tomorrow|today|noon|midday|overnight)\b",
    re.IGNORECASE,
)
"""A summary that already says when something is does not need the window bolted on."""

SKILL_WORDS: dict[str, str] = {
    "drive": "drives",
    "shop": "shops",
    "cook": "cooks",
    "errands": "runs errands",
    "lift": "can lift",
    "yard": "does yard work",
    "tech": "good with tech",
    "handy": "handy",
    "paperwork": "does paperwork",
    "companionship": "good company",
    "childcare-cleared": "cleared for childcare",
}
"""How to say a roster skill out loud."""

HONORIFICS = frozenset({"mr", "mrs", "ms", "miss", "dr", "mx", "prof", "rev", "sr", "sra"})

SOURCE_WORDS: dict[str, str] = {
    "sms": "text",
    "email": "email",
    "form": "form",
    "voicemail": "voicemail",
    "paper": "paper slip",
    "api": "message",
}

CALL_PHRASES: dict[str, str] = {
    "lookup_requester_history": "checking who this neighbour is",
    "find_similar_open_requests": "checking for a request already open",
    "find_candidates": "ranking the roster",
    "volunteer_load": "checking a volunteer's week",
    "recall_memory": "checking what we remember",
    "remember": "writing something down",
    "send_message": "sending a message",
    "schedule_message": "queueing a message",
    "read_replies": "checking for replies",
    "interpret_reply": "reading a reply",
    "assign_volunteer": "confirming a volunteer",
    "record_attempt": "recording an answer",
    "update_request": "updating the request",
    "close_request": "closing the request",
    "query_requests": "reading the day's requests",
    "query_log": "reading the log",
    # The structured output each agent finishes its turn with.
    "IntakeResult": "writing up what it understood",
    "MatchPlan": "settling on a shortlist",
    "OutreachStep": "wrapping up this pass",
    "StewardResult": "wrapping up",
    "VolunteerReply": "reading what that reply means",
    "BriefResult": "writing the brief",
}

AGENT_ROLES: dict[str, str] = {
    "intake": "Intake",
    "matcher": "Matcher",
    "outreach": "Outreach",
    "steward": "Steward",
    "brief": "Brief",
    "interpret_reply": "Reply reader",
    "volunteer_sim": "Volunteer",
    "graph": "Porchlight",
    "channel": "Inbox",
}


@dataclass(frozen=True)
class ToolNote:
    """One quiet-log line, and whether the coordinator should see it.

    Attributes:
        summary: The sentence that goes on the porch.
        visible: ``False`` for bookkeeping — kept in the trace and behind ``?all=1``.
    """

    summary: str
    visible: bool = True


# --------------------------------------------------------------------------------------
# Small text helpers (shared with the mock scenario planner)
# --------------------------------------------------------------------------------------


def first_name(name: str | None) -> str:
    """The part of a name you would actually say out loud, skipping any honorific."""
    parts = [part for part in (name or "").split() if part]
    for part in parts:
        if part.rstrip(".").lower() not in HONORIFICS:
            return part
    return parts[-1] if parts else "them"


def display_name(name: str | None, fallback: str = "a new neighbour") -> str:
    """A name to print — a phone number or an email address is not one."""
    text = (name or "").strip()
    if not text or "@" in text or any(char.isdigit() for char in text):
        return fallback
    return text


ENTITY_ID = re.compile(r"\b(?:req|vol|rqr|dec|msg|log|sm)_[A-Za-z0-9_]+")
"""A Porchlight identifier — ``req_9f3a1c04bd``, ``vol_maria``. Never porch material."""


def scrub_ids(text: str) -> str:
    """Replace any internal identifier with a word, so no row can leak one.

    Every porch line funnels through :func:`clip`, so scrubbing here covers free text an agent
    wrote (a close-out note, a remembered fact) as well as anything a future summarizer quotes.
    """
    return ENTITY_ID.sub("the earlier one", text)


def clip(text: str | None, limit: int = MAX_QUOTE) -> str:
    """One line of quoted text, trimmed at a word boundary and stripped of internal ids."""
    flat = scrub_ids(" ".join((text or "").split()))
    if len(flat) <= limit:
        return flat
    return flat[:limit].rsplit(" ", 1)[0] + "…"


def first_sentence(text: str | None, limit: int = MAX_QUOTE) -> str:
    """The opening sentence of a message body, for quoting in a summary."""
    flat = " ".join((text or "").split())
    for stop in (". ", "! ", "? "):
        head, sep, _ = flat.partition(stop)
        if sep and len(head) >= 12:
            flat = head + sep.strip()
            break
    return clip(flat, limit)


def local_time(moment: datetime, timezone: str) -> datetime:
    """The group's local time for a UTC moment."""
    from ..matching import zone_info

    return moment.astimezone(zone_info(timezone))


def clock_phrase(moment: datetime) -> str:
    """``Thursday at 9am`` — the way a neighbour writes a time."""
    return moment.strftime("%A at %-I%p").replace("AM", "am").replace("PM", "pm")


def short_when(moment: datetime | None, timezone: str) -> str:
    """``Thursday 9am`` — the compact form used inside a log line."""
    if moment is None:
        return ""
    local = local_time(moment, timezone)
    return local.strftime("%A %-I%p").replace("AM", "am").replace("PM", "pm")


def when_phrase(request: AidRequest, timezone: str) -> str:
    """A short, human way to say when a job is, in the group's local time."""
    if request.window_start is None:
        return "sometime this week"
    start = local_time(request.window_start, timezone)
    if not request.flexible:
        return f"on {clock_phrase(start)}"
    if request.window_end is not None:
        return f"any time before {local_time(request.window_end, timezone).strftime('%A')}"
    return "sometime this week"


def call_phrase(tool_name: str, agent: str | None = None) -> str:
    """The one-liner the Trace drawer shows while a tool is still running."""
    role = AGENT_ROLES.get(agent or "", (agent or "Porchlight").replace("_", " ").capitalize())
    what = CALL_PHRASES.get(tool_name)
    if what is None:
        what = f"finishing up ({tool_name})" if tool_name[:1].isupper() else tool_name.replace("_", " ")
    return f"{role} is {what}…"


# --------------------------------------------------------------------------------------
# Reading tool results
# --------------------------------------------------------------------------------------


def unwrap(result: Any) -> Any:
    """Pull the payload out of a Strands ``ToolResult`` (or pass a plain value through)."""
    if not isinstance(result, dict) or "content" not in result:
        return result
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        if "json" in block:
            return block["json"]
        text = block.get("text")
        if isinstance(text, str):
            try:
                return json.loads(text)
            except ValueError:
                return text
    return None


def _rows(payload: Any) -> list[dict[str, Any]]:
    """The list of dicts in a tool result, whatever wrapper it arrived in."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _request_of(ctx: AppContext, inputs: dict[str, Any]) -> AidRequest | None:
    request_id = inputs.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return None
    try:
        return ctx.store.get_request(request_id)
    except Exception:  # pragma: no cover - a store hiccup must not break the log
        return None


def _volunteer(ctx: AppContext, volunteer_id: Any) -> Volunteer | None:
    if not isinstance(volunteer_id, str) or not volunteer_id:
        return None
    try:
        return ctx.store.get_volunteer(volunteer_id)
    except Exception:  # pragma: no cover - defensive
        return None


def _requester(ctx: AppContext, requester_id: Any) -> Requester | None:
    if not isinstance(requester_id, str) or not requester_id:
        return None
    try:
        return ctx.store.get_requester(requester_id)
    except Exception:  # pragma: no cover - defensive
        return None


def _volunteer_name(ctx: AppContext, volunteer_id: Any) -> str:
    """The volunteer's name — never their id, which means nothing to a coordinator."""
    volunteer = _volunteer(ctx, volunteer_id)
    return volunteer.name if volunteer else "Someone"


def _person_name(ctx: AppContext, requester_id: Any) -> str:
    """The neighbour's first name, or something sayable when we do not have them on file."""
    requester = _requester(ctx, requester_id)
    return first_name(requester.name) if requester else "the neighbour"


def _skill_word(volunteer: Volunteer, request: AidRequest | None) -> str:
    """The one thing about this volunteer that matters for this request."""
    from ..models import CATEGORY_SKILLS

    wanted = CATEGORY_SKILLS.get(request.category, ()) if request else ()
    for skill in volunteer.skills:
        lowered = skill.lower()
        if lowered.startswith("translate"):
            if "translate" in wanted:
                return "interprets"
            continue
        if lowered in wanted:
            return SKILL_WORDS.get(lowered, lowered)
    for skill in volunteer.skills:
        word = SKILL_WORDS.get(skill.lower())
        if word:
            return word
    return ""


def _fit_phrase(ctx: AppContext, volunteer: Volunteer, request: AidRequest | None) -> str:
    """``Riverside, drives, free this week`` — why this person is on the shortlist."""
    from ._common import load_for

    zone = next((z for z in volunteer.zones if request and z == request.location_zone), None)
    parts = [zone or (volunteer.zones[0] if volunteer.zones else "")]
    parts.append(_skill_word(volunteer, request))
    try:
        load = load_for(ctx, volunteer.id)
    except Exception:  # pragma: no cover - defensive
        load = 0
    jobs = "job" if load == 1 else "jobs"
    parts.append("free this week" if load == 0 else f"{load} {jobs} already this week")
    return ", ".join(part for part in parts if part)


def _job(ctx: AppContext, inputs: dict[str, Any], request: AidRequest | None = None) -> str:
    """What the request is, as the summary reads.

    Left capitalised as written — half these summaries start with a proper noun ("Spanish
    interpreting at the clinic"), so every sentence here puts the job after a colon or a dash
    rather than lower-casing someone's language or street.
    """
    request = request or _request_of(ctx, inputs)
    if request is None:
        return "this one"
    return clip(request.summary or request.raw_text or str(request.category), 110)


def _names(rows: Sequence[dict[str, Any]], key: str = "name") -> list[str]:
    return [str(row[key]) for row in rows if row.get(key)]


def _join(names: Sequence[str]) -> str:
    """``a``, ``a and b``, ``a, b and c``."""
    items = [name for name in names if name]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# --------------------------------------------------------------------------------------
# Per-tool summaries
# --------------------------------------------------------------------------------------


def _lookup_requester_history(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    needle = str(inputs.get("contact_or_name") or "someone")
    data = payload if isinstance(payload, dict) else {}
    requester = data.get("requester")
    recent = _rows(data.get("recent_requests"))
    if not isinstance(requester, dict):
        return ToolNote(f"Checked the records for {needle} — nobody by that name yet.", visible=False)
    name = str(requester.get("name") or needle)
    if not recent:
        return ToolNote(f"Looked up {name} — first time they have asked us for anything.", visible=False)
    tail = ""
    last = recent[0].get("created_at")
    if isinstance(last, str):
        try:
            tail = f", the last one in {datetime.fromisoformat(last):%B}"
        except ValueError:  # pragma: no cover - defensive
            tail = ""
    count = f"{len(recent)} past request" + ("s" if len(recent) != 1 else "")
    return ToolNote(f"Looked up {name} — {count}{tail}.", visible=False)


def _find_similar_open_requests(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    rows = _rows(payload)
    if not rows:
        return ToolNote("Checked whether this neighbour already has something open — nothing.", False)
    other = str(rows[0].get("summary") or "an earlier request")
    return ToolNote(f"Checked for an open request from the same neighbour — found “{other}”.", False)


def _find_candidates(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    rows = _rows(payload)
    request = _request_of(ctx, inputs)
    what = str(request.category).replace("_", " ") if request else "this"
    if not rows:
        return ToolNote(f"Went through the roster for the {what} — nobody free.", visible=False)
    return ToolNote(f"Went through the roster for the {what}: {_join(_names(rows))}.", visible=False)


def _volunteer_load(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    name = _volunteer_name(ctx, inputs.get("volunteer_id"))
    data = payload if isinstance(payload, dict) else {}
    this_week = data.get("this_week")
    cap = data.get("max_per_week")
    if this_week is None:
        return ToolNote(f"Checked {name}'s week.", visible=False)
    return ToolNote(f"Checked {name}'s week — {this_week} of {cap} jobs so far.", visible=False)


def _recall_memory(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    about = _volunteer(ctx, inputs.get("about")) or _requester(ctx, inputs.get("about"))
    who = f" about {about.name}" if about else ""
    rows = _rows(payload)
    if not rows:
        return ToolNote(f"Checked what we remember{who} — nothing on file.", visible=False)
    return ToolNote(f"Checked what we remember{who} — {len(rows)} note(s).", visible=False)


def _read_replies(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    rows = _rows(payload)
    if not rows:
        return ToolNote("Checked for replies — nothing back yet.", visible=False)
    return ToolNote(f"Checked for replies — {len(rows)} waiting.", visible=False)


def _interpret_reply(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    name = str(inputs.get("volunteer_name") or "")
    whose = f"{first_name(name)}'s" if name else "the"
    text = clip(str(inputs.get("reply_text") or ""))
    return ToolNote(f"Read {whose} reply: “{text}”", visible=False)


def _send_message(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    to = str(inputs.get("to") or "")
    body = str(inputs.get("body") or "")
    request = _request_of(ctx, inputs)
    timezone = ctx.settings.timezone
    if to == "volunteer":
        who = first_name(_volunteer_name(ctx, inputs.get("recipient_id")))
        job = _job(ctx, inputs, request)
        return ToolNote(f"Asked {who}: {job}{_window_tail(request, job, timezone)}.")
    if to == "requester":
        who = _person_name(ctx, inputs.get("recipient_id"))
        volunteer = _volunteer(ctx, request.assigned_volunteer_id) if request else None
        if volunteer is not None:
            job = _job(ctx, inputs, request)
            tail = _window_tail(request, job, timezone)
            return ToolNote(f"Told {who} that {first_name(volunteer.name)} is coming{tail} — {job}.")
        return ToolNote(f"Wrote back to {who}: “{first_sentence(body)}”")
    return ToolNote(f"Left you a note: “{first_sentence(body)}”")


def _window_tail(request: AidRequest | None, job: str, timezone: str) -> str:
    """`` on Thursday 9am`` — unless the summary has already said when."""
    if request is None or request.window_start is None or TIME_WORDS.search(job):
        return ""
    return f" {short_when(request.window_start, timezone)}"


def _schedule_message(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    to = str(inputs.get("to") or "")
    body = str(inputs.get("body") or "")
    when_iso = str(inputs.get("send_at_iso") or "")
    timezone = ctx.settings.timezone
    who = (
        first_name(_volunteer_name(ctx, inputs.get("recipient_id")))
        if to == "volunteer"
        else _person_name(ctx, inputs.get("recipient_id"))
    )
    try:
        moment = datetime.fromisoformat(when_iso)
    except ValueError:  # pragma: no cover - defensive
        return ToolNote(f"Queued a message to {who}.")
    local = local_time(moment, timezone)
    when = short_when(moment, timezone)
    wake = int(ctx.settings.quiet_hours[1])
    if local.hour == wake and local.minute == 0:
        return ToolNote(f"Held the message to {who} until {when} — quiet hours here.")
    if body.lower().startswith("reminder"):
        return ToolNote(f"Set a reminder for {who} on {when}.")
    return ToolNote(f"Queued a note to {who} for {when}.")


def _assign_volunteer(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    name = _volunteer_name(ctx, inputs.get("volunteer_id"))
    return ToolNote(f"{name} said yes — confirmed for: {_job(ctx, inputs)}")


def _record_attempt(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    who = first_name(_volunteer_name(ctx, inputs.get("volunteer_id")))
    outcome = str(inputs.get("outcome") or "")
    note = clip(str(inputs.get("note") or ""))
    quoted = f" — “{note}”" if note else ""
    request = _request_of(ctx, inputs)
    more_to_ask = request is not None and len(request.attempts) < ctx.settings.max_candidates
    if outcome == "declined":
        tail = " Trying the next person." if more_to_ask else ""
        return ToolNote(f"{who} can't{quoted}.{tail}")
    if outcome == "counter":
        return ToolNote(f"{who} offered a different time{quoted}.")
    if outcome == "concern":
        return ToolNote(f"{who} flagged something{quoted}.")
    if outcome == "timeout":
        return ToolNote(f"{who} hasn't answered — moving on.")
    if outcome == "accepted":
        # ``assign_volunteer`` tells this one better, and always runs alongside it.
        return ToolNote(f"{who} said yes{quoted}.", visible=False)
    return ToolNote(f"Waiting to hear back from {who}.", visible=False)


FIELD_WORDS: dict[str, str] = {
    "window_start": "the time",
    "window_end": "the time",
    "category": "what kind of help it is",
    "constraints": "the constraints",
    "summary": "the summary",
    "location_zone": "the neighbourhood",
    "urgency": "how urgent it is",
    "assigned_volunteer_id": "who is doing it",
}


def _update_request(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    fields = inputs.get("fields") if isinstance(inputs.get("fields"), dict) else inputs
    names = [key for key in fields if key not in ("request_id", "updated_at", "version", "id")]
    job = _job(ctx, inputs)
    interesting = [FIELD_WORDS[name] for name in names if name in FIELD_WORDS]
    if not interesting:
        status = str(fields.get("status") or "")
        return ToolNote(
            f"Moved it to “{status.replace('_', ' ')}”: {job}" if status else f"Tidied up: {job}",
            visible=False,
        )
    unique = list(dict.fromkeys(interesting))
    return ToolNote(f"Changed {_join(unique)} on: {job}")


def _close_request(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    outcome = str(inputs.get("outcome") or "")
    note = clip(str(inputs.get("note") or ""))
    job = _job(ctx, inputs)
    if outcome == "completed":
        return ToolNote(f"Closed out, done: {job}")
    if outcome == "declined":
        return ToolNote(f"Turned down: {job}{f' — {note}' if note else ''}")
    return ToolNote(f"Closed without asking anyone: {job}{f' — {note}' if note else ''}")


def _remember(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    content = clip(str(inputs.get("content") or ""), 140)
    if not content:
        return ToolNote("Tried to write down an empty note.", visible=False)
    return ToolNote(f"Remembered: {content}")


def _query_requests(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    return ToolNote(f"Read back {len(_rows(payload))} request(s).", visible=False)


def _query_log(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    return ToolNote(f"Read back {len(_rows(payload))} line(s) of the log.", visible=False)


# --- structured outputs (the "tool" an agent finishes its turn with) --------------------


def _intake_result(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    who = display_name(str(inputs.get("requester_name") or ""), "a new neighbour")
    source = SOURCE_WORDS.get(str(inputs.get("source") or ""), "message")
    summary = clip(str(inputs.get("summary") or ""), 110) or "something they need a hand with"
    whose = f"{who}'s {source}" if who[0].isupper() else f"a {source} from {who}"
    if inputs.get("is_request") is False:
        return ToolNote(f"Read {whose} — nothing to arrange: {summary}.")
    if inputs.get("duplicate_of"):
        return ToolNote(f"Read {whose} — it chases the same job they asked about already.")
    flags = [str(flag) for flag in (inputs.get("safety_flags") or []) if flag]
    if flags:
        return ToolNote(f"Read {whose}: {summary} — flagged {_join(flags[:2])}.")
    if inputs.get("money_involved"):
        return ToolNote(f"Read {whose}: {summary} — the group's money is involved.")
    return ToolNote(f"Read {whose}: {summary}.")


def _match_plan(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    rows = _rows(inputs.get("candidates"))
    if not rows:
        return ToolNote("Nobody on the roster fits this one.")
    request = _request_of(ctx, inputs)
    lead = _volunteer(ctx, rows[0].get("volunteer_id"))
    name = lead.name if lead else _volunteer_name(ctx, rows[0].get("volunteer_id"))
    why = _fit_phrase(ctx, lead, request) if lead else clip(str(rows[0].get("rationale") or ""), 70)
    bench = _join([_volunteer_name(ctx, row.get("volunteer_id")) for row in rows[1:]])
    tail = f", then {bench}" if bench else " — and nobody else free"
    return ToolNote(f"Shortlisted {name}{f' ({why})' if why else ''}{tail}.")


def _outreach_step(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    note = clip(str(inputs.get("note") or "")) or str(inputs.get("action") or "outreach")
    return ToolNote(f"Outreach pass done: {note}", visible=False)


def _steward_result(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    note = clip(str(inputs.get("summary") or "")) or "nothing to do"
    return ToolNote(f"Wrapped up: {note}", visible=False)


def _volunteer_reply(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    intent = str(inputs.get("intent") or "unclear")
    return ToolNote(f"Read that reply as “{intent}”.", visible=False)


def _brief_result(ctx: AppContext, inputs: dict, payload: Any) -> ToolNote:
    return ToolNote("Wrote the evening brief.", visible=False)


Summarizer = Callable[[AppContext, dict, Any], ToolNote]

SUMMARIZERS: dict[str, Summarizer] = {
    "lookup_requester_history": _lookup_requester_history,
    "find_similar_open_requests": _find_similar_open_requests,
    "find_candidates": _find_candidates,
    "volunteer_load": _volunteer_load,
    "recall_memory": _recall_memory,
    "read_replies": _read_replies,
    "interpret_reply": _interpret_reply,
    "send_message": _send_message,
    "schedule_message": _schedule_message,
    "assign_volunteer": _assign_volunteer,
    "record_attempt": _record_attempt,
    "update_request": _update_request,
    "close_request": _close_request,
    "remember": _remember,
    "query_requests": _query_requests,
    "query_log": _query_log,
    "IntakeResult": _intake_result,
    "MatchPlan": _match_plan,
    "OutreachStep": _outreach_step,
    "StewardResult": _steward_result,
    "VolunteerReply": _volunteer_reply,
    "BriefResult": _brief_result,
}


def describe_tool(
    ctx: AppContext,
    name: str,
    inputs: dict[str, Any] | None = None,
    result: Any = None,
    *,
    cancelled: bool = False,
    cancel_message: str | None = None,
    card: dict[str, Any] | None = None,
) -> ToolNote:
    """Describe one tool call the way a colleague would write it down.

    Args:
        ctx: The app context, for looking up the people and the request by id.
        name: The tool's name — including the structured-output models agents finish with.
        inputs: The tool's arguments.
        result: The tool's result, either raw or wrapped in a Strands ``ToolResult``.
        cancelled: True when policy stopped the call before it ran.
        cancel_message: Why it was stopped.
        card: The decision card policy raised instead, when there was one.

    Returns:
        A :class:`ToolNote`. Unknown tools get a readable fallback and are treated as
        bookkeeping, so a new tool can never put a raw name on the porch.
    """
    args = dict(inputs or {})
    if cancelled:
        return _cancelled_note(ctx, name, args, cancel_message, card)
    summarizer = SUMMARIZERS.get(name)
    if summarizer is None:
        pretty = name if name[:1].isupper() else name.replace("_", " ")
        return ToolNote(f"Ran {pretty}.", visible=False)
    try:
        return summarizer(ctx, args, unwrap(result))
    except Exception:  # pragma: no cover - a wording bug must never break a run
        return ToolNote(f"Ran {name.replace('_', ' ')}.", visible=False)


STOPPED_VERBS: dict[str, str] = {
    "send_message": "sending that message",
    "schedule_message": "queueing that message",
    "assign_volunteer": "confirming anyone",
    "close_request": "closing this out",
    "record_attempt": "writing that down",
    "remember": "writing that down",
}


POLICY_TAG = re.compile(r"^\[[a-z0-9-]+\]\s*")
"""The ``[porchlight-policy]`` stamp the intervention registry puts in front of its feedback."""


def _plain_reason(cancel_message: str | None) -> tuple[str, bool]:
    """Strip the machinery off a policy verdict and say whether it was a redirect.

    The SDK hands the model a verdict string — ``DENIED: ...`` for a refusal, ``GUIDANCE: ...``
    for a nudge — stamped with the policy name. None of that belongs on the porch, and guidance
    text is written *at the model* ("Call schedule_message with..."), so only its first sentence
    is worth keeping. Returns ``(reason, redirected)``.
    """
    raw = (cancel_message or "").strip()
    redirected = raw.startswith("GUIDANCE:")
    for prefix in ("DENIED:", "GUIDANCE:", "BLOCKED:"):
        raw = raw.removeprefix(prefix).strip()
    raw = POLICY_TAG.sub("", raw).strip()
    if redirected:
        raw = raw.split(". ")[0].rstrip(".")
        raw = raw[:1].lower() + raw[1:] if raw else raw
    return clip(raw, 120), redirected


def _cancelled_note(
    ctx: AppContext,
    name: str,
    inputs: dict[str, Any],
    cancel_message: str | None,
    card: dict[str, Any] | None,
) -> ToolNote:
    """The line for a call policy stopped: what was about to happen, and why it did not."""
    what = STOPPED_VERBS.get(name, f"calling {name.replace('_', ' ')}")
    if card:
        title = str(card.get("title") or "a decision")
        return ToolNote(f"Paused before {what} — {title}. Card raised.")
    reason, redirected = _plain_reason(cancel_message)
    if redirected:
        # A nudge, not a stop: the agent immediately does the right thing instead, and *that*
        # row ("Held the message to Walter until Saturday 8am") tells the story. This one stays
        # behind ``?all=1`` as the audit trail.
        line = f"Held off {what} — {reason}." if reason else f"Held off {what}."
        return ToolNote(line, visible=False)
    if reason:
        return ToolNote(f"Stopped before {what} — {reason}")
    return ToolNote(f"Stopped before {what}.")

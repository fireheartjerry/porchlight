"""Record-keeping tools: assignments, attempts, request updates, memory, and the quiet log."""

from __future__ import annotations

from typing import Any, get_args

from strands import tool
from strands.types.tools import ToolContext

from ..context import AppContext, get_ctx
from ..memory import add_memory, search_memory
from ..models import (
    Attempt,
    AttemptOutcome,
    LogKind,
    RequestStatus,
    jsonable,
)
from ._common import agent_name, error, parse_iso, record, trace

VALID_OUTCOMES: frozenset[str] = frozenset(get_args(AttemptOutcome))
CLOSING_STATUSES: frozenset[str] = frozenset({"completed", "cancelled", "declined"})
MEMORY_RECALL_LIMIT = 5
SUMMARY_CHARS = 100


# --------------------------------------------------------------------------------------
# Assignment and attempts
# --------------------------------------------------------------------------------------


def assign_volunteer_impl(
    ctx: AppContext, request_id: str, volunteer_id: str, *, agent: str | None = None
) -> dict[str, Any]:
    """Confirm a volunteer on a request (the plain-function form)."""
    request = ctx.store.get_request(request_id)
    if request is None:
        return error(f"unknown request {request_id}")
    volunteer = ctx.store.get_volunteer(volunteer_id)
    if volunteer is None:
        return error(f"unknown volunteer {volunteer_id}")

    now = ctx.clock.now()
    # Two atomic writes rather than one whole-row rewrite: another thread recording an attempt
    # or updating a different field at the same moment keeps its work.
    ctx.store.resolve_attempt(request_id, Attempt(volunteer_id=volunteer_id, sent_at=now, outcome="accepted"))
    updated = ctx.store.update_request_fields(
        request_id,
        assigned_volunteer_id=volunteer_id,
        status=RequestStatus.CONFIRMED,
        updated_at=now,
    )
    request = updated or request

    volunteer.stats.accepted += 1
    volunteer.stats.last_active = now
    ctx.store.put_volunteer(volunteer)

    record(
        ctx,
        LogKind.TOOL_CALL,
        f"{volunteer.name} is confirmed for {request.summary or request.category}",
        request_id=request_id,
        agent=agent,
        detail={"volunteer_id": volunteer_id, "status": str(request.status)},
    )
    return {"request_id": request_id, "volunteer_id": volunteer_id, "status": str(request.status)}


def record_attempt_impl(
    ctx: AppContext,
    request_id: str,
    volunteer_id: str,
    outcome: str,
    note: str | None = None,
    *,
    agent: str | None = None,
) -> dict[str, Any]:
    """Record the result of asking one volunteer (the plain-function form)."""
    if outcome not in VALID_OUTCOMES:
        return error(f"invalid outcome {outcome!r}; use one of {sorted(VALID_OUTCOMES)}")
    request = ctx.store.get_request(request_id)
    if request is None:
        return error(f"unknown request {request_id}")

    now = ctx.clock.now()
    settled = ctx.store.resolve_attempt(
        request_id,
        Attempt(
            volunteer_id=volunteer_id,
            sent_at=now,
            outcome=outcome,  # type: ignore[arg-type]
            note=note,
        ),
    )
    request = ctx.store.update_request_fields(request_id, updated_at=now) or settled or request

    volunteer = ctx.store.get_volunteer(volunteer_id)
    if volunteer is not None and outcome == "declined":
        volunteer.stats.declined += 1
        volunteer.stats.last_active = now
        ctx.store.put_volunteer(volunteer)

    who = volunteer.name if volunteer else volunteer_id
    record(
        ctx,
        LogKind.TOOL_CALL,
        f"{who} {outcome}" + (f" — {note[:SUMMARY_CHARS]}" if note else ""),
        request_id=request_id,
        agent=agent,
        detail={"volunteer_id": volunteer_id, "outcome": outcome, "note": note},
    )
    return {"request_id": request_id, "attempts": len(request.attempts), "outcome": outcome}


# --------------------------------------------------------------------------------------
# Request updates
# --------------------------------------------------------------------------------------


def update_request_impl(
    ctx: AppContext, request_id: str, fields: dict[str, Any], *, agent: str | None = None
) -> dict[str, Any]:
    """Validate and apply a partial update to a request (the plain-function form)."""
    request = ctx.store.get_request(request_id)
    if request is None:
        return error(f"unknown request {request_id}")
    if not fields:
        return jsonable(request)

    model_fields = type(request).model_fields
    unknown = [key for key in fields if key not in model_fields]
    if unknown:
        return error(f"unknown field(s) {sorted(unknown)}; valid fields are {sorted(model_fields)}")
    if "id" in fields and fields["id"] != request.id:
        return error("a request's id cannot be changed")
    # ``id`` and ``version`` are the store's to manage; a no-op restatement of either is dropped
    # rather than rejected, so a model echoing the whole record back still succeeds.
    writable = {key: value for key, value in fields.items() if key not in ("id", "version")}

    try:
        updated = ctx.store.update_request_fields(request_id, updated_at=ctx.clock.now(), **writable)
    except ValueError as exc:
        return error(f"invalid update: {exc}")
    if updated is None:
        return error(f"unknown request {request_id}")
    record(
        ctx,
        LogKind.TOOL_CALL,
        "Updated " + ", ".join(sorted(fields)) + f" on {updated.summary or updated.category}",
        request_id=request_id,
        agent=agent,
        detail={"fields": jsonable(fields)},
    )
    return jsonable(updated)


def close_request_impl(
    ctx: AppContext,
    request_id: str,
    outcome: str,
    note: str | None = None,
    *,
    agent: str | None = None,
) -> dict[str, Any]:
    """Close a request out (the plain-function form)."""
    if outcome not in CLOSING_STATUSES:
        return error(f"invalid outcome {outcome!r}; use completed, cancelled, or declined")
    request = ctx.store.get_request(request_id)
    if request is None:
        return error(f"unknown request {request_id}")

    now = ctx.clock.now()
    request = (
        ctx.store.update_request_fields(request_id, status=RequestStatus(outcome), updated_at=now) or request
    )

    if outcome == "completed" and request.assigned_volunteer_id:
        volunteer = ctx.store.get_volunteer(request.assigned_volunteer_id)
        if volunteer is not None:
            volunteer.stats.completed += 1
            volunteer.stats.last_active = now
            ctx.store.put_volunteer(volunteer)

    requester = ctx.store.get_requester(request.requester_id) if request.requester_id else None
    if requester is not None and outcome == "completed":
        requester.history_count += 1
        ctx.store.put_requester(requester)

    record(
        ctx,
        LogKind.TOOL_CALL,
        f"Closed as {outcome}: {note or request.summary or request.category}",
        request_id=request_id,
        agent=agent,
        detail={"outcome": outcome, "note": note},
    )
    return {"request_id": request_id, "status": str(request.status)}


# --------------------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------------------


def recall_memory_impl(
    ctx: AppContext,
    query: str,
    about: str | None = None,
    *,
    limit: int = MEMORY_RECALL_LIMIT,
    agent: str | None = None,
) -> list[dict[str, Any]]:
    """Search long-term memory (the plain-function form)."""
    if ctx.memory is None:
        trace(ctx, "tool_call", "long-term memory is not configured", agent=agent)
        return []
    entries = search_memory(ctx.memory, query, about=about, limit=limit)
    trace(
        ctx,
        "tool_call",
        f"recalled {len(entries)} note(s) for {query!r}",
        agent=agent,
        detail={"about": about, "count": len(entries)},
    )
    return entries


def remember_impl(
    ctx: AppContext,
    content: str,
    about_id: str | None = None,
    kind: str = "fact",
    *,
    agent: str | None = None,
) -> dict[str, Any]:
    """Write a durable note (the plain-function form).

    The note goes to long-term memory and, when ``about_id`` names someone on the roster, is
    also pinned to their record so the coordinator sees it in the UI.
    """
    text = (content or "").strip()
    if not text:
        return error("refusing to store an empty note")
    metadata = {"about_id": about_id, "kind": kind, "ts": ctx.clock.now().isoformat()}
    stored = add_memory(ctx.memory, text, metadata)
    pinned = False
    if about_id:
        volunteer = ctx.store.get_volunteer(about_id)
        if volunteer is not None:
            if text not in volunteer.notes:
                volunteer.notes.append(text)
                ctx.store.put_volunteer(volunteer)
            pinned = True
        else:
            requester = ctx.store.get_requester(about_id)
            if requester is not None:
                if text not in requester.notes:
                    requester.notes.append(text)
                    ctx.store.put_requester(requester)
                pinned = True
    note = "" if ctx.memory is not None else " (no long-term memory configured)"
    record(
        ctx,
        LogKind.MEMORY,
        f"Remembered: {text[:SUMMARY_CHARS]}{note}",
        agent=agent,
        detail={"about_id": about_id, "kind": kind, "stored": stored, "pinned": pinned},
    )
    return {"stored": stored or pinned, "content": text, "about_id": about_id}


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def query_requests_impl(
    ctx: AppContext,
    status: str | None = None,
    since_iso: str | None = None,
    *,
    agent: str | None = None,
) -> list[dict[str, Any]]:
    """List requests, newest first (the plain-function form)."""
    try:
        parsed_status = RequestStatus(status) if status else None
    except ValueError:
        return [error(f"invalid status {status!r}; valid statuses are {[s.value for s in RequestStatus]}")]
    requests = ctx.store.list_requests(parsed_status)
    since = parse_iso(since_iso)
    if since is not None:
        requests = [r for r in requests if r.created_at >= since]
    trace(ctx, "tool_call", f"read {len(requests)} request(s)", agent=agent)
    return [jsonable(r) for r in requests]


def query_log_impl(
    ctx: AppContext,
    request_id: str | None = None,
    since_iso: str | None = None,
    limit: int = 100,
    *,
    agent: str | None = None,
) -> list[dict[str, Any]]:
    """Read the quiet log, newest first (the plain-function form)."""
    events = ctx.store.list_log(request_id=request_id, limit=limit, since=parse_iso(since_iso))
    trace(ctx, "tool_call", f"read {len(events)} log event(s)", request_id=request_id, agent=agent)
    return [jsonable(e) for e in events]


# --------------------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------------------


@tool(context=True)
def assign_volunteer(request_id: str, volunteer_id: str, tool_context: ToolContext) -> dict:
    """Assign a volunteer to a request and mark it confirmed.

    Call this only after the volunteer has actually said yes.

    Args:
        request_id: The aid request.
        volunteer_id: The volunteer who accepted.

    Returns:
        ``{"request_id": str, "volunteer_id": str, "status": str}``.
    """
    ctx = get_ctx(tool_context)
    return assign_volunteer_impl(
        ctx, request_id, volunteer_id, agent=agent_name(tool_context.invocation_state.get("agent"))
    )


@tool(context=True)
def record_attempt(
    request_id: str, volunteer_id: str, outcome: str, tool_context: ToolContext, note: str | None = None
) -> dict:
    """Record the result of asking one volunteer, so nobody is asked twice.

    Args:
        request_id: The aid request.
        volunteer_id: The volunteer who was asked.
        outcome: ``pending``, ``accepted``, ``declined``, ``counter``, ``concern``, or ``timeout``.
        note: Optional short note, e.g. the counter-offer time or what worried them.

    Returns:
        ``{"request_id": str, "attempts": int, "outcome": str}``.
    """
    ctx = get_ctx(tool_context)
    return record_attempt_impl(
        ctx,
        request_id,
        volunteer_id,
        outcome,
        note,
        agent=agent_name(tool_context.invocation_state.get("agent")),
    )


@tool(context=True)
def update_request(request_id: str, tool_context: ToolContext, **fields: Any) -> dict:
    """Update fields on an aid request (status, window, category, constraints, ...).

    Every value is validated against the request model, so an invalid status or timestamp comes
    back as an error instead of corrupting the record.

    Args:
        request_id: The aid request to update.
        fields: An object mapping ``AidRequest`` field names to new values, e.g.
            ``{"status": "matching", "window_start": "2026-09-09T15:00:00Z"}``.

    Returns:
        The updated request as a dict, or ``{"error": ...}`` when a field is invalid.
    """
    ctx = get_ctx(tool_context)
    payload = fields
    if len(fields) == 1 and isinstance(fields.get("fields"), dict):
        # The generated tool schema nests the keyword arguments under "fields".
        payload = fields["fields"]
    return update_request_impl(
        ctx, request_id, dict(payload), agent=agent_name(tool_context.invocation_state.get("agent"))
    )


@tool(context=True)
def close_request(request_id: str, outcome: str, tool_context: ToolContext, note: str | None = None) -> dict:
    """Close out a request once it is finished, declined, or cancelled.

    Args:
        request_id: The aid request to close.
        outcome: ``completed``, ``cancelled``, or ``declined``.
        note: Optional one-line summary for the quiet log.

    Returns:
        ``{"request_id": str, "status": str}``.
    """
    ctx = get_ctx(tool_context)
    return close_request_impl(
        ctx, request_id, outcome, note, agent=agent_name(tool_context.invocation_state.get("agent"))
    )


@tool(context=True)
def recall_memory(query: str, tool_context: ToolContext, about: str | None = None) -> list[dict]:
    """Recall durable facts the group has learned about a person or a kind of request.

    Args:
        query: What you want to remember, in plain language.
        about: Optional volunteer or requester id to scope the search to.

    Returns:
        A list of ``{"content": str, "metadata": {...}}`` entries, most relevant first; empty
        when nothing is known or long-term memory is not configured.
    """
    ctx = get_ctx(tool_context)
    return recall_memory_impl(ctx, query, about, agent=agent_name(tool_context.invocation_state.get("agent")))


@tool(context=True)
def remember(
    content: str, tool_context: ToolContext, about_id: str | None = None, kind: str = "fact"
) -> dict:
    """Write a durable note to long-term memory.

    Keep notes short, specific, and useful next month, e.g. "Mr. Okafor prefers Maria; hard of
    hearing, call rather than text." Do not store anything a neighbour told you in confidence.

    Args:
        content: The note to store.
        about_id: Volunteer or requester id the note is about.
        kind: ``fact``, ``preference``, or ``outcome``.

    Returns:
        ``{"stored": bool, "content": str, "about_id": str | None}``.
    """
    ctx = get_ctx(tool_context)
    return remember_impl(
        ctx, content, about_id, kind, agent=agent_name(tool_context.invocation_state.get("agent"))
    )


@tool(context=True)
def query_requests(
    tool_context: ToolContext, status: str | None = None, since_iso: str | None = None
) -> list[dict]:
    """List aid requests, newest first.

    Args:
        status: Optional status filter, e.g. ``awaiting_reply`` or ``completed``.
        since_iso: Only include requests created at or after this ISO-8601 timestamp.

    Returns:
        A list of aid request dicts.
    """
    ctx = get_ctx(tool_context)
    return query_requests_impl(
        ctx, status, since_iso, agent=agent_name(tool_context.invocation_state.get("agent"))
    )


@tool(context=True)
def query_log(
    tool_context: ToolContext,
    request_id: str | None = None,
    since_iso: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Read the quiet log: everything Porchlight did, newest first.

    Args:
        request_id: Only show events for this request.
        since_iso: Only show events at or after this ISO-8601 timestamp.
        limit: Maximum number of events.

    Returns:
        A list of log event dicts.
    """
    ctx = get_ctx(tool_context)
    return query_log_impl(
        ctx, request_id, since_iso, limit, agent=agent_name(tool_context.invocation_state.get("agent"))
    )

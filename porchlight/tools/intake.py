"""Intake tools: what does Porchlight already know about the person asking?"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from strands import tool
from strands.types.tools import ToolContext

from ..context import AppContext, get_ctx
from ..models import OPEN_STATUSES, AidRequest, Category, Requester, jsonable
from ._common import agent_name, trace

HISTORY_LIMIT = 10
SIMILAR_LIMIT = 5
DEFAULT_SIMILAR_WINDOW_HOURS = 72
"""How far back a second message can still be reading as a chase of the first."""


def _find_requester(ctx: AppContext, needle: str) -> Requester | None:
    """Match a requester by contact, then by exact name, then by loose name/contact substring."""
    text = needle.strip()
    if not text:
        return None
    found = ctx.store.find_requester_by_contact(text)
    if found is not None:
        return found
    lowered = text.lower()
    everyone = ctx.store.list_requesters()
    for requester in everyone:
        if requester.name.lower() == lowered:
            return requester
    for requester in everyone:
        if lowered in requester.name.lower() or lowered in requester.contact.lower():
            return requester
    return None


def lookup_requester_history_impl(
    ctx: AppContext, contact_or_name: str, *, agent: str | None = None, limit: int = HISTORY_LIMIT
) -> dict[str, Any]:
    """Look up a requester and their recent requests (the plain-function form)."""
    requester = _find_requester(ctx, contact_or_name)
    if requester is None:
        trace(ctx, "tool_call", f"no history for {contact_or_name!r} — first-time requester", agent=agent)
        return {"requester": None, "recent_requests": []}
    recent = [r for r in ctx.store.list_requests(limit=200) if r.requester_id == requester.id][:limit]
    trace(
        ctx,
        "tool_call",
        f"{requester.name} has {len(recent)} request(s) on file",
        agent=agent,
        detail={"requester_id": requester.id},
    )
    return {"requester": jsonable(requester), "recent_requests": jsonable(recent)}


@tool(context=True)
def lookup_requester_history(contact_or_name: str, tool_context: ToolContext) -> dict:
    """Look up a requester and their recent requests.

    Use this during intake to tell whether someone is new to the group (which changes the
    vetting policy) and to recall what they have asked for before.

    Args:
        contact_or_name: The phone number, email, or name the message arrived from.

    Returns:
        ``{"requester": {...} | None, "recent_requests": [...]}``. ``requester`` is ``None``
        when this is a first-time requester.
    """
    ctx = get_ctx(tool_context)
    return lookup_requester_history_impl(
        ctx, contact_or_name, agent=agent_name(tool_context.invocation_state.get("agent"))
    )


def _similar(
    request: AidRequest,
    *,
    requester_id: str,
    category: Category | None,
    earliest: datetime,
    exclude_id: str | None,
) -> bool:
    """True when ``request`` is an open request from the same person, recent, same category."""
    if request.id == exclude_id or request.requester_id != requester_id:
        return False
    if request.status not in OPEN_STATUSES or not request.is_request:
        return False
    if category is not None and request.category != category:
        return False
    return request.created_at >= earliest


def find_similar_open_requests_impl(
    ctx: AppContext,
    requester_id: str,
    category: str | None = None,
    window_hours: int = DEFAULT_SIMILAR_WINDOW_HOURS,
    *,
    exclude_request_id: str | None = None,
    agent: str | None = None,
) -> list[dict[str, Any]]:
    """Find this requester's other open requests of the same kind (the plain-function form)."""
    try:
        wanted = Category(category) if category else None
    except ValueError:
        wanted = None
    hours = max(0, int(window_hours or 0))
    earliest = ctx.clock.now() - timedelta(hours=hours)
    matches = [
        request
        for request in ctx.store.list_requests(limit=200)
        if _similar(
            request,
            requester_id=requester_id,
            category=wanted,
            earliest=earliest,
            exclude_id=exclude_request_id,
        )
    ][:SIMILAR_LIMIT]
    trace(
        ctx,
        "tool_call",
        f"{len(matches)} open request(s) already on file for this neighbour"
        + (f" in the last {hours}h" if hours else ""),
        agent=agent,
        detail={"requester_id": requester_id, "category": category, "count": len(matches)},
    )
    return [
        {
            "request_id": request.id,
            "summary": request.summary,
            "category": str(request.category),
            "status": str(request.status),
            "created_at": request.created_at.isoformat(),
            "window_start": request.window_start.isoformat() if request.window_start else None,
            "assigned_volunteer_id": request.assigned_volunteer_id,
        }
        for request in matches
    ]


@tool(context=True)
def find_similar_open_requests(
    requester_id: str,
    tool_context: ToolContext,
    category: str | None = None,
    window_hours: int = DEFAULT_SIMILAR_WINDOW_HOURS,
) -> list[dict]:
    """Find open requests this neighbour has already sent, so a chase is not booked twice.

    People often follow up ("me again, just checking you got my message") before anyone has
    replied. Call this during intake whenever the requester is known, and set ``duplicate_of``
    on your result when one of these is plainly the same job.

    Args:
        requester_id: The requester's id, from ``lookup_requester_history``.
        category: Only look at requests of this category, e.g. ``ride``.
        window_hours: How far back to look; the default is three days.

    Returns:
        A list of ``{"request_id", "summary", "category", "status", "created_at",
        "window_start", "assigned_volunteer_id"}``, newest first; empty when nothing matches.
    """
    ctx = get_ctx(tool_context)
    state = tool_context.invocation_state
    return find_similar_open_requests_impl(
        ctx,
        requester_id,
        category,
        window_hours,
        exclude_request_id=state.get("request_id"),
        agent=agent_name(state.get("agent")),
    )

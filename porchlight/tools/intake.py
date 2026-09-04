"""Intake tools: what does Porchlight already know about the person asking?"""

from __future__ import annotations

from typing import Any

from strands import tool
from strands.types.tools import ToolContext

from ..context import AppContext, get_ctx
from ..models import Requester, jsonable
from ._common import agent_name, trace

HISTORY_LIMIT = 10


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

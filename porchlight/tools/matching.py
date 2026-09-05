"""Matching tools: who could take this, and who has already done too much this week."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from strands import tool
from strands.types.tools import ToolContext

from ..context import AppContext, get_ctx
from ..matching import rank_candidates
from ..memory import search_memory
from ..models import AidRequest, Volunteer
from ._common import agent_name, error, load_for, trace
from .summaries import describe_tool

MEMORY_RECALL_LIMIT = 8


def _memory_query(request: AidRequest) -> str:
    """The question we ask long-term memory on the request's behalf."""
    parts = [request.summary or request.raw_text[:120], str(request.category)]
    if request.location_zone:
        parts.append(request.location_zone)
    return " ".join(p for p in parts if p).strip()


def _recalled_by_volunteer(
    ctx: AppContext, request: AidRequest, volunteers: Sequence[Volunteer]
) -> dict[str, list[str]]:
    """Group long-term memory hits by the volunteer they are about.

    A note counts for a volunteer when its ``about_id`` names them, or when their first name
    appears in the text ("Mr. Okafor asks for Maria by name").
    """
    hits = search_memory(ctx.memory, _memory_query(request), limit=MEMORY_RECALL_LIMIT)
    if not hits:
        return {}
    by_volunteer: dict[str, list[str]] = {}
    for hit in hits:
        content = hit.get("content", "")
        about = (hit.get("metadata") or {}).get("about_id")
        for volunteer in volunteers:
            first_name = volunteer.name.split()[0].lower()
            if about == volunteer.id or first_name in content.lower():
                by_volunteer.setdefault(volunteer.id, []).append(content)
    return by_volunteer


def rank_for_request(ctx: AppContext, request: AidRequest, limit: int = 5) -> list[Any]:
    """Score the roster against one request, long-term memory included.

    Everything that picks a volunteer goes through here — the ``find_candidates`` tool and the
    offline scenario planner both — so the person the matcher shortlists is the person outreach
    actually texts, rather than two rankings that disagree about what the group remembers.

    Args:
        ctx: The app context.
        request: The request to match.
        limit: How many candidates to return.

    Returns:
        A list of :class:`~porchlight.matching.Candidate`, best first.
    """
    volunteers = ctx.store.list_volunteers()
    return rank_candidates(
        volunteers,
        request,
        loads={v.id: load_for(ctx, v.id) for v in volunteers},
        now=ctx.clock.now(),
        timezone=ctx.settings.timezone,
        limit=limit,
        exclude=request.attempted_volunteer_ids(),
        recalled=_recalled_by_volunteer(ctx, request, volunteers),
    )


def find_candidates_impl(
    ctx: AppContext, request_id: str, limit: int = 5, *, agent: str | None = None
) -> list[dict[str, Any]]:
    """Score the roster against one request (the plain-function form)."""
    request = ctx.store.get_request(request_id)
    if request is None:
        trace(ctx, "tool_call", "Nothing to match — that request is gone.", agent=agent)
        return []
    candidates = rank_for_request(ctx, request, limit)
    rows = [c.to_dict() for c in candidates]
    trace(
        ctx,
        "tool_call",
        describe_tool(ctx, "find_candidates", {"request_id": request_id}, rows).summary,
        request_id=request_id,
        agent=agent,
        detail={"candidates": rows},
    )
    return rows


def volunteer_load_impl(ctx: AppContext, volunteer_id: str, *, agent: str | None = None) -> dict[str, Any]:
    """Report one volunteer's recent load (the plain-function form)."""
    volunteer = ctx.store.get_volunteer(volunteer_id)
    if volunteer is None:
        return error(f"unknown volunteer {volunteer_id}")
    this_week = load_for(ctx, volunteer_id)
    last_active = volunteer.stats.last_active
    payload = {
        "this_week": this_week,
        "max_per_week": volunteer.max_per_week,
        "last_active": last_active.isoformat() if last_active else None,
    }
    trace(
        ctx,
        "tool_call",
        describe_tool(ctx, "volunteer_load", {"volunteer_id": volunteer_id}, payload).summary,
        agent=agent,
        detail={"volunteer_id": volunteer_id},
    )
    return payload


@tool(context=True)
def find_candidates(request_id: str, tool_context: ToolContext, limit: int = 5) -> list[dict]:
    """Find and rank the volunteers who could take a request.

    Scores each eligible volunteer from 0 to 1 on six things: skill fit for the category, zone
    proximity, overlap with their weekly availability, how much they have already been asked
    this week (fairness), their follow-through record, and anything the group remembers about
    them. Volunteers already asked about this request are excluded, and in-home categories
    (childcare, companionship, tech help, repairs, paperwork) only return vetted people.

    Args:
        request_id: The aid request to match.
        limit: Maximum number of candidates to return.

    Returns:
        A list of ``{volunteer_id, name, score, reasons, load_this_week, zones, skills,
        memory_notes}`` dicts, best first. ``reasons`` is plain English you can quote to the
        coordinator.
    """
    ctx = get_ctx(tool_context)
    return find_candidates_impl(
        ctx, request_id, limit, agent=agent_name(tool_context.invocation_state.get("agent"))
    )


@tool(context=True)
def volunteer_load(volunteer_id: str, tool_context: ToolContext) -> dict:
    """Report how busy a volunteer has been over the last seven days.

    Use this to spread work fairly instead of always asking the same reliable people.

    Args:
        volunteer_id: The volunteer to check.

    Returns:
        ``{"this_week": int, "max_per_week": int, "last_active": iso | None}``.
    """
    ctx = get_ctx(tool_context)
    return volunteer_load_impl(
        ctx, volunteer_id, agent=agent_name(tool_context.invocation_state.get("agent"))
    )

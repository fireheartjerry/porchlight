"""The steward agent: confirm the requester, set reminders, and write down what was learned."""

from __future__ import annotations

from strands import Agent

from ..context import AppContext
from ..tools import close_request, remember, schedule_message, send_message, update_request
from .base import build_agent
from .outputs import StewardResult
from .prompts import steward_prompt

__all__ = ["make_steward_agent"]


def make_steward_agent(ctx: AppContext) -> Agent:
    """Build the steward agent (fast tier: the hard decisions are already made)."""
    return build_agent(
        ctx,
        name="steward",
        system_prompt=steward_prompt(ctx.settings),
        tools=[send_message, schedule_message, remember, close_request, update_request],
        output_model=StewardResult,
        tier="haiku",
        description="Confirms the requester, schedules follow-ups, and records what was learned.",
    )

"""The brief agent: a day of quiet log and open cards → one digest the coordinator reads."""

from __future__ import annotations

from strands import Agent

from ..context import AppContext
from ..tools import query_log, query_requests
from .base import build_agent
from .outputs import BriefResult
from .prompts import brief_prompt

__all__ = ["make_brief_agent"]


def make_brief_agent(ctx: AppContext) -> Agent:
    """Build the daily-brief agent (judgement tier: it has to notice patterns, not list rows)."""
    return build_agent(
        ctx,
        name="brief",
        system_prompt=brief_prompt(ctx.settings),
        tools=[query_requests, query_log],
        output_model=BriefResult,
        tier="sonnet",
        description="Writes the coordinator's daily digest.",
    )

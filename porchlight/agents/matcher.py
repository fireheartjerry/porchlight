"""The matcher agent: one request → a ranked, fairness-aware ``MatchPlan``."""

from __future__ import annotations

from strands import Agent

from ..context import AppContext
from ..models import MatchPlan
from ..tools import find_candidates, recall_memory, volunteer_load
from .base import build_agent
from .prompts import matcher_prompt

__all__ = ["make_matcher_agent"]


def make_matcher_agent(ctx: AppContext) -> Agent:
    """Build the matcher agent (judgement tier: fairness and memory beat raw scores)."""
    return build_agent(
        ctx,
        name="matcher",
        system_prompt=matcher_prompt(ctx.settings),
        tools=[find_candidates, volunteer_load, recall_memory],
        output_model=MatchPlan,
        tier="sonnet",
        description="Ranks volunteers for a request and reports honest confidence.",
    )

"""Porchlight's agents.

Five Strands agents, each with a structured output model, the group's values in its system
prompt, and the same audit/trace hooks and policy intervention attached. See
``docs/CONTRACTS.md`` §7 for the factory signatures.
"""

from __future__ import annotations

from .base import WINDOW_SIZE, build_agent, build_model
from .brief import make_brief_agent
from .intake import build_intake_task, make_intake_agent
from .matcher import make_matcher_agent
from .outputs import AGENT_OUTPUT_MODELS, BriefResult, IntakeResult, OutreachStep, StewardResult
from .outreach import (
    OUTREACH_AGENT_TOOLS,
    interpret_reply,
    make_interpret_reply_agent,
    make_outreach_agent,
)
from .prompts import (
    VALUES,
    brief_prompt,
    intake_prompt,
    interpret_reply_prompt,
    matcher_prompt,
    outreach_prompt,
    steward_prompt,
    volunteer_sim_prompt,
)
from .steward import make_steward_agent

__all__ = [
    "AGENT_OUTPUT_MODELS",
    "OUTREACH_AGENT_TOOLS",
    "VALUES",
    "WINDOW_SIZE",
    "BriefResult",
    "IntakeResult",
    "OutreachStep",
    "StewardResult",
    "brief_prompt",
    "build_agent",
    "build_intake_task",
    "build_model",
    "intake_prompt",
    "interpret_reply",
    "interpret_reply_prompt",
    "make_brief_agent",
    "make_intake_agent",
    "make_interpret_reply_agent",
    "make_matcher_agent",
    "make_outreach_agent",
    "make_steward_agent",
    "matcher_prompt",
    "outreach_prompt",
    "steward_prompt",
    "volunteer_sim_prompt",
]

"""The outreach agent, plus ``interpret_reply`` — a sub-agent exposed as a tool.

Reply parsing is the one place where a wrong reading costs a neighbour a missed ride, so it is
isolated in its own tiny agent with its own structured output. That keeps it testable on its
own and stops the outreach agent from talking itself into "they probably meant yes".
"""

from __future__ import annotations

import logging

from strands import Agent, tool
from strands.types.tools import ToolContext

from ..context import AppContext, get_ctx
from ..models import ReplyIntent, VolunteerReply, jsonable
from ..tools import assign_volunteer, read_replies, record_attempt, schedule_message, send_message
from .base import build_agent
from .outputs import OutreachStep
from .prompts import interpret_reply_prompt, outreach_prompt

logger = logging.getLogger(__name__)

__all__ = ["OUTREACH_AGENT_TOOLS", "interpret_reply", "make_interpret_reply_agent", "make_outreach_agent"]


def make_interpret_reply_agent(ctx: AppContext) -> Agent:
    """Build the one-shot reply classifier used by :func:`interpret_reply`."""
    return build_agent(
        ctx,
        name="interpret_reply",
        system_prompt=interpret_reply_prompt(ctx.settings),
        tools=[],
        output_model=VolunteerReply,
        tier="haiku",
        description="Classifies one volunteer reply as accept / decline / counter / concern.",
    )


@tool(context=True)
def interpret_reply(reply_text: str, tool_context: ToolContext, volunteer_name: str | None = None) -> dict:
    """Read one volunteer's reply and return what they actually meant.

    Always use this instead of judging a reply yourself. It returns a structured intent, so a
    hedged "I think so?" and a soft "sorry, not this week" are handled consistently, and a
    concern is never quietly downgraded into a decline.

    Args:
        reply_text: The volunteer's message, verbatim.
        volunteer_name: Their first name, when you know it, for context.

    Returns:
        ``{"intent": ..., "proposed_time": iso|None, "concern_text": str|None, "confidence": float}``.
    """
    ctx = get_ctx(tool_context)
    prompt = (
        f"Volunteer: {volunteer_name or 'a volunteer'}\n"
        f"Their reply, verbatim:\n\n{reply_text}\n\n"
        "Classify it."
    )
    try:
        agent = make_interpret_reply_agent(ctx)
        result = agent(prompt, invocation_state={"ctx": ctx})
    except Exception:
        logger.exception("interpret_reply sub-agent failed; treating the reply as unclear")
        return jsonable(VolunteerReply(intent=ReplyIntent.UNCLEAR, confidence=0.0))
    parsed = result.structured_output
    if not isinstance(parsed, VolunteerReply):
        parsed = VolunteerReply(intent=ReplyIntent.UNCLEAR, confidence=0.0)
    return jsonable(parsed)


OUTREACH_AGENT_TOOLS = [
    send_message,
    schedule_message,
    read_replies,
    interpret_reply,
    record_attempt,
    assign_volunteer,
]
"""``porchlight.tools.OUTREACH_TOOLS`` plus the reply-interpreting sub-agent."""


def make_outreach_agent(ctx: AppContext) -> Agent:
    """Build the outreach agent (judgement tier: it writes to real people)."""
    return build_agent(
        ctx,
        name="outreach",
        system_prompt=outreach_prompt(ctx.settings),
        tools=OUTREACH_AGENT_TOOLS,
        output_model=OutreachStep,
        tier="sonnet",
        description="Asks volunteers one at a time and reads their replies.",
    )

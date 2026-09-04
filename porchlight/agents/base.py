"""Shared wiring for every Porchlight agent.

One place decides what an agent gets: the model tier, the sliding conversation window, the
audit and trace hooks, and the policy intervention. Individual factories then only choose a
name, a prompt, a tool set, and an output model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from ..context import AppContext
from ..models_provider import make_model
from ..policy import AuditHook, PorchlightPolicy, TraceHook

WINDOW_SIZE = 40
"""Turns kept in an agent's context before the oldest are dropped."""

Tier = Literal["sonnet", "haiku"]


def build_model(ctx: AppContext, tier: Tier, *output_models: type[BaseModel]) -> Any:
    """Build the model for one agent tier.

    ``output_models`` are registered with :class:`~porchlight.testing.mock_model.MockModel` so
    an unscripted test run can still synthesize a valid structured payload for them. Real
    providers ignore the extra argument.
    """
    model = make_model(ctx.settings, tier)
    registry = getattr(model, "_output_models", None)
    if isinstance(registry, dict):
        registry.update({cls.__name__: cls for cls in output_models})
    return model


def build_agent(
    ctx: AppContext,
    *,
    name: str,
    system_prompt: str,
    tools: list[Any],
    output_model: type[BaseModel] | None,
    tier: Tier,
    description: str = "",
) -> Agent:
    """Assemble one Strands agent with Porchlight's standard wiring.

    Args:
        ctx: The application context every tool and hook reads from.
        name: Node/agent name; also how :class:`ScenarioModel` routes scripted turns.
        system_prompt: The role prompt, already composed with the group's values.
        tools: Tools this agent may call.
        output_model: Pydantic model the agent must answer with, or ``None`` for free text.
        tier: ``"haiku"`` for fast classification, ``"sonnet"`` for judgement.
        description: One line about the agent, surfaced in traces.

    Returns:
        A ready ``strands.Agent``. It deliberately has **no** session manager: graph nodes are
        rejected by Strands when their executor owns one, so persistence lives on the graph.
    """
    return Agent(
        model=build_model(ctx, tier, *([output_model] if output_model else [])),
        name=name,
        description=description or None,
        system_prompt=system_prompt,
        tools=tools,
        structured_output_model=output_model,
        conversation_manager=SlidingWindowConversationManager(window_size=WINDOW_SIZE),
        hooks=[AuditHook(ctx), TraceHook(ctx)],
        interventions=[PorchlightPolicy(ctx)],
        callback_handler=None,
    )

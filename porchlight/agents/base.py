"""Shared wiring for every Porchlight agent.

One place decides what an agent gets: the model tier, the sliding conversation window, the
audit and trace hooks, the policy intervention, and the injected clock. Individual factories
then only choose a name, a prompt, a tool set, and an output model.

**The clock is context, not a tool.** ``strands_tools.current_time`` is deprecated ("inject the
current time as context with ContextInjector"), and a tool call to ask what day it is costs a
whole model round trip anyway. Every agent instead carries a
:class:`strands.vended_plugins.context_injector.ContextInjector` that folds the group's local
time into the model input before each call. It is ephemeral — the text never enters durable
history or the session — so a request resumed from a decision card two hours later sees *then*,
not the stale time it was filed at.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.vended_plugins.context_injector import ContextInjector, InjectionContext

from ..context import AppContext
from ..models_provider import make_model
from ..policy import AuditHook, PorchlightPolicy, TraceHook, is_quiet_hours, to_local

WINDOW_SIZE = 40
"""Turns kept in an agent's context before the oldest are dropped."""

CLOCK_INJECTOR_NAME = "porchlight:current-time"
"""Name of the clock :class:`ContextInjector`, so it can be told apart in logs and tests."""

Tier = Literal["sonnet", "haiku"]

__all__ = [
    "CLOCK_INJECTOR_NAME",
    "WINDOW_SIZE",
    "Tier",
    "build_agent",
    "build_model",
    "clock_injector",
    "render_now",
]


def render_now(ctx: AppContext) -> str:
    """The ``<current-time>`` block injected ahead of every model call.

    Reads :meth:`AppContext.now`, not the wall clock, so a frozen test clock and a replayed
    demo day both see the time the rest of the system is running at.
    """
    now = ctx.now()
    local = to_local(now, ctx.settings)
    quiet_start, quiet_end = ctx.settings.quiet_hours
    quiet = "yes" if is_quiet_hours(now, ctx.settings) else "no"
    return (
        "<current-time>\n"
        f"now_utc: {now.isoformat()}\n"
        f"now_local: {local:%A %d %B %Y, %H:%M} ({ctx.settings.timezone})\n"
        f"quiet_hours: {quiet} (local {quiet_start}:00–{quiet_end}:00)\n"
        'Resolve every relative time in the message — "tomorrow", "Thursday morning", '
        '"tonight" — against this, and write windows back as absolute UTC.\n'
        "</current-time>"
    )


def clock_injector(ctx: AppContext) -> ContextInjector:
    """Build the plugin that gives an agent the current time and timezone.

    ``trigger="everyTurn"`` rather than the default ``"userTurn"``: these agents are autonomous
    loops, so the turn that finally writes a window is usually a tool-result turn, and the time
    has to still be in front of the model there.
    """

    def render(_context: InjectionContext) -> str:
        return render_now(ctx)

    return ContextInjector(render, name=CLOCK_INJECTOR_NAME, trigger="everyTurn")


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
        A ready ``strands.Agent`` carrying the clock injector. It deliberately has **no** session
        manager: graph nodes are rejected by Strands when their executor owns one, so persistence
        lives on the graph.
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
        plugins=[clock_injector(ctx)],
        callback_handler=None,
    )

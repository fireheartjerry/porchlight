"""Each agent factory builds, is wired the way the contract says, and produces its output model."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from porchlight.agents import (
    VALUES,
    BriefResult,
    IntakeResult,
    OutreachStep,
    StewardResult,
    build_intake_task,
    interpret_reply,
    make_brief_agent,
    make_intake_agent,
    make_interpret_reply_agent,
    make_matcher_agent,
    make_outreach_agent,
    make_steward_agent,
)
from porchlight.agents.base import WINDOW_SIZE
from porchlight.agents.prompts import (
    brief_prompt,
    intake_prompt,
    matcher_prompt,
    outreach_prompt,
    steward_prompt,
)
from porchlight.config import Settings
from porchlight.context import AppContext
from porchlight.models import AidRequest, MatchPlan, ReplyIntent, Source, VolunteerReply
from porchlight.policy import AuditHook, PorchlightPolicy, TraceHook
from porchlight.testing.mock_model import MockModel, MockTurn

FACTORIES = {
    "intake": (make_intake_agent, IntakeResult),
    "matcher": (make_matcher_agent, MatchPlan),
    "outreach": (make_outreach_agent, OutreachStep),
    "steward": (make_steward_agent, StewardResult),
    "brief": (make_brief_agent, BriefResult),
}

# A one-pixel PNG, enough to exercise the image content block.
TINY_PNG = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
).decode()


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_factory_builds_a_wired_agent(ctx: AppContext, name: str) -> None:
    factory, output_model = FACTORIES[name]
    agent = factory(ctx)
    assert isinstance(agent, Agent)
    assert agent.name == name
    assert agent._default_structured_output_model is output_model
    assert isinstance(agent.conversation_manager, SlidingWindowConversationManager)
    assert agent.conversation_manager.window_size == WINDOW_SIZE
    assert agent.tool_names, "every agent should have at least one tool"


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_agents_carry_the_hooks_and_the_policy(ctx: AppContext, name: str) -> None:
    factory, _ = FACTORIES[name]
    agent = factory(ctx)
    handlers = agent._intervention_registry.handlers  # type: ignore[attr-defined]
    assert [handler.name for handler in handlers] == [PorchlightPolicy.name]
    owners = {
        type(getattr(entry.callback, "__self__", None))
        for entries in agent.hooks._registered_callbacks.values()  # type: ignore[attr-defined]
        for entry in entries
    }
    assert {AuditHook, TraceHook} <= owners


def test_agents_have_no_session_manager(ctx: AppContext) -> None:
    """Strands refuses graph nodes whose executor owns a session manager."""
    for factory, _ in FACTORIES.values():
        assert factory(ctx)._session_manager is None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "builder", [intake_prompt, matcher_prompt, outreach_prompt, steward_prompt, brief_prompt]
)
def test_prompts_carry_the_group_values(settings: Settings, builder: Any) -> None:
    prompt = builder(settings)
    assert settings.group_name in prompt
    for phrase in ("Never over-promise", "Quiet hours", "Escalate rather than guess", "easy to say no"):
        assert phrase in prompt, f"{builder.__name__} lost the values block"


def test_values_mention_the_configured_quiet_hours(settings: Settings) -> None:
    prompt = intake_prompt(settings)
    start, end = settings.quiet_hours
    assert f"{start}:00 to {end}:00" in prompt


def test_prompts_are_routable_by_the_scenario_model(settings: Settings) -> None:
    assert "[[agent:intake]]" in intake_prompt(settings)
    assert "[[agent:matcher]]" in matcher_prompt(settings)


def test_values_block_is_not_accidentally_empty() -> None:
    assert len(VALUES.splitlines()) > 10


def test_intake_agent_returns_structured_output(ctx: AppContext) -> None:
    request = AidRequest(raw_text="Ride to dialysis Thursday 9am", source=Source.SMS)
    ctx.store.put_request(request)
    agent = make_intake_agent(ctx)
    result = agent(build_intake_task(request), invocation_state={"ctx": ctx, "request_id": request.id})
    assert isinstance(result.structured_output, IntakeResult)


def test_intake_task_includes_an_image_block() -> None:
    request = AidRequest(raw_text="", source=Source.PAPER)
    blocks = build_intake_task(request, TINY_PNG)
    images = [block for block in blocks if "image" in block]
    assert len(images) == 1
    assert images[0]["image"]["format"] == "png"
    assert isinstance(images[0]["image"]["source"]["bytes"], bytes)


def test_intake_task_survives_a_broken_image() -> None:
    request = AidRequest(raw_text="a ride please", source=Source.PAPER)
    blocks = build_intake_task(request, "not base64 at all!!")
    assert not [block for block in blocks if "image" in block]
    assert any("a ride please" in block.get("text", "") for block in blocks)


def test_intake_task_accepts_a_data_url() -> None:
    request = AidRequest(raw_text="", source=Source.PAPER)
    blocks = build_intake_task(request, f"data:image/png;base64,{TINY_PNG}")
    assert [block for block in blocks if "image" in block]


def test_intake_result_applies_to_a_request(ctx: AppContext) -> None:
    request = AidRequest(raw_text="raw", safety_flags=["stove on"])
    parsed = IntakeResult(summary="Ride to dialysis", safety_flags=["kid alone"], money_involved=True)
    parsed.apply_to(request)
    assert request.summary == "Ride to dialysis"
    assert request.safety_flags == ["stove on", "kid alone"]
    assert request.money_involved is True


def test_interpret_reply_agent_is_a_tiny_structured_agent(ctx: AppContext) -> None:
    agent = make_interpret_reply_agent(ctx)
    assert agent.name == "interpret_reply"
    assert agent._default_structured_output_model is VolunteerReply
    assert agent.tool_names == []


def test_interpret_reply_tool_returns_a_reply_dict(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    scripted = VolunteerReply(intent=ReplyIntent.DECLINE, confidence=0.9)
    monkeypatch.setattr(
        "porchlight.agents.base.make_model",
        lambda settings, tier: MockModel(script=[MockTurn(structured=scripted)]),
    )
    payload = interpret_reply(
        reply_text="sorry, not this week", volunteer_name="Maria", tool_context=_ToolContext(ctx)
    )
    assert payload["intent"] == "decline"
    assert payload["confidence"] == pytest.approx(0.9)


def test_interpret_reply_falls_back_to_unclear(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("model exploded")

    monkeypatch.setattr("porchlight.agents.outreach.make_interpret_reply_agent", boom)
    payload = interpret_reply(reply_text="???", tool_context=_ToolContext(ctx))
    assert payload["intent"] == "unclear"


def test_outreach_agent_exposes_the_sub_agent_as_a_tool(ctx: AppContext) -> None:
    assert "interpret_reply" in make_outreach_agent(ctx).tool_names


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_agents_produce_their_output_model(ctx: AppContext, name: str) -> None:
    factory, output_model = FACTORIES[name]
    agent = factory(ctx)
    result = agent("go", invocation_state={"ctx": ctx})
    assert isinstance(result.structured_output, output_model)


class _ToolContext:
    """Minimal ``ToolContext`` stand-in for calling a ``@tool(context=True)`` directly."""

    def __init__(self, ctx: AppContext) -> None:
        self.invocation_state = {"ctx": ctx}
        self.tool_use = {"name": "interpret_reply", "input": {}, "toolUseId": "tu_1"}

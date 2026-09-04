"""The mock model must drive real Strands agents, tools, structured output, and graphs."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from strands import Agent, tool
from strands.multiagent import GraphBuilder
from strands.types.exceptions import StructuredOutputException
from strands.types.tools import ToolContext

from porchlight.config import Settings
from porchlight.context import AppContext
from porchlight.models import MatchPlan, VolunteerReply
from porchlight.models_provider import make_model, model_id_for
from porchlight.testing import MockModel, MockTurn, ScenarioModel


class Greeting(BaseModel):
    """Tiny structured-output model used by the tests."""

    greeting: str
    excited: bool = False


@tool
def shout(text: str) -> str:
    """Uppercase some text.

    Args:
        text: The text to shout.
    """
    return text.upper()


@tool(context=True)
def whoami(tool_context: ToolContext) -> str:
    """Return the group name from the app context."""
    ctx: AppContext = tool_context.invocation_state["ctx"]
    return ctx.settings.group_name


def _agent(model: object, **kwargs: object) -> Agent:
    return Agent(model=model, callback_handler=None, system_prompt="you are a test agent", **kwargs)


# --- scripted turns --------------------------------------------------------------------


def test_scripted_text_turn() -> None:
    model = MockModel(script=[MockTurn(text="hello there")])
    result = _agent(model)("hi")
    assert result.stop_reason == "end_turn"
    assert "hello there" in str(result)


def test_agent_calls_a_tool_then_ends() -> None:
    model = MockModel(script=[MockTurn(tool_calls=[("shout", {"text": "quiet"})]), MockTurn(text="QUIET")])
    agent = _agent(model, tools=[shout], name="shouter")
    result = agent("shout quiet")

    tool_uses = [
        block["toolUse"]
        for message in agent.messages
        for block in message.get("content", [])
        if "toolUse" in block
    ]
    assert [use["name"] for use in tool_uses] == ["shout"]
    assert tool_uses[0]["input"] == {"text": "quiet"}
    assert result.stop_reason == "end_turn"
    assert "QUIET" in str(result)


def test_tool_receives_app_context_from_invocation_state(ctx: AppContext) -> None:
    model = MockModel(script=[MockTurn(tool_calls=[("whoami", {})]), MockTurn(text="done")])
    agent = _agent(model, tools=[whoami], name="ctx-reader")
    agent("who are you", invocation_state={"ctx": ctx})

    results = [
        block["toolResult"]
        for message in agent.messages
        for block in message.get("content", [])
        if "toolResult" in block
    ]
    assert results and ctx.settings.group_name in str(results[0])


def test_text_and_tool_call_in_one_turn() -> None:
    model = MockModel(
        script=[MockTurn(text="on it", tool_calls=[("shout", {"text": "hi"})]), MockTurn(text="HI")]
    )
    agent = _agent(model, tools=[shout])
    agent("go")
    assistant_blocks = [
        block for message in agent.messages if message["role"] == "assistant" for block in message["content"]
    ]
    assert any("text" in block for block in assistant_blocks)
    assert any("toolUse" in block for block in assistant_blocks)


# --- structured output -----------------------------------------------------------------


def test_structured_output_is_synthesized_when_unscripted() -> None:
    result = _agent(MockModel(), structured_output_model=Greeting)("greet")
    assert isinstance(result.structured_output, Greeting)


def test_structured_output_can_be_scripted() -> None:
    model = MockModel(script=[MockTurn(structured=Greeting(greeting="hi", excited=True))])
    result = _agent(model, structured_output_model=Greeting)("greet")
    assert result.structured_output == Greeting(greeting="hi", excited=True)


def test_structured_output_accepts_a_raw_dict() -> None:
    model = MockModel(script=[MockTurn(structured={"greeting": "yo"})])
    result = _agent(model, structured_output_model=Greeting)("greet")
    assert result.structured_output is not None
    assert result.structured_output.greeting == "yo"


@pytest.mark.parametrize("model_cls", [MatchPlan, VolunteerReply, Greeting])
def test_structured_output_for_project_models(model_cls: type[BaseModel]) -> None:
    result = _agent(MockModel(), structured_output_model=model_cls)("go")
    assert isinstance(result.structured_output, model_cls)


async def test_model_structured_output_method_yields_output() -> None:
    model = MockModel()
    events = [event async for event in model.structured_output(Greeting, [], None)]
    assert isinstance(events[-1]["output"], Greeting)


def test_default_structured_can_be_disabled() -> None:
    """With synthesis off the model never calls the tool, so Strands raises its own error."""
    model = MockModel(default_structured=False)
    with pytest.raises(StructuredOutputException):
        _agent(model, structured_output_model=Greeting)("greet")


# --- model plumbing --------------------------------------------------------------------


def test_config_and_token_counting() -> None:
    model = MockModel(model_id="mock-haiku")
    assert model.get_config()["model_id"] == "mock-haiku"
    assert model.context_window_limit == 200_000
    model.update_config(context_window_limit=1000)
    assert model.context_window_limit == 1000


async def test_count_tokens_is_positive() -> None:
    model = MockModel()
    tokens = await model.count_tokens([{"role": "user", "content": [{"text": "hello world"}]}])
    assert tokens > 0


def test_calls_are_recorded_and_reset() -> None:
    model = MockModel(script=[MockTurn(text="a"), MockTurn(text="b")])
    _agent(model)("one")
    assert len(model.calls) == 1
    assert model.remaining_turns == 1
    model.reset()
    assert model.calls == []
    assert model.remaining_turns == 2


# --- scenario routing ------------------------------------------------------------------


def test_scenario_model_routes_by_agent_name() -> None:
    scenario = ScenarioModel({"intake": [MockTurn(text="parsed")], "matcher": [MockTurn(text="ranked")]})
    assert "parsed" in str(_agent(scenario, name="intake")("go"))
    assert "ranked" in str(_agent(scenario, name="matcher")("go"))


def test_scenario_model_falls_back_to_default() -> None:
    scenario = ScenarioModel({"intake": [MockTurn(text="parsed")]}, default=[MockTurn(text="fallback")])
    assert "fallback" in str(_agent(scenario, name="steward")("go"))


def test_scenario_model_reads_a_system_prompt_marker() -> None:
    scenario = ScenarioModel({"brief": [MockTurn(text="digest")]})
    assert scenario.resolve_agent_name(None, "you are [[agent:brief]] today") == "brief"
    assert scenario.resolve_agent_name({"agent": None}, None) == "default"


# --- graph -----------------------------------------------------------------------------


def test_mock_model_drives_a_two_node_graph() -> None:
    scenario = ScenarioModel({"first": [MockTurn(text="one")], "second": [MockTurn(text="two")]})
    first = _agent(scenario, name="first")
    second = _agent(scenario, name="second")

    builder = GraphBuilder()
    builder.add_node(first, "first")
    builder.add_node(second, "second")
    builder.add_edge("first", "second")
    builder.set_entry_point("first")
    builder.set_max_node_executions(6)
    graph = builder.build()

    result = graph("run the pipeline")
    assert [node.node_id for node in result.execution_order] == ["first", "second"]
    assert "two" in str(result.results["second"].result)


def test_graph_conditional_edge_can_skip_a_node() -> None:
    scenario = ScenarioModel({"start": [MockTurn(text="stop here")], "never": [MockTurn(text="unreachable")]})
    builder = GraphBuilder()
    builder.add_node(_agent(scenario, name="start"), "start")
    builder.add_node(_agent(scenario, name="never"), "never")
    builder.add_edge("start", "never", condition=lambda state: False)
    builder.set_entry_point("start")
    builder.set_max_node_executions(4)

    result = builder.build()("go")
    assert [node.node_id for node in result.execution_order] == ["start"]


# --- provider --------------------------------------------------------------------------


def test_make_model_returns_mock_without_aws() -> None:
    settings = Settings(model_provider="mock")
    assert isinstance(make_model(settings, "sonnet"), MockModel)
    assert isinstance(make_model(settings, "haiku"), MockModel)


def test_model_id_for_tier() -> None:
    settings = Settings(model_sonnet="sonnet-id", model_haiku="haiku-id")
    assert model_id_for(settings, "sonnet") == "sonnet-id"
    assert model_id_for(settings, "haiku") == "haiku-id"
    with pytest.raises(ValueError):
        model_id_for(settings, "opus")  # type: ignore[arg-type]

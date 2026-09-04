"""A scriptable ``strands.models.Model`` so the whole system runs with no AWS credentials.

``MockModel`` emits the exact Bedrock-shaped ``StreamEvent`` sequence the Strands event loop
expects, so real ``Agent``s, tools, structured output, hooks, interventions, and ``Graph``s all
behave normally.
"""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncGenerator, AsyncIterable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from strands.models.model import Model
from strands.types.content import Messages, SystemContentBlock
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

from .synth import example_dict, example_for_schema

T = TypeVar("T", bound=BaseModel)

STRUCTURED_OUTPUT_MARKER = "This StructuredOutputTool"
"""Substring Strands puts in the description of the synthetic structured-output tool."""

AGENT_MARKER = "[[agent:"
"""Optional system-prompt marker used to route :class:`ScenarioModel` scripts."""

DEFAULT_CONTEXT_WINDOW = 200_000


@dataclass
class MockTurn:
    """One scripted model response.

    Attributes:
        text: Assistant text to emit.
        tool_calls: ``(tool_name, input_dict)`` pairs to request; forces ``stopReason="tool_use"``.
        structured: Payload for the structured-output tool, as a model instance or raw dict.
    """

    text: str | None = None
    tool_calls: list[tuple[str, dict[str, Any]]] | None = None
    structured: BaseModel | dict[str, Any] | None = None


@dataclass
class _Counter:
    """Monotonic ids for tool uses, guarded so concurrent agents never collide."""

    value: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def next(self) -> int:
        """Return the next integer."""
        with self.lock:
            self.value += 1
            return self.value


def _structured_output_spec(tool_specs: Sequence[ToolSpec] | None) -> ToolSpec | None:
    """Return the synthetic structured-output tool spec from ``tool_specs``, if present."""
    for spec in tool_specs or []:
        if STRUCTURED_OUTPUT_MARKER in (spec.get("description") or ""):
            return spec
    return None


def _model_by_name(name: str, extra: dict[str, type[BaseModel]]) -> type[BaseModel] | None:
    """Find a Pydantic model class by its class name (the structured-output tool's name)."""
    if name in extra:
        return extra[name]
    from ..models import ALL_MODELS

    for model_cls in ALL_MODELS:
        if model_cls.__name__ == name:
            return model_cls
    return None


def _payload_for_spec(spec: ToolSpec, extra: dict[str, type[BaseModel]]) -> dict[str, Any]:
    """Synthesize a valid input payload for a structured-output tool spec."""
    model_cls = _model_by_name(spec.get("name", ""), extra)
    if model_cls is not None:
        return example_dict(model_cls)
    schema = (spec.get("inputSchema") or {}).get("json") or {}
    value = example_for_schema(schema)
    return value if isinstance(value, dict) else {}


async def emit_message(
    text: str | None,
    tool_calls: Sequence[tuple[str, dict[str, Any]]] = (),
    ids: _Counter | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """Emit one assistant message as the Bedrock-shaped stream events Strands expects.

    Shared by :class:`MockModel` and by
    :class:`porchlight.sim.mock_scenarios.PorchlightScenarioModel`, which computes its turns
    from live state instead of replaying a script.

    Args:
        text: Assistant text to emit, if any.
        tool_calls: ``(tool_name, input_dict)`` pairs; a non-empty list forces
            ``stopReason="tool_use"``.
        ids: Counter used to mint tool-use ids; a fresh one is made when omitted.
    """
    ids = ids or _Counter()
    yield {"messageStart": {"role": "assistant"}}

    index = 0
    if text:
        yield {"contentBlockStart": {"contentBlockIndex": index, "start": {}}}
        yield {"contentBlockDelta": {"contentBlockIndex": index, "delta": {"text": text}}}
        yield {"contentBlockStop": {"contentBlockIndex": index}}
        index += 1

    for name, tool_input in tool_calls:
        tool_use_id = f"mock_tool_{ids.next()}"
        yield {
            "contentBlockStart": {
                "contentBlockIndex": index,
                "start": {"toolUse": {"toolUseId": tool_use_id, "name": name}},
            }
        }
        yield {
            "contentBlockDelta": {
                "contentBlockIndex": index,
                "delta": {"toolUse": {"input": json.dumps(tool_input)}},
            }
        }
        yield {"contentBlockStop": {"contentBlockIndex": index}}
        index += 1

    yield {"messageStop": {"stopReason": "tool_use" if tool_calls else "end_turn"}}
    yield {
        "metadata": {
            "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
            "metrics": {"latencyMs": 1},
        }
    }


class MockModel(Model):
    """A deterministic model driven by an optional script of :class:`MockTurn`\\ s.

    Each call to :meth:`stream` consumes the next turn. When the script runs out, the model
    finishes the turn: it calls the structured-output tool with a synthesized-but-valid payload
    when the agent asked for structured output, otherwise it emits a short text reply.

    Args:
        script: Turns to play back, in order.
        default_structured: When True (default), satisfy an unscripted structured-output request
            with :func:`porchlight.testing.synth.example_instance`.
        model_id: Cosmetic id reported by :meth:`get_config`.
        output_models: Extra Pydantic classes to resolve structured-output tool names against.
        default_text: Text emitted when the script is exhausted and no structured output is due.
    """

    def __init__(
        self,
        script: list[MockTurn] | None = None,
        default_structured: bool = True,
        *,
        model_id: str = "mock",
        output_models: Iterable[type[BaseModel]] | None = None,
        default_text: str = "Done.",
    ) -> None:
        self.script: list[MockTurn] = list(script or [])
        self.default_structured = default_structured
        self.default_text = default_text
        self.calls: list[dict[str, Any]] = []
        self._config: dict[str, Any] = {
            "model_id": model_id,
            "context_window_limit": DEFAULT_CONTEXT_WINDOW,
        }
        self._output_models: dict[str, type[BaseModel]] = {cls.__name__: cls for cls in (output_models or ())}
        self._cursor = 0
        self._ids = _Counter()

    # --- Model plumbing -----------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        """Return the model configuration."""
        return self._config

    def update_config(self, **model_config: Any) -> None:
        """Merge ``model_config`` into the model configuration."""
        self._config.update(model_config)

    async def count_tokens(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
    ) -> int:
        """Cheap deterministic token estimate (characters / 4)."""
        blob = json.dumps(messages, default=str) + (system_prompt or "")
        blob += json.dumps(tool_specs or [], default=str)
        return len(blob) // 4

    # --- scripting ----------------------------------------------------------

    def add_turn(self, turn: MockTurn) -> MockModel:
        """Append a turn to the script and return self (chainable)."""
        self.script.append(turn)
        return self

    def reset(self) -> None:
        """Rewind the script cursor and forget recorded calls."""
        self._cursor = 0
        self.calls.clear()

    @property
    def remaining_turns(self) -> int:
        """How many scripted turns have not been played yet."""
        return max(0, len(self.script) - self._cursor)

    def _next_turn(self) -> MockTurn | None:
        if self._cursor >= len(self.script):
            return None
        turn = self.script[self._cursor]
        self._cursor += 1
        return turn

    # --- streaming ----------------------------------------------------------

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
        invocation_state: dict[str, Any] | None = None,
        cancel_signal: threading.Event | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        """Play back the next scripted turn as Bedrock-shaped stream events."""
        self.calls.append(
            {
                "messages": messages,
                "tool_names": [spec.get("name") for spec in tool_specs or []],
                "system_prompt": system_prompt,
                "tool_choice": tool_choice,
            }
        )
        turn = self._next_turn()
        structured_spec = _structured_output_spec(tool_specs)

        text = turn.text if turn else None
        tool_calls = list(turn.tool_calls or []) if turn else []

        if structured_spec is not None and not tool_calls:
            payload = self._structured_payload(turn, structured_spec)
            if payload is not None:
                tool_calls = [(structured_spec["name"], payload)]

        if not tool_calls and text is None:
            text = self.default_text

        async for event in self._emit(text, tool_calls):
            yield event

    def _structured_payload(self, turn: MockTurn | None, spec: ToolSpec) -> dict[str, Any] | None:
        """Decide what to send to the structured-output tool for this turn."""
        scripted = turn.structured if turn else None
        if isinstance(scripted, BaseModel):
            return scripted.model_dump(mode="json")
        if isinstance(scripted, dict):
            return scripted
        if turn is not None and turn.text is not None:
            # An explicitly scripted text turn wins over synthesizing structured output.
            return None
        if not self.default_structured:
            return None
        return _payload_for_spec(spec, self._output_models)

    async def _emit(
        self, text: str | None, tool_calls: list[tuple[str, dict[str, Any]]]
    ) -> AsyncGenerator[StreamEvent, None]:
        """Emit one complete assistant message."""
        async for event in emit_message(text, tool_calls, self._ids):
            yield event

    # --- structured output --------------------------------------------------

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield a single ``{"output": instance}`` event.

        A scripted turn whose ``structured`` payload matches ``output_model`` is used when
        available; otherwise a synthesized instance is returned.
        """
        turn = self._next_turn()
        scripted = turn.structured if turn else None
        if isinstance(scripted, output_model):
            yield {"output": scripted}
            return
        if isinstance(scripted, dict):
            yield {"output": output_model(**scripted)}
            return
        yield {"output": output_model(**example_dict(output_model))}

    def __repr__(self) -> str:
        return f"MockModel(model_id={self._config['model_id']!r}, remaining_turns={self.remaining_turns})"


class ScenarioModel(Model):
    """Route scripted turns per agent, keyed by ``agent.name``.

    The agent name is read from ``invocation_state["agent"].name``; when that is unavailable it
    falls back to an ``[[agent:<name>]]`` marker anywhere in the system prompt.

    Args:
        scenarios: ``{agent_name: [MockTurn, ...]}``.
        default: Turns used for an agent with no entry in ``scenarios``.
        **model_kwargs: Passed through to each underlying :class:`MockModel`.
    """

    def __init__(
        self,
        scenarios: dict[str, list[MockTurn]] | None = None,
        default: list[MockTurn] | None = None,
        **model_kwargs: Any,
    ) -> None:
        self.scenarios = {name: list(turns) for name, turns in (scenarios or {}).items()}
        self.default = list(default or [])
        self._model_kwargs = model_kwargs
        self._models: dict[str, MockModel] = {}
        self._lock = threading.Lock()
        self._config: dict[str, Any] = {
            "model_id": "mock-scenario",
            "context_window_limit": DEFAULT_CONTEXT_WINDOW,
        }

    # --- routing ------------------------------------------------------------

    @staticmethod
    def resolve_agent_name(
        invocation_state: dict[str, Any] | None,
        system_prompt: str | None,
    ) -> str:
        """Work out which script applies to this call."""
        agent = (invocation_state or {}).get("agent")
        name = getattr(agent, "name", None)
        if isinstance(name, str) and name:
            return name
        if system_prompt and AGENT_MARKER in system_prompt:
            start = system_prompt.index(AGENT_MARKER) + len(AGENT_MARKER)
            end = system_prompt.find("]]", start)
            if end > start:
                return system_prompt[start:end].strip()
        return "default"

    def model_for(self, name: str) -> MockModel:
        """Return (creating on first use) the :class:`MockModel` backing one agent name."""
        with self._lock:
            if name not in self._models:
                script = self.scenarios.get(name, self.default)
                self._models[name] = MockModel(
                    script=list(script), model_id=f"mock-{name}", **self._model_kwargs
                )
            return self._models[name]

    # --- Model plumbing -----------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        """Return the model configuration."""
        return self._config

    def update_config(self, **model_config: Any) -> None:
        """Merge ``model_config`` into the model configuration."""
        self._config.update(model_config)

    async def count_tokens(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
    ) -> int:
        """Delegate to the routed model."""
        name = self.resolve_agent_name(None, system_prompt)
        return await self.model_for(name).count_tokens(
            messages, tool_specs, system_prompt, system_prompt_content
        )

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
        invocation_state: dict[str, Any] | None = None,
        cancel_signal: threading.Event | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        """Delegate to the :class:`MockModel` for the calling agent."""
        name = self.resolve_agent_name(invocation_state, system_prompt)
        async for event in self.model_for(name).stream(
            messages,
            tool_specs,
            system_prompt,
            tool_choice=tool_choice,
            system_prompt_content=system_prompt_content,
            invocation_state=invocation_state,
            cancel_signal=cancel_signal,
            **kwargs,
        ):
            yield event

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Delegate structured output to the routed model."""
        name = self.resolve_agent_name(None, system_prompt)
        async for event in self.model_for(name).structured_output(
            output_model, prompt, system_prompt, **kwargs
        ):
            yield event

    def __repr__(self) -> str:
        return f"ScenarioModel(agents={sorted(self.scenarios)})"

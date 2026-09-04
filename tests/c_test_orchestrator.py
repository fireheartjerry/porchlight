"""Orchestrator abstraction: outcome coercion, session-id padding, AgentCore payloads."""

from __future__ import annotations

import io
import json
from datetime import date
from typing import Any

import pytest

from porchlight.context import AppContext
from porchlight.models import Decision, DecisionKind, DecisionOption, RequestStatus
from porchlight.orchestrator import (
    MIN_RUNTIME_SESSION_ID,
    AgentCoreOrchestrator,
    GraphUnavailableError,
    LocalOrchestrator,
    Orchestrator,
    RunOutcome,
    SweepOutcome,
    coerce_run_outcome,
    coerce_sweep_outcome,
    make_orchestrator,
    parse_invoke_response,
    runtime_session_id,
)


class StubAgentCoreClient:
    """Records ``invoke_agent_runtime`` calls and replays canned responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.responses.pop(0) if self.responses else {"response": b"{}"}

    @staticmethod
    def json_body(payload: Any) -> dict[str, Any]:
        """A response shaped like botocore's StreamingBody + application/json."""
        return {
            "contentType": "application/json",
            "statusCode": 200,
            "response": io.BytesIO(json.dumps(payload).encode("utf-8")),
        }


# --------------------------------------------------------------------------------------
# Session ids
# --------------------------------------------------------------------------------------


def test_short_request_id_is_padded_to_the_agentcore_minimum() -> None:
    padded = runtime_session_id("req_9f3a1c04bd")
    assert len(padded) >= MIN_RUNTIME_SESSION_ID
    assert padded.startswith("req_9f3a1c04bd-")


def test_session_id_padding_is_deterministic() -> None:
    assert runtime_session_id("req_abc") == runtime_session_id("req_abc")
    assert runtime_session_id("req_abc") != runtime_session_id("req_abd")


def test_long_session_ids_pass_through_unpadded() -> None:
    raw = "req_" + "a" * 40
    assert runtime_session_id(raw) == raw


def test_session_ids_are_sanitised() -> None:
    assert " " not in runtime_session_id("req with spaces/and slashes")


def test_empty_session_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        runtime_session_id("")


# --------------------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------------------


def test_parses_a_single_json_body() -> None:
    response = StubAgentCoreClient.json_body({"request_id": "req_1", "summary": "done"})
    assert parse_invoke_response(response) == {"request_id": "req_1", "summary": "done"}


def test_parses_streamed_chunks() -> None:
    response = {
        "contentType": "application/json",
        "response": [
            {"chunk": {"bytes": b'{"request_id": "req_1",'}},
            {"chunk": {"bytes": b' "log_events": 4}'}},
        ],
    }
    assert parse_invoke_response(response) == {"request_id": "req_1", "log_events": 4}


def test_parses_an_event_stream_body_and_keeps_the_last_frame() -> None:
    body = (
        'data: {"type": "trace", "summary": "intake started"}\n\n'
        'data: {"request_id": "req_7", "status": "confirmed", "interrupted": false}\n\n'
        "data: [DONE]\n\n"
    )
    response = {"contentType": "text/event-stream", "response": io.BytesIO(body.encode("utf-8"))}
    assert parse_invoke_response(response)["request_id"] == "req_7"


def test_empty_body_parses_to_none() -> None:
    assert parse_invoke_response({"response": io.BytesIO(b"")}) is None


def test_non_json_body_comes_back_as_text() -> None:
    assert parse_invoke_response({"response": b"not json"}) == "not json"


# --------------------------------------------------------------------------------------
# Outcome coercion
# --------------------------------------------------------------------------------------


def test_coerces_a_dict_with_nested_decisions() -> None:
    outcome = coerce_run_outcome(
        {
            "status": "escalated",
            "interrupted": True,
            "log_events": 9,
            "summary": "needs a human",
            "decisions_created": [{"id": "dec_1", "kind": "safety", "title": "Child alone"}],
            "unexpected_extra": "ignored",
        },
        "req_fallback",
    )
    assert outcome.request_id == "req_fallback"
    assert outcome.status is RequestStatus.ESCALATED
    assert outcome.decisions_created[0].kind is DecisionKind.SAFETY
    assert outcome.interrupted is True
    assert outcome.handled_quietly is False


def test_coerces_an_object_with_matching_attributes() -> None:
    class GraphOutcome:
        request_id = "req_2"
        status = RequestStatus.COMPLETED
        decisions_created: list[Decision] = []
        log_events = 3
        interrupted = False
        summary = "all set"

    outcome = coerce_run_outcome(GraphOutcome(), "req_ignored")
    assert outcome.request_id == "req_2"
    assert outcome.handled_quietly is True


def test_coerces_a_json_string() -> None:
    outcome = coerce_run_outcome('{"request_id": "req_3", "log_events": 2}', "req_x")
    assert outcome.request_id == "req_3"
    assert outcome.log_events == 2


def test_coerces_sweep_outcomes() -> None:
    swept = coerce_sweep_outcome({"messages_sent": 2, "timed_out": ["req_a"], "summary": "ok"})
    assert swept.messages_sent == 2
    assert swept.escalated == []


# --------------------------------------------------------------------------------------
# AgentCoreOrchestrator
# --------------------------------------------------------------------------------------


ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/porchlight-abc"


def _agentcore(ctx: AppContext, responses: list[dict[str, Any]]) -> tuple[Any, StubAgentCoreClient]:
    client = StubAgentCoreClient(responses)
    return AgentCoreOrchestrator(ctx, arn=ARN, region="us-west-2", client=client), client


def test_process_request_sends_the_contract_payload(ctx: AppContext) -> None:
    orchestrator, client = _agentcore(
        ctx, [StubAgentCoreClient.json_body({"request_id": "req_1", "status": "confirmed"})]
    )
    outcome = orchestrator.process_request("req_1")

    call = client.calls[0]
    assert call["agentRuntimeArn"] == ARN
    assert json.loads(call["payload"]) == {"action": "process_request", "request_id": "req_1"}
    assert call["contentType"] == "application/json"
    assert len(call["runtimeSessionId"]) >= MIN_RUNTIME_SESSION_ID
    assert call["runtimeSessionId"].startswith("req_1-")
    assert outcome.status is RequestStatus.CONFIRMED


def test_resume_decision_uses_the_requests_session(ctx: AppContext) -> None:
    decision = Decision(
        id="dec_abc",
        request_id="req_hist_dialysis",
        kind=DecisionKind.UNMATCHED,
        options=[DecisionOption(id="widen_pool", label="Widen the pool")],
    )
    ctx.store.put_decision(decision)
    orchestrator, client = _agentcore(
        ctx, [StubAgentCoreClient.json_body({"request_id": "req_hist_dialysis", "status": "matching"})]
    )

    outcome = orchestrator.resume_decision("dec_abc", "widen_pool", "ask Northgate too")

    call = client.calls[0]
    assert json.loads(call["payload"]) == {
        "action": "resume_decision",
        "decision_id": "dec_abc",
        "option_id": "widen_pool",
        "note": "ask Northgate too",
    }
    assert call["runtimeSessionId"].startswith("req_hist_dialysis-")
    assert outcome.request_id == "req_hist_dialysis"


def test_resume_decision_falls_back_to_the_decision_id(ctx: AppContext) -> None:
    orchestrator, client = _agentcore(ctx, [StubAgentCoreClient.json_body({})])
    outcome = orchestrator.resume_decision("dec_unknown", "approve")
    assert client.calls[0]["runtimeSessionId"].startswith("dec_unknown-")
    assert outcome.request_id == "dec_unknown"


def test_sweep_and_brief_payloads(ctx: AppContext) -> None:
    orchestrator, client = _agentcore(
        ctx,
        [
            StubAgentCoreClient.json_body({"messages_sent": 3, "escalated": ["req_9"]}),
            StubAgentCoreClient.json_body({"markdown": "## Tuesday\n\nAll quiet."}),
        ],
    )

    swept = orchestrator.sweep()
    markdown = orchestrator.brief(date(2026, 9, 8))

    assert isinstance(swept, SweepOutcome)
    assert swept.escalated == ["req_9"]
    assert json.loads(client.calls[0]["payload"]) == {"action": "sweep"}
    assert json.loads(client.calls[1]["payload"]) == {"action": "brief", "day": "2026-09-08"}
    assert markdown.startswith("## Tuesday")
    assert all(len(call["runtimeSessionId"]) >= MIN_RUNTIME_SESSION_ID for call in client.calls)


def test_invoking_the_runtime_emits_a_trace_event(ctx: AppContext) -> None:
    orchestrator, _ = _agentcore(ctx, [StubAgentCoreClient.json_body({"request_id": "req_1"})])
    orchestrator.process_request("req_1")
    emitted = ctx.emitted  # type: ignore[attr-defined]
    assert any(event["type"] == "model_call" for event in emitted)


def test_agentcore_orchestrator_satisfies_the_protocol(ctx: AppContext) -> None:
    orchestrator, _ = _agentcore(ctx, [])
    assert isinstance(orchestrator, Orchestrator)
    assert isinstance(LocalOrchestrator(ctx), Orchestrator)


# --------------------------------------------------------------------------------------
# Selection & local orchestrator
# --------------------------------------------------------------------------------------


def test_make_orchestrator_picks_local_without_an_arn(ctx: AppContext) -> None:
    assert isinstance(make_orchestrator(ctx), LocalOrchestrator)


def test_make_orchestrator_picks_agentcore_when_an_arn_is_set(ctx: AppContext) -> None:
    settings = ctx.settings.model_copy(update={"agent_runtime_arn": ARN})
    orchestrator = make_orchestrator(ctx, settings)
    assert isinstance(orchestrator, AgentCoreOrchestrator)
    assert orchestrator.arn == ARN
    assert orchestrator._client is None  # boto3 is never created at construction time


def test_local_orchestrator_delegates_to_the_graph(ctx: AppContext, monkeypatch: Any) -> None:
    class FakeGraph:
        @staticmethod
        def run_request(context: AppContext, request_id: str) -> dict[str, Any]:
            assert context is ctx
            return {"request_id": request_id, "status": "completed", "log_events": 5}

        @staticmethod
        def run_sweep(context: AppContext) -> dict[str, Any]:
            return {"messages_sent": 1, "summary": "one reminder"}

        @staticmethod
        def run_brief(context: AppContext, day: date) -> str:
            return f"# brief {day.isoformat()}"

    monkeypatch.setattr("porchlight.orchestrator.graph_module", lambda: FakeGraph)
    orchestrator = LocalOrchestrator(ctx)

    assert orchestrator.process_request("req_1").status is RequestStatus.COMPLETED
    assert orchestrator.sweep().messages_sent == 1
    assert orchestrator.brief(date(2026, 9, 8)) == "# brief 2026-09-08"


def test_local_orchestrator_reports_a_missing_graph(ctx: AppContext, monkeypatch: Any) -> None:
    def boom() -> Any:
        raise GraphUnavailableError("porchlight.graph is not available yet")

    monkeypatch.setattr("porchlight.orchestrator.graph_module", boom)
    with pytest.raises(GraphUnavailableError):
        LocalOrchestrator(ctx).process_request("req_1")


def test_run_outcome_round_trips_through_json() -> None:
    outcome = RunOutcome(request_id="req_1", status=RequestStatus.CONFIRMED, summary="matched Maria")
    assert RunOutcome.model_validate_json(outcome.model_dump_json()) == outcome

"""The AgentCore Runtime's reply, exactly as us-east-1 sends it.

The live API answered ``POST /api/inbox`` with ``{"status": "new", "log_events": 0,
"summary": ""}`` after 39 seconds — while the CloudWatch logs showed the graph running to
completion and the request reaching ``confirmed``. Nothing timed out and nothing raised: the
answer was simply thrown away.

:func:`porchlight.runtime.dispatch` does not return a ``RunOutcome``. It returns an envelope
— ``{"action", "session_id", "ok", "outcome"}`` — and every one of those keys is unknown to
``RunOutcome``, so :func:`coerce_run_outcome` filtered all four out and validated an empty
model with the fallback ``request_id``. Hence a perfectly successful run reported as ``new``.

The bodies below were captured from the deployed runtime
``porchlight_Porchlight-tKZxVxH9Tf`` with ``boto3.client("bedrock-agentcore")
.invoke_agent_runtime(...)``: a buffered ``application/json`` ``StreamingBody``, not SSE — a
non-streaming entrypoint return goes through Starlette's ``Response(..., "application/json")``
in ``bedrock_agentcore.runtime.app``.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from porchlight.context import AppContext
from porchlight.models import RequestStatus
from porchlight.orchestrator import (
    RUNTIME_CONNECT_TIMEOUT,
    RUNTIME_READ_TIMEOUT,
    AgentCoreOrchestrator,
    RuntimeInvocationError,
    coerce_run_outcome,
    parse_invoke_response,
    unwrap_runtime_result,
)

ARN = "arn:aws:bedrock-agentcore:us-east-1:892077329800:runtime/porchlight_Porchlight-tKZxVxH9Tf"

SESSION_ID = "req_dc8d0445c3-4f0a1d2c8b9e7a6f5d4c3b2a1908f7e6d5c4b3a2019876543210fedcba98"

LIVE_PROCESS_REQUEST = {
    "action": "process_request",
    "session_id": SESSION_ID,
    "ok": True,
    "outcome": {
        "request_id": "req_dc8d0445c3",
        "status": "confirmed",
        "decisions_created": [],
        "log_events": 11,
        "interrupted": False,
        "summary": "Maria Alvarez is driving Grace to dialysis Thursday at 09:00.",
    },
}
"""One real ``process_request`` reply, with the outcome inside the envelope."""

LIVE_REFUSAL = {
    "action": "process_request",
    "session_id": "probe-" + "x" * 40,
    "ok": False,
    "error": "request_id is required",
}
"""Captured verbatim by invoking the deployed runtime with ``{"action": "process_request"}``."""

LIVE_BRIEF = {
    "action": "brief",
    "session_id": "brief-2026-09-08-" + "a" * 20,
    "ok": True,
    "markdown": "## Tuesday\n\nTwo rides confirmed, nothing needs you.",
}


def _body(payload: Any) -> dict[str, Any]:
    """A response shaped like the one botocore hands back for a buffered JSON body."""
    return {
        "runtimeSessionId": SESSION_ID,
        "contentType": "application/json",
        "statusCode": 200,
        "response": io.BytesIO(json.dumps(payload).encode("utf-8")),
    }


class StubClient:
    """Replays canned responses and records how it was called."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.responses.pop(0)


# --------------------------------------------------------------------------------------
# The shape on the wire
# --------------------------------------------------------------------------------------


def test_the_live_body_is_one_buffered_json_document_not_sse() -> None:
    """``BedrockAgentCoreApp`` only streams when the entrypoint returns an async iterator."""
    parsed = parse_invoke_response(_body(LIVE_PROCESS_REQUEST))
    assert parsed == LIVE_PROCESS_REQUEST


def test_the_envelope_alone_coerces_to_a_useless_outcome() -> None:
    """The bug, pinned: this is what the live API returned to the browser."""
    dropped = coerce_run_outcome(LIVE_PROCESS_REQUEST, "req_dc8d0445c3")
    assert dropped.status is RequestStatus.NEW
    assert dropped.log_events == 0
    assert dropped.summary == ""


def test_unwrapping_the_envelope_recovers_the_real_outcome() -> None:
    outcome = coerce_run_outcome(unwrap_runtime_result(LIVE_PROCESS_REQUEST, "outcome"), "req_dc8d0445c3")
    assert outcome.request_id == "req_dc8d0445c3"
    assert outcome.status is RequestStatus.CONFIRMED
    assert outcome.log_events == 11
    assert outcome.summary.startswith("Maria Alvarez")


def test_a_bare_outcome_still_passes_through_untouched() -> None:
    """An outcome that never went near the runtime must not be mangled by the unwrapper."""
    bare = {"request_id": "req_1", "status": "confirmed", "log_events": 3}
    assert unwrap_runtime_result(bare, "outcome") == bare


def test_a_non_dict_payload_passes_through() -> None:
    assert unwrap_runtime_result("## Tuesday", "markdown") == "## Tuesday"
    assert unwrap_runtime_result(None, "outcome") is None


def test_an_envelope_with_no_result_key_falls_back_to_itself() -> None:
    """Defensive: a future action that answers ``ok`` and nothing else is not data loss."""
    envelope = {"action": "sweep", "session_id": SESSION_ID, "ok": True}
    assert unwrap_runtime_result(envelope, "outcome") == envelope


# --------------------------------------------------------------------------------------
# End to end through the orchestrator
# --------------------------------------------------------------------------------------


def test_process_request_returns_the_real_outcome(ctx: AppContext) -> None:
    client = StubClient(_body(LIVE_PROCESS_REQUEST))
    orchestrator = AgentCoreOrchestrator(ctx, arn=ARN, region="us-east-1", client=client)

    outcome = orchestrator.process_request("req_dc8d0445c3")

    assert outcome.status is RequestStatus.CONFIRMED
    assert outcome.log_events == 11
    assert outcome.handled_quietly is True


def test_a_refusal_is_raised_rather_than_returned_as_an_empty_outcome(ctx: AppContext) -> None:
    client = StubClient(_body(LIVE_REFUSAL))
    orchestrator = AgentCoreOrchestrator(ctx, arn=ARN, region="us-east-1", client=client)

    with pytest.raises(RuntimeInvocationError, match="request_id is required"):
        orchestrator.process_request("req_dc8d0445c3")


def test_brief_reads_the_markdown_out_of_the_envelope(ctx: AppContext) -> None:
    from datetime import date

    client = StubClient(_body(LIVE_BRIEF))
    orchestrator = AgentCoreOrchestrator(ctx, arn=ARN, region="us-east-1", client=client)

    assert orchestrator.brief(date(2026, 9, 8)).startswith("## Tuesday")


def test_sweep_reads_the_outcome_out_of_the_envelope(ctx: AppContext) -> None:
    envelope = {
        "action": "sweep",
        "session_id": "sweep-2026-09-08-" + "b" * 20,
        "ok": True,
        "outcome": {"messages_sent": 2, "escalated": ["req_9"], "timed_out": [], "summary": "two nudges"},
    }
    client = StubClient(_body(envelope))
    orchestrator = AgentCoreOrchestrator(ctx, arn=ARN, region="us-east-1", client=client)

    swept = orchestrator.sweep()

    assert swept.messages_sent == 2
    assert swept.escalated == ["req_9"]


def test_resume_decision_returns_the_real_outcome(ctx: AppContext) -> None:
    envelope = {
        "action": "resume_decision",
        "session_id": SESSION_ID,
        "ok": True,
        "outcome": {"request_id": "req_dc8d0445c3", "status": "escalated", "interrupted": True},
    }
    client = StubClient(_body(envelope))
    orchestrator = AgentCoreOrchestrator(ctx, arn=ARN, region="us-east-1", client=client)

    outcome = orchestrator.resume_decision("dec_1", "widen_pool")

    assert outcome.status is RequestStatus.ESCALATED
    assert outcome.interrupted is True


# --------------------------------------------------------------------------------------
# Timeouts, and why there is exactly one attempt
# --------------------------------------------------------------------------------------


def test_the_client_waits_out_a_whole_graph_run_and_never_retries(ctx: AppContext, monkeypatch: Any) -> None:
    """botocore's defaults are a 60-second read *and* retries — a retry re-runs the graph."""
    captured: dict[str, Any] = {}

    class FakeBoto3:
        @staticmethod
        def client(service: str, **kwargs: Any) -> str:
            captured["service"] = service
            captured["kwargs"] = kwargs
            return "stub-client"

    monkeypatch.setitem(__import__("sys").modules, "boto3", FakeBoto3)
    orchestrator = AgentCoreOrchestrator(ctx, arn=ARN, region="us-east-1")

    assert orchestrator.client == "stub-client"
    config = captured["kwargs"]["config"]
    assert captured["service"] == "bedrock-agentcore"
    assert config.read_timeout == RUNTIME_READ_TIMEOUT
    assert RUNTIME_READ_TIMEOUT >= 900, "a graph run outlasts botocore's 60-second default"
    assert config.connect_timeout == RUNTIME_CONNECT_TIMEOUT
    assert config.retries["total_max_attempts"] == 1


# --------------------------------------------------------------------------------------
# The AgentCore CLI's prompt envelope
# --------------------------------------------------------------------------------------


def test_the_cli_prompt_envelope_is_unwrapped() -> None:
    """``agentcore invoke '{"action": "sweep"}'`` nests the payload inside ``prompt``."""
    from porchlight.runtime import unwrap_prompt

    assert unwrap_prompt({"prompt": '{"action": "sweep"}'}) == {"action": "sweep"}


def test_a_direct_payload_is_left_alone() -> None:
    """The API, the sweep Lambda and curl all post the payload itself."""
    from porchlight.runtime import unwrap_prompt

    payload = {"action": "process_request", "request_id": "req_1"}
    assert unwrap_prompt(payload) == payload


def test_a_plain_chat_prompt_is_not_mistaken_for_a_payload() -> None:
    """Someone typing English at the CLI still gets the default action, not a crash."""
    from porchlight.runtime import unwrap_prompt

    assert unwrap_prompt({"prompt": "run the sweep please"}) == {"prompt": "run the sweep please"}
    assert unwrap_prompt({"prompt": "{not json"}) == {"prompt": "{not json"}
    assert unwrap_prompt({"prompt": "[1, 2]"}) == {"prompt": "[1, 2]"}


def test_the_inner_payload_wins_over_the_outer_one() -> None:
    from porchlight.runtime import unwrap_prompt

    unwrapped = unwrap_prompt({"action": "process_request", "prompt": '{"action": "brief"}'})
    assert unwrapped == {"action": "brief"}

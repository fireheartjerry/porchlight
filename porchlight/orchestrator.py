"""How the API asks Porchlight to do work.

Two implementations behind one protocol:

* :class:`LocalOrchestrator` runs the Strands graph in this process (local demo, tests).
* :class:`AgentCoreOrchestrator` calls a deployed Amazon Bedrock AgentCore Runtime with
  ``invoke_agent_runtime`` (the AWS topology in ``docs/DESIGN.md`` §7).

``porchlight.graph`` is imported lazily inside the methods so this module — and therefore the
API — imports cleanly before the graph exists, and without ever touching AWS at import time.

Contract note: ``docs/CONTRACTS.md`` §7 places ``RunOutcome``/``SweepOutcome`` in
``porchlight.graph``. They are defined *here* so the API can depend on them without importing
the graph (and therefore Strands/Bedrock) at module import time; ``porchlight.graph`` should
import them from this module. Whatever the graph returns is coerced by
:func:`coerce_run_outcome`, so a structurally identical class defined elsewhere also works.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, is_dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .context import AppContext
from .models import Decision, RequestStatus

logger = logging.getLogger(__name__)

MIN_RUNTIME_SESSION_ID = 33
"""AgentCore's ``runtimeSessionId`` must be at least 33 characters (botocore ``SessionType``)."""

MAX_RUNTIME_SESSION_ID = 256


class GraphUnavailableError(RuntimeError):
    """Raised when ``porchlight.graph`` is not importable yet (parallel build, bad deploy)."""


# --------------------------------------------------------------------------------------
# Outcomes
# --------------------------------------------------------------------------------------


class RunOutcome(BaseModel):
    """What one end-to-end run of a request produced."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: RequestStatus = RequestStatus.NEW
    decisions_created: list[Decision] = Field(default_factory=list)
    log_events: int = 0
    interrupted: bool = False
    summary: str = ""

    @property
    def handled_quietly(self) -> bool:
        """True when the run finished without asking the coordinator anything."""
        return not self.interrupted and not self.decisions_created


class SweepOutcome(BaseModel):
    """What one sweep (due messages, stale outreach, timeouts) produced."""

    model_config = ConfigDict(extra="forbid")

    messages_sent: int = 0
    escalated: list[str] = Field(default_factory=list)
    timed_out: list[str] = Field(default_factory=list)
    summary: str = ""


def _as_mapping(value: Any) -> dict[str, Any]:
    """Best-effort conversion of an outcome-ish object into a plain dict."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"summary": value}
        return parsed if isinstance(parsed, dict) else {"summary": value}
    fields = ("request_id", "status", "decisions_created", "log_events", "interrupted", "summary")
    return {name: getattr(value, name) for name in fields if hasattr(value, name)}


def coerce_run_outcome(value: Any, request_id: str) -> RunOutcome:
    """Turn anything graph-shaped into a :class:`RunOutcome`.

    Args:
        value: A ``RunOutcome``, a dict, a dataclass, or any object with the same attributes.
        request_id: Fallback request id when ``value`` does not carry one.

    Returns:
        A validated :class:`RunOutcome`.
    """
    if isinstance(value, RunOutcome):
        return value
    data = _as_mapping(value)
    data.setdefault("request_id", request_id)
    data["decisions_created"] = [
        d if isinstance(d, Decision) else Decision.model_validate(d)
        for d in (data.get("decisions_created") or [])
    ]
    known = set(RunOutcome.model_fields)
    return RunOutcome.model_validate({k: v for k, v in data.items() if k in known})


def coerce_sweep_outcome(value: Any) -> SweepOutcome:
    """Turn anything sweep-shaped into a :class:`SweepOutcome`."""
    if isinstance(value, SweepOutcome):
        return value
    data = _as_mapping(value)
    known = set(SweepOutcome.model_fields)
    return SweepOutcome.model_validate({k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------------------------
# Protocol
# --------------------------------------------------------------------------------------


@runtime_checkable
class Orchestrator(Protocol):
    """Whatever actually runs the agents, seen from the API's side of the wall."""

    def process_request(self, request_id: str) -> RunOutcome:
        """Run one request end-to-end; may stop on a decision card."""
        ...

    def resume_decision(self, decision_id: str, option_id: str, note: str | None = None) -> RunOutcome:
        """Answer a decision card and resume the paused graph."""
        ...

    def sweep(self) -> SweepOutcome:
        """Send due messages, escalate stale outreach, time out silent volunteers."""
        ...

    def brief(self, day: date) -> str:
        """Return the coordinator's markdown digest for ``day``."""
        ...


# --------------------------------------------------------------------------------------
# Local (in-process Strands graph)
# --------------------------------------------------------------------------------------


def graph_module() -> Any:
    """Import and return :mod:`porchlight.graph`.

    Raises:
        GraphUnavailableError: When the graph module is not importable yet.
    """
    try:
        from . import graph
    except ImportError as exc:  # pragma: no cover - depends on build order
        raise GraphUnavailableError(
            "porchlight.graph is not available yet; run with a stubbed orchestrator or wait for "
            f"the graph build to land ({exc})"
        ) from exc
    return graph


def graph_available() -> bool:
    """True when the Strands graph can be imported (used by /api/health and the CLI)."""
    try:
        graph_module()
    except GraphUnavailableError:
        return False
    return True


class LocalOrchestrator:
    """Runs the Strands graph in this process against the shared :class:`AppContext`."""

    def __init__(self, ctx: AppContext) -> None:
        """Bind the orchestrator to one application context."""
        self.ctx = ctx

    def process_request(self, request_id: str) -> RunOutcome:
        """Run ``request_id`` through intake → matcher → outreach → steward."""
        result = graph_module().run_request(self.ctx, request_id)
        return coerce_run_outcome(result, request_id)

    def resume_decision(self, decision_id: str, option_id: str, note: str | None = None) -> RunOutcome:
        """Resume the graph paused on ``decision_id`` with the coordinator's choice."""
        result = graph_module().resume_decision(self.ctx, decision_id, option_id, note)
        decision = self.ctx.store.get_decision(decision_id)
        fallback = (decision.request_id if decision else None) or decision_id
        return coerce_run_outcome(result, fallback)

    def sweep(self) -> SweepOutcome:
        """Run one sweep pass."""
        return coerce_sweep_outcome(graph_module().run_sweep(self.ctx))

    def brief(self, day: date) -> str:
        """Render the daily brief for ``day`` as markdown."""
        return str(graph_module().run_brief(self.ctx, day))

    def __repr__(self) -> str:
        return f"LocalOrchestrator(mode={self.ctx.settings.mode})"


# --------------------------------------------------------------------------------------
# AgentCore Runtime
# --------------------------------------------------------------------------------------


_SESSION_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def runtime_session_id(raw: str, minimum: int = MIN_RUNTIME_SESSION_ID) -> str:
    """Turn an id into a valid, stable AgentCore ``runtimeSessionId``.

    The API keys a request's graph session on its ``request_id``, but AgentCore requires at
    least 33 characters. Short ids are extended with a deterministic digest so the same
    request always resumes the same runtime session.

    Args:
        raw: The logical session key (usually a ``req_...`` id).
        minimum: Minimum length AgentCore accepts.

    Returns:
        A sanitised session id of at least ``minimum`` characters.
    """
    if not raw:
        raise ValueError("session id must not be empty")
    cleaned = _SESSION_SAFE.sub("-", raw)
    if len(cleaned) >= minimum:
        return cleaned[:MAX_RUNTIME_SESSION_ID]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{cleaned}-{digest}"[:64]


def _iter_sse_payloads(text: str) -> list[Any]:
    """Extract the JSON payloads from a ``text/event-stream`` body."""
    payloads: list[Any] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        chunk = line[len("data:") :].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            payloads.append(json.loads(chunk))
        except json.JSONDecodeError:
            payloads.append(chunk)
    return payloads


def _chunk_bytes(chunk: Any) -> bytes:
    """Pull the bytes out of one event-stream chunk, whatever shape boto3 hands back."""
    if isinstance(chunk, bytes | bytearray):
        return bytes(chunk)
    if isinstance(chunk, str):
        return chunk.encode("utf-8")
    if isinstance(chunk, dict):
        for key in ("bytes", "chunk", "PayloadPart", "payload"):
            if key in chunk:
                return _chunk_bytes(chunk[key])
        return json.dumps(chunk).encode("utf-8")
    return bytes(chunk)


def parse_invoke_response(response: dict[str, Any]) -> Any:
    """Decode an ``invoke_agent_runtime`` response into Python data.

    Handles the three shapes botocore can produce: a ``StreamingBody`` holding one JSON
    document, an iterable of streamed chunks, and a ``text/event-stream`` body whose last
    ``data:`` frame carries the result.

    Args:
        response: The raw dict returned by ``invoke_agent_runtime``.

    Returns:
        The decoded payload (usually a dict), or ``None`` when the body was empty.
    """
    body = response.get("response")
    content_type = str(response.get("contentType") or "")
    raw: bytes
    if body is None:
        raw = b""
    elif hasattr(body, "read"):
        raw = body.read() or b""
    elif isinstance(body, bytes | bytearray | str):
        raw = _chunk_bytes(body)
    else:
        raw = b"".join(_chunk_bytes(chunk) for chunk in body)

    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if "event-stream" in content_type or text.startswith("data:"):
        payloads = _iter_sse_payloads(text)
        for payload in reversed(payloads):
            if isinstance(payload, dict) and payload.get("type") not in {"trace", "event"}:
                return payload
        return payloads[-1] if payloads else None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


class AgentCoreOrchestrator:
    """Calls a deployed AgentCore Runtime instead of running the graph locally."""

    def __init__(
        self,
        ctx: AppContext,
        arn: str,
        region: str | None = None,
        client: Any | None = None,
        qualifier: str | None = None,
    ) -> None:
        """Bind to one runtime ARN.

        Args:
            ctx: Application context (used for the store and for trace events).
            arn: ``agentRuntimeArn`` of the deployed runtime.
            region: AWS region; defaults to ``ctx.settings.aws_region``.
            client: Pre-built boto3 ``bedrock-agentcore`` client (tests inject a stub).
            qualifier: Optional runtime endpoint qualifier.
        """
        self.ctx = ctx
        self.arn = arn
        self.region = region or ctx.settings.aws_region
        self.qualifier = qualifier
        self._client = client

    @property
    def client(self) -> Any:
        """The boto3 ``bedrock-agentcore`` client, created on first use (never at import)."""
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-agentcore", region_name=self.region)
        return self._client

    def _invoke(self, payload: dict[str, Any], session_key: str) -> Any:
        """Send one payload to the runtime and return the decoded response."""
        kwargs: dict[str, Any] = {
            "agentRuntimeArn": self.arn,
            "runtimeSessionId": runtime_session_id(session_key),
            "contentType": "application/json",
            "accept": "application/json",
            "payload": json.dumps(payload).encode("utf-8"),
        }
        if self.qualifier:
            kwargs["qualifier"] = self.qualifier
        self.ctx.emit(
            {
                "type": "model_call",
                "agent": "runtime",
                "request_id": payload.get("request_id"),
                "summary": f"invoke_agent_runtime {payload['action']}",
                "detail": {"arn": self.arn, "action": payload["action"]},
            }
        )
        response = self.client.invoke_agent_runtime(**kwargs)
        return parse_invoke_response(response)

    def process_request(self, request_id: str) -> RunOutcome:
        """Ask the runtime to process ``request_id``."""
        payload = {"action": "process_request", "request_id": request_id}
        return coerce_run_outcome(self._invoke(payload, request_id), request_id)

    def resume_decision(self, decision_id: str, option_id: str, note: str | None = None) -> RunOutcome:
        """Ask the runtime to resume the graph paused on ``decision_id``.

        The runtime session must be the one the interrupt was raised in, so the session key is
        the decision's ``request_id`` when we know it.
        """
        decision = self.ctx.store.get_decision(decision_id)
        session_key = (decision.request_id if decision else None) or decision_id
        payload = {
            "action": "resume_decision",
            "decision_id": decision_id,
            "option_id": option_id,
            "note": note,
        }
        return coerce_run_outcome(self._invoke(payload, session_key), session_key)

    def sweep(self) -> SweepOutcome:
        """Ask the runtime to run a sweep."""
        day = self.ctx.now().date().isoformat()
        return coerce_sweep_outcome(self._invoke({"action": "sweep"}, f"sweep-{day}"))

    def brief(self, day: date) -> str:
        """Ask the runtime for the daily brief."""
        result = self._invoke({"action": "brief", "day": day.isoformat()}, f"brief-{day.isoformat()}")
        if isinstance(result, dict):
            for key in ("markdown", "brief", "summary", "text"):
                if isinstance(result.get(key), str):
                    return result[key]
            return json.dumps(result, indent=2)
        return "" if result is None else str(result)

    def __repr__(self) -> str:
        return f"AgentCoreOrchestrator(arn={self.arn!r}, region={self.region!r})"


def make_orchestrator(ctx: AppContext, settings: Any | None = None) -> Orchestrator:
    """Pick the orchestrator the settings ask for.

    An ``agent_runtime_arn`` means "the agents live on AgentCore Runtime"; otherwise the graph
    runs in this process.

    Args:
        ctx: The application context to bind.
        settings: Settings to read; defaults to ``ctx.settings``.

    Returns:
        A :class:`LocalOrchestrator` or :class:`AgentCoreOrchestrator`.
    """
    settings = settings or ctx.settings
    arn = getattr(settings, "agent_runtime_arn", None)
    if arn:
        logger.info("orchestrating through AgentCore Runtime %s", arn)
        return AgentCoreOrchestrator(ctx, arn=arn, region=settings.aws_region)
    return LocalOrchestrator(ctx)


__all__ = [
    "AgentCoreOrchestrator",
    "GraphUnavailableError",
    "LocalOrchestrator",
    "Orchestrator",
    "RunOutcome",
    "SweepOutcome",
    "coerce_run_outcome",
    "coerce_sweep_outcome",
    "graph_available",
    "graph_module",
    "make_orchestrator",
    "parse_invoke_response",
    "runtime_session_id",
]

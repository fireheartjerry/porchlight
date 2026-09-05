"""AgentCore Runtime entrypoint.

Runs the same graph the local demo runs, behind ``POST /invocations``::

    {"action": "process_request", "request_id": "req_...", "image_base64": "..."}
    {"action": "resume_decision", "decision_id": "dec_...", "option_id": "approve", "note": "..."}
    {"action": "sweep"}
    {"action": "brief", "day": "2026-09-08"}

Add ``"stream": true`` to any of them to get the trace events as server-sent events while the
graph is still running — that is what the Trace drawer in the web UI reads.

The entrypoint also takes AgentCore's ``context``. Its ``session_id`` is what the API put in
``invoke_agent_runtime(runtimeSessionId=...)`` — for a request that is
``porchlight.orchestrator.runtime_session_id(request_id)`` — so it comes back in every
response, is logged with every invocation, and stands in for ``request_id`` when a caller
sends ``{"action": "process_request"}`` with nothing else.

Locally: ``python -m porchlight.runtime`` (port 8080), or ``python runtime/main.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from .config import Settings, get_settings
from .context import AppContext, build_context
from .graph import resume_decision, run_brief, run_request, run_sweep
from .models import jsonable
from .telemetry import setup_telemetry

logger = logging.getLogger(__name__)

ACTIONS = ("process_request", "resume_decision", "sweep", "brief")
POLL_INTERVAL = 0.05
"""How often the streaming loop checks for new trace events, in seconds."""

REQUEST_ID_PREFIX = "req_"
"""Session ids that start with this carry a request id in their first segment."""

app = BedrockAgentCoreApp()

__all__ = [
    "ACTIONS",
    "app",
    "dispatch",
    "main",
    "porchlight_entrypoint",
    "request_id_from_session",
    "runtime_settings",
    "session_id_of",
    "unwrap_prompt",
]


def runtime_settings() -> Settings:
    """Settings for a runtime process: live wiring unless the environment says otherwise."""
    os.environ.setdefault("PORCHLIGHT_MODE", "live")
    return get_settings()


def _context(emit: Any = None) -> AppContext:
    """Build the application context for one invocation."""
    settings = runtime_settings()
    setup_telemetry(settings)
    return build_context(settings, **({"emit": emit} if emit is not None else {}))


def session_id_of(context: Any) -> str | None:
    """The AgentCore session id for this invocation, if there is one.

    Args:
        context: AgentCore's ``RequestContext`` (or anything, or ``None`` — running the
            entrypoint by hand in a test passes no context at all).

    Returns:
        The non-empty ``session_id``, or ``None``.
    """
    session_id = getattr(context, "session_id", None)
    return session_id if isinstance(session_id, str) and session_id else None


def request_id_from_session(session_id: str | None) -> str | None:
    """Recover the request id the API encoded into an AgentCore session id.

    ``porchlight.orchestrator.runtime_session_id`` pads a short id to AgentCore's 33-character
    minimum by appending ``-<sha256>``. Request ids are ``req_<hex>`` and carry no dash, so the
    first segment is the id. Session keys for the other actions (``sweep-...``, ``brief-...``)
    do not start with ``req_`` and are left alone.

    Args:
        session_id: The runtime session id, or ``None``.

    Returns:
        The request id, or ``None`` when the session id does not encode one.
    """
    if not session_id or not session_id.startswith(REQUEST_ID_PREFIX):
        return None
    request_id = session_id.split("-", 1)[0]
    return request_id if len(request_id) > len(REQUEST_ID_PREFIX) else None


def _parse_day(value: Any) -> date | None:
    """Parse a ``YYYY-MM-DD`` payload field, tolerating junk."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        logger.warning("ignoring unparseable day %r", value)
        return None


def unwrap_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the real payload, unwrapping the ``prompt`` envelope the AgentCore CLI adds.

    ``agentcore invoke '{"action": "sweep"}'`` sends ``{"prompt": "{\"action\": \"sweep\"}"}``
    — the CLI treats its positional argument as a chat prompt, so a payload typed at the command
    line arrives as a JSON string nested inside one field. Everything else (the API's own boto3
    call, the sweep Lambda, a local ``curl``) posts the payload directly and is untouched here.

    Args:
        payload: The decoded body of ``POST /invocations``.

    Returns:
        The inner object when ``prompt`` carries one, otherwise ``payload`` unchanged.
    """
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip().startswith("{"):
        return payload
    try:
        inner = json.loads(prompt)
    except json.JSONDecodeError:
        return payload
    if not isinstance(inner, dict):
        return payload
    return {**{k: v for k, v in payload.items() if k != "prompt"}, **inner}


def dispatch(ctx: AppContext, payload: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
    """Run one payload against the graph and return a JSON-safe result.

    Args:
        ctx: Application context (store, channel, memory, clock, trace sink).
        payload: The invocation payload; ``action`` selects what to do.
        session_id: AgentCore's session id for this invocation. Echoed back on every result,
            and used as the request id when ``process_request`` arrives without one.

    Returns:
        ``{"action": ..., "ok": bool, "session_id": ..., ...}``. Unknown actions and missing
        arguments come back as ``ok=False`` with a message rather than raising, so the caller
        always gets JSON.
    """
    payload = unwrap_prompt(payload)
    action = str(payload.get("action") or "process_request")
    result: dict[str, Any] = {"action": action, "session_id": session_id}

    if action == "process_request":
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            request_id = request_id_from_session(session_id)
        if not request_id:
            return {**result, "ok": False, "error": "request_id is required"}
        outcome = run_request(ctx, request_id, image_base64=payload.get("image_base64"))
        return {**result, "ok": True, "outcome": jsonable(outcome)}

    if action == "resume_decision":
        decision_id = payload.get("decision_id")
        option_id = payload.get("option_id")
        if not isinstance(decision_id, str) or not isinstance(option_id, str):
            return {**result, "ok": False, "error": "decision_id and option_id are required"}
        outcome = resume_decision(ctx, decision_id, option_id, payload.get("note"))
        return {**result, "ok": True, "outcome": jsonable(outcome)}

    if action == "sweep":
        return {**result, "ok": True, "outcome": jsonable(run_sweep(ctx))}

    if action == "brief":
        markdown = run_brief(ctx, _parse_day(payload.get("day")))
        return {**result, "ok": True, "markdown": markdown}

    return {**result, "ok": False, "error": f"unknown action; expected one of {list(ACTIONS)}"}


async def _stream(payload: dict[str, Any], session_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
    """Run the payload on a worker thread, yielding trace events as they are emitted."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def emit(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    ctx = _context(emit=emit)
    work = asyncio.create_task(asyncio.to_thread(dispatch, ctx, payload, session_id))
    try:
        while not work.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=POLL_INTERVAL)
            except TimeoutError:
                continue
    finally:
        if not work.done():  # pragma: no cover - only on client disconnect
            work.cancel()
    try:
        yield {"type": "result", "detail": work.result()}
    except Exception as error:  # pragma: no cover - surfaced to the SSE client
        logger.exception("streaming invocation failed")
        yield {"type": "error", "detail": {"error": str(error)}}


@app.entrypoint
def porchlight_entrypoint(payload: dict[str, Any] | None = None, context: Any = None) -> Any:
    """AgentCore entrypoint: a dict for a normal call, an SSE stream when ``stream`` is set.

    Args:
        payload: The decoded JSON body of ``POST /invocations``.
        context: AgentCore's ``RequestContext``. The parameter has to be named ``context``
            — that is how ``BedrockAgentCoreApp`` decides whether to pass one.
    """
    payload = payload or {}
    session_id = session_id_of(context)
    logger.info("invocation action=%r session=%r", payload.get("action"), session_id)
    if payload.get("stream"):
        return _stream(payload, session_id)
    return dispatch(_context(), payload, session_id)


def main() -> None:
    """Serve the runtime locally on port 8080."""
    logging.basicConfig(level=logging.INFO)
    app.run(port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":  # pragma: no cover - manual entry point
    main()

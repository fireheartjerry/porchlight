"""AgentCore Runtime entrypoint.

Runs the same graph the local demo runs, behind ``POST /invocations``::

    {"action": "process_request", "request_id": "req_...", "image_base64": "..."}
    {"action": "resume_decision", "decision_id": "dec_...", "option_id": "approve", "note": "..."}
    {"action": "sweep"}
    {"action": "brief", "day": "2026-09-08"}

Add ``"stream": true`` to any of them to get the trace events as server-sent events while the
graph is still running — that is what the Trace drawer in the web UI reads.

Locally: ``python -m porchlight.runtime`` (port 8080).
"""

from __future__ import annotations

import asyncio
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

app = BedrockAgentCoreApp()

__all__ = ["ACTIONS", "app", "dispatch", "main", "porchlight_entrypoint", "runtime_settings"]


def runtime_settings() -> Settings:
    """Settings for a runtime process: live wiring unless the environment says otherwise."""
    os.environ.setdefault("PORCHLIGHT_MODE", "live")
    return get_settings()


def _context(emit: Any = None) -> AppContext:
    """Build the application context for one invocation."""
    settings = runtime_settings()
    setup_telemetry(settings)
    return build_context(settings, **({"emit": emit} if emit is not None else {}))


def _parse_day(value: Any) -> date | None:
    """Parse a ``YYYY-MM-DD`` payload field, tolerating junk."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        logger.warning("ignoring unparseable day %r", value)
        return None


def dispatch(ctx: AppContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one payload against the graph and return a JSON-safe result.

    Args:
        ctx: Application context (store, channel, memory, clock, trace sink).
        payload: The invocation payload; ``action`` selects what to do.

    Returns:
        ``{"action": ..., "ok": bool, ...}``. Unknown actions and missing arguments come back
        as ``ok=False`` with a message rather than raising, so the caller always gets JSON.
    """
    action = str(payload.get("action") or "process_request")

    if action == "process_request":
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return {"action": action, "ok": False, "error": "request_id is required"}
        outcome = run_request(ctx, request_id, image_base64=payload.get("image_base64"))
        return {"action": action, "ok": True, "outcome": jsonable(outcome)}

    if action == "resume_decision":
        decision_id = payload.get("decision_id")
        option_id = payload.get("option_id")
        if not isinstance(decision_id, str) or not isinstance(option_id, str):
            return {"action": action, "ok": False, "error": "decision_id and option_id are required"}
        outcome = resume_decision(ctx, decision_id, option_id, payload.get("note"))
        return {"action": action, "ok": True, "outcome": jsonable(outcome)}

    if action == "sweep":
        return {"action": action, "ok": True, "outcome": jsonable(run_sweep(ctx))}

    if action == "brief":
        markdown = run_brief(ctx, _parse_day(payload.get("day")))
        return {"action": action, "ok": True, "markdown": markdown}

    return {"action": action, "ok": False, "error": f"unknown action; expected one of {list(ACTIONS)}"}


async def _stream(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Run the payload on a worker thread, yielding trace events as they are emitted."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def emit(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    ctx = _context(emit=emit)
    work = asyncio.create_task(asyncio.to_thread(dispatch, ctx, payload))
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
def porchlight_entrypoint(payload: dict[str, Any] | None = None) -> Any:
    """AgentCore entrypoint: a dict for a normal call, an SSE stream when ``stream`` is set."""
    payload = payload or {}
    if payload.get("stream"):
        return _stream(payload)
    return dispatch(_context(), payload)


def main() -> None:
    """Serve the runtime locally on port 8080."""
    logging.basicConfig(level=logging.INFO)
    app.run(port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":  # pragma: no cover - manual entry point
    main()

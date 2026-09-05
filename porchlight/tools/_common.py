"""Shared plumbing for the tool implementations: logging, tracing, and time parsing.

Every tool in this package is a thin ``@tool(context=True)`` wrapper around a plain function
that takes an :class:`~porchlight.context.AppContext` first. The plain functions are what the
MCP server (``porchlight.mcp_server``) exposes, so the two surfaces can never drift.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from dateutil import parser as date_parser

from ..context import AppContext
from ..models import LogEvent, LogKind, jsonable

WEEK = timedelta(days=7)

_TRACE_TYPE: dict[LogKind, str] = {
    LogKind.MESSAGE_SENT: "message",
    LogKind.DECISION: "decision",
    LogKind.POLICY: "policy",
    LogKind.MODEL: "model_call",
    LogKind.MEMORY: "log",
    LogKind.TOOL_CALL: "tool_call",
}


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string, returning ``None`` for empty or unparseable input."""
    if not value:
        return None
    try:
        return date_parser.isoparse(value)
    except (ValueError, TypeError, OverflowError):
        return None


def agent_name(value: Any) -> str | None:
    """Normalize ``invocation_state["agent"]`` (an ``Agent``, a name, or nothing) to a name."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    name = getattr(value, "name", None)
    return name if isinstance(name, str) and name else None


def record(
    ctx: AppContext,
    kind: LogKind,
    summary: str,
    *,
    request_id: str | None = None,
    detail: dict[str, Any] | None = None,
    agent: str | None = None,
    autonomous: bool = True,
    visible: bool = True,
) -> LogEvent:
    """Append one quiet-log line and mirror it to the live trace stream.

    Args:
        ctx: The app context.
        kind: What sort of event this is.
        summary: One plain-English sentence the coordinator can skim.
        request_id: The request this happened for, when there is one.
        detail: Structured payload for the expandable row in the UI.
        agent: Which agent did it (from ``invocation_state["agent"]``).
        autonomous: False when a human asked for it.
        visible: False for bookkeeping the coordinator should not have to read.

    Returns:
        The persisted :class:`~porchlight.models.LogEvent`.
    """
    event = LogEvent(
        ts=ctx.clock.now(),
        request_id=request_id,
        agent=agent,
        kind=kind,
        summary=summary,
        detail=jsonable(detail or {}),
        autonomous=autonomous,
        visible=visible,
    )
    ctx.store.append_log(event)
    ctx.emit(
        {
            "type": _TRACE_TYPE.get(kind, "log"),
            "ts": event.ts.isoformat(),
            "request_id": event.request_id,
            "agent": event.agent,
            "summary": event.summary,
            "detail": event.detail,
        }
    )
    return event


def trace(
    ctx: AppContext,
    event_type: str,
    summary: str,
    *,
    request_id: str | None = None,
    agent: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Emit a trace event without writing to the quiet log (used by read-only tools)."""
    ctx.emit(
        {
            "type": event_type,
            "ts": ctx.clock.now().isoformat(),
            "request_id": request_id,
            "agent": agent,
            "summary": summary,
            "detail": jsonable(detail or {}),
        }
    )


def week_start(ctx: AppContext) -> datetime:
    """Start of the rolling seven-day window used for load and fairness."""
    return ctx.clock.now() - WEEK


def load_for(ctx: AppContext, volunteer_id: str) -> int:
    """How many requests this volunteer was asked about or assigned in the last seven days."""
    return len(ctx.store.requests_for_volunteer(volunteer_id, week_start(ctx)))


def error(message: str) -> dict[str, str]:
    """A tool-level error the model can read and recover from."""
    return {"error": message}

"""The scheduled half of Porchlight: the hourly sweep and the nightly brief.

EventBridge Scheduler invokes this Lambda with a tiny event::

    {"action": "sweep"}                   # every hour
    {"action": "brief", "day": "2026-09-04"}   # 06:00 UTC, day optional

Both actions go through the same :class:`~porchlight.orchestrator.Orchestrator` the API uses, so
whether the agents run in-process or on AgentCore Runtime is decided by ``PORCHLIGHT_AGENT_RUNTIME_ARN``
and nothing here changes. The context is built on the first invocation and cached for the life of
the execution environment; nothing touches AWS at import time.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from porchlight.context import AppContext, build_context
from porchlight.orchestrator import Orchestrator, make_orchestrator

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SWEEP = "sweep"
BRIEF = "brief"
ACTIONS = (SWEEP, BRIEF)

_STATE: dict[str, Any] = {"ctx": None, "orchestrator": None}


class UnknownActionError(ValueError):
    """Raised when the schedule hands us an action this Lambda does not implement."""


def get_orchestrator() -> tuple[AppContext, Orchestrator]:
    """Build (once per execution environment) the context and orchestrator."""
    if _STATE["orchestrator"] is None:
        ctx = build_context()
        _STATE["ctx"] = ctx
        _STATE["orchestrator"] = make_orchestrator(ctx)
        logger.info("porchlight scheduled worker ready (%s, %s)", ctx.settings.mode, _STATE["orchestrator"])
    return _STATE["ctx"], _STATE["orchestrator"]


def reset_cache() -> None:
    """Drop the cached context (tests, and any handler that wants a clean build)."""
    _STATE["ctx"] = None
    _STATE["orchestrator"] = None


def parse_action(event: Any) -> str:
    """Read the action out of a scheduler event, defaulting to the hourly sweep.

    Args:
        event: The raw Lambda event. A plain string is accepted too, so a manual
            ``aws lambda invoke --payload '"brief"'`` works.

    Returns:
        Either ``"sweep"`` or ``"brief"``.

    Raises:
        UnknownActionError: When the event names something else.
    """
    if isinstance(event, str):
        raw = event
    elif isinstance(event, dict):
        raw = str(event.get("action") or event.get("detail-type") or SWEEP)
    else:
        raw = SWEEP
    action = raw.strip().lower()
    if action not in ACTIONS:
        raise UnknownActionError(f"action must be one of {ACTIONS}, got {raw!r}")
    return action


def parse_day(event: Any, ctx: AppContext) -> date:
    """Read an optional ``YYYY-MM-DD`` day out of the event, defaulting to today."""
    raw = event.get("day") if isinstance(event, dict) else None
    if not raw:
        return ctx.now().date()
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise ValueError(f"day must be YYYY-MM-DD, got {raw!r}") from exc


def do_sweep() -> dict[str, Any]:
    """Send due messages, escalate stale outreach, time out silent volunteers."""
    _, orchestrator = get_orchestrator()
    outcome = orchestrator.sweep()
    return {
        "action": SWEEP,
        "messages_sent": outcome.messages_sent,
        "escalated": list(outcome.escalated),
        "timed_out": list(outcome.timed_out),
        "summary": outcome.summary,
    }


def do_brief(day: date) -> dict[str, Any]:
    """Render the coordinator's digest for ``day`` and log it."""
    _, orchestrator = get_orchestrator()
    markdown = str(orchestrator.brief(day))
    return {
        "action": BRIEF,
        "day": day.isoformat(),
        "characters": len(markdown),
        "markdown": markdown,
    }


def handler(event: dict[str, Any] | str | None, context: Any = None) -> dict[str, Any]:
    """Lambda entry point for the scheduled sweep and brief.

    Args:
        event: ``{"action": "sweep"}`` or ``{"action": "brief", "day": "YYYY-MM-DD"}``.
        context: The Lambda context object (unused).

    Returns:
        A JSON-serialisable summary of what ran; also written to the log.

    Raises:
        Exception: Anything the orchestrator raises, so the schedule's retry policy sees it.
    """
    payload = event if event is not None else {}
    action = parse_action(payload)
    started = datetime.now(UTC)
    ctx, _ = get_orchestrator()
    try:
        result = do_sweep() if action == SWEEP else do_brief(parse_day(payload, ctx))
    except Exception:
        logger.exception("scheduled %s failed", action)
        raise
    result["ok"] = True
    result["seconds"] = round((datetime.now(UTC) - started).total_seconds(), 3)
    logger.info("scheduled %s: %s", action, json.dumps({k: v for k, v in result.items() if k != "markdown"}))
    return result


__all__ = [
    "ACTIONS",
    "BRIEF",
    "SWEEP",
    "UnknownActionError",
    "do_brief",
    "do_sweep",
    "get_orchestrator",
    "handler",
    "parse_action",
    "parse_day",
    "reset_cache",
]

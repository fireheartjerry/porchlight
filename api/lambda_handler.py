"""AWS Lambda entry point: the same FastAPI app behind a Function URL — the *buffered* one.

The deployed path (``infra/``) is different and better: the AWS Lambda Web Adapter layer runs a
real uvicorn process from ``run.sh`` and streams the Function URL response, which is what makes
``/api/events`` (SSE) arrive as it happens rather than all at once at the end.

This module is the alternative: point the function's handler at ``api.lambda_handler.handler``,
drop the layer and the ``AWS_LWA_*`` variables, and the same app runs through Mangum. Useful when
debugging the adapter, and as a fallback if the layer is unavailable in a region. Two caveats:
responses are buffered (no streaming, so an SSE client sees nothing until the stream ends), and
the ASGI lifespan never runs (``lifespan="off"``) — so the store-backed trace tailer that
``events_source="store"`` relies on never starts either.

Because there is no lifespan, the context and the orchestrator are built on the first request and
cached for the life of the execution environment. Nothing here touches AWS at import time, which
keeps cold starts honest and lets the module be imported in tests.
"""

from __future__ import annotations

import logging
from typing import Any

from mangum import Mangum

from porchlight.context import build_context
from porchlight.orchestrator import make_orchestrator

from .main import attach_bus, create_app, seed_if_empty

logger = logging.getLogger()
logger.setLevel(logging.INFO)

app = create_app()
"""The ASGI app. Its lifespan never runs under Mangum, so :func:`_ensure_ready` wires it."""

handler_asgi = Mangum(app, lifespan="off")
"""Mangum adapter. Call :func:`handler` instead so the app is initialised first."""


def _ensure_ready() -> None:
    """Build the context and orchestrator once per execution environment."""
    if app.state.ctx is not None:
        return
    ctx = build_context()
    attach_bus(ctx, app.state.bus)
    seed_if_empty(ctx)
    app.state.ctx = ctx
    app.state.orchestrator = make_orchestrator(ctx)
    logger.info("porchlight lambda ready (%s)", ctx.settings.mode)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for API Gateway / Function URL events.

    Args:
        event: The invocation event.
        context: The Lambda context object.

    Returns:
        The HTTP response Mangum produced.
    """
    _ensure_ready()
    return handler_asgi(event, context)


__all__ = ["app", "handler"]

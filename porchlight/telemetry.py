"""OpenTelemetry wiring, off by default.

Porchlight only turns tracing on when the environment says where to send it, so tests, the
local demo, and anyone without AWS credentials never pay for an exporter that has nowhere to
go. On AgentCore Runtime the ADOT sidecar sets ``OTEL_EXPORTER_OTLP_ENDPOINT`` and
``AGENT_OBSERVABILITY_ENABLED`` for us, and traces land in CloudWatch.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .config import Settings

logger = logging.getLogger(__name__)

OTLP_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
OBSERVABILITY_ENV = "AGENT_OBSERVABILITY_ENABLED"
CONSOLE_ENV = "PORCHLIGHT_TRACE_CONSOLE"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

__all__ = ["console_enabled", "otlp_enabled", "setup_telemetry"]


def _flag(name: str) -> bool:
    """True when an environment variable is set to something affirmative."""
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def otlp_enabled() -> bool:
    """True when an OTLP collector endpoint is configured, or AgentCore turned tracing on."""
    return bool(os.environ.get(OTLP_ENV, "").strip()) or _flag(OBSERVABILITY_ENV)


def console_enabled() -> bool:
    """True when ``PORCHLIGHT_TRACE_CONSOLE=1`` asks for spans on stdout."""
    return _flag(CONSOLE_ENV)


def setup_telemetry(settings: Settings) -> Any | None:
    """Configure Strands telemetry if — and only if — the environment asks for it.

    Args:
        settings: Used to tag spans with the group and deployment mode.

    Returns:
        The configured ``StrandsTelemetry``, or ``None`` when tracing stays off.
    """
    if not (otlp_enabled() or console_enabled()):
        logger.debug("telemetry disabled: no %s and no %s", OTLP_ENV, CONSOLE_ENV)
        return None

    os.environ.setdefault(
        "OTEL_RESOURCE_ATTRIBUTES",
        f"service.name=porchlight,deployment.environment={settings.mode}",
    )
    try:
        from strands.telemetry import StrandsTelemetry
    except ImportError:  # pragma: no cover - telemetry extra not installed
        logger.warning("strands telemetry is unavailable; continuing without tracing")
        return None

    telemetry = StrandsTelemetry()
    if otlp_enabled():
        telemetry.setup_otlp_exporter()
        logger.info("telemetry: OTLP exporter → %s", os.environ.get(OTLP_ENV, "(agentcore default)"))
    if console_enabled():
        telemetry.setup_console_exporter()
        logger.info("telemetry: console exporter enabled")
    return telemetry

"""OpenTelemetry wiring, off by default.

Porchlight only turns tracing on when the environment says where to send it, so tests, the
local demo, and anyone without AWS credentials never pay for an exporter that has nowhere to
go. On AgentCore Runtime the ADOT sidecar sets ``OTEL_EXPORTER_OTLP_ENDPOINT`` and
``AGENT_OBSERVABILITY_ENABLED`` for us, and traces land in CloudWatch.

Two things make this safe to call on every invocation:

* it is **idempotent** — a second call returns the telemetry the first call configured, so a
  long-lived runtime process does not stack a new ``BatchSpanProcessor`` per request;
* it **defers to ADOT** — AgentCore starts the entrypoint as ``opentelemetry-instrument
  main.py``, which has already installed an SDK tracer provider wired to the collector. When
  that provider is there we hand it to :class:`StrandsTelemetry` instead of replacing the
  global one, and we do not add a second OTLP exporter that would double every span.
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

_telemetry: Any | None = None
"""The one :class:`StrandsTelemetry` this process configured, if any."""

__all__ = [
    "console_enabled",
    "installed_tracer_provider",
    "otlp_enabled",
    "reset_telemetry",
    "setup_telemetry",
]


def _flag(name: str) -> bool:
    """True when an environment variable is set to something affirmative."""
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def otlp_enabled() -> bool:
    """True when an OTLP collector endpoint is configured, or AgentCore turned tracing on."""
    return bool(os.environ.get(OTLP_ENV, "").strip()) or _flag(OBSERVABILITY_ENV)


def console_enabled() -> bool:
    """True when ``PORCHLIGHT_TRACE_CONSOLE=1`` asks for spans on stdout."""
    return _flag(CONSOLE_ENV)


def installed_tracer_provider() -> Any | None:
    """The SDK tracer provider something else already installed, or ``None``.

    Under ``opentelemetry-instrument`` (how AgentCore Runtime starts us) the ADOT distro has
    already created a real ``TracerProvider`` and set it globally. Before that happens the
    global is a proxy/no-op provider, which is not something to attach exporters to.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:  # pragma: no cover - opentelemetry not installed
        return None
    provider = trace.get_tracer_provider()
    return provider if isinstance(provider, TracerProvider) else None


def reset_telemetry() -> None:
    """Forget the configured telemetry so the next call reconfigures (tests only)."""
    global _telemetry
    _telemetry = None


def setup_telemetry(settings: Settings) -> Any | None:
    """Configure Strands telemetry if — and only if — the environment asks for it.

    Safe to call once per invocation: the first call that finds tracing switched on does the
    wiring and every later call returns the same object.

    Args:
        settings: Used to tag spans with the group and deployment mode.

    Returns:
        The configured ``StrandsTelemetry``, or ``None`` when tracing stays off.
    """
    if not (otlp_enabled() or console_enabled()):
        logger.debug("telemetry disabled: no %s and no %s", OTLP_ENV, CONSOLE_ENV)
        return None
    global _telemetry
    if _telemetry is not None:
        return _telemetry

    os.environ.setdefault(
        "OTEL_RESOURCE_ATTRIBUTES",
        f"service.name=porchlight,deployment.environment={settings.mode}",
    )
    os.environ.setdefault("OTEL_SERVICE_NAME", "porchlight")
    try:
        from strands.telemetry import StrandsTelemetry
    except ImportError:  # pragma: no cover - telemetry extra not installed
        logger.warning("strands telemetry is unavailable; continuing without tracing")
        return None

    provider = installed_tracer_provider()
    telemetry = StrandsTelemetry(tracer_provider=provider) if provider else StrandsTelemetry()
    if provider is not None:
        logger.info("telemetry: reusing the tracer provider opentelemetry-instrument installed")
    elif otlp_enabled():
        telemetry.setup_otlp_exporter()
        logger.info("telemetry: OTLP exporter \u2192 %s", os.environ.get(OTLP_ENV, "(agentcore default)"))
    if console_enabled():
        telemetry.setup_console_exporter()
        logger.info("telemetry: console exporter enabled")
    _telemetry = telemetry
    return telemetry

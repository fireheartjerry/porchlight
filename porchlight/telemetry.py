"""OpenTelemetry wiring, off by default.

Porchlight only turns tracing on when the environment says where to send it, so tests, the
local demo, and anyone without AWS credentials never pay for an exporter that has nowhere to
go. On AgentCore Runtime the ADOT sidecar sets ``OTEL_EXPORTER_OTLP_ENDPOINT`` and
``AGENT_OBSERVABILITY_ENABLED`` for us, and traces land in CloudWatch GenAI Observability
(see ``docs/DEPLOY.md`` § Traces).

Three things make this safe to call on every invocation:

* it is **idempotent** — a second call returns the telemetry the first call configured, so a
  long-lived runtime process does not stack a new ``BatchSpanProcessor`` per request;
* it **defers to ADOT** — AgentCore starts the entrypoint as ``opentelemetry-instrument
  main.py``, which has already installed an SDK tracer provider wired to the collector. When
  that provider is there we hand it to :class:`StrandsTelemetry` instead of replacing the
  global one;
* it **never adds a second exporter under ADOT** — even if the distro's provider is not visible
  to us (a proxy provider, a distro that installs late, a provider class we do not recognise),
  the ADOT environment alone is enough to stop us configuring OTLP. Two processors posting the
  same spans, one of them to an endpoint rebuilt by hand, is the usual reading of ``Failed to
  export span batch code: 400`` in a runtime log; on our own stack that message turned out to
  come from the distro's exporter while CloudWatch Transaction Search was still switching on
  (``docs/DEPLOY.md`` § Traces has the diagnosis ladder).

Strands does not need our exporter to be traced: ``strands.telemetry.Tracer`` reads
``trace.get_tracer_provider()``, so once ADOT owns the global provider every agent, node, and
tool span flows through it.
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

ADOT_ENV: tuple[str, ...] = ("OTEL_PYTHON_DISTRO", "OTEL_PYTHON_CONFIGURATOR", "OTEL_TRACES_EXPORTER")
"""Environment variables that mean ``opentelemetry-instrument``/ADOT owns the export pipeline.

``agentcore/agentcore.json`` sets ``OTEL_PYTHON_DISTRO=aws_distro`` and
``OTEL_PYTHON_CONFIGURATOR=aws_configurator`` in the runtime's ``envVars``, alongside
``AGENT_OBSERVABILITY_ENABLED``; an operator-configured distro sets ``OTEL_TRACES_EXPORTER``.
Any one of them, or a real tracer provider already installed, means we must not add an
exporter of our own.
"""

AUTO_INSTRUMENTATION_MARKER = "opentelemetry/instrumentation/auto_instrumentation"
"""``opentelemetry-instrument`` puts its ``sitecustomize`` directory first on ``PYTHONPATH``."""

_TRUTHY = frozenset({"1", "true", "yes", "on"})

_telemetry: Any | None = None
"""The one :class:`StrandsTelemetry` this process configured, if any."""

__all__ = [
    "adot_instrumented",
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


def adot_instrumented() -> bool:
    """True when this process is already being traced by ADOT / ``opentelemetry-instrument``.

    Three independent signals, because the one that matters most — an installed provider — is
    the one we cannot rely on seeing:

    1. ``AGENT_OBSERVABILITY_ENABLED``: AgentCore Runtime's own switch;
    2. an ADOT/auto-instrumentation environment variable, or its ``sitecustomize`` directory on
       ``PYTHONPATH`` (which is exactly how ``opentelemetry-instrument`` bootstraps the child);
    3. a tracer provider that already exists and already has span processors on it.

    Any one of them means the export pipeline belongs to someone else, and adding an OTLP
    exporter of our own would post every span twice — a common cause of rejected span batches.
    """
    if _flag(OBSERVABILITY_ENV):
        return True
    if any(os.environ.get(name, "").strip() for name in ADOT_ENV):
        return True
    if AUTO_INSTRUMENTATION_MARKER in os.environ.get("PYTHONPATH", "").replace("\\", "/"):
        return True
    provider = installed_tracer_provider()
    processors = getattr(getattr(provider, "_active_span_processor", None), "_span_processors", ())
    return bool(processors)


def reset_telemetry() -> None:
    """Forget the configured telemetry so the next call reconfigures (tests only)."""
    global _telemetry
    _telemetry = None


def setup_telemetry(settings: Settings) -> Any | None:
    """Configure Strands telemetry if — and only if — the environment asks for it.

    Safe to call once per invocation: the first call that finds tracing switched on does the
    wiring and every later call returns the same object.

    Under ADOT this configures **no exporter at all**. It attaches :class:`StrandsTelemetry` to
    the provider ``opentelemetry-instrument`` installed when that provider is visible, so Strands
    agent/node/tool spans join the trace the distro is already exporting; when it is not visible
    it does nothing rather than installing a second pipeline over the top of ADOT's.

    Args:
        settings: Used to tag spans with the group and deployment mode.

    Returns:
        The configured ``StrandsTelemetry``, ``None`` when tracing stays off, and ``None`` under
        ADOT when the distro's provider is not ours to attach to.
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

    adot = adot_instrumented()
    provider = installed_tracer_provider()
    if adot and provider is None:
        # ADOT owns the pipeline but its provider is not an SDK provider we can attach to.
        # Building our own would set itself as the global and shadow the distro's exporter.
        logger.info("telemetry: ADOT is instrumenting this process; leaving the pipeline alone")
        return None

    telemetry = StrandsTelemetry(tracer_provider=provider) if provider else StrandsTelemetry()
    if adot:
        logger.info("telemetry: reusing the tracer provider opentelemetry-instrument installed")
    elif otlp_enabled():
        try:
            telemetry.setup_otlp_exporter()
        except Exception:  # pragma: no cover - the exporter extra is not installed locally
            # `strands` imports the OTLP exporter inside the method; without the
            # `opentelemetry-exporter-otlp-proto-http` wheel that import raises, and a missing
            # exporter must never stop the runtime from serving requests.
            logger.warning("telemetry: no OTLP exporter available; continuing without tracing")
        else:
            logger.info("telemetry: OTLP exporter \u2192 %s", os.environ.get(OTLP_ENV, "(agentcore default)"))
    if console_enabled():
        telemetry.setup_console_exporter()
        logger.info("telemetry: console exporter enabled")
    _telemetry = telemetry
    return telemetry

"""One exporter, not two, when ADOT is already instrumenting us (``docs/LIVE-FIXES.md`` F).

AgentCore Runtime starts the entrypoint as ``opentelemetry-instrument main.py``: the AWS distro
installs a tracer provider wired to the collector before a line of Porchlight runs. Adding our
own OTLP exporter on top of that posted every span twice and filled the runtime log with
``Failed to export span batch code: 400, reason: Bad Request``.

These tests simulate that environment — the env vars from ``agentcore/agentcore.json``, a
provider that already owns a span processor — and assert that ``setup_telemetry`` adds nothing
to it, keeps the global provider ADOT installed, and still hands the provider to
``StrandsTelemetry`` so agent, node, and tool spans join the same trace.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from porchlight.config import Settings
from porchlight.telemetry import (
    ADOT_ENV,
    adot_instrumented,
    console_enabled,
    installed_tracer_provider,
    otlp_enabled,
    reset_telemetry,
    setup_telemetry,
)

TELEMETRY_ENV = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "AGENT_OBSERVABILITY_ENABLED",
    "PORCHLIGHT_TRACE_CONSOLE",
    "PYTHONPATH",
    *ADOT_ENV,
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A process with no telemetry environment, no cached telemetry, and no global provider.

    The global tracer provider can only be set once per process, so an earlier test that
    configured one would otherwise leak into these; each test starts from the proxy provider a
    fresh interpreter has.
    """
    for name in TELEMETRY_ENV:
        monkeypatch.delenv(name, raising=False)
    proxy = trace.ProxyTracerProvider()
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: proxy)
    reset_telemetry()
    yield
    reset_telemetry()


@pytest.fixture
def settings() -> Settings:
    return Settings(mode="live", model_provider="mock", store="sqlite", sqlite_path=":memory:")


def agentcore_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly what ``agentcore/agentcore.json`` puts in the runtime's ``envVars``."""
    monkeypatch.setenv("AGENT_OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OTEL_PYTHON_DISTRO", "aws_distro")
    monkeypatch.setenv("OTEL_PYTHON_CONFIGURATOR", "aws_configurator")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4316/v1/traces")


def adot_provider(monkeypatch: pytest.MonkeyPatch) -> TracerProvider:
    """A provider shaped like the one ``opentelemetry-instrument`` leaves behind."""
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    return provider


def processors(provider: TracerProvider) -> tuple:
    return tuple(provider._active_span_processor._span_processors)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------------------
# Detecting ADOT
# --------------------------------------------------------------------------------------


def test_nothing_is_detected_in_a_plain_process(clean_env: None) -> None:
    assert adot_instrumented() is False
    assert otlp_enabled() is False
    assert console_enabled() is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AGENT_OBSERVABILITY_ENABLED", "true"),
        ("OTEL_PYTHON_DISTRO", "aws_distro"),
        ("OTEL_PYTHON_CONFIGURATOR", "aws_configurator"),
        ("OTEL_TRACES_EXPORTER", "otlp"),
    ],
)
def test_each_adot_marker_is_enough_on_its_own(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    assert adot_instrumented() is True


def test_the_auto_instrumentation_path_on_pythonpath_counts(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``opentelemetry-instrument`` bootstraps the child purely through ``PYTHONPATH``."""
    monkeypatch.setenv(
        "PYTHONPATH", "/var/task:/usr/lib/python3/opentelemetry/instrumentation/auto_instrumentation"
    )
    assert adot_instrumented() is True


def test_a_provider_that_already_exports_counts(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with no env markers, a provider with processors means someone else is exporting."""
    provider = adot_provider(monkeypatch)
    assert installed_tracer_provider() is provider
    assert adot_instrumented() is True


# --------------------------------------------------------------------------------------
# What setup_telemetry does about it
# --------------------------------------------------------------------------------------


def test_setup_adds_no_exporter_under_agentcore(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    agentcore_env(monkeypatch)
    provider = adot_provider(monkeypatch)
    before = processors(provider)

    telemetry = setup_telemetry(settings)

    assert telemetry is not None
    assert telemetry.tracer_provider is provider, "Strands spans must join ADOT's provider"
    assert processors(provider) == before, "a second exporter is the 400 Bad Request"
    assert trace.get_tracer_provider() is provider, "the global provider stays ADOT's"


def test_repeated_invocations_never_stack_processors(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """The runtime calls this on every request; the container lives for hours."""
    agentcore_env(monkeypatch)
    provider = adot_provider(monkeypatch)

    first = setup_telemetry(settings)
    for _ in range(5):
        assert setup_telemetry(settings) is first
    assert len(processors(provider)) == 1


def test_setup_installs_nothing_when_adot_is_on_but_its_provider_is_invisible(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A proxy provider is not ours to attach to — and replacing it would shadow ADOT."""
    agentcore_env(monkeypatch)
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: trace.ProxyTracerProvider())
    assert installed_tracer_provider() is None

    assert setup_telemetry(settings) is None
    assert isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider)


def test_a_self_hosted_collector_still_gets_our_exporter(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """Without ADOT, Porchlight is the one that has to wire the exporter up."""
    from strands.telemetry import StrandsTelemetry

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    calls: list[str] = []
    monkeypatch.setattr(
        StrandsTelemetry,
        "setup_otlp_exporter",
        lambda self, **kwargs: (calls.append("otlp"), self)[1],
    )
    assert adot_instrumented() is False
    assert otlp_enabled() is True

    telemetry = setup_telemetry(settings)

    assert telemetry is not None
    assert calls == ["otlp"], "nobody else is exporting, so this one is ours to configure"


def test_strands_spans_reach_the_adot_provider(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """``strands.telemetry.Tracer`` reads the global provider, so ADOT's is the one it uses."""
    from strands.telemetry.tracer import Tracer

    agentcore_env(monkeypatch)
    provider = adot_provider(monkeypatch)
    setup_telemetry(settings)

    assert Tracer().tracer_provider is provider

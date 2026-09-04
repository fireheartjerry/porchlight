"""The AgentCore entrypoint: invoked directly, with and without streaming."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from porchlight.agents.outputs import IntakeResult
from porchlight.clock import FrozenClock
from porchlight.config import Settings, reset_settings
from porchlight.context import AppContext, NullChannel
from porchlight.models import AidRequest, Category, DecisionKind, Source
from porchlight.runtime import (
    ACTIONS,
    app,
    dispatch,
    porchlight_entrypoint,
    request_id_from_session,
    runtime_settings,
    session_id_of,
)
from porchlight.telemetry import (
    console_enabled,
    installed_tracer_provider,
    otlp_enabled,
    reset_telemetry,
    setup_telemetry,
)
from porchlight.testing.mock_model import MockTurn, ScenarioModel

FROZEN_NOW = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _restore_mode() -> Iterator[None]:
    """``runtime_settings`` defaults ``PORCHLIGHT_MODE`` into the process env; undo that."""
    before = os.environ.get("PORCHLIGHT_MODE")
    yield
    if before is None:
        os.environ.pop("PORCHLIGHT_MODE", None)
    else:
        os.environ["PORCHLIGHT_MODE"] = before


@pytest.fixture
def rclock() -> FrozenClock:
    """A clock frozen at Tuesday midday."""
    return FrozenClock(FROZEN_NOW)


@pytest.fixture
def rctx(tmp_path: Path, rclock: FrozenClock) -> Iterator[AppContext]:
    """A runtime-shaped context that never touches AWS or the repo tree."""
    from porchlight.sim.fixtures import seed_store
    from porchlight.store.sqlite_store import SqliteStore

    settings = Settings(
        mode="live",
        model_provider="mock",
        store="sqlite",
        sqlite_path=":memory:",
        session_dir=str(tmp_path / "sessions"),
    )
    store = SqliteStore(":memory:")
    seed_store(store, rclock)
    events: list[dict] = []
    ctx = AppContext(
        settings=settings,
        store=store,
        channel=NullChannel(),
        memory=None,
        clock=rclock,
        emit=events.append,
    )
    ctx.emitted = events  # type: ignore[attr-defined]
    yield ctx
    store.close()


def _scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unscripted models: every agent synthesizes a valid structured output."""
    monkeypatch.setattr("porchlight.agents.base.make_model", lambda settings, tier: ScenarioModel())


def test_entrypoint_is_registered() -> None:
    assert app.handlers["main"] is porchlight_entrypoint
    assert set(ACTIONS) == {"process_request", "resume_decision", "sweep", "brief"}


def test_dispatch_processes_a_request(rctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    _scenario(monkeypatch)
    request = AidRequest(raw_text="Ride to dialysis Thursday", source=Source.SMS)
    rctx.store.put_request(request)

    result = dispatch(rctx, {"action": "process_request", "request_id": request.id})

    assert result["ok"] is True
    assert result["outcome"]["request_id"] == request.id
    assert isinstance(result["outcome"]["status"], str)


def test_dispatch_requires_a_request_id(rctx: AppContext) -> None:
    result = dispatch(rctx, {"action": "process_request"})
    assert result["ok"] is False
    assert "request_id" in result["error"]


def test_dispatch_resumes_a_decision(rctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "porchlight.agents.base.make_model",
        lambda settings, tier: ScenarioModel(
            {"intake": [MockTurn(structured=IntakeResult(summary="stove on", safety_flags=["stove is on"]))]}
        ),
    )
    request = AidRequest(raw_text="the kid is home alone and the stove is on", source=Source.SMS)
    rctx.store.put_request(request)
    started = dispatch(rctx, {"action": "process_request", "request_id": request.id})
    cards = started["outcome"]["decisions_created"]
    assert cards and cards[0]["kind"] == DecisionKind.SAFETY

    resumed = dispatch(
        rctx,
        {
            "action": "resume_decision",
            "decision_id": cards[0]["id"],
            "option_id": "i_will_handle",
            "note": "on my way",
        },
    )
    assert resumed["ok"] is True
    assert resumed["outcome"]["interrupted"] is False


def test_dispatch_resume_validates_its_arguments(rctx: AppContext) -> None:
    result = dispatch(rctx, {"action": "resume_decision", "decision_id": "dec_1"})
    assert result["ok"] is False


def test_dispatch_sweep(rctx: AppContext) -> None:
    result = dispatch(rctx, {"action": "sweep"})
    assert result["ok"] is True
    assert "messages_sent" in result["outcome"]


def test_dispatch_brief(rctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    _scenario(monkeypatch)
    result = dispatch(rctx, {"action": "brief", "day": FROZEN_NOW.date().isoformat()})
    assert result["ok"] is True
    assert isinstance(result["markdown"], str) and result["markdown"]


def test_dispatch_brief_ignores_a_bad_day(rctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    _scenario(monkeypatch)
    assert dispatch(rctx, {"action": "brief", "day": "not-a-date"})["ok"] is True


def test_dispatch_rejects_an_unknown_action(rctx: AppContext) -> None:
    result = dispatch(rctx, {"action": "make_coffee"})
    assert result["ok"] is False
    assert "unknown action" in result["error"]


def test_entrypoint_runs_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The real entrypoint builds its own context from the environment."""
    monkeypatch.setenv("PORCHLIGHT_MODEL_PROVIDER", "mock")
    monkeypatch.setenv("PORCHLIGHT_STORE", "sqlite")
    monkeypatch.setenv("PORCHLIGHT_SQLITE_PATH", str(tmp_path / "porchlight.db"))
    monkeypatch.setenv("PORCHLIGHT_SESSION_DIR", str(tmp_path / "sessions"))
    reset_settings()
    _scenario(monkeypatch)

    result = porchlight_entrypoint({"action": "sweep"})

    assert result["ok"] is True
    assert result["action"] == "sweep"


async def test_entrypoint_streams_trace_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PORCHLIGHT_MODEL_PROVIDER", "mock")
    monkeypatch.setenv("PORCHLIGHT_SQLITE_PATH", str(tmp_path / "porchlight.db"))
    monkeypatch.setenv("PORCHLIGHT_SESSION_DIR", str(tmp_path / "sessions"))
    reset_settings()
    _scenario(monkeypatch)

    from porchlight.store import make_store

    store = make_store(runtime_settings())
    request = AidRequest(raw_text="Ride to dialysis", source=Source.SMS, category=Category.RIDE)
    store.put_request(request)

    stream = porchlight_entrypoint({"action": "process_request", "request_id": request.id, "stream": True})
    events = [event async for event in stream]

    assert events, "the stream produced nothing"
    assert events[-1]["type"] == "result"
    assert events[-1]["detail"]["ok"] is True
    assert {"node_start", "node_end"} <= {event["type"] for event in events[:-1]}


def test_runtime_settings_default_to_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORCHLIGHT_MODE", raising=False)
    reset_settings()
    assert runtime_settings().mode == "live"


def test_telemetry_stays_off_without_configuration(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OTEL_EXPORTER_OTLP_ENDPOINT", "AGENT_OBSERVABILITY_ENABLED", "PORCHLIGHT_TRACE_CONSOLE"):
        monkeypatch.delenv(name, raising=False)
    assert otlp_enabled() is False
    assert console_enabled() is False
    assert setup_telemetry(settings) is None


def test_telemetry_flags_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    assert otlp_enabled() is True
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    monkeypatch.setenv("AGENT_OBSERVABILITY_ENABLED", "true")
    assert otlp_enabled() is True
    monkeypatch.setenv("PORCHLIGHT_TRACE_CONSOLE", "1")
    assert console_enabled() is True


# --- the AgentCore session id -------------------------------------------------------------


class _Context:
    """Stands in for AgentCore's ``RequestContext``, which only ever gives us a session id."""

    def __init__(self, session_id: str | None) -> None:
        self.session_id = session_id


def test_entrypoint_takes_a_parameter_named_context() -> None:
    """``BedrockAgentCoreApp`` passes the context only when the second parameter is so named."""
    import inspect

    assert list(inspect.signature(porchlight_entrypoint).parameters) == ["payload", "context"]
    assert app._takes_context(porchlight_entrypoint) is True


def test_session_id_of_reads_the_context() -> None:
    assert session_id_of(_Context("sess-" + "a" * 30)) == "sess-" + "a" * 30
    assert session_id_of(_Context("")) is None
    assert session_id_of(_Context(None)) is None
    assert session_id_of(None) is None
    assert session_id_of(object()) is None


def test_request_id_round_trips_through_a_runtime_session_id() -> None:
    """What the API encodes in ``runtimeSessionId``, the runtime can decode again."""
    from porchlight.orchestrator import runtime_session_id

    assert request_id_from_session(runtime_session_id("req_9c72e440ff")) == "req_9c72e440ff"
    assert request_id_from_session("sweep-2026-09-08-" + "x" * 20) is None
    assert request_id_from_session("req_") is None
    assert request_id_from_session(None) is None


def test_dispatch_echoes_the_session_id(rctx: AppContext) -> None:
    result = dispatch(rctx, {"action": "sweep"}, "sweep-2026-09-08-" + "x" * 20)
    assert result["session_id"] == "sweep-2026-09-08-" + "x" * 20


def test_dispatch_falls_back_to_the_session_id_for_the_request(
    rctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A payload with no ``request_id`` still works when the session id carries one."""
    from porchlight.orchestrator import runtime_session_id

    _scenario(monkeypatch)
    request = AidRequest(raw_text="Ride to dialysis Thursday", source=Source.SMS)
    rctx.store.put_request(request)

    result = dispatch(rctx, {"action": "process_request"}, runtime_session_id(request.id))

    assert result["ok"] is True
    assert result["outcome"]["request_id"] == request.id


def test_entrypoint_passes_the_context_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PORCHLIGHT_MODEL_PROVIDER", "mock")
    monkeypatch.setenv("PORCHLIGHT_SQLITE_PATH", str(tmp_path / "porchlight.db"))
    monkeypatch.setenv("PORCHLIGHT_SESSION_DIR", str(tmp_path / "sessions"))
    reset_settings()
    _scenario(monkeypatch)

    result = porchlight_entrypoint({"action": "sweep"}, _Context("sweep-" + "y" * 30))

    assert result["session_id"] == "sweep-" + "y" * 30


# --- telemetry ----------------------------------------------------------------------------


def test_telemetry_is_configured_once(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """A long-lived runtime calls this per invocation; it must not stack span processors."""
    monkeypatch.setenv("PORCHLIGHT_TRACE_CONSOLE", "1")
    reset_telemetry()
    try:
        first = setup_telemetry(settings)
        assert first is not None
        assert setup_telemetry(settings) is first
    finally:
        reset_telemetry()


def test_telemetry_reuses_an_installed_tracer_provider(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under ``opentelemetry-instrument`` ADOT owns the provider; we attach, never replace."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setenv("AGENT_OBSERVABILITY_ENABLED", "true")
    monkeypatch.delenv("PORCHLIGHT_TRACE_CONSOLE", raising=False)
    reset_telemetry()
    try:
        assert installed_tracer_provider() is provider
        telemetry = setup_telemetry(settings)
        assert telemetry is not None
        assert telemetry.tracer_provider is provider
        assert not provider._active_span_processor._span_processors
    finally:
        reset_telemetry()

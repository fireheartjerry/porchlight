"""The Porchlight API: one FastAPI app over one :class:`~porchlight.context.AppContext`.

Every endpoint in ``docs/CONTRACTS.md`` §9 lives here. The app owns exactly three things:

* one ``AppContext`` (store, channel, memory, clock, trace sink),
* one :class:`~porchlight.orchestrator.Orchestrator` (in-process graph, or AgentCore Runtime),
* one :class:`api.events.EventBus` that turns ``ctx.emit`` calls into the ``/api/events`` stream.

Agent work is handed to a threadpool (``run_in_threadpool``) so the event loop stays free to
push trace events while a request is being processed — that is what makes the demo feel live.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from porchlight import __version__
from porchlight.config import Settings, get_settings
from porchlight.context import AppContext, build_context
from porchlight.intake_ingest import create_request_from_inbox
from porchlight.models import (
    AidRequest,
    Decision,
    DecisionStatus,
    GroupSettings,
    LogEvent,
    RequestStatus,
    Volunteer,
)
from porchlight.orchestrator import (
    GraphUnavailableError,
    Orchestrator,
    RunOutcome,
    SweepOutcome,
    graph_available,
    make_orchestrator,
)
from porchlight.sim.fixtures import SAMPLE_MESSAGES, demo_sequence, seed_store

from .events import EventBus
from .schemas import (
    BriefResponse,
    HealthResponse,
    InboxIn,
    PorchResponse,
    PorchStats,
    RequestDetail,
    ResetResponse,
    ResolveIn,
    RunDayIn,
    RunDayStarted,
    SampleMessage,
    VolunteerLoad,
    VolunteerView,
)

logger = logging.getLogger(__name__)

SETTLED_STATUSES = (RequestStatus.CONFIRMED, RequestStatus.IN_PROGRESS, RequestStatus.COMPLETED)
"""Statuses that count as "Porchlight got this one done"."""

MAX_REPLAY = 200
"""Cap on how many past trace events a new SSE client may replay."""

ContextFactory = Callable[[], AppContext]
OrchestratorFactory = Callable[[AppContext], Orchestrator]


# --------------------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------------------


def attach_bus(ctx: AppContext, bus: EventBus) -> None:
    """Route ``ctx.emit`` into ``bus`` while preserving any existing sink."""
    inner = ctx.emit

    def emit(event: dict[str, Any]) -> None:
        bus.publish(event)
        try:
            inner(event)
        except Exception:  # pragma: no cover - a broken sink must not break a run
            logger.exception("trace sink raised")

    ctx.emit = emit


def seed_if_empty(ctx: AppContext) -> None:
    """Load the Maple Street fixtures when a demo store starts out empty."""
    if not ctx.settings.is_demo:
        return
    if ctx.store.list_volunteers():
        return
    counts = seed_store(ctx.store, ctx.clock)
    logger.info("seeded demo fixtures: %s", counts)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the context, the bus, and the orchestrator once per process."""
    bus: EventBus = app.state.bus
    bus.bind(asyncio.get_running_loop())

    context_factory: ContextFactory | None = app.state.context_factory
    owns_context = context_factory is None
    ctx = context_factory() if context_factory else build_context()
    attach_bus(ctx, bus)
    seed_if_empty(ctx)

    orchestrator_factory: OrchestratorFactory | None = app.state.orchestrator_factory
    orchestrator = orchestrator_factory(ctx) if orchestrator_factory else make_orchestrator(ctx)

    app.state.ctx = ctx
    app.state.orchestrator = orchestrator
    app.state.day_task = None
    logger.info("porchlight api ready (%s, %s)", ctx.settings.mode, orchestrator)
    try:
        yield
    finally:
        task = app.state.day_task
        if task is not None and not task.done():
            task.cancel()
        close = getattr(ctx.store, "close", None)
        if owns_context and callable(close):
            close()


def _ctx(request: Request) -> AppContext:
    """The app's context."""
    return request.app.state.ctx


def _orch(request: Request) -> Orchestrator:
    """The app's orchestrator (tests replace ``app.state.orchestrator`` directly)."""
    return request.app.state.orchestrator


def _bus(request: Request) -> EventBus:
    """The app's trace bus."""
    return request.app.state.bus


# --------------------------------------------------------------------------------------
# Read helpers
# --------------------------------------------------------------------------------------


def _group_settings(ctx: AppContext) -> GroupSettings:
    """Group settings from the store, falling back to the configured defaults."""
    try:
        return ctx.store.get_group_settings()
    except Exception:  # pragma: no cover - defensive; a store may have no settings row
        logger.exception("group settings unavailable; using configured defaults")
        settings: Settings = ctx.settings
        return GroupSettings(
            name=settings.group_name,
            timezone=settings.timezone,
            quiet_hours=settings.quiet_hours,
            petty_cash_limit=settings.petty_cash_limit,
            max_candidates=settings.max_candidates,
            escalate_hours_before_window=settings.escalate_hours_before_window,
            confidence_threshold=settings.confidence_threshold,
        )


def _stats(ctx: AppContext) -> PorchStats:
    """The store's day counters plus the two the roster needs."""
    now = ctx.now()
    raw = dict(ctx.store.stats(now.date()))
    week_ago = now - timedelta(days=7)
    recent = [r for r in ctx.store.list_requests(limit=500) if r.created_at >= week_ago]
    raw["confirmed_this_week"] = sum(1 for r in recent if r.status in SETTLED_STATUSES)
    active = {r.assigned_volunteer_id for r in recent if r.assigned_volunteer_id}
    raw["volunteers_active"] = len(active)
    return PorchStats.model_validate(raw)


def _status_line(stats: PorchStats) -> str:
    """Render the header line: ``"Quiet. 14 handled today · 2 need you."``."""
    open_count = stats.decisions_open
    handled = stats.handled_autonomously
    if open_count == 0:
        head, need = "All quiet.", "nothing needs you"
    else:
        head = "Quiet." if open_count <= 2 else "Busy evening."
        need = f"{open_count} need{'s' if open_count == 1 else ''} you"
    return f"{head} {handled} handled today · {need}."


def _volunteer_view(ctx: AppContext, volunteer: Volunteer, since: datetime) -> VolunteerView:
    """Attach this week's load to a volunteer."""
    rows = ctx.store.requests_for_volunteer(volunteer.id, since)
    this_week = sum(1 for r in rows if r.assigned_volunteer_id == volunteer.id)
    load = VolunteerLoad(
        this_week=this_week,
        max_per_week=volunteer.max_per_week,
        last_active=volunteer.stats.last_active,
    )
    return VolunteerView.model_validate({**volunteer.model_dump(), "load": load.model_dump()})


def _parse_day(value: str | None, ctx: AppContext) -> date:
    """Parse a ``YYYY-MM-DD`` query parameter, defaulting to today."""
    if not value:
        return ctx.now().date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"day must be YYYY-MM-DD, got {value!r}") from exc


def _parse_since(value: str | None) -> datetime | None:
    """Parse an ISO-8601 ``since`` query parameter."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"since must be ISO-8601, got {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _run(orchestrator_call: Callable[[], Any]) -> Any:
    """Run a blocking orchestrator call off the event loop, mapping failures to HTTP errors."""
    try:
        return await run_in_threadpool(orchestrator_call)
    except GraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------------------------------------------
# Demo day
# --------------------------------------------------------------------------------------


async def _run_demo_day(app: FastAPI, count: int, reset: bool) -> None:
    """Push ``count`` sample messages through the orchestrator, one at a time."""
    ctx: AppContext = app.state.ctx
    orchestrator: Orchestrator = app.state.orchestrator
    bus: EventBus = app.state.bus
    quiet = 0
    cards = 0

    def progress(done: int, summary: str, request_id: str | None = None, **extra: Any) -> None:
        bus.publish(
            {
                "type": "demo_progress",
                "request_id": request_id,
                "agent": "system",
                "summary": summary,
                "detail": {"done": done, "total": count, "quiet": quiet, "cards": cards, **extra},
            }
        )

    try:
        if reset:
            await run_in_threadpool(seed_store, ctx.store, ctx.clock)
        progress(0, f"Running a Tuesday — {count} requests")
        for index, sample in enumerate(demo_sequence(count)):
            request = await run_in_threadpool(
                create_request_from_inbox,
                ctx,
                sample["text"],
                sample["source"],
                sample["contact"],
            )
            try:
                outcome = await run_in_threadpool(orchestrator.process_request, request.id)
            except GraphUnavailableError as exc:
                progress(index, f"Stopped: {exc}", request.id, error=True)
                return
            if outcome.interrupted or outcome.decisions_created:
                cards += 1
                verdict = "needs you"
            else:
                quiet += 1
                verdict = "handled quietly"
            progress(index + 1, f"{index + 1} of {count} — {verdict}", request.id, sample=sample["id"])
        bus.publish(
            {
                "type": "log",
                "agent": "brief",
                "summary": f"Tuesday complete — {quiet} handled quietly, {cards} needed you",
                "detail": {"quiet": quiet, "cards": cards, "total": count},
            }
        )
    except asyncio.CancelledError:  # pragma: no cover - shutdown path
        raise
    except Exception as exc:  # pragma: no cover - surfaced to the UI, never crashes the app
        logger.exception("demo day failed")
        progress(quiet + cards, f"Demo day failed: {exc}", error=True)
    finally:
        app.state.day_task = None


# --------------------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------------------


def create_app(
    context_factory: ContextFactory | None = None,
    orchestrator_factory: OrchestratorFactory | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    Args:
        context_factory: Builds the :class:`AppContext` (tests inject a seeded in-memory one).
            Defaults to :func:`porchlight.context.build_context`.
        orchestrator_factory: Builds the orchestrator from the context. Defaults to
            :func:`porchlight.orchestrator.make_orchestrator`.

    Returns:
        The configured application. Nothing is built until the lifespan runs.
    """
    app = FastAPI(
        title="Porchlight",
        version=__version__,
        summary="Runs the coordination. Lights up only when you're needed.",
        lifespan=_lifespan,
    )
    app.state.bus = EventBus()
    app.state.ctx = None
    app.state.orchestrator = None
    app.state.day_task = None
    app.state.context_factory = context_factory
    app.state.orchestrator_factory = orchestrator_factory
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- health ---------------------------------------------------------------
    @app.get("/api/health", response_model=HealthResponse, tags=["ops"])
    async def health(request: Request) -> HealthResponse:
        """Liveness plus the wiring this process actually chose."""
        ctx = _ctx(request)
        return HealthResponse(
            mode=ctx.settings.mode,
            version=__version__,
            model_provider=ctx.settings.model_provider,
            store=ctx.settings.store,
            orchestrator=type(_orch(request)).__name__,
            graph_available=graph_available(),
        )

    # --- porch ----------------------------------------------------------------
    @app.get("/api/porch", response_model=PorchResponse, tags=["porch"])
    async def porch(request: Request, log_limit: int = Query(default=60, ge=1, le=500)) -> PorchResponse:
        """Everything the home screen shows: status line, open cards, quiet log, stats."""
        ctx = _ctx(request)
        stats = _stats(ctx)
        open_decisions = ctx.store.list_decisions(status=DecisionStatus.OPEN)
        return PorchResponse(
            status_line=_status_line(stats),
            light_on=len(open_decisions) > 0,
            open_decisions=open_decisions,
            quiet_log=ctx.store.list_log(limit=log_limit),
            stats=stats,
            group=_group_settings(ctx),
        )

    # --- requests -------------------------------------------------------------
    @app.get("/api/requests", response_model=list[AidRequest], tags=["requests"])
    async def list_requests(
        request: Request,
        status: RequestStatus | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> list[AidRequest]:
        """Every request, newest first, optionally filtered by status."""
        return _ctx(request).store.list_requests(status=status, limit=limit)

    @app.get("/api/requests/{request_id}", response_model=RequestDetail, tags=["requests"])
    async def get_request(request: Request, request_id: str) -> RequestDetail:
        """One request with its attempts, messages, and log."""
        ctx = _ctx(request)
        found = ctx.store.get_request(request_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no request {request_id}")
        return RequestDetail(
            request=found,
            attempts=found.attempts,
            messages=ctx.store.list_messages(request_id=request_id),
            log=ctx.store.list_log(request_id=request_id),
        )

    # --- inbox ----------------------------------------------------------------
    @app.post("/api/inbox", response_model=RunOutcome, tags=["inbox"])
    async def inbox(request: Request, payload: InboxIn) -> RunOutcome:
        """Accept an inbound message, record it, and run it through the graph."""
        ctx = _ctx(request)
        try:
            created = await run_in_threadpool(
                create_request_from_inbox,
                ctx,
                payload.text,
                payload.source,
                payload.contact,
                payload.image_base64,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        orchestrator = _orch(request)
        return await _run(lambda: orchestrator.process_request(created.id))

    # --- decisions ------------------------------------------------------------
    @app.get("/api/decisions", response_model=list[Decision], tags=["decisions"])
    async def list_decisions(request: Request, status: DecisionStatus | None = None) -> list[Decision]:
        """Decision cards, newest first."""
        return _ctx(request).store.list_decisions(status=status)

    @app.post("/api/decisions/{decision_id}/resolve", response_model=RunOutcome, tags=["decisions"])
    async def resolve_decision(request: Request, decision_id: str, payload: ResolveIn) -> RunOutcome:
        """Answer a decision card; the paused graph resumes from the interrupt."""
        ctx = _ctx(request)
        decision = ctx.store.get_decision(decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail=f"no decision {decision_id}")
        if decision.status == DecisionStatus.RESOLVED:
            raise HTTPException(status_code=409, detail="decision already resolved")
        options = decision.option_ids()
        if options and payload.option_id not in options:
            raise HTTPException(
                status_code=422, detail=f"option must be one of {options}, got {payload.option_id!r}"
            )
        orchestrator = _orch(request)
        return await _run(lambda: orchestrator.resume_decision(decision_id, payload.option_id, payload.note))

    # --- volunteers -----------------------------------------------------------
    @app.get("/api/volunteers", response_model=list[VolunteerView], tags=["volunteers"])
    async def list_volunteers(
        request: Request, zone: str | None = None, skill: str | None = None
    ) -> list[VolunteerView]:
        """The roster, each volunteer carrying this week's load."""
        ctx = _ctx(request)
        since = ctx.now() - timedelta(days=7)
        return [_volunteer_view(ctx, v, since) for v in ctx.store.list_volunteers(zone=zone, skill=skill)]

    # --- log ------------------------------------------------------------------
    @app.get("/api/log", response_model=list[LogEvent], tags=["porch"])
    async def list_log(
        request: Request,
        request_id: str | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
        since: str | None = None,
    ) -> list[LogEvent]:
        """The quiet log, newest first."""
        return _ctx(request).store.list_log(request_id=request_id, limit=limit, since=_parse_since(since))

    # --- events ---------------------------------------------------------------
    @app.get("/api/events", tags=["trace"])
    async def events(
        request: Request,
        replay: int = Query(default=0, ge=0, le=MAX_REPLAY, description="Recent events to resend"),
        limit: int = Query(default=0, ge=0, description="Close after N events (0 = stream forever)"),
    ) -> EventSourceResponse:
        """Server-sent stream of trace events; a comment heartbeat keeps proxies awake."""
        bus = _bus(request)

        async def stream() -> AsyncIterator[dict[str, str]]:
            with bus.subscribe() as queue:
                sent = 0
                backlog = [*bus.recent(replay), _connected_event(bus)]
                for event in backlog:
                    yield {"data": json.dumps(event)}
                    sent += 1
                    if limit and sent >= limit:
                        return
                while True:
                    if await request.is_disconnected():  # pragma: no cover - client-driven
                        return
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        continue
                    yield {"data": json.dumps(event)}
                    sent += 1
                    if limit and sent >= limit:
                        return

        return EventSourceResponse(stream(), ping=15)

    # --- sweep & brief --------------------------------------------------------
    @app.post("/api/sweep", response_model=SweepOutcome, tags=["ops"])
    async def sweep(request: Request) -> SweepOutcome:
        """Send due messages, escalate stale outreach, time out silent volunteers."""
        orchestrator = _orch(request)
        return await _run(orchestrator.sweep)

    @app.get("/api/brief", response_model=BriefResponse, tags=["ops"])
    async def brief(request: Request, day: str | None = None) -> BriefResponse:
        """The coordinator's markdown digest for a day (defaults to today)."""
        ctx = _ctx(request)
        when = _parse_day(day, ctx)
        orchestrator = _orch(request)
        markdown = await _run(lambda: orchestrator.brief(when))
        return BriefResponse(day=when.isoformat(), markdown=str(markdown))

    # --- demo -----------------------------------------------------------------
    @app.get("/api/demo/samples", response_model=list[SampleMessage], tags=["demo"])
    async def samples() -> list[SampleMessage]:
        """The canned inbound messages behind the demo inbox."""
        return [SampleMessage.model_validate(dict(sample)) for sample in SAMPLE_MESSAGES]

    @app.post("/api/demo/reset", response_model=ResetResponse, tags=["demo"])
    async def reset(request: Request) -> ResetResponse:
        """Wipe the store and reseed the Maple Street fixtures."""
        ctx = _ctx(request)
        counts = await run_in_threadpool(seed_store, ctx.store, ctx.clock)
        ctx.emit(
            {
                "type": "log",
                "agent": "system",
                "summary": "Demo reset — fixtures reseeded",
                "detail": dict(counts),
            }
        )
        return ResetResponse(ok=True, **counts)

    @app.post("/api/demo/run_day", response_model=RunDayStarted, status_code=202, tags=["demo"])
    async def run_day(request: Request, payload: RunDayIn = Body(default=RunDayIn())) -> RunDayStarted:
        """Stream ``count`` sample requests through the orchestrator in the background."""
        app_ = request.app
        task = app_.state.day_task
        if task is not None and not task.done():
            return RunDayStarted(started=False, count=payload.count, detail="a demo day is already running")
        app_.state.day_task = asyncio.create_task(_run_demo_day(app_, payload.count, payload.reset))
        return RunDayStarted(started=True, count=payload.count, detail="watch /api/events for demo_progress")

    @app.exception_handler(GraphUnavailableError)
    async def _graph_unavailable(request: Request, exc: GraphUnavailableError) -> JSONResponse:
        """Turn a missing graph into a clear 503 rather than a 500."""
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    return app


def _connected_event(bus: EventBus) -> dict[str, Any]:
    """The first frame every SSE client receives, so the UI can show "Live" immediately."""
    return {
        "type": "log",
        "ts": datetime.now(UTC).isoformat(),
        "request_id": None,
        "agent": "system",
        "summary": "Trace connected — the porch is listening",
        "detail": {"kind": "policy", "subscribers": bus.subscriber_count},
    }


app = create_app()
"""The ASGI app uvicorn and Mangum serve."""


def main() -> None:  # pragma: no cover - convenience entry point
    """Run the API with uvicorn (``python -m api.main``)."""
    import uvicorn

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info" if settings.is_demo else "warning")


if __name__ == "__main__":  # pragma: no cover
    main()

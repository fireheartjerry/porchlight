"""The Strands ``Graph`` that runs a request end to end, and the four entry points around it.

Shape of the graph::

    intake ──▶ matcher ──▶ outreach ──▶ steward
                  ▲            │
                  └── decline ─┘   (bounded by settings.max_candidates)

Two decision points are **graph-level interrupts**, raised by :class:`PolicyGateHook` before a
node runs, so the pause is persisted by the session manager and survives the process:

* before ``matcher`` — safety, money, or vetting flags on the request;
* before ``outreach`` — no candidate, low confidence, or the ask limit reached.

A third kind (a volunteer raising a concern) is raised inside a node by
:class:`~porchlight.policy.PorchlightPolicy`. All three arrive here the same way: as
``GraphResult.interrupts``, which :func:`run_request` turns into :class:`~porchlight.models.Decision`
rows for the coordinator's porch.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from strands.hooks import AfterNodeCallEvent, BeforeNodeCallEvent, HookProvider, HookRegistry
from strands.multiagent import GraphBuilder
from strands.multiagent.base import Status
from strands.multiagent.graph import Graph, GraphState
from strands.session.file_session_manager import FileSessionManager
from strands.session.session_manager import SessionManager

from .agents import (
    IntakeResult,
    OutreachStep,
    StewardResult,
    build_intake_task,
    make_brief_agent,
    make_intake_agent,
    make_matcher_agent,
    make_outreach_agent,
    make_steward_agent,
)
from .context import AppContext
from .models import (
    AidRequest,
    Decision,
    DecisionKind,
    DecisionOption,
    DecisionStatus,
    LogEvent,
    LogKind,
    MatchPlan,
    MessageStatus,
    RequestStatus,
    jsonable,
)
from .policy import (
    APPROVING_OPTIONS,
    HALTED_STATUSES,
    PolicyFlag,
    TraceHook,
    card_for,
    decode_decision,
    evaluate_request,
    option_id_of,
    unmatched_card,
)

logger = logging.getLogger(__name__)

INTERRUPT_NAME = "porchlight-decision"
"""Name given to every graph-level interrupt; the node id makes each one unique."""

NODES = ("intake", "matcher", "outreach", "steward")

__all__ = [
    "PolicyGateHook",
    "RequestSyncHook",
    "RunOutcome",
    "SweepOutcome",
    "build_graph",
    "resume_decision",
    "run_brief",
    "run_request",
    "run_sweep",
]


# --------------------------------------------------------------------------------------
# Outcomes
# --------------------------------------------------------------------------------------


class RunOutcome(BaseModel):
    """What one pass through the graph did."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: RequestStatus = RequestStatus.NEW
    decisions_created: list[Decision] = Field(default_factory=list)
    log_events: int = 0
    interrupted: bool = False
    summary: str = ""


class SweepOutcome(BaseModel):
    """What the hourly sweep did."""

    model_config = ConfigDict(extra="forbid")

    messages_sent: int = 0
    requests_checked: int = 0
    requests_escalated: int = 0
    decisions_created: list[Decision] = Field(default_factory=list)
    summary: str = ""


# --------------------------------------------------------------------------------------
# Reading node output
# --------------------------------------------------------------------------------------


def node_output(state: GraphState, node_id: str, model: type[BaseModel]) -> Any:
    """Return a node's structured output, or ``None`` when it has not produced one yet."""
    node_result = (state.results or {}).get(node_id)
    if node_result is None:
        return None
    for agent_result in node_result.get_agent_results():
        candidate = getattr(agent_result, "structured_output", None)
        if isinstance(candidate, model):
            return candidate
    return None


def _log(
    ctx: AppContext,
    request_id: str | None,
    kind: LogKind,
    summary: str,
    *,
    autonomous: bool = True,
    **detail: Any,
) -> None:
    """Write one quiet-log row and mirror it to the trace stream."""
    entry = LogEvent(
        ts=ctx.now(),
        request_id=request_id,
        agent="graph",
        kind=kind,
        summary=summary,
        detail=jsonable(detail),
        autonomous=autonomous,
    )
    try:
        ctx.store.append_log(entry)
    except Exception:  # pragma: no cover - logging must never break a run
        logger.exception("failed to append graph log")
    ctx.emit(
        {
            "type": "log",
            "ts": entry.ts.isoformat(),
            "request_id": request_id,
            "agent": "graph",
            "summary": summary,
            "detail": entry.detail,
        }
    )


# --------------------------------------------------------------------------------------
# Hooks
# --------------------------------------------------------------------------------------


class PolicyGateHook(HookProvider):
    """Raises decision cards as graph interrupts, and applies the coordinator's answer.

    The hook runs twice for each gated node: once on the way in (raising the interrupt), and
    once again after the coordinator responds, when ``event.interrupt`` returns their choice
    instead of pausing. That second pass is where the option's effect is applied to the request.
    """

    def __init__(self, ctx: AppContext) -> None:
        """Bind the hook to an application context."""
        self.ctx = ctx
        self._answered: set[tuple[str, str]] = set()

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Attach to node entry."""
        registry.add_callback(BeforeNodeCallEvent, self._before_node)

    # --- card selection --------------------------------------------------------

    def _request(self, event: BeforeNodeCallEvent) -> AidRequest | None:
        state = event.invocation_state or {}
        request_id = state.get("request_id")
        if not isinstance(request_id, str):
            return None
        return self.ctx.store.get_request(request_id)

    def _plan(self, event: BeforeNodeCallEvent) -> MatchPlan | None:
        graph = getattr(event, "source", None)
        state = getattr(graph, "state", None)
        if state is None:  # pragma: no cover - defensive
            return None
        return node_output(state, "matcher", MatchPlan)

    def _spec_for(self, event: BeforeNodeCallEvent, request: AidRequest | None) -> Any:
        """Return the decision card this node should raise, or ``None`` to proceed."""
        settings = self.ctx.settings
        if event.node_id == "matcher":
            flags: list[PolicyFlag] = evaluate_request(request, settings) if request else []
            return card_for(request, flags, settings)
        if event.node_id == "outreach":
            plan = self._plan(event)
            attempts = len(request.attempts) if request else 0
            thin = plan is None or not plan.candidates or plan.confidence < settings.confidence_threshold
            if thin or attempts >= settings.max_candidates:
                return unmatched_card(request, plan, settings)
        return None

    # --- lifecycle -------------------------------------------------------------

    def _before_node(self, event: BeforeNodeCallEvent) -> None:
        request = self._request(event)
        if request is None or event.node_id not in ("matcher", "outreach"):
            return
        spec = self._spec_for(event, request)
        if spec is None or (event.node_id, str(spec.kind)) in self._answered:
            return

        # Raises InterruptException the first time; returns the coordinator's answer on resume.
        response = event.interrupt(INTERRUPT_NAME, reason=spec.prompt())
        self._answered.add((event.node_id, str(spec.kind)))
        self._apply(request, spec.kind, response)

    def _apply(self, request: AidRequest, kind: DecisionKind, response: Any) -> None:
        """Turn the coordinator's chosen option into a state change on the request."""
        option = (option_id_of(response) or "").lower()
        note = response.get("note") if isinstance(response, dict) else None
        fresh = self.ctx.store.get_request(request.id) or request

        if option in APPROVING_OPTIONS:
            fresh.status = RequestStatus.MATCHING
            summary = f"coordinator chose '{option}' — continuing"
        elif option == "decline_request":
            fresh.status = RequestStatus.DECLINED
            summary = "coordinator declined the request"
        else:
            fresh.status = RequestStatus.ESCALATED
            summary = f"coordinator chose '{option or 'no option'}' — Porchlight stands down"

        fresh.touch(self.ctx.now())
        self.ctx.store.put_request(fresh)
        _log(
            self.ctx,
            fresh.id,
            LogKind.DECISION,
            summary,
            autonomous=False,
            decision_kind=str(kind),
            option=option,
            note=note,
        )


class RequestSyncHook(HookProvider):
    """Writes each node's structured output back onto the stored request as it completes."""

    def __init__(self, ctx: AppContext) -> None:
        """Bind the hook to an application context."""
        self.ctx = ctx

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Attach to node exit."""
        registry.add_callback(AfterNodeCallEvent, self._after_node)

    def _after_node(self, event: AfterNodeCallEvent) -> None:
        state = (event.invocation_state or {}).get("request_id")
        if not isinstance(state, str):
            return
        request = self.ctx.store.get_request(state)
        graph_state = getattr(getattr(event, "source", None), "state", None)
        if request is None or graph_state is None:
            return

        if event.node_id == "intake":
            parsed = node_output(graph_state, "intake", IntakeResult)
            if parsed is not None:
                parsed.apply_to(request)
                _log(self.ctx, request.id, LogKind.TOOL_CALL, f"intake: {request.summary or 'parsed'}")
            if request.status in (RequestStatus.NEW, RequestStatus.TRIAGING):
                request.status = RequestStatus.MATCHING
        elif event.node_id == "outreach":
            step = node_output(graph_state, "outreach", OutreachStep)
            if step is not None and step.action == "accepted" and request.assigned_volunteer_id:
                request.status = RequestStatus.CONFIRMED
            elif request.status is RequestStatus.MATCHING:
                request.status = RequestStatus.AWAITING_REPLY
        elif event.node_id == "steward":
            result = node_output(graph_state, "steward", StewardResult)
            if result is not None and result.outcome == "completed":
                request.status = RequestStatus.COMPLETED

        request.touch(self.ctx.now())
        self.ctx.store.put_request(request)


# --------------------------------------------------------------------------------------
# Graph construction
# --------------------------------------------------------------------------------------


def make_session_manager(ctx: AppContext, session_id: str) -> SessionManager | None:
    """Pick the session manager for a run: S3 when a bucket is configured, files otherwise."""
    settings = ctx.settings
    if settings.session_bucket:
        from strands.session.s3_session_manager import S3SessionManager

        return S3SessionManager(
            session_id=session_id, bucket=settings.session_bucket, region_name=settings.aws_region
        )
    return FileSessionManager(session_id=session_id, storage_dir=settings.session_dir)


def _request_of(ctx: AppContext, request_id: str | None) -> AidRequest | None:
    """Reload a request from the store; edge conditions must see the latest status."""
    return ctx.store.get_request(request_id) if request_id else None


def build_graph(ctx: AppContext, session_id: str) -> Graph:
    """Build the four-node request graph for one session.

    The session id is the request id, so rebuilding the graph later — in another process, hours
    after a decision card was raised — restores exactly the state the interrupt paused at.

    Args:
        ctx: Application context shared by every node, tool, and hook.
        session_id: Usually the request id; must not contain path separators.

    Returns:
        A built ``strands.multiagent.Graph`` with conditional edges and a bounded outreach cycle.
    """
    settings = ctx.settings
    request_id = session_id

    def should_outreach(state: GraphState) -> bool:
        """Move on to outreach unless the coordinator (or policy) halted the request."""
        request = _request_of(ctx, request_id)
        return request is None or request.status not in HALTED_STATUSES

    def should_retry(state: GraphState) -> bool:
        """Go back to the matcher for the next candidate after a decline.

        One hop *past* ``max_candidates`` is deliberate: it lets the graph re-enter ``outreach``
        so :class:`PolicyGateHook` can raise the "nobody free" card as a resumable interrupt,
        instead of the run ending quietly with an unanswered request.
        """
        step = node_output(state, "outreach", OutreachStep)
        if step is None or step.action not in ("declined", "countered"):
            return False
        request = _request_of(ctx, request_id)
        if request is None or request.status in HALTED_STATUSES:
            return False
        if request.assigned_volunteer_id:
            return False
        return len(request.attempts) <= settings.max_candidates

    def should_steward(state: GraphState) -> bool:
        """Hand over to the steward once a volunteer has actually accepted."""
        step = node_output(state, "outreach", OutreachStep)
        request = _request_of(ctx, request_id)
        accepted = step is not None and step.action == "accepted"
        confirmed = request is not None and request.status is RequestStatus.CONFIRMED
        return accepted or confirmed

    builder = GraphBuilder()
    builder.add_node(make_intake_agent(ctx), "intake")
    builder.add_node(make_matcher_agent(ctx), "matcher")
    builder.add_node(make_outreach_agent(ctx), "outreach")
    builder.add_node(make_steward_agent(ctx), "steward")

    builder.add_edge("intake", "matcher")
    builder.add_edge("matcher", "outreach", condition=should_outreach)
    builder.add_edge("outreach", "matcher", condition=should_retry)
    builder.add_edge("outreach", "steward", condition=should_steward)
    builder.set_entry_point("intake")

    # intake + steward, one matcher/outreach pair per candidate we may ask, one more pair for
    # the "nobody free" gate, and slack for the resumed pass after the coordinator answers.
    builder.set_max_node_executions(2 + 2 * (max(1, settings.max_candidates) + 1) + 3)
    builder.reset_on_revisit(True)
    builder.set_hook_providers([PolicyGateHook(ctx), RequestSyncHook(ctx), TraceHook(ctx)])
    session_manager = make_session_manager(ctx, session_id)
    if session_manager is not None:
        builder.set_session_manager(session_manager)
    return builder.build()


# --------------------------------------------------------------------------------------
# Interrupts → decision cards
# --------------------------------------------------------------------------------------


def _node_ids_by_uuid() -> dict[str, str]:
    """Map the uuid5 fragment Strands puts in a node interrupt id back to the node id."""
    return {str(uuid.uuid5(uuid.NAMESPACE_OID, node)): node for node in NODES}


def _node_for(interrupt_id: str, graph: Graph) -> str | None:
    """Work out which node raised an interrupt."""
    lookup = _node_ids_by_uuid()
    for fragment in str(interrupt_id).split(":"):
        if fragment in lookup:
            return lookup[fragment]
    interrupted = sorted(node.node_id for node in graph.state.interrupted_nodes)
    return interrupted[0] if interrupted else None


def _fallback_payload(request: AidRequest | None, reason: Any) -> dict[str, Any]:
    """A generic card for an interrupt we could not decode."""
    return {
        "kind": str(DecisionKind.POLICY),
        "title": "Porchlight paused and needs you",
        "context": str(reason)[:2000] if reason else "An agent paused for a human decision.",
        "recommendation": "Read the context and choose how to continue.",
        "request_id": request.id if request else None,
        "options": [
            {"id": "approve", "label": "Continue", "description": "Let Porchlight carry on."},
            {"id": "i_will_handle", "label": "I'll handle this", "description": "You take it from here."},
        ],
    }


def _decisions_for(
    ctx: AppContext, graph: Graph, result: Any, session_id: str, request: AidRequest | None
) -> list[Decision]:
    """Turn every interrupt on a graph result into an open decision card."""
    # Strands derives an interrupt id from the node name, so the same node in two different
    # runs raises the *same* id. The session (= request) is what makes a card unique.
    existing = {
        (decision.session_id, decision.interrupt_id): decision
        for decision in ctx.store.list_decisions(DecisionStatus.OPEN)
        if decision.interrupt_id
    }
    cards: list[Decision] = []
    for interrupt in getattr(result, "interrupts", None) or []:
        already = existing.get((session_id, interrupt.id))
        if already is not None:
            cards.append(already)
            continue
        payload = decode_decision(interrupt.reason) or _fallback_payload(request, interrupt.reason)
        try:
            kind = DecisionKind(payload.get("kind", "policy"))
        except ValueError:
            kind = DecisionKind.POLICY
        decision = Decision(
            request_id=payload.get("request_id") or (request.id if request else None),
            kind=kind,
            title=payload.get("title", "Porchlight needs you"),
            context=payload.get("context", ""),
            recommendation=payload.get("recommendation", ""),
            options=[DecisionOption(**option) for option in payload.get("options", [])],
            interrupt_id=interrupt.id,
            session_id=session_id,
            node=_node_for(interrupt.id, graph),
            created_at=ctx.now(),
        )
        ctx.store.put_decision(decision)
        cards.append(decision)
        ctx.emit(
            {
                "type": "decision",
                "ts": decision.created_at.isoformat(),
                "request_id": decision.request_id,
                "agent": decision.node,
                "summary": decision.title,
                "detail": {"decision_id": decision.id, "kind": str(kind), "options": decision.option_ids()},
            }
        )
        _log(
            ctx,
            decision.request_id,
            LogKind.DECISION,
            f"decision card: {decision.title}",
            autonomous=False,
            decision_id=decision.id,
            decision_kind=str(kind),
        )
    return cards


def _finish(ctx: AppContext, request_id: str, graph: Graph, result: Any, logs_before: int) -> RunOutcome:
    """Common post-processing for both ``run_request`` and ``resume_decision``."""
    interrupted = bool(getattr(result, "interrupts", None)) or (
        getattr(result, "status", None) is Status.INTERRUPTED
    )
    request = ctx.store.get_request(request_id)
    decisions = _decisions_for(ctx, graph, result, request_id, request) if interrupted else []

    if interrupted and request is not None and request.status not in HALTED_STATUSES:
        request.status = RequestStatus.ESCALATED
        request.touch(ctx.now())
        ctx.store.put_request(request)
        request = ctx.store.get_request(request_id)

    status = request.status if request else RequestStatus.NEW
    logs_after = len(ctx.store.list_log(request_id=request_id, limit=1000))
    if interrupted:
        summary = f"paused for the coordinator: {'; '.join(d.title for d in decisions) or 'a decision'}"
    elif getattr(result, "status", None) is Status.FAILED:
        summary = "the graph could not finish this request"
    else:
        summary = f"handled autonomously; request is {status}"
    return RunOutcome(
        request_id=request_id,
        status=status,
        decisions_created=decisions,
        log_events=max(0, logs_after - logs_before),
        interrupted=interrupted,
        summary=summary,
    )


# --------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------


def run_request(ctx: AppContext, request_id: str, *, image_base64: str | None = None) -> RunOutcome:
    """Process one new or updated request end to end.

    Args:
        ctx: Application context.
        request_id: Id of an :class:`~porchlight.models.AidRequest` already in the store.
        image_base64: Optional photo of a paper request slip, for multimodal intake.

    Returns:
        A :class:`RunOutcome`. ``interrupted=True`` means the porch light is on and
        ``decisions_created`` holds the cards waiting for the coordinator.
    """
    request = ctx.store.get_request(request_id)
    if request is None:
        return RunOutcome(request_id=request_id, summary=f"unknown request {request_id}")

    logs_before = len(ctx.store.list_log(request_id=request_id, limit=1000))
    if request.status in (RequestStatus.NEW,):
        request.status = RequestStatus.TRIAGING
        request.touch(ctx.now())
        ctx.store.put_request(request)

    graph = build_graph(ctx, session_id=request_id)
    task = build_intake_task(request, image_base64)
    result = graph(task, invocation_state={"ctx": ctx, "request_id": request_id})
    return _finish(ctx, request_id, graph, result, logs_before)


def resume_decision(ctx: AppContext, decision_id: str, option_id: str, note: str | None = None) -> RunOutcome:
    """Answer one decision card and let the graph carry on from exactly where it stopped.

    Args:
        ctx: Application context.
        decision_id: The card the coordinator tapped.
        option_id: The option they chose (``approve``, ``i_will_handle``, ``widen_pool``, …).
        note: Optional free-text note they added.

    Returns:
        A :class:`RunOutcome` for the resumed run; it may interrupt again.
    """
    decision = ctx.store.get_decision(decision_id)
    if decision is None:
        return RunOutcome(request_id="", summary=f"unknown decision {decision_id}")
    request_id = decision.session_id or decision.request_id or ""
    if not decision.open():
        settled = ctx.store.get_request(request_id)
        return RunOutcome(
            request_id=request_id,
            status=settled.status if settled else RequestStatus.NEW,
            summary="decision was already resolved",
        )

    logs_before = len(ctx.store.list_log(request_id=request_id, limit=1000))
    decision.resolve(option_id, note, now=ctx.now())
    ctx.store.put_decision(decision)
    _log(
        ctx,
        decision.request_id,
        LogKind.DECISION,
        f"coordinator chose '{option_id}' on {decision.title}",
        autonomous=False,
        decision_id=decision.id,
        note=note,
    )

    if not decision.interrupt_id:
        request = ctx.store.get_request(request_id)
        status = request.status if request else RequestStatus.NEW
        return RunOutcome(request_id=request_id, status=status, summary="card had no interrupt to resume")

    graph = build_graph(ctx, session_id=request_id)
    responses = [
        {
            "interruptResponse": {
                "interruptId": decision.interrupt_id,
                "response": {"option": option_id, "note": note},
            }
        }
    ]
    result = graph(responses, invocation_state={"ctx": ctx, "request_id": request_id})
    outcome = _finish(ctx, request_id, graph, result, logs_before)
    if not outcome.interrupted:
        outcome.summary = f"coordinator chose '{option_id}'; request is {outcome.status}"
    return outcome


def run_sweep(ctx: AppContext) -> SweepOutcome:
    """Hourly housekeeping: send what is due, escalate what has gone quiet.

    Deliberately model-free — it is a cron job, not an agent — so it is cheap to run every hour
    and its behaviour is fully deterministic.
    """
    now = ctx.now()
    settings = ctx.settings
    sent = 0
    for message in ctx.store.list_messages(status=MessageStatus.SCHEDULED, due_before=now):
        try:
            delivered = ctx.channel.send(message)
        except Exception:  # pragma: no cover - a channel failure must not stop the sweep
            logger.exception("failed to send scheduled message %s", message.id)
            continue
        ctx.store.put_message(delivered)
        sent += 1
        _log(ctx, message.request_id, LogKind.MESSAGE_SENT, f"sent scheduled message to {message.to}")

    escalated = 0
    cards: list[Decision] = []
    open_requests = [
        request
        for status in (RequestStatus.MATCHING, RequestStatus.AWAITING_REPLY)
        for request in ctx.store.list_requests(status)
    ]
    for request in open_requests:
        hours = request.hours_until_window(now)
        out_of_time = hours is not None and hours <= settings.escalate_hours_before_window
        exhausted = len(request.attempts) >= settings.max_candidates and not request.assigned_volunteer_id
        if not (out_of_time or exhausted):
            continue
        spec = unmatched_card(request, None, settings)
        reason = "the window is close" if out_of_time else "everyone has been asked"
        decision = Decision(
            request_id=request.id,
            kind=DecisionKind.UNMATCHED,
            title=spec.title,
            context=f"{spec.context}\n\nEscalated by the sweep because {reason}.",
            recommendation=spec.recommendation,
            options=[
                DecisionOption(id=option_id, label=label, description=description)
                for option_id, label, description in spec.options
            ],
            session_id=request.id,
            node="sweep",
            created_at=now,
        )
        ctx.store.put_decision(decision)
        cards.append(decision)
        request.status = RequestStatus.ESCALATED
        request.touch(now)
        ctx.store.put_request(request)
        escalated += 1
        _log(ctx, request.id, LogKind.DECISION, f"sweep escalated: {reason}", decision_id=decision.id)

    return SweepOutcome(
        messages_sent=sent,
        requests_checked=len(open_requests),
        requests_escalated=escalated,
        decisions_created=cards,
        summary=f"{sent} message(s) sent, {escalated} request(s) escalated",
    )


def run_brief(ctx: AppContext, day: date | None = None) -> str:
    """Write the coordinator's digest for one day, as markdown."""
    day = day or ctx.now().date()
    stats = ctx.store.stats(day)
    start = datetime.combine(day, datetime.min.time()).replace(tzinfo=ctx.now().tzinfo)
    prompt = (
        f"Write the brief for {day.isoformat()}.\n"
        f"Use since_iso='{start.isoformat()}' when you query.\n"
        f"Counters the store already has: {jsonable(stats)}"
    )
    agent = make_brief_agent(ctx)
    result = agent(prompt, invocation_state={"ctx": ctx, "day": day.isoformat()})
    parsed = result.structured_output
    markdown = getattr(parsed, "markdown", "") if parsed is not None else ""
    if not markdown:
        markdown = _fallback_brief(ctx, day, stats)
    _log(ctx, None, LogKind.MODEL, f"brief written for {day.isoformat()}")
    return markdown


def _fallback_brief(ctx: AppContext, day: date, stats: dict[str, Any]) -> str:
    """A plain digest built from the store, used when the model returns nothing usable."""
    open_cards = ctx.store.list_decisions(DecisionStatus.OPEN)
    lines = [
        f"# {ctx.settings.group_name} — {day.isoformat()}",
        "",
        f"{stats.get('handled_autonomously', 0)} handled quietly · {len(open_cards)} need you.",
        "",
        "## Needs you",
    ]
    lines += [f"- {card.title}" for card in open_cards] or ["Nothing needs you."]
    by_status = stats.get("requests_by_status", {}) or {}
    if by_status:
        lines += ["", "## Handled quietly"]
        lines += [f"- {status}: {count}" for status, count in sorted(by_status.items())]
    return "\n".join(lines)


def next_reminder_time(
    window_start: datetime | None, now: datetime, hours_before: int = 12
) -> datetime | None:
    """When to remind a volunteer about a job, or ``None`` when there is no window."""
    if window_start is None:
        return None
    candidate = window_start - timedelta(hours=hours_before)
    return candidate if candidate > now else now

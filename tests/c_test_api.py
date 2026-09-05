"""The FastAPI surface, driven with a stubbed orchestrator over a seeded in-memory store."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.events import EventBus, normalize
from api.main import create_app
from porchlight.context import AppContext
from porchlight.models import (
    Decision,
    DecisionKind,
    DecisionOption,
    DecisionStatus,
    LogEvent,
    RequestStatus,
)
from porchlight.orchestrator import GraphUnavailableError, RunOutcome, SweepOutcome


class FakeOrchestrator:
    """Stands in for the Strands graph: records calls, returns believable outcomes."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.processed: list[str] = []
        self.resumed: list[tuple[str, str, str | None]] = []
        self.swept = 0
        self.briefed: list[date] = []
        self.raise_graph_unavailable = False
        self.decision_to_create: Decision | None = None

    def process_request(self, request_id: str) -> RunOutcome:
        if self.raise_graph_unavailable:
            raise GraphUnavailableError("porchlight.graph is not available yet")
        self.processed.append(request_id)
        request = self.ctx.store.get_request(request_id)
        assert request is not None, "the API must persist the request before running it"
        decisions: list[Decision] = []
        if self.decision_to_create is not None:
            decision = self.decision_to_create.model_copy(update={"request_id": request_id})
            self.ctx.store.put_decision(decision)
            decisions.append(decision)
        request.status = RequestStatus.ESCALATED if decisions else RequestStatus.CONFIRMED
        self.ctx.store.put_request(request)
        self.ctx.store.append_log(
            LogEvent(request_id=request_id, agent="matcher", summary="Asked Maria Alvarez")
        )
        self.ctx.emit(
            {
                "type": "node_end",
                "request_id": request_id,
                "agent": "matcher",
                "summary": "matched",
            }
        )
        return RunOutcome(
            request_id=request_id,
            status=request.status,
            decisions_created=decisions,
            log_events=1,
            interrupted=bool(decisions),
            summary="Maria Alvarez accepted" if not decisions else "Needs the coordinator",
        )

    def resume_decision(self, decision_id: str, option_id: str, note: str | None = None) -> RunOutcome:
        self.resumed.append((decision_id, option_id, note))
        decision = self.ctx.store.get_decision(decision_id)
        assert decision is not None
        decision.resolve(option_id, note, self.ctx.now())
        self.ctx.store.put_decision(decision)
        return RunOutcome(
            request_id=decision.request_id or decision_id,
            status=RequestStatus.CONFIRMED,
            summary=f"resumed with {option_id}",
        )

    def sweep(self) -> SweepOutcome:
        self.swept += 1
        return SweepOutcome(messages_sent=2, timed_out=["req_hist_snow"], summary="two reminders sent")

    def brief(self, day: date) -> str:
        self.briefed.append(day)
        return f"## Brief for {day.isoformat()}\n\nAll quiet."


@pytest.fixture
def orchestrator(ctx: AppContext) -> FakeOrchestrator:
    """A stubbed orchestrator bound to the test context."""
    return FakeOrchestrator(ctx)


@pytest.fixture
def client(ctx: AppContext, orchestrator: FakeOrchestrator) -> Iterator[TestClient]:
    """A TestClient over an app wired to the seeded in-memory context."""
    app = create_app(context_factory=lambda: ctx, orchestrator_factory=lambda _ctx: orchestrator)
    with TestClient(app) as test_client:
        yield test_client


def _open_decision(ctx: AppContext, **overrides: Any) -> Decision:
    """Store and return an open decision card."""
    fields: dict[str, Any] = {
        "request_id": "req_hist_dialysis",
        "kind": DecisionKind.UNMATCHED,
        "title": "Nobody free for Thursday's dialysis ride",
        "context": "Three volunteers asked, none available.",
        "recommendation": "Widen the pool to Northgate.",
        "options": [
            DecisionOption(id="widen_pool", label="Widen the pool"),
            DecisionOption(id="i_will_handle", label="I'll take it"),
        ],
        **overrides,
    }
    decision = Decision(**fields)
    ctx.store.put_decision(decision)
    return decision


# --------------------------------------------------------------------------------------
# Health & porch
# --------------------------------------------------------------------------------------


def test_health_reports_the_wiring(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["mode"] == "demo"
    assert body["model_provider"] == "mock"
    assert body["store"] == "sqlite"
    assert body["orchestrator"] == "FakeOrchestrator"
    assert isinstance(body["graph_available"], bool)


def test_cors_is_open(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_porch_is_dark_when_nothing_needs_the_coordinator(client: TestClient) -> None:
    body = client.get("/api/porch").json()
    assert body["light_on"] is False
    assert body["status_line"].endswith("nothing needs you.")
    assert body["open_decisions"] == []
    assert body["group"]["name"] == "Maple Street Mutual Aid"
    assert "handled_autonomously" in body["stats"]


def test_porch_lights_up_and_counts_open_cards(ctx: AppContext, client: TestClient) -> None:
    _open_decision(ctx)
    body = client.get("/api/porch").json()
    assert body["light_on"] is True
    assert len(body["open_decisions"]) == 1
    assert "1 needs you." in body["status_line"]


def test_the_quiet_log_hides_housekeeping_until_asked(ctx: AppContext, client: TestClient) -> None:
    """The porch shows the story; ``?all=1`` shows the mechanics behind it."""
    ctx.store.append_log(LogEvent(summary="Asked Maria: Ride to dialysis Thursday 9am."))
    ctx.store.append_log(LogEvent(summary="Looked up Ezra Okafor — 4 past requests.", visible=False))

    quiet = [row["summary"] for row in client.get("/api/porch").json()["quiet_log"]]
    assert "Asked Maria: Ride to dialysis Thursday 9am." in quiet
    assert not any("Looked up" in summary for summary in quiet)

    everything = [row["summary"] for row in client.get("/api/porch?all=1").json()["quiet_log"]]
    assert any("Looked up" in summary for summary in everything)


def test_status_line_pluralises_two_cards(ctx: AppContext, client: TestClient) -> None:
    _open_decision(ctx)
    _open_decision(ctx, title="Second card")
    assert "2 need you." in client.get("/api/porch").json()["status_line"]


# --------------------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------------------


def test_lists_and_filters_requests(client: TestClient) -> None:
    every = client.get("/api/requests").json()
    assert len(every) == 4
    completed = client.get("/api/requests", params={"status": "completed"}).json()
    assert {row["id"] for row in completed} == {row["id"] for row in every}


def test_request_detail_includes_attempts_messages_and_log(client: TestClient) -> None:
    body = client.get("/api/requests/req_hist_dialysis").json()
    assert body["request"]["id"] == "req_hist_dialysis"
    assert body["attempts"] == []
    assert body["messages"] == []
    assert isinstance(body["log"], list)


def test_unknown_request_is_a_404(client: TestClient) -> None:
    assert client.get("/api/requests/req_nope").status_code == 404


# --------------------------------------------------------------------------------------
# Inbox
# --------------------------------------------------------------------------------------


def test_inbox_creates_a_request_and_runs_it(
    ctx: AppContext, client: TestClient, orchestrator: FakeOrchestrator
) -> None:
    response = client.post(
        "/api/inbox",
        json={"text": "Ride to dialysis Thursday 9am please", "source": "sms", "contact": "+1-555-0201"},
    )
    assert response.status_code == 200
    outcome = response.json()

    assert outcome["status"] == "confirmed"
    assert outcome["interrupted"] is False
    assert orchestrator.processed == [outcome["request_id"]]
    stored = ctx.store.get_request(outcome["request_id"])
    assert stored is not None
    assert stored.raw_text.startswith("Ride to dialysis")
    assert stored.requester_id == "rqr_okafor"


def test_inbox_creates_a_decision_card_when_the_graph_interrupts(
    ctx: AppContext, client: TestClient, orchestrator: FakeOrchestrator
) -> None:
    orchestrator.decision_to_create = Decision(
        kind=DecisionKind.SAFETY,
        title="Child alone, stove on",
        options=[DecisionOption(id="call_911", label="Tell them to call 911")],
    )
    outcome = client.post(
        "/api/inbox", json={"text": "kid home alone and the stove is on", "source": "sms"}
    ).json()

    assert outcome["interrupted"] is True
    assert outcome["decisions_created"][0]["kind"] == "safety"
    assert client.get("/api/porch").json()["light_on"] is True


def test_inbox_rejects_an_empty_message(client: TestClient) -> None:
    assert client.post("/api/inbox", json={"text": "   ", "source": "sms"}).status_code == 422


def test_inbox_returns_503_when_the_graph_is_missing(
    client: TestClient, orchestrator: FakeOrchestrator
) -> None:
    orchestrator.raise_graph_unavailable = True
    response = client.post("/api/inbox", json={"text": "anything", "source": "form"})
    assert response.status_code == 503
    assert "not available" in response.json()["detail"]


# --------------------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------------------


def test_lists_open_decisions(ctx: AppContext, client: TestClient) -> None:
    _open_decision(ctx)
    rows = client.get("/api/decisions", params={"status": "open"}).json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "unmatched"


def test_resolving_a_decision_resumes_the_graph(
    ctx: AppContext, client: TestClient, orchestrator: FakeOrchestrator
) -> None:
    decision = _open_decision(ctx)
    response = client.post(
        f"/api/decisions/{decision.id}/resolve",
        json={"option_id": "widen_pool", "note": "try Northgate"},
    )

    assert response.status_code == 200
    assert response.json()["summary"] == "resumed with widen_pool"
    assert orchestrator.resumed == [(decision.id, "widen_pool", "try Northgate")]
    stored = ctx.store.get_decision(decision.id)
    assert stored is not None and stored.status is DecisionStatus.RESOLVED


def test_resolving_rejects_an_unknown_option(ctx: AppContext, client: TestClient) -> None:
    decision = _open_decision(ctx)
    response = client.post(f"/api/decisions/{decision.id}/resolve", json={"option_id": "nope"})
    assert response.status_code == 422


def test_resolving_twice_is_a_conflict(ctx: AppContext, client: TestClient) -> None:
    decision = _open_decision(ctx)
    client.post(f"/api/decisions/{decision.id}/resolve", json={"option_id": "widen_pool"})
    again = client.post(f"/api/decisions/{decision.id}/resolve", json={"option_id": "widen_pool"})
    assert again.status_code == 409


def test_resolving_an_unknown_decision_is_a_404(client: TestClient) -> None:
    response = client.post("/api/decisions/dec_nope/resolve", json={"option_id": "approve"})
    assert response.status_code == 404


# --------------------------------------------------------------------------------------
# Volunteers & log
# --------------------------------------------------------------------------------------


def test_volunteers_carry_a_load_bar(client: TestClient) -> None:
    rows = client.get("/api/volunteers").json()
    assert len(rows) >= 10
    maria = next(row for row in rows if row["id"] == "vol_maria")
    assert maria["load"]["max_per_week"] == maria["max_per_week"]
    assert maria["load"]["this_week"] >= 0
    assert "drive" in maria["skills"]


def test_volunteers_can_be_filtered_by_zone(client: TestClient) -> None:
    rows = client.get("/api/volunteers", params={"zone": "Riverside"}).json()
    assert rows
    assert all("Riverside" in row["zones"] for row in rows)


def test_log_is_newest_first_and_filterable(ctx: AppContext, client: TestClient) -> None:
    ctx.store.append_log(LogEvent(request_id="req_hist_dialysis", agent="steward", summary="Confirmed"))
    ctx.store.append_log(LogEvent(request_id="req_hist_snow", agent="steward", summary="Other request"))

    scoped = client.get("/api/log", params={"request_id": "req_hist_dialysis"}).json()
    assert [row["summary"] for row in scoped] == ["Confirmed"]
    assert len(client.get("/api/log", params={"limit": 1}).json()) == 1


def test_log_rejects_a_bad_since(client: TestClient) -> None:
    assert client.get("/api/log", params={"since": "yesterday"}).status_code == 422


# --------------------------------------------------------------------------------------
# Sweep & brief
# --------------------------------------------------------------------------------------


def test_sweep_returns_the_outcome(client: TestClient, orchestrator: FakeOrchestrator) -> None:
    body = client.post("/api/sweep").json()
    assert body["messages_sent"] == 2
    assert body["timed_out"] == ["req_hist_snow"]
    assert orchestrator.swept == 1


def test_brief_defaults_to_today(client: TestClient, orchestrator: FakeOrchestrator) -> None:
    body = client.get("/api/brief").json()
    assert body["day"] == "2026-09-08"
    assert body["markdown"].startswith("## Brief for 2026-09-08")
    assert orchestrator.briefed == [date(2026, 9, 8)]


def test_brief_accepts_a_day(client: TestClient) -> None:
    assert client.get("/api/brief", params={"day": "2026-09-01"}).json()["day"] == "2026-09-01"


def test_brief_rejects_a_bad_day(client: TestClient) -> None:
    assert client.get("/api/brief", params={"day": "not-a-day"}).status_code == 422


# --------------------------------------------------------------------------------------
# Demo endpoints
# --------------------------------------------------------------------------------------


def test_demo_samples_are_served(client: TestClient) -> None:
    rows = client.get("/api/demo/samples").json()
    assert len(rows) >= 12
    assert {row["expected"] for row in rows} <= {"quiet", "card"}
    assert all(row["text"] for row in rows)


def test_demo_reset_reseeds(ctx: AppContext, client: TestClient) -> None:
    ctx.store.append_log(LogEvent(summary="something that should be wiped"))
    body = client.post("/api/demo/reset").json()
    assert body["ok"] is True
    assert body["volunteers"] >= 10
    assert ctx.store.list_log() == []


def test_demo_run_day_runs_in_the_background(client: TestClient, orchestrator: FakeOrchestrator) -> None:
    response = client.post("/api/demo/run_day", json={"count": 3})
    assert response.status_code == 202
    assert response.json()["started"] is True
    # The background task shares the loop; any later request lets it finish.
    for _ in range(40):
        if len(orchestrator.processed) >= 3:
            break
        client.get("/api/health")
    assert len(orchestrator.processed) >= 3


# --------------------------------------------------------------------------------------
# SSE
# --------------------------------------------------------------------------------------


def test_events_stream_yields_a_connected_frame(client: TestClient) -> None:
    body = client.get("/api/events", params={"limit": 1}).text
    payload = json.loads(body.split("data: ", 1)[1].split("\r\n", 1)[0])
    assert payload["type"] == "log"
    assert payload["agent"] == "system"
    assert "listening" in payload["summary"]


def test_events_stream_replays_recent_events(ctx: AppContext, client: TestClient) -> None:
    ctx.emit({"type": "tool_call", "agent": "matcher", "summary": "find_candidates"})
    body = client.get("/api/events", params={"replay": 5, "limit": 1}).text
    assert "find_candidates" in body


# --------------------------------------------------------------------------------------
# EventBus
# --------------------------------------------------------------------------------------


def test_normalize_fills_in_the_contract_shape() -> None:
    event = normalize({"summary": "hello"})
    assert event["type"] == "log"
    assert event["detail"] == {}
    assert event["request_id"] is None
    assert event["ts"]


def test_bus_keeps_history_without_subscribers() -> None:
    bus = EventBus()
    bus.publish({"type": "log", "summary": "one"})
    bus.publish({"type": "log", "summary": "two"})
    assert [event["summary"] for event in bus.recent(5)] == ["one", "two"]
    assert bus.recent(0) == []


async def test_bus_delivers_to_subscribers() -> None:
    bus = EventBus()
    with bus.subscribe() as queue:
        assert bus.subscriber_count == 1
        bus.publish({"type": "decision", "summary": "porch light on"})
        event = await queue.get()
    assert event["summary"] == "porch light on"
    assert bus.subscriber_count == 0

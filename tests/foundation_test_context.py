"""Settings, AppContext assembly, and the tool surface."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from strands.types.tools import ToolContext

from porchlight import tools as porchlight_tools
from porchlight.config import Settings, get_settings, reset_settings
from porchlight.context import AppContext, NullChannel, build_context, get_ctx
from porchlight.models import (
    AidRequest,
    Category,
    MessageStatus,
    OutboundMessage,
    RequestStatus,
    Source,
)
from porchlight.store.sqlite_store import SqliteStore


def _tool_context(ctx: AppContext | None) -> ToolContext:
    return ToolContext(
        tool_use={"toolUseId": "t1", "name": "test", "input": {}},
        agent=None,
        invocation_state={} if ctx is None else {"ctx": ctx},
    )


# --- settings --------------------------------------------------------------------------


def test_settings_defaults_match_the_contract() -> None:
    settings = Settings()
    assert settings.mode == "demo"
    assert settings.store == "sqlite"
    assert settings.tools == "local"
    assert settings.sqlite_path == "data/local/porchlight.db"
    assert settings.session_dir == "data/sessions"
    assert settings.dynamo_table == "porchlight"
    assert settings.group_name == "Maple Street Mutual Aid"
    assert settings.quiet_hours == (21, 8)
    assert settings.petty_cash_limit == 40.0
    assert settings.max_candidates == 3
    assert settings.escalate_hours_before_window == 6
    assert settings.confidence_threshold == 0.55
    assert settings.is_demo


def test_settings_read_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORCHLIGHT_MODE", "live")
    monkeypatch.setenv("PORCHLIGHT_MAX_CANDIDATES", "7")
    monkeypatch.setenv("PORCHLIGHT_QUIET_HOURS", "[22, 7]")
    settings = Settings()
    assert settings.mode == "live"
    assert settings.max_candidates == 7
    assert settings.quiet_hours == (22, 7)
    assert not settings.is_demo


def test_aws_region_falls_back_to_standard_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORCHLIGHT_AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    assert Settings().aws_region == "eu-west-1"

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    assert Settings().aws_region == "ap-south-1"

    monkeypatch.setenv("PORCHLIGHT_AWS_REGION", "us-east-2")
    assert Settings().aws_region == "us-east-2"


def test_get_settings_is_cached_until_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORCHLIGHT_GROUP_NAME", "First Group")
    reset_settings()
    assert get_settings().group_name == "First Group"
    monkeypatch.setenv("PORCHLIGHT_GROUP_NAME", "Second Group")
    assert get_settings().group_name == "First Group"
    reset_settings()
    assert get_settings().group_name == "Second Group"


# --- context ---------------------------------------------------------------------------


def test_build_context_in_demo_mode(tmp_path) -> None:
    settings = Settings(mode="demo", store="sqlite", sqlite_path=str(tmp_path / "demo.db"))
    context = build_context(settings)
    assert isinstance(context.store, SqliteStore)
    assert context.channel is not None
    assert context.now().tzinfo is not None
    assert os.path.exists(tmp_path / "demo.db")


def test_build_context_accepts_overrides(settings: Settings, empty_store: SqliteStore) -> None:
    events: list[dict] = []
    context = build_context(
        settings, store=empty_store, channel=NullChannel(), memory=None, emit=events.append
    )
    assert context.store is empty_store
    context.emit({"type": "log"})
    assert events == [{"type": "log"}]


def test_build_context_rejects_unknown_overrides(settings: Settings) -> None:
    with pytest.raises(TypeError):
        build_context(settings, nonsense=1)


def test_get_ctx_requires_an_app_context(ctx: AppContext) -> None:
    assert get_ctx(_tool_context(ctx)) is ctx
    with pytest.raises(RuntimeError):
        get_ctx(_tool_context(None))


def test_null_channel_records_sends_and_schedules(clock) -> None:
    channel = NullChannel()
    sent = channel.send(OutboundMessage(body="hi"))
    assert sent.status is MessageStatus.SENT and sent.sent_at is not None
    later = clock.now() + timedelta(hours=2)
    scheduled = channel.schedule(OutboundMessage(body="later"), later)
    assert scheduled.status is MessageStatus.SCHEDULED and scheduled.scheduled_for == later
    assert channel.fetch_replies("req_1") == []
    assert "sent=1" in repr(channel)


# --- tools -----------------------------------------------------------------------------


def test_tool_groups_are_exported_and_consistent() -> None:
    names = {t.tool_name for t in porchlight_tools.ALL_TOOLS}
    assert names == {
        "lookup_requester_history",
        "find_candidates",
        "volunteer_load",
        "find_similar_open_requests",
        "recall_memory",
        "remember",
        "send_message",
        "schedule_message",
        "read_replies",
        "assign_volunteer",
        "record_attempt",
        "update_request",
        "close_request",
        "query_requests",
        "query_log",
    }
    for group in (
        porchlight_tools.INTAKE_TOOLS,
        porchlight_tools.MATCHER_TOOLS,
        porchlight_tools.OUTREACH_TOOLS,
        porchlight_tools.STEWARD_TOOLS,
        porchlight_tools.BRIEF_TOOLS,
    ):
        assert group
        assert {t.tool_name for t in group} <= names


def test_every_tool_has_a_useful_description() -> None:
    for tool in porchlight_tools.ALL_TOOLS:
        description = tool.tool_spec["description"]
        assert len(description) > 40, tool.tool_name


def _seeded_request(ctx: AppContext) -> AidRequest:
    request = AidRequest(
        id="req_test",
        source=Source.SMS,
        raw_text="Ride to dialysis Thursday 9am",
        requester_id="rqr_okafor",
        category=Category.RIDE,
        summary="Ride to dialysis",
        location_zone="Maple St",
        status=RequestStatus.MATCHING,
        created_at=ctx.clock.now(),
        updated_at=ctx.clock.now(),
    )
    ctx.store.put_request(request)
    return request


def test_lookup_requester_history_finds_a_known_person(ctx: AppContext) -> None:
    result = porchlight_tools.lookup_requester_history("+1-555-0201", tool_context=_tool_context(ctx))
    assert result["requester"]["id"] == "rqr_okafor"
    assert any(r["id"] == "req_hist_dialysis" for r in result["recent_requests"])

    unknown = porchlight_tools.lookup_requester_history("+1-555-9999", tool_context=_tool_context(ctx))
    assert unknown == {"requester": None, "recent_requests": []}


def test_find_candidates_ranks_by_skill_and_zone(ctx: AppContext) -> None:
    _seeded_request(ctx)
    candidates = porchlight_tools.find_candidates("req_test", tool_context=_tool_context(ctx), limit=3)
    assert 1 <= len(candidates) <= 3
    assert all(set(c) >= {"volunteer_id", "name", "score", "reasons", "load_this_week"} for c in candidates)
    assert candidates == sorted(candidates, key=lambda c: c["score"], reverse=True)
    assert porchlight_tools.find_candidates("req_missing", tool_context=_tool_context(ctx)) == []


def test_volunteer_load_reports_the_weekly_cap(ctx: AppContext) -> None:
    load = porchlight_tools.volunteer_load("vol_maria", tool_context=_tool_context(ctx))
    assert load["max_per_week"] == 3
    assert load["this_week"] >= 0
    assert "error" in porchlight_tools.volunteer_load("vol_nope", tool_context=_tool_context(ctx))


def test_send_and_read_messages(ctx: AppContext) -> None:
    _seeded_request(ctx)
    sent = porchlight_tools.send_message(
        "req_test", "volunteer", "vol_maria", "Can you drive Ezra?", tool_context=_tool_context(ctx)
    )
    assert sent["status"] == "sent"
    assert ctx.store.list_messages(request_id="req_test")
    assert porchlight_tools.read_replies("req_test", tool_context=_tool_context(ctx)) == []


def test_schedule_message_validates_its_timestamp(ctx: AppContext) -> None:
    _seeded_request(ctx)
    ok = porchlight_tools.schedule_message(
        "req_test",
        "requester",
        "rqr_okafor",
        "Reminder tomorrow",
        "2026-09-09T13:00:00Z",
        tool_context=_tool_context(ctx),
    )
    assert ok["status"] == "scheduled"
    bad = porchlight_tools.schedule_message(
        "req_test", "requester", "rqr_okafor", "x", "not-a-time", tool_context=_tool_context(ctx)
    )
    assert "error" in bad


def test_record_attempt_then_assign_volunteer(ctx: AppContext) -> None:
    _seeded_request(ctx)
    first = porchlight_tools.record_attempt(
        "req_test", "vol_maria", "pending", tool_context=_tool_context(ctx)
    )
    assert first["attempts"] == 1
    declined = porchlight_tools.record_attempt(
        "req_test", "vol_maria", "declined", note="busy", tool_context=_tool_context(ctx)
    )
    assert declined["attempts"] == 1

    porchlight_tools.record_attempt("req_test", "vol_hank", "pending", tool_context=_tool_context(ctx))
    assigned = porchlight_tools.assign_volunteer("req_test", "vol_hank", tool_context=_tool_context(ctx))
    assert assigned["status"] == "confirmed"
    stored = ctx.store.get_request("req_test")
    assert stored is not None
    assert stored.assigned_volunteer_id == "vol_hank"
    assert [a.outcome for a in stored.attempts] == ["declined", "accepted"]

    assert "error" in porchlight_tools.record_attempt(
        "req_test", "vol_hank", "exploded", tool_context=_tool_context(ctx)
    )
    assert "error" in porchlight_tools.assign_volunteer(
        "req_test", "vol_nope", tool_context=_tool_context(ctx)
    )


def test_update_and_close_request(ctx: AppContext) -> None:
    _seeded_request(ctx)
    updated = porchlight_tools.update_request(
        "req_test", tool_context=_tool_context(ctx), fields={"status": "awaiting_reply"}
    )
    assert updated["status"] == "awaiting_reply"

    kwargs_style = porchlight_tools.update_request(
        "req_test", tool_context=_tool_context(ctx), urgency="high"
    )
    assert kwargs_style["urgency"] == "high"

    assert "error" in porchlight_tools.update_request(
        "req_test", tool_context=_tool_context(ctx), fields={"nope": 1}
    )
    assert "error" in porchlight_tools.update_request(
        "req_test", tool_context=_tool_context(ctx), fields={"status": "not-a-status"}
    )

    closed = porchlight_tools.close_request(
        "req_test", "completed", note="done", tool_context=_tool_context(ctx)
    )
    assert closed["status"] == "completed"
    assert "error" in porchlight_tools.close_request("req_test", "exploded", tool_context=_tool_context(ctx))


def test_query_requests_and_log(ctx: AppContext) -> None:
    _seeded_request(ctx)
    porchlight_tools.close_request("req_test", "completed", tool_context=_tool_context(ctx))

    completed = porchlight_tools.query_requests(tool_context=_tool_context(ctx), status="completed")
    assert any(r["id"] == "req_test" for r in completed)
    assert "error" in porchlight_tools.query_requests(tool_context=_tool_context(ctx), status="bogus")[0]

    events = porchlight_tools.query_log(tool_context=_tool_context(ctx), request_id="req_test")
    assert events and events[0]["request_id"] == "req_test"
    assert ctx.emitted  # type: ignore[attr-defined]


def test_recall_and_remember_without_a_memory_backend(ctx: AppContext) -> None:
    assert porchlight_tools.recall_memory("anything", tool_context=_tool_context(ctx)) == []
    stored = porchlight_tools.remember(
        "Prefers mornings.", about_id="vol_maria", tool_context=_tool_context(ctx)
    )
    assert stored["stored"] is True
    maria = ctx.store.get_volunteer("vol_maria")
    assert maria is not None and "Prefers mornings." in maria.notes

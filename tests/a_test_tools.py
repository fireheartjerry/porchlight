"""Every Porchlight tool, exercised directly and through a real Strands agent."""

from __future__ import annotations

import json
from typing import Any

import pytest
from a_helpers import make_ctx, make_request, tool_ctx
from strands import Agent

from porchlight.models import LogKind, MessageStatus, RequestStatus
from porchlight.testing.mock_model import MockModel, MockTurn
from porchlight.tools import (
    ALL_TOOLS,
    BRIEF_TOOLS,
    INTAKE_TOOLS,
    MATCHER_TOOLS,
    OUTREACH_TOOLS,
    STEWARD_TOOLS,
    assign_volunteer,
    close_request,
    find_candidates,
    lookup_requester_history,
    query_log,
    query_requests,
    read_replies,
    recall_memory,
    record_attempt,
    remember,
    schedule_message,
    send_message,
    update_request,
    volunteer_load,
)

CONTRACT_NAMES = {
    "lookup_requester_history",
    "find_candidates",
    "volunteer_load",
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


@pytest.fixture
def actx(store, clock):
    """A context with the simulated channel and SQLite long-term memory."""
    return make_ctx(store, clock)


@pytest.fixture
def request_id(store, clock) -> str:
    return make_request(store, clock).id


def tc(ctx, name: str = "tool"):
    return tool_ctx(ctx, tool_name=name)


# --------------------------------------------------------------------------------------
# Contract shape
# --------------------------------------------------------------------------------------


def test_tool_names_match_the_contract():
    assert {t.tool_name for t in ALL_TOOLS} == CONTRACT_NAMES


def test_tool_groups_are_subsets_with_the_documented_membership():
    for group in (INTAKE_TOOLS, MATCHER_TOOLS, OUTREACH_TOOLS, STEWARD_TOOLS, BRIEF_TOOLS):
        assert set(group) <= set(ALL_TOOLS)
    assert {t.tool_name for t in MATCHER_TOOLS} == {"find_candidates", "volunteer_load", "recall_memory"}
    assert {t.tool_name for t in BRIEF_TOOLS} == {"query_requests", "query_log"}


def test_every_tool_has_a_model_readable_description():
    for tool in ALL_TOOLS:
        spec = tool.tool_spec
        assert len(spec["description"]) > 40, tool.tool_name
        assert spec["inputSchema"]["json"]["type"] == "object"


# --------------------------------------------------------------------------------------
# Direct calls
# --------------------------------------------------------------------------------------


def test_lookup_requester_history_finds_by_contact_and_by_name(actx):
    by_contact = lookup_requester_history("+1-555-0201", tool_context=tc(actx))
    assert by_contact["requester"] is not None
    by_name = lookup_requester_history(by_contact["requester"]["name"], tool_context=tc(actx))
    assert by_name["requester"]["id"] == by_contact["requester"]["id"]
    assert isinstance(by_name["recent_requests"], list)


def test_lookup_requester_history_returns_none_for_a_stranger(actx):
    assert lookup_requester_history("+1-555-9999", tool_context=tc(actx)) == {
        "requester": None,
        "recent_requests": [],
    }


def test_find_candidates_ranks_and_explains(actx, request_id):
    candidates = find_candidates(request_id, tool_context=tc(actx), limit=3)
    assert 1 <= len(candidates) <= 3
    assert candidates[0]["reasons"]
    assert candidates == sorted(candidates, key=lambda c: c["score"], reverse=True)
    assert any(event["type"] == "tool_call" for event in actx.emitted)


def test_find_candidates_skips_volunteers_already_asked(actx, store, clock, request_id):
    first = find_candidates(request_id, tool_context=tc(actx))[0]["volunteer_id"]
    record_attempt(request_id, first, "declined", tool_context=tc(actx))
    again = find_candidates(request_id, tool_context=tc(actx))
    assert first not in {c["volunteer_id"] for c in again}


def test_find_candidates_on_an_unknown_request_is_empty(actx):
    assert find_candidates("req_nope", tool_context=tc(actx)) == []


def test_volunteer_load_reports_the_weekly_window(actx):
    load = volunteer_load("vol_maria", tool_context=tc(actx))
    assert load.keys() == {"this_week", "max_per_week", "last_active"}
    assert load["max_per_week"] == 3
    assert "error" in volunteer_load("vol_nobody", tool_context=tc(actx))


def test_send_message_goes_through_the_channel_and_is_logged(actx, store, request_id):
    result = send_message(
        request_id, "volunteer", "vol_maria", "Could you drive Ezra Thursday 9am?", tool_context=tc(actx)
    )
    assert result["status"] == MessageStatus.SENT
    stored = store.list_messages(request_id=request_id)
    assert [m.id for m in stored] == [result["message_id"]]
    assert stored[0].sent_at is not None
    logged = store.list_log(request_id=request_id)
    assert any(e.kind == LogKind.MESSAGE_SENT and "Maria Alvarez" in e.summary for e in logged)
    assert any(e["type"] == "message" for e in actx.emitted)


def test_send_message_rejects_a_bad_recipient_kind_and_empty_body(actx, request_id):
    assert "error" in send_message(request_id, "dog", "vol_maria", "hi", tool_context=tc(actx))
    assert "error" in send_message(request_id, "volunteer", "vol_maria", "   ", tool_context=tc(actx))


def test_schedule_message_queues_for_later(actx, store, request_id):
    result = schedule_message(
        request_id,
        "requester",
        "rqr_okafor",
        "Just checking Maria arrived this morning.",
        "2026-09-10T15:00:00Z",
        tool_context=tc(actx),
    )
    assert result["status"] == MessageStatus.SCHEDULED
    assert result["scheduled_for"].startswith("2026-09-10T15:00")
    scheduled = store.list_messages(status=MessageStatus.SCHEDULED)
    assert scheduled and scheduled[0].scheduled_for is not None


def test_schedule_message_rejects_an_unparseable_time(actx, request_id):
    result = schedule_message(
        request_id, "volunteer", "vol_maria", "hello", "next tuesday-ish", tool_context=tc(actx)
    )
    assert "error" in result


def test_read_replies_returns_what_the_channel_produced(actx, request_id):
    send_message(request_id, "volunteer", "vol_maria", "Can you help Thursday?", tool_context=tc(actx))
    replies = read_replies(request_id, tool_context=tc(actx))
    assert len(replies) == 1
    assert replies[0]["from_volunteer_id"] == "vol_maria"
    assert replies[0]["text"]


def test_assign_volunteer_confirms_and_credits(actx, store, request_id):
    before = store.get_volunteer("vol_hank").stats.accepted
    result = assign_volunteer(request_id, "vol_hank", tool_context=tc(actx))
    assert result["status"] == RequestStatus.CONFIRMED
    updated = store.get_request(request_id)
    assert updated.assigned_volunteer_id == "vol_hank"
    assert updated.attempts[-1].outcome == "accepted"
    assert store.get_volunteer("vol_hank").stats.accepted == before + 1


def test_assign_volunteer_validates_ids(actx, request_id):
    assert "error" in assign_volunteer("req_nope", "vol_hank", tool_context=tc(actx))
    assert "error" in assign_volunteer(request_id, "vol_nope", tool_context=tc(actx))


def test_record_attempt_updates_a_pending_attempt_then_appends(actx, store, request_id):
    first = record_attempt(request_id, "vol_devon", "pending", tool_context=tc(actx))
    assert first["attempts"] == 1
    second = record_attempt(request_id, "vol_devon", "declined", tool_context=tc(actx), note="weekends only")
    assert second["attempts"] == 1
    attempts = store.get_request(request_id).attempts
    assert attempts[0].outcome == "declined" and attempts[0].note == "weekends only"
    third = record_attempt(request_id, "vol_hank", "pending", tool_context=tc(actx))
    assert third["attempts"] == 2
    assert store.get_volunteer("vol_devon").stats.declined == 12


def test_record_attempt_rejects_an_unknown_outcome(actx, request_id):
    assert "error" in record_attempt(request_id, "vol_devon", "maybe", tool_context=tc(actx))


def test_update_request_validates_against_the_model(actx, store, request_id):
    updated = update_request(request_id, tool_context=tc(actx), status="awaiting_reply")
    assert updated["status"] == RequestStatus.AWAITING_REPLY
    assert store.get_request(request_id).status == RequestStatus.AWAITING_REPLY
    assert "error" in update_request(request_id, tool_context=tc(actx), status="on_fire")
    assert "error" in update_request(request_id, tool_context=tc(actx), nonsense=1)
    assert "error" in update_request("req_nope", tool_context=tc(actx), status="new")


def test_update_request_accepts_the_nested_fields_object(actx, store, request_id):
    updated = update_request(
        request_id, tool_context=tc(actx), fields={"urgency": "high", "constraints": ["wheelchair"]}
    )
    assert updated["urgency"] == "high"
    assert store.get_request(request_id).constraints == ["wheelchair"]


def test_close_request_completes_and_credits_everyone(actx, store, request_id):
    assign_volunteer(request_id, "vol_maria", tool_context=tc(actx))
    completed_before = store.get_volunteer("vol_maria").stats.completed
    history_before = store.get_requester("rqr_okafor").history_count
    result = close_request(request_id, "completed", tool_context=tc(actx), note="went fine")
    assert result["status"] == RequestStatus.COMPLETED
    assert store.get_volunteer("vol_maria").stats.completed == completed_before + 1
    assert store.get_requester("rqr_okafor").history_count == history_before + 1


def test_close_request_rejects_an_invalid_outcome(actx, request_id):
    assert "error" in close_request(request_id, "abandoned", tool_context=tc(actx))


def test_remember_writes_to_memory_and_pins_to_the_person(actx, store):
    result = remember(
        "Prefers mornings; call rather than text.",
        tool_context=tc(actx),
        about_id="vol_maria",
        kind="preference",
    )
    assert result["stored"] is True
    assert "Prefers mornings; call rather than text." in store.get_volunteer("vol_maria").notes
    assert actx.memory.count() == 1


def test_remember_without_memory_still_pins_and_says_so(store, clock):
    ctx = make_ctx(store, clock, with_memory=False)
    result = remember("Hard of hearing.", tool_context=tc(ctx), about_id="rqr_okafor")
    assert result["stored"] is True
    assert "Hard of hearing." in store.get_requester("rqr_okafor").notes
    assert any("no long-term memory configured" in e.summary for e in store.list_log())


def test_remember_refuses_an_empty_note(actx):
    assert "error" in remember("   ", tool_context=tc(actx))


def test_recall_memory_finds_what_was_remembered(actx):
    remember(
        "Mr. Okafor asks for Maria by name for his dialysis rides.",
        tool_context=tc(actx),
        about_id="vol_maria",
    )
    hits = recall_memory("dialysis ride", tool_context=tc(actx))
    assert hits and "Maria" in hits[0]["content"]
    assert hits[0]["metadata"]["about_id"] == "vol_maria"
    assert recall_memory("dialysis", tool_context=tc(actx), about="vol_devon") == []


def test_recall_memory_is_empty_without_a_store(store, clock):
    ctx = make_ctx(store, clock, with_memory=False)
    assert recall_memory("anything", tool_context=tc(ctx)) == []


def test_query_requests_filters_by_status_and_time(actx, store, clock, request_id):
    all_requests = query_requests(tool_context=tc(actx))
    assert any(r["id"] == request_id for r in all_requests)
    matching = query_requests(tool_context=tc(actx), status="matching")
    assert {r["status"] for r in matching} == {"matching"}
    future = query_requests(tool_context=tc(actx), since_iso="2030-01-01T00:00:00Z")
    assert future == []
    assert "error" in query_requests(tool_context=tc(actx), status="nope")[0]


def test_query_log_reads_back_what_the_tools_wrote(actx, request_id):
    send_message(request_id, "volunteer", "vol_maria", "Free Thursday?", tool_context=tc(actx))
    events = query_log(tool_context=tc(actx), request_id=request_id)
    assert events and events[0]["request_id"] == request_id
    assert query_log(tool_context=tc(actx), since_iso="2030-01-01T00:00:00Z") == []


def test_side_effect_tools_record_the_agent_that_acted(actx, store, request_id):
    ctx = tool_ctx(actx, agent="outreach")
    send_message(request_id, "volunteer", "vol_maria", "Free Thursday?", tool_context=ctx)
    assert any(e.agent == "outreach" for e in store.list_log(request_id=request_id))


# --------------------------------------------------------------------------------------
# Through a real Strands agent driven by MockModel
# --------------------------------------------------------------------------------------


def run_tool_through_agent(
    ctx, tool_name: str, tool_input: dict[str, Any], *, agent_name: str = "outreach"
) -> Any:
    """Drive a real ``Agent`` whose model is scripted to call exactly one tool."""
    model = MockModel(
        script=[MockTurn(tool_calls=[(tool_name, tool_input)]), MockTurn(text="Done.")],
        default_structured=False,
    )
    agent = Agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt="You are Porchlight's test agent.",
        name=agent_name,
        callback_handler=None,
    )
    result = agent("Handle this.", invocation_state={"ctx": ctx})
    assert result.stop_reason == "end_turn"
    for message in agent.messages:
        for block in message.get("content", []):
            if "toolResult" in block:
                payload = block["toolResult"]["content"][0].get("text", "")
                assert block["toolResult"]["status"] == "success", payload
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    return payload
    raise AssertionError("the agent never called a tool")


def test_agent_can_call_find_candidates(actx, request_id):
    candidates = run_tool_through_agent(
        actx, "find_candidates", {"request_id": request_id, "limit": 2}, agent_name="matcher"
    )
    assert len(candidates) == 2
    assert candidates[0]["score"] >= candidates[1]["score"]


def test_agent_can_send_a_message_and_it_is_attributed(actx, store, request_id):
    result = run_tool_through_agent(
        actx,
        "send_message",
        {
            "request_id": request_id,
            "to": "volunteer",
            "recipient_id": "vol_hank",
            "body": "Hank, could you drive Ezra to dialysis Thursday 9am?",
        },
    )
    assert result["status"] == MessageStatus.SENT
    logged = store.list_log(request_id=request_id)
    assert any(e.agent == "outreach" and e.kind == LogKind.MESSAGE_SENT for e in logged)


def test_agent_can_assign_a_volunteer(actx, store, request_id):
    result = run_tool_through_agent(
        actx,
        "assign_volunteer",
        {
            "request_id": request_id,
            "volunteer_id": "vol_maria",
        },
    )
    assert result["status"] == RequestStatus.CONFIRMED
    assert store.get_request(request_id).assigned_volunteer_id == "vol_maria"


def test_agent_can_update_a_request_through_the_nested_fields_schema(actx, store, request_id):
    result = run_tool_through_agent(
        actx, "update_request", {"request_id": request_id, "fields": {"status": "awaiting_reply"}}
    )
    assert result["status"] == RequestStatus.AWAITING_REPLY
    assert store.get_request(request_id).status == RequestStatus.AWAITING_REPLY


def test_agent_can_remember_and_recall(actx):
    stored = run_tool_through_agent(
        actx,
        "remember",
        {"content": "Devon only does weekends.", "about_id": "vol_devon", "kind": "preference"},
        agent_name="steward",
    )
    assert stored["stored"] is True
    recalled = run_tool_through_agent(actx, "recall_memory", {"query": "weekends"}, agent_name="matcher")
    assert recalled and "weekends" in recalled[0]["content"].lower()


@pytest.mark.parametrize(
    ("tool_name", "make_input"),
    [
        ("lookup_requester_history", lambda rid: {"contact_or_name": "+1-555-0201"}),
        ("volunteer_load", lambda rid: {"volunteer_id": "vol_maria"}),
        ("read_replies", lambda rid: {"request_id": rid}),
        ("record_attempt", lambda rid: {"request_id": rid, "volunteer_id": "vol_hank", "outcome": "pending"}),
        (
            "schedule_message",
            lambda rid: {
                "request_id": rid,
                "to": "requester",
                "recipient_id": "rqr_okafor",
                "body": "Confirming for tomorrow.",
                "send_at_iso": "2026-09-09T13:00:00Z",
            },
        ),
        ("close_request", lambda rid: {"request_id": rid, "outcome": "cancelled"}),
        ("query_requests", lambda rid: {}),
        ("query_log", lambda rid: {"limit": 5}),
    ],
)
def test_every_remaining_tool_runs_inside_an_agent(actx, request_id, tool_name, make_input):
    result = run_tool_through_agent(actx, tool_name, make_input(request_id))
    assert result is not None
    if isinstance(result, dict):
        assert "error" not in result

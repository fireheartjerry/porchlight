"""The demo-only volunteer simulator agent."""

from __future__ import annotations

import pytest
from a_helpers import make_ctx, make_request

from porchlight.channels.sim import SimChannel
from porchlight.context import NullChannel
from porchlight.models import Category, OutboundMessage, Recipient, ReplyIntent
from porchlight.sim import volunteer_sim as vs
from porchlight.sim.fixtures import SCRIPTED_REPLIES
from porchlight.sim.volunteer_sim import (
    SimReply,
    attach_volunteer_sim,
    build_system_prompt,
    build_user_prompt,
    guess_intent,
    make_volunteer_sim,
)


@pytest.fixture
def ctx(store, clock):
    return make_ctx(store, clock)


@pytest.fixture
def request_obj(store, clock):
    return make_request(store, clock)


# --- prompts --------------------------------------------------------------------------


def test_the_system_prompt_carries_the_persona(store):
    devon = store.get_volunteer("vol_devon")
    prompt = build_system_prompt(devon)
    assert devon.name in prompt
    assert "busy contractor" in prompt
    assert "Northgate" in prompt
    assert "Sat 08:00-18:00" in prompt
    assert "one or two short, casual sentences" in prompt


def test_a_volunteer_without_a_persona_still_gets_a_prompt(store):
    plain = store.get_volunteer("vol_maria").model_copy(deep=True)
    plain.persona = None
    plain.availability = []
    plain.notes = []
    prompt = build_system_prompt(plain)
    assert "ordinary, friendly neighbour" in prompt
    assert "no fixed windows on file" in prompt


def test_the_user_prompt_states_the_job_and_the_message(store, request_obj):
    prompt = build_user_prompt(
        store.get_volunteer("vol_maria"), request_obj, "Free Thursday 9am?", "America/Toronto"
    )
    assert "Free Thursday 9am?" in prompt
    assert "Ride to dialysis and back" in prompt
    assert "Maple St" in prompt
    assert "Thursday 10 Sep at 09:00" in prompt


def test_a_flexible_request_says_so(store, clock):
    request = make_request(store, clock, flexible=True)
    prompt = build_user_prompt(store.get_volunteer("vol_maria"), request, "any time?")
    assert "(flexible)" in prompt


def test_an_unscheduled_request_says_no_time_is_fixed(store, clock):
    request = make_request(store, clock, window_start=None)
    prompt = build_user_prompt(store.get_volunteer("vol_maria"), request, "when suits?")
    assert "no time fixed yet" in prompt


# --- intent ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes! Happy to. Morning is perfect.", ReplyIntent.ACCEPT),
        ("Sorry, I'm away that week.", ReplyIntent.DECLINE),
        ("Could we make it 3pm instead? I finish work at 2:30.", ReplyIntent.COUNTER),
        ("How old is the child? If it's fine with the parent I can do it.", ReplyIntent.CONCERN),
        ("hmm", ReplyIntent.UNCLEAR),
    ],
)
def test_guess_intent_labels_the_scripted_lines(text, expected):
    assert guess_intent(text) == expected


def test_sim_reply_rejects_unknown_fields():
    assert SimReply(text="ok", intent="accept").intent == ReplyIntent.ACCEPT
    with pytest.raises(ValueError):
        SimReply(text="ok", intent="accept", mood="grumpy")


# --- the agent ------------------------------------------------------------------------


def test_the_simulator_replies_with_the_scripted_line_under_the_mock_model(ctx, store, request_obj):
    reply = make_volunteer_sim(ctx)
    maria = store.get_volunteer("vol_maria")
    answer = reply(maria, request_obj, "Maria, could you drive Ezra Thursday 9am?")
    assert answer == SCRIPTED_REPLIES["vol_maria"][0]


def test_replies_cycle_per_volunteer_and_are_independent(ctx, store, request_obj):
    reply = make_volunteer_sim(ctx)
    maria = store.get_volunteer("vol_maria")
    devon = store.get_volunteer("vol_devon")
    answers = [reply(maria, request_obj, "?"), reply(devon, request_obj, "?"), reply(maria, request_obj, "?")]
    assert answers == [
        SCRIPTED_REPLIES["vol_maria"][0],
        SCRIPTED_REPLIES["vol_devon"][0],
        SCRIPTED_REPLIES["vol_maria"][1],
    ]


def test_the_simulator_emits_a_trace_event_with_the_intent(ctx, store, request_obj):
    make_volunteer_sim(ctx)(store.get_volunteer("vol_hank"), request_obj, "Free Thursday?")
    events = [e for e in ctx.emitted if e["agent"] == "volunteer_sim"]
    assert len(events) == 1
    assert events[0]["type"] == "message"
    assert events[0]["detail"]["intent"] == ReplyIntent.ACCEPT
    assert events[0]["detail"]["simulated"] is True
    assert "Hank Boisvert replied" in events[0]["summary"]


def test_a_model_failure_falls_back_to_the_script(ctx, store, request_obj, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bedrock is down")

    monkeypatch.setattr(vs, "make_model", boom)
    answer = make_volunteer_sim(ctx)(store.get_volunteer("vol_priya"), request_obj, "Tuesday?")
    assert answer == SCRIPTED_REPLIES["vol_priya"][0]


def test_a_volunteer_with_no_scripted_lines_still_answers(ctx, store, clock, request_obj):
    stranger = store.get_volunteer("vol_maria").model_copy(deep=True)
    stranger.id = "vol_stranger"
    stranger.name = "Pat Stranger"
    store.put_volunteer(stranger)
    answer = make_volunteer_sim(ctx)(stranger, request_obj, "Can you help?")
    assert answer and isinstance(answer, str)


# --- wiring into the channel ----------------------------------------------------------


def test_the_channel_uses_the_simulator_when_one_is_attached(store, clock, request_obj):
    ctx = make_ctx(store, clock)
    attached = attach_volunteer_sim(ctx)
    assert attached is not None
    assert isinstance(ctx.channel, SimChannel)
    ctx.channel.send(
        OutboundMessage(
            request_id=request_obj.id,
            to=Recipient.VOLUNTEER,
            recipient_id="vol_ines",
            body="Could you cook for the Bells this week?",
        )
    )
    replies = ctx.channel.fetch_replies(request_obj.id)
    assert replies[0].text == SCRIPTED_REPLIES["vol_ines"][0]
    assert any(e["agent"] == "volunteer_sim" for e in ctx.emitted)


def test_attaching_to_a_channel_that_cannot_simulate_is_a_no_op(store, clock):
    ctx = make_ctx(store, clock)
    ctx.channel = NullChannel()
    assert attach_volunteer_sim(ctx) is None


def test_the_simulator_handles_every_category(ctx, store, clock):
    reply = make_volunteer_sim(ctx)
    maria = store.get_volunteer("vol_maria")
    for index, category in enumerate(Category):
        request = make_request(store, clock, request_id=f"req_cat_{index}", category=category)
        assert reply(maria, request, "Can you help?")

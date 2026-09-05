"""``PORCHLIGHT_CHANNEL``: who Porchlight actually talks to, and who answers.

The live deployment used to stall every request at ``awaiting_reply``: live mode meant
``EmailChannel``, ``EmailChannel`` in dry-run sends nothing, and nothing ever replied. The fix
is a channel setting independent of the mode, so a deployment can be *live* in every other
respect — real models, DynamoDB, AgentCore Runtime — and still role-play the volunteers.

These tests pin the three things that has to be true:

1. ``auto`` still follows the mode, so nothing about the local demo changed;
2. ``sim`` on a live deployment builds the simulated channel and attaches the model-backed
   volunteer simulator;
3. a reply survives the process that produced it, because it goes through the store.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from a_helpers import make_request

from porchlight.channels import EmailChannel, SimChannel, make_channel
from porchlight.channels.sim import REPLY_LOG_KEY
from porchlight.config import Settings
from porchlight.context import build_context
from porchlight.models import OutboundMessage, Recipient

REPO = Path(__file__).resolve().parent.parent


def _settings(**overrides) -> Settings:
    """Settings that never touch AWS: mock models, in-memory SQLite."""
    base = {"model_provider": "mock", "store": "sqlite", "sqlite_path": ":memory:"}
    return Settings(**{**base, **overrides})


def _outbound(request_id: str) -> OutboundMessage:
    return OutboundMessage(
        request_id=request_id,
        to=Recipient.VOLUNTEER,
        recipient_id="vol_maria",
        body="Free Thursday morning for a ride to dialysis?",
    )


# --------------------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "channel", "expected"),
    [
        ("demo", "auto", "sim"),
        ("live", "auto", "email"),
        ("demo", "email", "email"),
        ("live", "sim", "sim"),
        ("live", "email", "email"),
    ],
)
def test_channel_kind_resolves_auto_against_the_mode(mode, channel, expected) -> None:
    settings = _settings(mode=mode, channel=channel)
    assert settings.channel_kind == expected
    assert settings.simulates_replies is (expected == "sim")


def test_the_default_is_auto_so_the_demo_is_unchanged() -> None:
    assert _settings(mode="demo").channel == "auto"
    assert _settings(mode="demo").channel_kind == "sim"


def test_channel_is_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("PORCHLIGHT_CHANNEL", "sim")
    assert Settings(mode="live", sqlite_path=":memory:").channel_kind == "sim"


def test_an_unknown_channel_is_rejected_rather_than_ignored() -> None:
    with pytest.raises(ValueError):
        _settings(channel="carrier_pigeon")


# --------------------------------------------------------------------------------------
# What make_channel builds
# --------------------------------------------------------------------------------------


def test_live_mode_with_channel_sim_builds_the_simulated_channel(store, clock) -> None:
    built = make_channel(_settings(mode="live", channel="sim"), store, clock)
    assert isinstance(built, SimChannel)


def test_demo_mode_with_channel_email_builds_the_email_channel(store, clock) -> None:
    settings = _settings(mode="demo", channel="email", from_addr="porch@maplestreet.org")
    built = make_channel(settings, store, clock)
    assert isinstance(built, EmailChannel) and built.dry_run is False


# --------------------------------------------------------------------------------------
# The simulator is attached, and uses the configured model provider
# --------------------------------------------------------------------------------------


def test_build_context_attaches_the_simulator_to_a_channel_it_built(store, clock) -> None:
    """Without a ``reply_fn`` the channel replays fixtures; the demo wants the model."""
    ctx = build_context(_settings(mode="live", channel="sim"), store=store, clock=clock, memory=None)
    assert isinstance(ctx.channel, SimChannel)
    assert callable(ctx.channel.reply_fn)


def test_build_context_leaves_a_channel_the_caller_passed_alone(store, clock) -> None:
    passed = SimChannel(store, clock)
    settings = _settings(mode="live", channel="sim")
    ctx = build_context(settings, store=store, clock=clock, channel=passed, memory=None)
    assert ctx.channel is passed
    assert passed.reply_fn is None


def test_the_simulator_speaks_through_the_configured_model_provider(store, clock) -> None:
    """``model_provider=mock`` has to reach the simulator, or this test would call Bedrock.

    The ``volunteer_sim`` trace event is the proof the *agent* answered: the channel's own
    fixture fallback emits nothing.
    """
    ctx = build_context(_settings(mode="live", channel="sim"), store=store, clock=clock, memory=None)
    request = make_request(store, clock)
    ctx.channel.send(_outbound(request.id))

    replies = ctx.channel.fetch_replies(request.id)
    assert len(replies) == 1
    assert replies[0].from_volunteer_id == "vol_maria"
    assert replies[0].text.strip()

    trace = store.list_trace(0, 100)
    assert any(event.get("agent") == "volunteer_sim" for event in trace)


def test_no_simulator_is_attached_to_an_email_channel(store, clock) -> None:
    ctx = build_context(_settings(mode="live", channel="email"), store=store, clock=clock, memory=None)
    assert isinstance(ctx.channel, EmailChannel)


# --------------------------------------------------------------------------------------
# Replies live in the store, not in one process
# --------------------------------------------------------------------------------------


def test_a_reply_survives_the_process_that_produced_it(store, clock) -> None:
    """On AWS the sweep runs in the Lambda and the graph on the Runtime — different processes.

    ``SimChannel`` mirrors every reply into the quiet log, so a channel built later over the
    same store still sees it. Nothing here depends on the store being SQLite; a ``DynamoStore``
    reads the same rows back the same way.
    """
    request = make_request(store, clock)
    sender = SimChannel(store, clock, lambda volunteer, req, text: "Yes, I can do Thursday.")
    sender.send(_outbound(request.id))

    elsewhere = SimChannel(store, clock)
    replies = elsewhere.fetch_replies(request.id)

    assert [reply.text for reply in replies] == ["Yes, I can do Thursday."]
    assert elsewhere._replies == {}, "the reply came from the store, not from memory"


def test_the_mirrored_reply_round_trips_as_json(store, clock) -> None:
    """The mirror rides in ``LogEvent.detail``, which DynamoDB stores as a JSON string."""
    request = make_request(store, clock)
    SimChannel(store, clock, lambda v, r, t: "On my way.").send(_outbound(request.id))

    events = [e for e in store.list_log(request_id=request.id) if REPLY_LOG_KEY in e.detail]
    assert events, "no reply was mirrored into the quiet log"
    payload = events[0].detail[REPLY_LOG_KEY]
    assert json.loads(json.dumps(payload))["text"] == "On my way."


# --------------------------------------------------------------------------------------
# Both deployed halves have to agree
# --------------------------------------------------------------------------------------


def test_the_runtime_and_the_lambda_both_simulate() -> None:
    """The graph messages volunteers on the Runtime; the sweep does it from the Lambda."""
    project = json.loads((REPO / "agentcore" / "agentcore.json").read_text(encoding="utf-8"))
    env_vars = {var["name"]: var["value"] for var in project["runtimes"][0]["envVars"]}
    assert env_vars["PORCHLIGHT_CHANNEL"] == "sim"

    stack = (REPO / "infra" / "lib" / "porchlight-stack.ts").read_text(encoding="utf-8")
    assert re.search(r"PORCHLIGHT_CHANNEL:\s*'sim'", stack)

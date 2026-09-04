"""The simulated and email channels."""

from __future__ import annotations

from datetime import timedelta

import pytest
from a_helpers import make_request

from porchlight.channels import Channel, EmailChannel, SimChannel, make_channel
from porchlight.channels.sim import REPLY_LOG_KEY
from porchlight.config import Settings
from porchlight.models import MessageStatus, OutboundMessage, Recipient
from porchlight.sim.fixtures import SCRIPTED_REPLIES


@pytest.fixture
def request_id(store, clock) -> str:
    return make_request(store, clock).id


def outbound(request_id: str, recipient_id: str = "vol_maria", to=Recipient.VOLUNTEER, body="Free Thursday?"):
    return OutboundMessage(request_id=request_id, to=to, recipient_id=recipient_id, body=body)


# --- protocol -------------------------------------------------------------------------


def test_both_channels_satisfy_the_protocol(store, clock):
    assert isinstance(SimChannel(store, clock), Channel)
    assert isinstance(EmailChannel(store=store, clock=clock), Channel)


def test_make_channel_picks_sim_in_demo_and_email_in_live(store, clock):
    demo = make_channel(Settings(mode="demo", sqlite_path=":memory:"), store, clock)
    assert isinstance(demo, SimChannel)
    settings = Settings(mode="live", sqlite_path=":memory:", from_addr="porch@maplestreet.org")
    live = make_channel(settings, store, clock)
    assert isinstance(live, EmailChannel) and live.dry_run is False


def test_live_mode_logs_instead_of_sending_from_the_placeholder_address(store, clock):
    """SES rejects an unverified sender, so a placeholder from-address must not go live."""
    live = make_channel(Settings(mode="live", sqlite_path=":memory:"), store, clock)
    assert isinstance(live, EmailChannel)
    assert live.from_addr == "porchlight@example.org"
    assert live.dry_run is True


# --- SimChannel -----------------------------------------------------------------------


def test_send_marks_sent_and_persists(store, clock, request_id):
    channel = SimChannel(store, clock)
    sent = channel.send(outbound(request_id))
    assert sent.status == MessageStatus.SENT
    assert sent.sent_at == clock.now()
    assert sent.channel == "sim"
    assert [m.id for m in store.list_messages(request_id=request_id)] == [sent.id]


def test_messaging_a_volunteer_produces_a_scripted_reply(store, clock, request_id):
    channel = SimChannel(store, clock)
    channel.send(outbound(request_id))
    replies = channel.fetch_replies(request_id)
    assert len(replies) == 1
    assert replies[0].text == SCRIPTED_REPLIES["vol_maria"][0]
    assert replies[0].from_volunteer_id == "vol_maria"


def test_scripted_replies_cycle_per_volunteer(store, clock, request_id):
    channel = SimChannel(store, clock)
    for _ in range(4):
        channel.send(outbound(request_id))
    texts = [r.text for r in channel.fetch_replies(request_id)]
    expected = SCRIPTED_REPLIES["vol_maria"]
    assert texts == [expected[0], expected[1], expected[2], expected[0]]


def test_the_simulation_is_deterministic_across_runs(store, clock, request_id):
    def run() -> list[str]:
        fresh = SimChannel(store, clock)
        fresh.send(outbound(request_id, "vol_devon"))
        return [r.text for r in fresh.fetch_replies(request_id)]

    store.reset()
    from porchlight.sim.fixtures import seed_store

    seed_store(store, clock)
    make_request(store, clock)
    first = run()
    store.reset()
    seed_store(store, clock)
    make_request(store, clock)
    second = run()
    assert first == second == [SCRIPTED_REPLIES["vol_devon"][0]]


def test_messaging_a_requester_never_generates_a_reply(store, clock, request_id):
    channel = SimChannel(store, clock)
    channel.send(outbound(request_id, "rqr_okafor", Recipient.REQUESTER, "Maria is on her way."))
    assert channel.fetch_replies(request_id) == []


def test_auto_reply_can_be_switched_off_to_test_timeouts(store, clock, request_id):
    channel = SimChannel(store, clock, auto_reply=False)
    channel.send(outbound(request_id))
    assert channel.fetch_replies(request_id) == []


def test_a_reply_fn_overrides_the_script(store, clock, request_id):
    seen: list[tuple[str, str]] = []

    def reply_fn(volunteer, request, text):
        seen.append((volunteer.id, request.id))
        return "  Sure, I'll take it.  "

    channel = SimChannel(store, clock, reply_fn)
    channel.send(outbound(request_id))
    assert seen == [("vol_maria", request_id)]
    assert channel.fetch_replies(request_id)[0].text == "Sure, I'll take it."


def test_a_broken_reply_fn_falls_back_to_the_script(store, clock, request_id):
    def boom(volunteer, request, text):
        raise RuntimeError("model on fire")

    channel = SimChannel(store, clock, boom)
    channel.send(outbound(request_id))
    assert channel.fetch_replies(request_id)[0].text == SCRIPTED_REPLIES["vol_maria"][0]


def test_an_empty_reply_falls_back_to_the_script(store, clock, request_id):
    channel = SimChannel(store, clock, lambda v, r, t: "   ")
    channel.send(outbound(request_id))
    assert channel.fetch_replies(request_id)[0].text == SCRIPTED_REPLIES["vol_maria"][0]


def test_set_reply_fn_swaps_the_simulator_in_later(store, clock, request_id):
    channel = SimChannel(store, clock)
    channel.set_reply_fn(lambda v, r, t: "Yes, count me in.")
    channel.send(outbound(request_id))
    assert channel.fetch_replies(request_id)[0].text == "Yes, count me in."


def test_replies_are_mirrored_into_the_quiet_log_and_survive_a_new_channel(store, clock, request_id):
    first = SimChannel(store, clock)
    first.send(outbound(request_id))
    logged = store.list_log(request_id=request_id)
    assert any(REPLY_LOG_KEY in event.detail for event in logged)
    assert any("Maria Alvarez replied" in event.summary for event in logged)

    second = SimChannel(store, clock)
    replies = second.fetch_replies(request_id)
    assert len(replies) == 1 and replies[0].from_volunteer_id == "vol_maria"


def test_replies_are_returned_oldest_first(store, clock, request_id):
    channel = SimChannel(store, clock)
    channel.send(outbound(request_id, "vol_maria"))
    clock.advance(minutes=5)
    channel.send(outbound(request_id, "vol_hank"))
    replies = channel.fetch_replies(request_id)
    assert [r.from_volunteer_id for r in replies] == ["vol_maria", "vol_hank"]


def test_inject_reply_records_an_out_of_band_answer(store, clock, request_id):
    channel = SimChannel(store, clock)
    reply = channel.inject_reply(request_id, "vol_devon", "Saturday works.")
    assert reply.text == "Saturday works."
    assert channel.fetch_replies(request_id) == [reply]


def test_schedule_queues_without_simulating(store, clock, request_id):
    channel = SimChannel(store, clock)
    when = clock.now() + timedelta(hours=12)
    scheduled = channel.schedule(outbound(request_id), when)
    assert scheduled.status == MessageStatus.SCHEDULED
    assert scheduled.scheduled_for == when
    assert channel.fetch_replies(request_id) == []
    assert store.list_messages(status=MessageStatus.SCHEDULED)[0].id == scheduled.id


def test_an_unknown_recipient_is_ignored_rather_than_crashing(store, clock, request_id):
    channel = SimChannel(store, clock)
    channel.send(outbound(request_id, "vol_ghost"))
    assert channel.fetch_replies(request_id) == []


# --- EmailChannel ---------------------------------------------------------------------


class FakeSes:
    """Records the SES calls a real client would have received."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def send_email(self, **kwargs):
        if self.fail:
            raise RuntimeError("SES said no")
        self.calls.append(kwargs)
        return {"MessageId": "ses-1"}


def test_dry_run_never_builds_a_client(store, clock, request_id):
    ses = FakeSes()
    channel = EmailChannel(lambda: ses, "porch@example.org", dry_run=True, store=store, clock=clock)
    sent = channel.send(outbound(request_id))
    assert sent.status == MessageStatus.SENT
    assert ses.calls == []
    assert store.list_messages(request_id=request_id)[0].channel == "email"


def test_live_send_calls_ses_with_the_volunteers_address(store, clock, request_id):
    ses = FakeSes()
    channel = EmailChannel(
        lambda: ses, "porch@example.org", dry_run=False, store=store, clock=clock, group_name="Maple"
    )
    sent = channel.send(outbound(request_id))
    assert sent.status == MessageStatus.SENT
    assert ses.calls[0]["Destination"]["ToAddresses"] == ["maria.alvarez@example.org"]
    assert ses.calls[0]["Source"] == "porch@example.org"
    assert ses.calls[0]["Message"]["Subject"]["Data"].startswith("[Maple] ")


def test_a_volunteer_without_an_email_is_logged_not_sent(store, clock, request_id):
    ses = FakeSes()
    channel = EmailChannel(lambda: ses, dry_run=False, store=store, clock=clock)
    sent = channel.send(outbound(request_id, "vol_devon"))
    assert ses.calls == []
    assert sent.status == MessageStatus.SENT


def test_an_ses_failure_marks_the_message_failed(store, clock, request_id):
    channel = EmailChannel(lambda: FakeSes(fail=True), dry_run=False, store=store, clock=clock)
    sent = channel.send(outbound(request_id))
    assert sent.status == MessageStatus.FAILED
    assert store.list_messages(request_id=request_id)[0].status == MessageStatus.FAILED


def test_email_replies_arrive_out_of_band(store, clock, request_id):
    channel = EmailChannel(store=store, clock=clock)
    assert channel.fetch_replies(request_id) == []


def test_email_schedule_persists_the_queue(store, clock, request_id):
    channel = EmailChannel(store=store, clock=clock)
    when = clock.now() + timedelta(hours=8)
    scheduled = channel.schedule(outbound(request_id), when)
    assert scheduled.status == MessageStatus.SCHEDULED
    assert store.list_messages(status=MessageStatus.SCHEDULED)[0].scheduled_for == when


def test_requester_addresses_come_from_the_contact_field(store, clock, request_id):
    channel = EmailChannel(store=store, clock=clock)
    msg = outbound(request_id, "rqr_novak", Recipient.REQUESTER, "Confirming Thursday.")
    address = channel.address_for(msg)
    requester = store.get_requester("rqr_novak")
    assert address == (requester.contact if "@" in requester.contact else None)

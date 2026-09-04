"""Recording an inbound message as an AidRequest (the deterministic half of intake)."""

from __future__ import annotations

import pytest

from porchlight.context import AppContext
from porchlight.intake_ingest import PHOTO_MARKER, create_request_from_inbox, inbound_image
from porchlight.models import RequestStatus, Source


def test_known_contact_is_matched_to_its_requester(ctx: AppContext) -> None:
    request = create_request_from_inbox(ctx, "Ride to dialysis please", "sms", "+1-555-0201")

    assert request.requester_id == "rqr_okafor"
    assert request.status is RequestStatus.NEW
    assert request.source is Source.SMS
    assert request.first_time_requester is False
    assert ctx.store.get_request(request.id) is not None


def test_unknown_contact_creates_a_first_time_requester(ctx: AppContext) -> None:
    request = create_request_from_inbox(ctx, "New here, need a hand", "email", "petra.new@example.org")

    assert request.first_time_requester is True
    requester = ctx.store.get_requester(request.requester_id or "")
    assert requester is not None
    assert requester.name == "Petra New"
    assert requester.contact == "petra.new@example.org"


def test_a_second_message_is_no_longer_first_time(ctx: AppContext) -> None:
    create_request_from_inbox(ctx, "first", "sms", "+1-555-9999")
    second = create_request_from_inbox(ctx, "second", "sms", "+1-555-9999")
    assert second.first_time_requester is False


def test_a_message_with_no_contact_is_unattributed(ctx: AppContext) -> None:
    request = create_request_from_inbox(ctx, "Found this note on the board", "paper")
    assert request.requester_id is None
    assert request.first_time_requester is True


def test_the_raw_text_is_preserved_verbatim(ctx: AppContext) -> None:
    text = "  Could someone grab milk for Mrs. Chen?  "
    request = create_request_from_inbox(ctx, text, "form", "+1-555-0202")
    assert request.raw_text == text.strip()


def test_an_image_only_message_gets_a_marker_and_is_retrievable(ctx: AppContext) -> None:
    request = create_request_from_inbox(ctx, "", "paper", None, image_base64="ZmFrZS1pbWFnZQ==")
    assert request.raw_text == PHOTO_MARKER
    assert inbound_image(ctx, request.id) == "ZmFrZS1pbWFnZQ=="


def test_no_image_means_no_stored_image(ctx: AppContext) -> None:
    request = create_request_from_inbox(ctx, "typed message", "form")
    assert inbound_image(ctx, request.id) is None


def test_an_empty_message_is_rejected(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match="needs text or an image"):
        create_request_from_inbox(ctx, "   ", "sms", "+1-555-0201")


def test_arrival_is_logged_and_traced(ctx: AppContext) -> None:
    request = create_request_from_inbox(ctx, "Ride please", "sms", "+1-555-0201")

    log = ctx.store.list_log(request_id=request.id)
    assert any("Inbound sms from Ezra Okafor" in event.summary for event in log)
    emitted = ctx.emitted  # type: ignore[attr-defined]
    assert any(event["request_id"] == request.id for event in emitted)


def test_timestamps_come_from_the_context_clock(ctx: AppContext) -> None:
    request = create_request_from_inbox(ctx, "Ride please", "sms", "+1-555-0201")
    assert request.created_at == ctx.now()
    assert request.updated_at == ctx.now()

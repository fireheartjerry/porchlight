"""Domain model behaviour: helpers, enums, and JSON round-trips."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from porchlight.clock import FrozenClock, SystemClock
from porchlight.ids import new_id
from porchlight.models import (
    ALL_MODELS,
    AidRequest,
    Attempt,
    Category,
    Decision,
    DecisionOption,
    DecisionStatus,
    GroupSettings,
    LogEvent,
    MessageStatus,
    OutboundMessage,
    RequestStatus,
    Urgency,
    Volunteer,
    jsonable,
)

NOW = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)


def test_new_id_is_prefixed_and_unique() -> None:
    first = new_id("req")
    second = new_id("req")
    assert first.startswith("req_")
    assert len(first) == len("req_") + 10
    assert first != second


def test_new_id_rejects_bad_prefix() -> None:
    with pytest.raises(ValueError):
        new_id("bad_prefix")


def test_frozen_clock_advances() -> None:
    clock = FrozenClock(NOW)
    assert clock.now() == NOW
    assert clock.advance(hours=3) == NOW + timedelta(hours=3)
    assert clock.now() == NOW + timedelta(hours=3)
    clock.set(NOW)
    assert clock.now() == NOW


def test_system_clock_is_utc_aware() -> None:
    assert SystemClock().now().tzinfo is not None


def test_request_is_open_for_working_statuses() -> None:
    request = AidRequest(status=RequestStatus.AWAITING_REPLY)
    assert request.is_open()
    request.status = RequestStatus.COMPLETED
    assert not request.is_open()


def test_hours_until_window() -> None:
    request = AidRequest(window_start=NOW + timedelta(hours=6))
    assert request.hours_until_window(NOW) == pytest.approx(6.0)
    assert AidRequest().hours_until_window(NOW) is None
    past = AidRequest(window_start=NOW - timedelta(hours=2))
    assert past.hours_until_window(NOW) == pytest.approx(-2.0)


def test_volunteer_can_do_by_skill() -> None:
    driver = Volunteer(name="Driver", skills=["drive"])
    assert driver.can_do(Category.RIDE)
    assert driver.can_do("groceries")
    assert not driver.can_do(Category.MEAL)
    assert driver.can_do(Category.OTHER)


def test_volunteer_can_do_translation_matches_any_language() -> None:
    interpreter = Volunteer(name="Interpreter", skills=["translate:es"])
    assert interpreter.can_do(Category.TRANSLATION)
    assert not Volunteer(name="Nope", skills=["cook"]).can_do(Category.TRANSLATION)


def test_volunteer_serves_zone() -> None:
    volunteer = Volunteer(name="Zoned", zones=["Riverside"])
    assert volunteer.serves_zone("Riverside")
    assert not volunteer.serves_zone("Northgate")
    assert volunteer.serves_zone(None)
    assert Volunteer(name="Anywhere").serves_zone("Northgate")


def test_decision_open_and_resolve() -> None:
    decision = Decision(
        title="Money request",
        options=[
            DecisionOption(id="approve", label="Approve"),
            DecisionOption(id="decline_request", label="Decline"),
        ],
    )
    assert decision.open()
    assert decision.option_ids() == ["approve", "decline_request"]
    decision.resolve("approve", note="petty cash", now=NOW)
    assert not decision.open()
    assert decision.status is DecisionStatus.RESOLVED
    assert decision.resolved_option == "approve"
    assert decision.resolved_at == NOW


def test_attempted_volunteer_ids_and_touch() -> None:
    request = AidRequest(
        attempts=[Attempt(volunteer_id="vol_a"), Attempt(volunteer_id="vol_b", outcome="declined")]
    )
    assert request.attempted_volunteer_ids() == ["vol_a", "vol_b"]
    request.touch(NOW)
    assert request.updated_at == NOW


def test_outbound_message_is_due() -> None:
    message = OutboundMessage(status=MessageStatus.SCHEDULED, scheduled_for=NOW - timedelta(minutes=1))
    assert message.is_due(NOW)
    assert not OutboundMessage(status=MessageStatus.DRAFT).is_due(NOW)


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Volunteer(name="Nope", nickname="oops")


def test_log_event_detail_accepts_arbitrary_json() -> None:
    event = LogEvent(summary="did a thing", detail={"nested": {"a": [1, 2, 3]}})
    assert event.detail["nested"]["a"] == [1, 2, 3]


def test_jsonable_serializes_datetimes() -> None:
    request = AidRequest(created_at=NOW, urgency=Urgency.HIGH)
    payload = jsonable(request)
    assert payload["created_at"] == NOW.isoformat().replace("+00:00", "Z") or isinstance(
        payload["created_at"], str
    )
    assert payload["urgency"] == "high"
    assert jsonable([request])[0]["id"] == request.id
    assert jsonable({"when": NOW})["when"] == NOW.isoformat()


@pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda cls: cls.__name__)
def test_every_model_round_trips_through_json(model_cls: type) -> None:
    from porchlight.testing.synth import example_instance

    instance = example_instance(model_cls)
    restored = model_cls.model_validate_json(instance.model_dump_json())
    assert restored == instance


def test_group_settings_defaults_match_contract() -> None:
    settings = GroupSettings()
    assert settings.quiet_hours == (21, 8)
    assert settings.max_candidates == 3
    assert settings.confidence_threshold == 0.55

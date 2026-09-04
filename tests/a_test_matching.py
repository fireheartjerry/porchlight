"""The deterministic scoring engine behind ``find_candidates``."""

from __future__ import annotations

from datetime import timedelta

import pytest
from a_helpers import FROZEN_NOW, THURSDAY_MORNING, make_request

from porchlight.matching import (
    IN_HOME_CATEGORIES,
    WEIGHTS,
    ZONE_ADJACENCY,
    eligible,
    plan_confidence,
    rank_candidates,
    requires_vetting,
    score_volunteer,
    zone_distance,
)
from porchlight.models import Category, RequestStatus, Volunteer, VolunteerStats
from porchlight.sim.fixtures import VOLUNTEERS, ZONES

TZ = "America/Toronto"


def _volunteer(vid: str) -> Volunteer:
    return next(v for v in VOLUNTEERS if v.id == vid).model_copy(deep=True)


# --- geography ------------------------------------------------------------------------


def test_zone_adjacency_is_symmetric_and_covers_every_fixture_zone():
    assert set(ZONE_ADJACENCY) == set(ZONES)
    for zone, neighbours in ZONE_ADJACENCY.items():
        assert zone not in neighbours
        for neighbour in neighbours:
            assert zone in ZONE_ADJACENCY[neighbour], f"{zone}/{neighbour} not symmetric"


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("Maple St", "Maple St", 0), ("Maple St", "Riverside", 1), ("Riverside", "Northgate", 2)],
)
def test_zone_distance(a, b, expected):
    assert zone_distance(a, b) == expected


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


# --- eligibility ----------------------------------------------------------------------


def test_in_home_categories_require_vetting(store, clock):
    assert Category.CHILDCARE in IN_HOME_CATEGORIES
    assert requires_vetting(Category.CHILDCARE)
    assert not requires_vetting(Category.RIDE)
    request = make_request(store, clock, category=Category.CHILDCARE, zone="Northgate")
    unvetted = _volunteer("vol_grace")
    unvetted.vetted = False
    assert not eligible(unvetted, request)
    unvetted.vetted = True
    assert eligible(unvetted, request) == unvetted.can_do(Category.CHILDCARE)


def test_already_asked_and_inactive_volunteers_are_excluded(store, clock):
    request = make_request(store, clock)
    maria = _volunteer("vol_maria")
    assert eligible(maria, request)
    assert not eligible(maria, request, exclude={"vol_maria"})
    maria.active = False
    assert not eligible(maria, request)


def test_skill_filter_keeps_out_people_who_cannot_do_the_job(store, clock):
    request = make_request(store, clock, category=Category.TRANSLATION)
    assert not eligible(_volunteer("vol_devon"), request)
    assert eligible(_volunteer("vol_tomas"), request)


# --- components -----------------------------------------------------------------------


def test_same_zone_beats_adjacent_beats_far(store, clock):
    request = make_request(store, clock, zone="Maple St")
    in_zone = score_volunteer(_volunteer("vol_maria"), request, now=FROZEN_NOW, timezone=TZ)
    adjacent = score_volunteer(_volunteer("vol_walter"), request, now=FROZEN_NOW, timezone=TZ)
    assert in_zone.components["zone"] > adjacent.components["zone"]
    assert any("covers Maple St" in reason for reason in in_zone.reasons)


def test_availability_overlap_rewards_people_free_in_the_window(store, clock):
    request = make_request(store, clock, window_start=THURSDAY_MORNING)
    morning_person = score_volunteer(_volunteer("vol_hank"), request, now=FROZEN_NOW, timezone=TZ)
    evening_person = score_volunteer(_volunteer("vol_priya"), request, now=FROZEN_NOW, timezone=TZ)
    assert morning_person.components["availability"] == 1.0
    assert evening_person.components["availability"] < 0.2


def test_flexible_requests_soften_an_availability_miss(store, clock):
    request = make_request(store, clock, window_start=THURSDAY_MORNING)
    strict = score_volunteer(_volunteer("vol_priya"), request, now=FROZEN_NOW, timezone=TZ)
    request.flexible = True
    flexible = score_volunteer(_volunteer("vol_priya"), request, now=FROZEN_NOW, timezone=TZ)
    assert flexible.components["availability"] > strict.components["availability"]
    assert any("flexible" in reason for reason in flexible.reasons)


def test_load_fairness_penalises_someone_at_their_cap(store, clock):
    request = make_request(store, clock)
    maria = _volunteer("vol_maria")
    light = score_volunteer(maria, request, load_this_week=0, now=FROZEN_NOW, timezone=TZ)
    at_cap = score_volunteer(maria, request, load_this_week=maria.max_per_week, now=FROZEN_NOW, timezone=TZ)
    assert at_cap.score < light.score
    assert at_cap.components["fairness"] == 0.0
    assert any("cap" in reason for reason in at_cap.reasons)


def test_recency_and_no_shows_lower_reliability(store, clock):
    request = make_request(store, clock)
    reliable = _volunteer("vol_maria")
    flaky = reliable.model_copy(deep=True)
    flaky.stats = VolunteerStats(
        accepted=10, declined=2, completed=5, no_show=4, last_active=FROZEN_NOW - timedelta(days=200)
    )
    good = score_volunteer(reliable, request, now=FROZEN_NOW, timezone=TZ)
    bad = score_volunteer(flaky, request, now=FROZEN_NOW, timezone=TZ)
    assert bad.components["reliability"] < good.components["reliability"]


def test_memory_notes_boost_the_person_the_group_remembers(store, clock):
    request = make_request(store, clock, summary="Ride to dialysis and back")
    plain = score_volunteer(_volunteer("vol_hank"), request, now=FROZEN_NOW, timezone=TZ)
    remembered = score_volunteer(
        _volunteer("vol_hank"),
        request,
        now=FROZEN_NOW,
        timezone=TZ,
        recalled=["Mr. Okafor asks for Hank by name for dialysis rides."],
    )
    assert remembered.components["memory"] > plain.components["memory"]
    assert any(reason.startswith("remembered:") for reason in remembered.reasons)


# --- ranking --------------------------------------------------------------------------


def test_rank_candidates_is_ordered_bounded_and_explainable(store, clock):
    request = make_request(store, clock)
    ranked = rank_candidates(store.list_volunteers(), request, now=clock.now(), timezone=TZ, limit=4)
    assert 0 < len(ranked) <= 4
    assert [c.score for c in ranked] == sorted((c.score for c in ranked), reverse=True)
    for candidate in ranked:
        assert 0.0 <= candidate.score <= 1.0
        assert candidate.reasons and all(isinstance(r, str) and r for r in candidate.reasons)
        assert candidate.to_dict().keys() == {
            "volunteer_id",
            "name",
            "score",
            "reasons",
            "load_this_week",
            "zones",
            "skills",
            "memory_notes",
        }


def test_ranking_is_deterministic(store, clock):
    request = make_request(store, clock)
    volunteers = store.list_volunteers()
    first = rank_candidates(volunteers, request, now=clock.now(), timezone=TZ)
    second = rank_candidates(list(reversed(volunteers)), request, now=clock.now(), timezone=TZ)
    assert [c.volunteer_id for c in first] == [c.volunteer_id for c in second]


def test_a_good_local_driver_wins_a_morning_ride(store, clock):
    request = make_request(store, clock, category=Category.RIDE, zone="Maple St")
    ranked = rank_candidates(store.list_volunteers(), request, now=clock.now(), timezone=TZ)
    assert ranked[0].volunteer_id in {"vol_maria", "vol_hank"}


def test_loads_shift_the_winner(store, clock):
    request = make_request(store, clock, category=Category.RIDE, zone="Maple St")
    heavy = {"vol_maria": 3, "vol_hank": 0}
    ranked = rank_candidates(store.list_volunteers(), request, loads=heavy, now=clock.now(), timezone=TZ)
    assert ranked[0].volunteer_id == "vol_hank"


def test_plan_confidence_tracks_the_best_score_and_the_bench():
    request_free = []
    assert plan_confidence(request_free) == 0.0


def test_plan_confidence_rises_with_depth(store, clock):
    request = make_request(store, clock, status=RequestStatus.MATCHING)
    ranked = rank_candidates(store.list_volunteers(), request, now=clock.now(), timezone=TZ, limit=3)
    assert plan_confidence(ranked[:1]) <= plan_confidence(ranked)
    assert 0.0 <= plan_confidence(ranked) <= 1.0

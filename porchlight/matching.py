"""Deterministic volunteer scoring.

The matcher agent reasons *about* candidates; it does not invent them. This module is the
explainable part: given a request and the roster it returns a ranked shortlist where every
score comes from six named components and every candidate carries plain-English reasons the
coordinator can audit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import CATEGORY_SKILLS, AidRequest, Category, Volunteer

# --------------------------------------------------------------------------------------
# Neighbourhood geography
# --------------------------------------------------------------------------------------

ZONE_ADJACENCY: dict[str, frozenset[str]] = {
    "Riverside": frozenset({"Maple St", "Eastbank"}),
    "Maple St": frozenset({"Riverside", "Northgate", "Old Mill"}),
    "Northgate": frozenset({"Maple St", "Old Mill"}),
    "Old Mill": frozenset({"Maple St", "Northgate", "Eastbank"}),
    "Eastbank": frozenset({"Riverside", "Old Mill"}),
}
"""Which of the group's five zones border each other (symmetric)."""

FAR = 2
"""Distance reported for two known-but-not-adjacent zones."""


def zone_distance(a: str, b: str) -> int:
    """Hops between two zones: 0 same, 1 adjacent, 2 otherwise."""
    if a == b:
        return 0
    if b in ZONE_ADJACENCY.get(a, frozenset()):
        return 1
    return FAR


# --------------------------------------------------------------------------------------
# Policy-ish constants
# --------------------------------------------------------------------------------------

IN_HOME_CATEGORIES: frozenset[Category] = frozenset(
    {
        Category.CHILDCARE,
        Category.COMPANIONSHIP,
        Category.TECH_HELP,
        Category.REPAIR,
        Category.PAPERWORK,
    }
)
"""Categories where the volunteer ends up inside someone's home, so vetting is required."""

WEIGHTS: dict[str, float] = {
    "skills": 0.26,
    "zone": 0.18,
    "availability": 0.20,
    "fairness": 0.16,
    "reliability": 0.10,
    "memory": 0.10,
}
"""Component weights; they sum to 1.0 so the raw score is already in [0, 1]."""

OVER_CAP_PENALTY = 0.45
"""Multiplier applied when a volunteer is already at or over their weekly cap."""

MAX_WINDOW_HOURS = 24
"""Longest request window considered when measuring availability overlap."""

RECENT_DAYS = 14
"""A volunteer active within this many days counts as fully "warm"."""

_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "at",
        "be",
        "can",
        "could",
        "for",
        "from",
        "has",
        "have",
        "her",
        "him",
        "his",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "need",
        "needs",
        "of",
        "on",
        "or",
        "our",
        "please",
        "she",
        "some",
        "someone",
        "the",
        "their",
        "them",
        "they",
        "this",
        "to",
        "up",
        "was",
        "we",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


def requires_vetting(category: Category | str) -> bool:
    """True when the category puts a volunteer inside a home, so only vetted people qualify."""
    return Category(category) in IN_HOME_CATEGORIES


def _words(text: str) -> set[str]:
    """Lowercase content words of ``text``, minus very common filler."""
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def zone_info(timezone: str) -> ZoneInfo:
    """Resolve a timezone name, falling back to UTC when the platform lacks the database."""
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


# --------------------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------------------


def _skill_component(volunteer: Volunteer, request: AidRequest) -> tuple[float, str]:
    """How well the volunteer's skills cover the request's category and constraints."""
    required = CATEGORY_SKILLS.get(request.category, ())
    skills = {s.lower() for s in volunteer.skills}
    if not required:
        return 0.6, "no special skill needed"
    matched = [
        want
        for want in required
        if want in skills or (want == "translate" and any(s.startswith("translate") for s in skills))
    ]
    base = 0.7 + 0.3 * (len(matched) / len(required))
    constraint_text = " ".join(request.constraints)
    if constraint_text:
        wanted = _words(constraint_text)
        blob = " ".join(volunteer.skills) + " " + " ".join(volunteer.notes)
        if wanted & _words(blob):
            base = min(1.0, base + 0.15)
            return base, f"skills match {', '.join(matched)} and the request's constraints"
    return base, f"has {', '.join(matched)} for {request.category}"


def _zone_component(volunteer: Volunteer, request: AidRequest) -> tuple[float, str]:
    """How close the volunteer's zones are to the request's zone."""
    zone = request.location_zone
    if zone is None:
        return 0.6, "no zone on the request"
    if not volunteer.zones:
        return 0.5, "covers no particular zone"
    distance = min(zone_distance(z, zone) for z in volunteer.zones)
    if distance == 0:
        return 1.0, f"covers {zone}"
    if distance == 1:
        return 0.6, f"next door to {zone} ({', '.join(volunteer.zones)})"
    return 0.2, f"across the neighbourhood from {zone}"


def _availability_component(volunteer: Volunteer, request: AidRequest, timezone: str) -> tuple[float, str]:
    """Fraction of the request's window the volunteer's weekly availability covers."""
    if not volunteer.availability:
        return 0.6, "no availability on file"
    if request.window_start is None:
        return 0.6, "no time fixed yet"
    tz = zone_info(timezone)
    start = request.window_start.astimezone(tz)
    end = (request.window_end or request.window_start + timedelta(hours=1)).astimezone(tz)
    if end <= start:
        end = start + timedelta(hours=1)
    hours = min(MAX_WINDOW_HOURS, max(1, int((end - start).total_seconds() // 3600) or 1))
    covered = sum(
        1
        for offset in range(hours)
        if any(w.covers(start + timedelta(hours=offset)) for w in volunteer.availability)
    )
    ratio = covered / hours
    if ratio >= 0.99:
        return 1.0, f"free for the whole {start:%a %H:%M} window"
    if ratio > 0:
        return 0.4 + 0.5 * ratio, f"free for part of the {start:%a %H:%M} window"
    if request.flexible:
        return 0.4, "not free then, but the request is flexible"
    return 0.05, f"not usually free {start:%A} at {start:%H:%M}"


def _fairness_component(volunteer: Volunteer, load_this_week: int) -> tuple[float, str, float]:
    """Reward volunteers who have not been leaned on this week; penalise those over cap."""
    cap = max(1, volunteer.max_per_week)
    if load_this_week >= cap:
        return 0.0, f"already at their cap ({load_this_week}/{cap} this week)", OVER_CAP_PENALTY
    score = 1.0 - (load_this_week / cap)
    return score, f"{load_this_week} of {cap} jobs this week", 1.0


def _reliability_component(volunteer: Volunteer, now: datetime) -> tuple[float, str]:
    """Blend follow-through, no-shows, and how recently they were active."""
    stats = volunteer.stats
    asked = stats.accepted + stats.declined
    follow_through = stats.completed / stats.accepted if stats.accepted else 0.5
    no_show_rate = stats.no_show / stats.accepted if stats.accepted else 0.0
    if stats.last_active is None:
        recency = 0.5
        recency_reason = "no recent activity on record"
    else:
        days = max(0.0, (now - stats.last_active).total_seconds() / 86400.0)
        recency = _clamp(1.0 - max(0.0, days - RECENT_DAYS) / 60.0)
        recency_reason = f"last helped {int(days)} days ago"
    score = _clamp(0.5 * _clamp(follow_through) + 0.3 * recency + 0.2 * (1.0 - _clamp(no_show_rate)))
    if asked >= 5:
        reason = f"{stats.completed} completed of {stats.accepted} accepted; {recency_reason}"
    else:
        reason = f"newer volunteer; {recency_reason}"
    return score, reason


def _memory_component(
    volunteer: Volunteer, request: AidRequest, recalled: Sequence[str]
) -> tuple[float, str | None, list[str]]:
    """Boost volunteers the group's notes actually point at for this kind of request."""
    notes = list(volunteer.notes) + [n for n in recalled if n]
    if not notes:
        return 0.35, None, []
    wanted = _words(f"{request.summary} {request.raw_text} {request.category}")
    hits = [note for note in notes if _words(note) & wanted]
    named = [note for note in recalled if volunteer.name.split()[0].lower() in note.lower()]
    if named:
        return 1.0, f"remembered: {named[0][:90]}", notes
    if hits:
        return 0.8, f"notes mention this kind of job: {hits[0][:90]}", notes
    return 0.45, None, notes


# --------------------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------------------


@dataclass
class Candidate:
    """One scored volunteer, ready to hand to the matcher agent or the API."""

    volunteer_id: str
    name: str
    score: float
    reasons: list[str] = field(default_factory=list)
    load_this_week: int = 0
    zones: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    memory_notes: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Contract shape returned by the ``find_candidates`` tool."""
        return {
            "volunteer_id": self.volunteer_id,
            "name": self.name,
            "score": self.score,
            "reasons": list(self.reasons),
            "load_this_week": self.load_this_week,
            "zones": list(self.zones),
            "skills": list(self.skills),
            "memory_notes": list(self.memory_notes),
        }


def score_volunteer(
    volunteer: Volunteer,
    request: AidRequest,
    *,
    load_this_week: int = 0,
    now: datetime,
    timezone: str = "UTC",
    recalled: Sequence[str] = (),
) -> Candidate:
    """Score one volunteer against one request.

    Args:
        volunteer: The person being considered.
        request: The job.
        load_this_week: How many requests they have already been on in the last seven days.
        now: Current time (from the context clock).
        timezone: The group's local timezone; availability windows are local.
        recalled: Long-term memory snippets relevant to this request.

    Returns:
        A :class:`Candidate` with a score in [0, 1] and human-readable reasons.
    """
    reasons: list[str] = []
    components: dict[str, float] = {}

    skill_score, skill_reason = _skill_component(volunteer, request)
    zone_score, zone_reason = _zone_component(volunteer, request)
    avail_score, avail_reason = _availability_component(volunteer, request, timezone)
    fair_score, fair_reason, penalty = _fairness_component(volunteer, load_this_week)
    rel_score, rel_reason = _reliability_component(volunteer, now)
    mem_score, mem_reason, notes = _memory_component(volunteer, request, recalled)

    components.update(
        skills=skill_score,
        zone=zone_score,
        availability=avail_score,
        fairness=fair_score,
        reliability=rel_score,
        memory=mem_score,
    )
    reasons.extend([skill_reason, zone_reason, avail_reason, fair_reason, rel_reason])
    if mem_reason:
        reasons.append(mem_reason)
    if volunteer.vetted and requires_vetting(request.category):
        reasons.append("vetted for in-home visits")

    raw = sum(WEIGHTS[name] * value for name, value in components.items())
    score = _clamp(round(raw * penalty, 3))
    return Candidate(
        volunteer_id=volunteer.id,
        name=volunteer.name,
        score=score,
        reasons=reasons,
        load_this_week=load_this_week,
        zones=list(volunteer.zones),
        skills=list(volunteer.skills),
        memory_notes=notes,
        components={k: round(v, 3) for k, v in components.items()},
    )


def eligible(volunteer: Volunteer, request: AidRequest, exclude: Iterable[str] = ()) -> bool:
    """Hard filters: active, not already asked, has a qualifying skill, vetted when required."""
    if not volunteer.active or volunteer.id in set(exclude):
        return False
    if not volunteer.can_do(request.category):
        return False
    if requires_vetting(request.category) and not volunteer.vetted:
        return False
    return True


def rank_candidates(
    volunteers: Iterable[Volunteer],
    request: AidRequest,
    *,
    loads: Mapping[str, int] | None = None,
    now: datetime,
    timezone: str = "UTC",
    limit: int = 5,
    exclude: Iterable[str] = (),
    recalled: Mapping[str, Sequence[str]] | None = None,
) -> list[Candidate]:
    """Rank the roster for one request, best first.

    Args:
        volunteers: The roster to consider.
        request: The job to match.
        loads: Volunteer id -> jobs in the last seven days.
        now: Current time.
        timezone: The group's local timezone.
        limit: How many candidates to return.
        exclude: Volunteer ids to skip (usually the ones already asked).
        recalled: Volunteer id -> long-term memory snippets.

    Returns:
        Up to ``limit`` :class:`Candidate`\\ s, highest score first, ties broken by lighter load
        then by name so the ordering is stable.
    """
    loads = loads or {}
    recalled = recalled or {}
    skip = set(exclude)
    scored = [
        score_volunteer(
            volunteer,
            request,
            load_this_week=loads.get(volunteer.id, 0),
            now=now,
            timezone=timezone,
            recalled=recalled.get(volunteer.id, ()),
        )
        for volunteer in volunteers
        if eligible(volunteer, request, skip)
    ]
    scored.sort(key=lambda c: (-c.score, c.load_this_week, c.name))
    return scored[: max(0, limit)]


def plan_confidence(candidates: Sequence[Candidate]) -> float:
    """Confidence the matcher can defend: the best score, nudged up when there is a bench."""
    if not candidates:
        return 0.0
    best = candidates[0].score
    depth = min(len(candidates), 3) - 1
    return _clamp(round(best + 0.05 * depth, 3))

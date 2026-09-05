"""Seed data for the fictional "Maple Street Mutual Aid" neighbourhood group.

Everything here is invented. It exists so the demo, the tests, and the volunteer simulator all
work with no AWS account and no real people's data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from ..clock import Clock, SystemClock
from ..config import Settings, get_settings
from ..models import (
    AidRequest,
    AvailabilityWindow,
    Category,
    GroupSettings,
    Requester,
    RequestStatus,
    Source,
    Urgency,
    Volunteer,
    VolunteerStats,
)
from ..store.base import Store

ZONES: list[str] = ["Riverside", "Maple St", "Northgate", "Old Mill", "Eastbank"]
"""The five zones the group covers."""

GROUP_NAME = "Maple Street Mutual Aid"


def _win(*windows: tuple[int, int, int]) -> list[AvailabilityWindow]:
    """Shorthand: ``_win((0, 9, 17), (2, 18, 21))``."""
    return [AvailabilityWindow(weekday=d, start_hour=s, end_hour=e) for d, s, e in windows]


WEEKDAY_DAYS = (0, 1, 2, 3, 4)
WEEKEND_DAYS = (5, 6)


def _daily(days: tuple[int, ...], start: int, end: int) -> list[AvailabilityWindow]:
    """Same window on several weekdays."""
    return [AvailabilityWindow(weekday=d, start_hour=start, end_hour=end) for d in days]


# --------------------------------------------------------------------------------------
# Volunteers
# --------------------------------------------------------------------------------------

VOLUNTEERS: list[Volunteer] = [
    Volunteer(
        id="vol_maria",
        name="Maria Alvarez",
        phone="+1-555-0101",
        email="maria.alvarez@example.org",
        zones=["Maple St", "Riverside"],
        skills=["drive", "shop", "errands", "companionship", "translate:es"],
        availability=_daily(WEEKDAY_DAYS, 9, 15),
        max_per_week=3,
        vetted=True,
        notes=["Great with seniors; Mr. Okafor asks for her by name.", "Prefers mornings."],
        stats=VolunteerStats(accepted=41, declined=6, completed=39, no_show=0),
        persona="warm retired nurse, replies within minutes, says yes to mornings, "
        "declines anything after 4pm because she picks up her grandson",
    ),
    Volunteer(
        id="vol_devon",
        name="Devon Clarke",
        phone="+1-555-0102",
        zones=["Northgate", "Eastbank"],
        skills=["drive", "lift", "yard", "handy"],
        availability=_daily(WEEKEND_DAYS, 8, 18) + _win((3, 17, 21)),
        max_per_week=2,
        vetted=True,
        notes=["Has a pickup truck.", "Best for heavy lifting and snow."],
        stats=VolunteerStats(accepted=27, declined=11, completed=25, no_show=1),
        persona="busy contractor, terse texter, only free weekends, counters weekday asks "
        "with a Saturday time",
    ),
    Volunteer(
        id="vol_priya",
        name="Priya Raman",
        phone="+1-555-0103",
        email="priya.raman@example.org",
        zones=["Riverside"],
        skills=["tech", "paperwork", "companionship", "translate:ta"],
        availability=_win((1, 18, 21), (3, 18, 21), (6, 13, 18)),
        max_per_week=2,
        vetted=True,
        notes=["Patient teacher; set up three people's tablets."],
        stats=VolunteerStats(accepted=18, declined=3, completed=18, no_show=0),
        persona="software engineer, only evenings and Sunday afternoons, asks one clarifying "
        "question before accepting",
    ),
    Volunteer(
        id="vol_hank",
        name="Hank Boisvert",
        phone="+1-555-0104",
        zones=["Old Mill", "Maple St"],
        skills=["drive", "errands", "lift"],
        availability=_daily(WEEKDAY_DAYS, 7, 12),
        max_per_week=4,
        vetted=True,
        notes=["Retired bus driver; unfazed by hospital parking."],
        stats=VolunteerStats(accepted=63, declined=4, completed=61, no_show=0, last_active=None),
        persona="eager retiree, replies fast, says yes unless it is in the evening",
    ),
    Volunteer(
        id="vol_ines",
        name="Inés Moreau",
        phone="+1-555-0105",
        email="ines.moreau@example.org",
        zones=["Eastbank"],
        skills=["cook", "shop", "companionship"],
        availability=_win((0, 16, 20), (2, 16, 20), (5, 10, 16)),
        max_per_week=3,
        vetted=True,
        notes=["Cooks for new parents; keeps a freezer stash of soup."],
        stats=VolunteerStats(accepted=34, declined=8, completed=33, no_show=1),
        persona="generous home cook, always says yes to meals, always declines driving",
    ),
    Volunteer(
        id="vol_tomas",
        name="Tomás Reyes",
        phone="+1-555-0106",
        zones=["Northgate", "Old Mill"],
        skills=["drive", "translate:es", "errands"],
        availability=_daily(WEEKDAY_DAYS, 12, 18),
        max_per_week=2,
        vetted=True,
        notes=["Interprets Spanish at the clinic."],
        stats=VolunteerStats(accepted=22, declined=9, completed=21, no_show=0),
        persona="afternoon-only, bilingual, cheerful, sometimes counters with a later time",
    ),
    Volunteer(
        id="vol_grace",
        name="Grace Okonkwo",
        phone="+1-555-0107",
        email="grace.okonkwo@example.org",
        zones=["Maple St", "Northgate"],
        skills=["childcare-cleared", "companionship", "cook"],
        availability=_daily(WEEKDAY_DAYS, 8, 16),
        max_per_week=3,
        vetted=True,
        notes=["Police-check on file; the only childcare-cleared volunteer on weekdays."],
        stats=VolunteerStats(accepted=29, declined=5, completed=28, no_show=0),
        persona="calm and careful, asks about the child's age before accepting, never rushes",
    ),
    Volunteer(
        id="vol_sam",
        name="Sam Whitehorse",
        phone="+1-555-0108",
        zones=["Riverside", "Old Mill"],
        skills=["drive", "lift", "yard"],
        availability=_win((1, 6, 11), (4, 6, 11), (5, 7, 15)),
        max_per_week=2,
        vetted=False,
        notes=["New in July; two jobs so far, both fine."],
        stats=VolunteerStats(accepted=2, declined=0, completed=2, no_show=0),
        persona="new volunteer, keen but unsure, accepts anything in the early morning",
    ),
    Volunteer(
        id="vol_bea",
        name="Beatrice Lund",
        phone="+1-555-0109",
        zones=["Eastbank", "Riverside"],
        skills=["shop", "errands", "companionship", "paperwork"],
        availability=_daily(WEEKDAY_DAYS, 10, 14),
        max_per_week=2,
        vetted=True,
        notes=["Walks everywhere; no car."],
        stats=VolunteerStats(accepted=19, declined=14, completed=18, no_show=0),
        persona="cautious, declines about half the time, explains why kindly",
    ),
    Volunteer(
        id="vol_omar",
        name="Omar Haddad",
        phone="+1-555-0110",
        email="omar.haddad@example.org",
        zones=["Northgate"],
        skills=["tech", "drive", "translate:ar", "paperwork"],
        availability=_win((2, 19, 22), (6, 10, 16)),
        max_per_week=2,
        vetted=True,
        notes=["Arabic interpreter; also fixes phones."],
        stats=VolunteerStats(accepted=15, declined=7, completed=14, no_show=1),
        persona="night owl, replies late, often counters with a Sunday slot",
    ),
    Volunteer(
        id="vol_junie",
        name="Junie Park",
        phone="+1-555-0111",
        zones=["Maple St"],
        skills=["cook", "shop", "companionship", "translate:ko"],
        availability=_daily(WEEKEND_DAYS, 9, 17),
        max_per_week=3,
        vetted=True,
        notes=["Runs the Saturday meal train."],
        stats=VolunteerStats(accepted=38, declined=6, completed=37, no_show=0),
        persona="organized and quick, weekends only, says yes to meals and groceries",
    ),
    Volunteer(
        id="vol_walter",
        name="Walter Nguyen",
        phone="+1-555-0112",
        zones=["Old Mill", "Eastbank"],
        skills=["drive", "handy", "lift", "yard"],
        availability=_daily(WEEKDAY_DAYS, 15, 20) + _daily(WEEKEND_DAYS, 9, 18),
        max_per_week=4,
        vetted=True,
        notes=["Most reliable driver for evening dialysis runs."],
        stats=VolunteerStats(accepted=57, declined=3, completed=55, no_show=1),
        persona="dependable, short replies, accepts almost everything but hates surprises",
    ),
    Volunteer(
        id="vol_rosa",
        name="Rosa Ferreira",
        phone="+1-555-0113",
        zones=["Riverside", "Maple St"],
        skills=["companionship", "paperwork", "translate:pt"],
        availability=_win((0, 13, 17), (2, 13, 17), (4, 13, 17)),
        max_per_week=2,
        vetted=True,
        notes=["Visits Mrs. Chen most weeks; they play cards."],
        stats=VolunteerStats(accepted=24, declined=4, completed=24, no_show=0),
        persona="gentle and chatty, loves companionship visits, cannot drive",
    ),
    Volunteer(
        id="vol_kwame",
        name="Kwame Mensah",
        phone="+1-555-0114",
        email="kwame.mensah@example.org",
        zones=["Northgate", "Eastbank", "Maple St"],
        skills=["drive", "lift", "shop", "errands", "tech"],
        availability=_daily(WEEKDAY_DAYS, 6, 9) + _daily(WEEKEND_DAYS, 12, 20),
        max_per_week=3,
        vetted=False,
        notes=["Joined in August; not yet police-checked, so no in-home jobs."],
        stats=VolunteerStats(accepted=4, declined=1, completed=4, no_show=0),
        persona="enthusiastic newcomer, early bird, says yes then asks logistics questions",
    ),
]


# --------------------------------------------------------------------------------------
# Requesters
# --------------------------------------------------------------------------------------

REQUESTERS: list[Requester] = [
    Requester(
        id="rqr_okafor",
        name="Ezra Okafor",
        contact="+1-555-0201",
        zone="Maple St",
        address="14 Maple St, Apt 3",
        notes=["Dialysis Tue/Thu. Prefers Maria. Hard of hearing — call, do not text."],
        history_count=22,
    ),
    Requester(
        id="rqr_chen",
        name="Mrs. Chen",
        contact="+1-555-0202",
        zone="Riverside",
        address="9 Riverbend Cres",
        notes=["Lives alone. Likes a chat more than the groceries."],
        history_count=14,
    ),
    Requester(
        id="rqr_daza",
        name="Lucía Daza",
        contact="lucia.daza@example.org",
        zone="Northgate",
        address="221 Northgate Ave",
        notes=["Speaks Spanish at home; clinic appointments need an interpreter."],
        history_count=6,
    ),
    Requester(
        id="rqr_flores",
        name="Tomiko Flores",
        contact="+1-555-0204",
        zone="Eastbank",
        address="7 Eastbank Row",
        notes=["New baby as of last week."],
        history_count=1,
    ),
    Requester(
        id="rqr_bell",
        name="Arthur Bell",
        contact="+1-555-0205",
        zone="Old Mill",
        address="88 Old Mill Rd",
        notes=["Bad knee. Snow is the recurring problem."],
        history_count=9,
    ),
    Requester(
        id="rqr_novak",
        name="Petra Novak",
        contact="petra.novak@example.org",
        zone="Riverside",
        address="3 Riverside Lane",
        notes=["Wants help with her tablet roughly monthly."],
        history_count=4,
    ),
    Requester(
        id="rqr_adeyemi",
        name="Femi Adeyemi",
        contact="+1-555-0207",
        zone="Northgate",
        notes=["Asked once in March for a ride."],
        history_count=1,
    ),
    Requester(
        id="rqr_kessler",
        name="Dana Kessler",
        contact="+1-555-0208",
        zone="Maple St",
        notes=["Coordinator's neighbour; usually relays requests for others."],
        history_count=3,
    ),
]


# --------------------------------------------------------------------------------------
# Inbound sample messages
# --------------------------------------------------------------------------------------


class SampleMessage(TypedDict):
    """One inbound message used by the demo inbox and the policy tests."""

    id: str
    label: str
    source: str
    contact: str
    text: str
    expected: str
    expected_kind: str | None


SAMPLE_MESSAGES: list[SampleMessage] = [
    {
        "id": "sm_dialysis_ride",
        "label": "Routine ride to dialysis",
        "source": "sms",
        "contact": "+1-555-0201",
        "text": "Hi it's Ezra Okafor. I need a ride to dialysis Thursday at 9am, back around 1. "
        "Same as usual. Thank you.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_grocery_run",
        "label": "Grocery run",
        "source": "sms",
        "contact": "+1-555-0202",
        "text": "Could someone pick up milk, bread and my usual tea sometime this week? "
        "No rush at all. - Mrs. Chen",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_new_parent_meal",
        "label": "Hot meal for new parents",
        "source": "form",
        "contact": "+1-555-0204",
        "text": "We had the baby on Tuesday and we are both wrecked. A hot dinner any evening "
        "this week would be a lifesaver. No dairy please.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_prescription",
        "label": "Prescription pickup",
        "source": "voicemail",
        "contact": "+1-555-0205",
        "text": "Arthur Bell here. Pharmacy on Old Mill has my blood pressure pills ready. "
        "Any day before Friday is fine.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_snow_shovel",
        "label": "Snow shovelling",
        "source": "sms",
        "contact": "+1-555-0205",
        "text": "Snow again. My walk needs clearing before the nurse comes Wednesday morning. "
        "My knee is not up to it.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_tablet_help",
        "label": "Tech help for a senior",
        "source": "email",
        "contact": "petra.novak@example.org",
        "text": "My tablet stopped showing my grandchildren's photos and I cannot work out why. "
        "Could someone patient sit with me for half an hour?",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_clinic_translation",
        "label": "Translation at a clinic",
        "source": "email",
        "contact": "lucia.daza@example.org",
        "text": "I have a clinic appointment Monday at 2pm on Northgate and I need someone who "
        "speaks Spanish to come in with me.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_companionship",
        "label": "Companionship visit",
        "source": "sms",
        "contact": "+1-555-0202",
        "text": "Nothing needed really. But if someone were passing on Friday afternoon I would "
        "love the company. The days are long.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_spanish_request",
        "label": "Request written in Spanish",
        "source": "sms",
        "contact": "+1-555-0207",
        "text": "Buenas tardes. Necesito que alguien me lleve a la farmacia el viernes por la "
        "mañana, no tengo coche. Gracias.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_garbled_voicemail",
        "label": "Garbled voicemail transcript",
        "source": "voicemail",
        "contact": "+1-555-0201",
        "text": "[voicemail transcript] uh hello this is ... [inaudible] ... the thing on "
        "thursday ... my daughter usually ... [inaudible] ... call me back",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_flexible_window",
        "label": "Flexible window",
        "source": "form",
        "contact": "+1-555-0202",
        "text": "Any afternoon next week works for a lift to the library. Truly whenever suits "
        "whoever helps.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_urgent_ride",
        "label": "Urgent same-day ride",
        "source": "sms",
        "contact": "+1-555-0201",
        "text": "Sorry for short notice — the clinic moved my appointment to today at 3pm. Is anyone free?",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_child_home_alone",
        "label": "Child home alone, stove on",
        "source": "sms",
        "contact": "+1-555-0208",
        "text": "My neighbour's kid is home alone next door and I can smell the stove is on. "
        "I don't know what to do.",
        "expected": "card",
        "expected_kind": "safety",
    },
    {
        "id": "sm_electric_bill",
        "label": "Help paying an electric bill",
        "source": "email",
        "contact": "+1-555-0207",
        "text": "I am $180 short on my electric bill and they are threatening to cut it off "
        "Monday. Can the group help with money?",
        "expected": "card",
        "expected_kind": "money",
    },
    {
        "id": "sm_first_time_in_home",
        "label": "First-time requester, in-home help",
        "source": "form",
        "contact": "+1-555-0299",
        "text": "Hello, I'm new to the neighbourhood. I need someone to come inside and help me "
        "move furniture and sort out my bedroom.",
        "expected": "card",
        "expected_kind": "vetting",
    },
    {
        "id": "sm_volunteer_concern",
        "label": "Volunteer raises a concern",
        "source": "sms",
        "contact": "+1-555-0109",
        "text": "I dropped the groceries at 9 Riverbend today. Something felt off — there was a "
        "man there who told me to leave the bags outside and not come back. I'd rather not go alone again.",
        "expected": "card",
        "expected_kind": "concern",
    },
    {
        "id": "sm_chest_pain",
        "label": "Chest pain (emergency)",
        "source": "sms",
        "contact": "+1-555-0205",
        "text": "I've had chest pain since this morning and my arm feels heavy. Can someone drive "
        "me to the hospital?",
        "expected": "card",
        "expected_kind": "safety",
    },
    {
        "id": "sm_duplicate_dialysis",
        "label": "Duplicate of the dialysis ride",
        "source": "sms",
        "contact": "+1-555-0201",
        "text": "Me again — just checking you got my message about the Thursday 9am dialysis ride.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_conflicting_times",
        "label": "Conflicting times in one message",
        "source": "email",
        "contact": "petra.novak@example.org",
        "text": "Could someone come Tuesday at 10? Actually Wednesday is better. Or Tuesday "
        "afternoon. Sorry, I keep changing my mind.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_thank_you",
        "label": "Thank-you note (not a request)",
        "source": "sms",
        "contact": "+1-555-0204",
        "text": "Just wanted to say the lasagne was incredible and we cried a little. Thank you "
        "to whoever cooked it.",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_paper_slip",
        "label": "Photographed paper slip",
        "source": "paper",
        "contact": "+1-555-0202",
        "text": "[photo of a paper slip] NAME: M. Chen  NEED: ride to eye doctor  WHEN: Fri 11am "
        "ZONE: Riverside",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_gift_card",
        "label": "Gift card request",
        "source": "sms",
        "contact": "+1-555-0207",
        "text": "Could the group get me a $50 grocery gift card instead of a shopping run? "
        "It'd be easier for me.",
        "expected": "card",
        "expected_kind": "money",
    },
    {
        "id": "sm_night_send",
        "label": "Arrives during quiet hours",
        "source": "sms",
        "contact": "+1-555-0205",
        "text": "It's 11:40pm and I know it's late. Nothing urgent — could someone take my bins "
        "out Thursday morning?",
        "expected": "quiet",
        "expected_kind": None,
    },
    {
        "id": "sm_nobody_free",
        "label": "Nobody is likely free",
        "source": "form",
        "contact": "+1-555-0208",
        "text": "Long shot: my mother needs a lift to Riverside at 4am Sunday for a hospital "
        "transfer. I know that's a big ask.",
        "expected": "card",
        "expected_kind": "unmatched",
    },
]


# --------------------------------------------------------------------------------------
# Scripted volunteer replies (used when no LLM simulator is available)
# --------------------------------------------------------------------------------------

SCRIPTED_REPLIES: dict[str, list[str]] = {
    "vol_maria": [
        "Yes of course, I can do Thursday morning. Tell Ezra I'll be there ten minutes early.",
        "Sorry, not after four — I have my grandson. Mornings any day though.",
        "Happy to. Can you send me the address once it's confirmed?",
    ],
    "vol_devon": [
        "Can't do weekdays. Saturday morning works if that helps.",
        "Yep, I'll bring the truck.",
        "No, sorry. Booked solid this week.",
    ],
    "vol_priya": [
        "I can do it Tuesday evening. Does she have wifi, or should I bring a hotspot?",
        "Sunday afternoon works better for me if that's alright.",
        "Yes, count me in.",
    ],
    "vol_hank": [
        "Yes! Happy to. Morning is perfect.",
        "Sure thing, I'll be there.",
        "Evenings are no good for me but any morning, just say the word.",
    ],
    "vol_ines": [
        "I'll cook. Dropping a big pot of soup and some bread Thursday evening.",
        "I can't drive but I can absolutely feed them.",
        "Yes — no dairy noted.",
    ],
    "vol_tomas": [
        "Sí, I can interpret. 2pm Monday is fine.",
        "Could we make it 3pm instead? I finish work at 2:30.",
        "Sorry, I'm away that week.",
    ],
    "vol_grace": [
        "How old is the child? If it's fine with the parent I can do it.",
        "Yes, I'm cleared for that and I'm free Wednesday.",
        "I'd rather not this week, sorry — my own kids are off school.",
    ],
    "vol_sam": [
        "Sure, I can do early. Is 7am too early for them?",
        "Yes I'll take it.",
        "I'm not sure I'm the right person for that one.",
    ],
    "vol_bea": [
        "I don't have a car, so only if it's walking distance.",
        "Sorry, I can't this time. I hope someone else can.",
        "Yes, I can pick that up on my walk.",
    ],
    "vol_omar": [
        "I can do Sunday. Weeknights I'm working until nine.",
        "Yes, I'll bring my toolkit for the phone too.",
        "Sorry — that's the same time as my shift.",
    ],
    "vol_junie": [
        "On it. I'll add it to Saturday's meal train.",
        "Yes, I'll do the shop Saturday morning.",
        "Weekends only for me, sorry.",
    ],
    "vol_walter": [
        "Yes.",
        "Confirmed, I'll be there at the time given.",
        "That works. Send the address.",
    ],
    "vol_rosa": [
        "I'd love to visit her, Friday afternoon is perfect.",
        "I can't drive but I'll happily sit with her.",
        "Yes please, put me down.",
    ],
    "vol_kwame": [
        "Yes! Where do I pick up, and is there parking?",
        "I can do early morning before work.",
        "Sorry, I'm not police-checked yet so I don't think I can go inside.",
    ],
}
"""Volunteer id -> canned replies covering accept / decline / counter / concern."""


DEFAULT_REPLIES: list[str] = [
    "Yes, I can help with that.",
    "Sorry, I can't this time.",
    "Could we do it a bit later in the day?",
]
"""Fallback replies for a volunteer with no scripted lines."""


def reply_for(volunteer_id: str, index: int = 0) -> str:
    """Return one scripted reply for a volunteer, cycling through the available lines."""
    replies = SCRIPTED_REPLIES.get(volunteer_id) or DEFAULT_REPLIES
    return replies[index % len(replies)]


# --------------------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------------------


def group_settings(settings: Settings | None = None) -> GroupSettings:
    """The group's policy settings, taken from the deployment's configuration.

    Every knob here also exists on :class:`~porchlight.config.Settings`, and the policy engine
    reads the ``Settings`` one — so the seeded row has to come from the same place or the porch
    would advertise a rule nobody enforces. The hosted demo turns quiet hours off, and this is
    what stops it from still claiming 21:00–08:00 on ``/api/porch``.

    Args:
        settings: The configuration to mirror. Defaults to the process-wide settings.

    Returns:
        The group row to seed.
    """
    settings = settings or get_settings()
    return GroupSettings(
        name=settings.group_name,
        timezone=settings.timezone,
        quiet_hours=settings.quiet_hours,
        petty_cash_limit=settings.petty_cash_limit,
        max_candidates=settings.max_candidates,
        escalate_hours_before_window=settings.escalate_hours_before_window,
        confidence_threshold=settings.confidence_threshold,
        zones=list(ZONES),
    )


def _history(now: datetime) -> list[AidRequest]:
    """A handful of finished requests so week-one demos have a past to recall."""
    return [
        AidRequest(
            id="req_hist_dialysis",
            source=Source.SMS,
            raw_text="Ride to dialysis last Thursday, 9am.",
            requester_id="rqr_okafor",
            category=Category.RIDE,
            summary="Ride to dialysis and back",
            window_start=now - timedelta(days=7, hours=5),
            window_end=now - timedelta(days=7, hours=1),
            location_zone="Maple St",
            urgency=Urgency.NORMAL,
            status=RequestStatus.COMPLETED,
            assigned_volunteer_id="vol_maria",
            created_at=now - timedelta(days=8),
            updated_at=now - timedelta(days=7),
        ),
        AidRequest(
            id="req_hist_groceries",
            source=Source.SMS,
            raw_text="Milk, bread, tea.",
            requester_id="rqr_chen",
            category=Category.GROCERIES,
            summary="Weekly groceries",
            location_zone="Riverside",
            flexible=True,
            status=RequestStatus.COMPLETED,
            assigned_volunteer_id="vol_bea",
            created_at=now - timedelta(days=6),
            updated_at=now - timedelta(days=5),
        ),
        AidRequest(
            id="req_hist_snow",
            source=Source.VOICEMAIL,
            raw_text="Walk needs clearing.",
            requester_id="rqr_bell",
            category=Category.YARD_WORK,
            summary="Clear the front walk",
            location_zone="Old Mill",
            status=RequestStatus.COMPLETED,
            assigned_volunteer_id="vol_devon",
            created_at=now - timedelta(days=4),
            updated_at=now - timedelta(days=3),
        ),
        AidRequest(
            id="req_hist_tablet",
            source=Source.EMAIL,
            raw_text="Tablet trouble again.",
            requester_id="rqr_novak",
            category=Category.TECH_HELP,
            summary="Tablet photo app not loading",
            location_zone="Riverside",
            status=RequestStatus.COMPLETED,
            assigned_volunteer_id="vol_priya",
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(days=2),
        ),
    ]


def seed_store(store: Store, clock: Clock | None = None, settings: Settings | None = None) -> dict[str, int]:
    """Wipe ``store`` and load the Maple Street fixtures into it.

    Args:
        store: Any :class:`~porchlight.store.base.Store`.
        clock: Time source used to date the seeded history; defaults to the system clock.
        settings: Configuration the seeded group row mirrors; defaults to the process settings.

    Returns:
        ``{"volunteers": n, "requesters": n, "requests": n}``.
    """
    now = (clock or SystemClock()).now()
    store.reset()
    store.put_group_settings(group_settings(settings))

    for volunteer in VOLUNTEERS:
        seeded = volunteer.model_copy(deep=True)
        seeded.created_at = now - timedelta(days=90)
        if seeded.stats.last_active is None:
            seeded.stats.last_active = now - timedelta(days=5)
        store.put_volunteer(seeded)

    for requester in REQUESTERS:
        seeded_r = requester.model_copy(deep=True)
        seeded_r.first_seen = now - timedelta(days=120)
        store.put_requester(seeded_r)

    history = _history(now)
    for request in history:
        store.put_request(request)

    return {
        "volunteers": len(VOLUNTEERS),
        "requesters": len(REQUESTERS),
        "requests": len(history),
    }


def sample_by_id(sample_id: str) -> SampleMessage | None:
    """Look up one sample inbound message."""
    return next((m for m in SAMPLE_MESSAGES if m["id"] == sample_id), None)


def samples_expecting(expected: str) -> list[SampleMessage]:
    """All sample messages whose expected outcome is ``"quiet"`` or ``"card"``."""
    return [m for m in SAMPLE_MESSAGES if m["expected"] == expected]


def sample_payloads() -> list[dict[str, Any]]:
    """The sample messages as plain dicts, for the demo inbox API."""
    return [dict(message) for message in SAMPLE_MESSAGES]


QUIET_PER_CARD = 3
"""Routine requests shown between each one that needs the coordinator."""


def demo_sequence(count: int | None = None) -> list[SampleMessage]:
    """The order a demo should run the samples in.

    A real Tuesday is mostly routine with the occasional card, so the sequence interleaves the
    quiet samples with the ones that need a person at :data:`QUIET_PER_CARD` to one. That way a
    short run (``--count 6``) still shows both halves of the product instead of six ride
    requests in a row. Original order is preserved within each group, so the sequence is stable.

    Args:
        count: How many samples to return; ``None`` returns all of them.

    Returns:
        Sample messages, ready to push through the graph.
    """
    quiet = list(samples_expecting("quiet"))
    cards = list(samples_expecting("card"))
    ordered: list[SampleMessage] = []
    while quiet or cards:
        for _ in range(QUIET_PER_CARD):
            if quiet:
                ordered.append(quiet.pop(0))
        if cards:
            ordered.append(cards.pop(0))
    if count is None:
        return ordered
    return [ordered[index % len(ordered)] for index in range(max(1, count))]


DEMO_EPOCH = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)
"""The instant the frozen demo clock starts at (a Tuesday afternoon)."""

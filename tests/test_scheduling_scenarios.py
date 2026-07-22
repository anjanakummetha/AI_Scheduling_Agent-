"""Calendar-reality scenarios (plan Phase 2): the engine, over a realistic busy
week, must never offer a time that collides with a protected block, must skip
travel days, and must prefer Kory's morning windows."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.scheduling.busy_intervals import slot_conflicts_busy, parse_event_datetime, local_dt
from app.scheduling.slot_engine import find_valid_slots

MT = ZoneInfo("America/Denver")
# Reference "now": Sunday 2026-07-19 06:00 MT, so the upcoming week is Mon 7/20+.
NOW = datetime(2026, 7, 19, 6, 0, tzinfo=MT)


def _ev(subject: str, day: str, start: str, end: str, show: str = "busy") -> dict:
    return {
        "subject": subject,
        "start": {"dateTime": f"{day}T{start}:00", "timeZone": "America/Denver"},
        "end": {"dateTime": f"{day}T{end}:00", "timeZone": "America/Denver"},
        "showAs": show,
    }


def _context(events: list[dict]) -> dict:
    return {"status": "available", "horizon_days": 12, "busy_events": events}


# A realistic upcoming week mirroring the live calendar's shape.
BUSY = [
    _ev("KM Personal Training Session", "2026-07-20", "06:30", "08:30"),   # Mon workout
    _ev("Doug (Executive Coach)", "2026-07-20", "13:15", "14:15"),         # Mon coach
    _ev("KM daily inbox review [DO NOT MOVE]", "2026-07-20", "15:00", "15:30"),
    _ev("WOB", "2026-07-21", "08:00", "10:00"),                            # Tue deep work
    _ev("KM Personal Training Session", "2026-07-22", "06:30", "08:30"),   # Wed workout
    _ev("Kory in NYC", "2026-07-23", "06:00", "20:00"),                    # Thu travel day
    _ev("Patrick | Kory Weekly Check In", "2026-07-24", "10:30", "11:30"), # Fri sync
    _ev("KM Personal Training Session", "2026-07-24", "06:30", "08:30"),   # Fri workout
]


def _offered(intent: str, subject: str):
    prop = find_valid_slots(
        _context(BUSY), intent=intent, subject=subject, body="", reference_now=NOW
    )
    return prop.slots


def test_no_slot_collides_with_any_protected_block():
    slots = _offered("virtual_30", "30-min Teams intro")
    assert slots, "expected some availability in the week"
    for s in slots:
        assert not slot_conflicts_busy(s, BUSY), f"slot {s} overlaps a protected block"


def test_travel_day_thursday_never_offered():
    slots = _offered("virtual_30", "30-min Teams intro")
    for s in slots:
        d = local_dt(parse_event_datetime(s["start"])).date()
        assert d != datetime(2026, 7, 23).date(), "must not offer on the NYC travel day"


def test_offers_land_in_business_hours_and_before_6pm():
    for intent, subj in [("virtual_30", "30-min Teams"), ("coffee", "Coffee?")]:
        for s in _offered(intent, subj):
            start = local_dt(parse_event_datetime(s["start"]))
            end = local_dt(parse_event_datetime(s["end"]))
            assert start.hour >= 6
            assert end.hour < 18 or (end.hour == 18 and end.minute == 0)


def test_weekend_not_offered():
    slots = _offered("virtual_30", "30-min Teams intro")
    for s in slots:
        wd = local_dt(parse_event_datetime(s["start"])).weekday()
        assert wd < 5, "no weekend meetings by default"

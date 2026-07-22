"""Regression tests for Phase 2 scheduling correctness fixes."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.jobs.hold_lifecycle import _next_week_window_mt
from app.rules.validators import validate_proposal_slots

MT = ZoneInfo("America/Denver")


def _slot(day: str, start: str, end: str) -> dict[str, str]:
    # day like "2026-07-14" (a Tuesday); times in MT
    return {"start": f"{day}T{start}:00-06:00", "end": f"{day}T{end}:00-06:00"}


# --- East-Coast 6 AM (Tue/Thu) ------------------------------------------------

def test_east_coast_6am_tuesday_accepted():
    # 2026-07-14 is a Tuesday. 6:00 AM MT should be valid for an East-Coast contact.
    slot = _slot("2026-07-14", "06:00", "06:30")
    res = validate_proposal_slots(
        [slot], intent="virtual_30", meeting_format="virtual", east_coast=True
    )
    assert res.valid, res.violations


def test_non_east_coast_6am_tuesday_rejected():
    slot = _slot("2026-07-14", "06:00", "06:30")
    res = validate_proposal_slots(
        [slot], intent="virtual_30", meeting_format="virtual", east_coast=False
    )
    assert not res.valid
    assert any("6 AM" in v and "East Coast" in v for v in res.violations)


# --- Happy-hour weekly cap: alternatives count once --------------------------

def test_happy_hour_three_alternatives_same_week_within_cap():
    # Three alternative HH times in one week for ONE happy hour must not trip the
    # cap of 2 (only one option would ever be booked).
    slots = [
        _slot("2026-07-14", "15:30", "17:00"),  # Tue
        _slot("2026-07-15", "16:00", "17:30"),  # Wed
        _slot("2026-07-16", "15:30", "17:00"),  # Thu
    ]
    res = validate_proposal_slots(slots, intent="happy_hour", meeting_format="in_person")
    assert not any("happy hour cap" in v for v in res.violations), res.violations


# --- Friday next-week window is Mountain Time --------------------------------

def test_next_week_window_is_next_monday_mt():
    # A Friday in MT → window starts the following Monday 00:00 MT.
    friday = datetime(2026, 7, 17, 16, 0, tzinfo=MT)  # Fri
    assert friday.weekday() == 4
    week_start, week_end = _next_week_window_mt(friday)
    assert week_start == datetime(2026, 7, 20, 0, 0, tzinfo=MT)  # Mon
    assert week_end == datetime(2026, 7, 27, 0, 0, tzinfo=MT)
    assert week_start.weekday() == 0


def test_next_week_window_excludes_this_weekend():
    friday = datetime(2026, 7, 17, 23, 30, tzinfo=MT)
    week_start, _ = _next_week_window_mt(friday)
    # Saturday 7/18 (this week) must NOT fall in the next-week window.
    assert datetime(2026, 7, 18, 12, 0, tzinfo=MT) < week_start

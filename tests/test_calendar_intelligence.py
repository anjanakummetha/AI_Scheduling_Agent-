"""Tests for calendar intelligence (Kory blocking vs kid-only / copies)."""

from __future__ import annotations

from app.scheduling.calendar_intelligence import (
    EventBlockingClass,
    classify_event,
    dedupe_and_filter_blocking_events,
    resolve_calendar_horizon_days,
)


def _event(subject: str, *, calendar: str = "Calendar", start: str = "2026-07-01T16:30:00") -> dict:
    return {
        "subject": subject,
        "calendar_name": calendar,
        "start": {"dateTime": start, "timeZone": "America/Denver"},
        "end": {"dateTime": "2026-07-01T17:30:00", "timeZone": "America/Denver"},
        "showAs": "busy",
    }


def test_kid_summer_camp_on_master_does_not_block() -> None:
    classified = classify_event(
        _event(
            "Maclain @ ISD Summer Camp : Mystery Camp (8:30-3:30pm) (copy)",
            calendar="Kory Master Calendar (ALL)",
        )
    )
    assert classified.blocking_class == EventBlockingClass.KID_ONLY_NON_BLOCKING
    assert classified.blocks_kory is False


def test_km_personal_training_blocks() -> None:
    classified = classify_event(
        _event(
            "KM Personal Training Session (copy)",
            calendar="Kory Master Calendar (ALL)",
            start="2026-07-01T08:30:00",
        )
    )
    assert classified.blocking_class == EventBlockingClass.PERSONAL_KORY_BLOCKING
    assert classified.blocks_kory is True


def test_work_hold_on_calendar_blocks() -> None:
    classified = classify_event(_event("HOLD: Intro call w/ Steve"))
    assert classified.blocking_class == EventBlockingClass.WORK_BLOCKING
    assert classified.blocks_kory is True


def test_duplicate_copy_on_master_skipped_when_work_exists() -> None:
    work = _event("HOLD: Intro call w/ Steve", calendar="Calendar")
    copy = _event(
        "HOLD: Intro call w/ Steve (copy)",
        calendar="Kory Master Calendar (ALL)",
    )
    blocking, _ = dedupe_and_filter_blocking_events([work, copy])
    assert len(blocking) == 1
    assert blocking[0]["calendar_name"] == "Calendar"


def test_travel_stay_blocks() -> None:
    classified = classify_event(
        _event(
            "Stay at Comfort Suites Denver",
            calendar="Kory Master Calendar (ALL)",
        )
    )
    assert classified.blocking_class == EventBlockingClass.TRAVEL_BLOCKING
    assert classified.blocks_kory is True


def test_horizon_extends_for_far_future_email() -> None:
    days = resolve_calendar_horizon_days(
        subject="Meeting in July",
        body="Can we meet late next month?",
    )
    assert days >= 60

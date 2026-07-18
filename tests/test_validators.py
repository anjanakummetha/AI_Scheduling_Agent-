"""Tests for Kory scheduling validators."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.rules.validators import validate_proposal_slots

MT = ZoneInfo("America/Denver")


def _slot(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    *,
    duration_min: int = 30,
) -> dict[str, str]:
    start = datetime(year, month, day, hour, minute, tzinfo=MT)
    from datetime import timedelta

    end = start + timedelta(minutes=duration_min)
    return {"start": start.isoformat(), "end": end.isoformat()}


def test_rejects_monday_trainer_block() -> None:
    result = validate_proposal_slots(
        [_slot(2026, 7, 6, 7, 0)],
        intent="virtual_30",
    )
    assert not result.valid
    assert any("Trainer" in v for v in result.violations)


def test_rejects_weekend_by_default() -> None:
    result = validate_proposal_slots(
        [_slot(2026, 7, 11, 10, 0)],
        intent="virtual_30",
    )
    assert not result.valid


def test_coffee_prefers_block_and_rejects_after_six() -> None:
    late = validate_proposal_slots(
        [_slot(2026, 7, 7, 17, 0, duration_min=90)],
        intent="coffee",
        meeting_format="in_person",
    )
    assert not late.valid


def test_travel_day_rejected() -> None:
    busy = [
        {
            "subject": "Flight to London",
            "blocking_class": "travel_blocking",
            "start": {"dateTime": "2026-07-08T08:00:00"},
            "end": {"dateTime": "2026-07-08T22:00:00"},
        }
    ]
    result = validate_proposal_slots(
        [_slot(2026, 7, 8, 10, 0)],
        intent="virtual_30",
        busy_events=busy,
    )
    assert not result.valid
    assert any("traveling" in v.lower() for v in result.violations)


def test_calendar_overlap_rejected() -> None:
    busy = [
        {
            "subject": "Existing meeting",
            "start": {"dateTime": "2026-07-09T10:00:00-06:00"},
            "end": {"dateTime": "2026-07-09T11:00:00-06:00"},
        }
    ]
    result = validate_proposal_slots(
        [_slot(2026, 7, 9, 10, 15)],
        intent="virtual_30",
        busy_events=busy,
    )
    assert not result.valid


def test_lunch_rejected_without_override() -> None:
    result = validate_proposal_slots(
        [_slot(2026, 7, 7, 12, 0)],
        intent="lunch",
        meeting_format="in_person",
    )
    assert not result.valid

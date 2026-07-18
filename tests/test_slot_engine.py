"""Tests for deterministic slot engine."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.scheduling.busy_intervals import slot_conflicts_busy
from app.scheduling.slot_engine import find_valid_slots, infer_meeting_format

MT = ZoneInfo("America/Denver")


def _busy_event(subject: str, start: datetime, end: datetime) -> dict:
    return {
        "subject": subject,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "blocking_class": "work_blocking",
    }


def _calendar_context(
    busy: list[dict] | None = None,
    *,
    horizon_days: int = 21,
) -> dict:
    now = datetime.now(tz=MT)
    return {
        "status": "available",
        "horizon_days": horizon_days,
        "range_start": now.isoformat(),
        "range_end": (now + timedelta(days=horizon_days)).isoformat(),
        "busy_events": busy or [],
    }


def test_infer_coffee_in_person() -> None:
    assert infer_meeting_format("coffee", subject="Coffee next week") == "in_person"


def test_find_slots_skips_busy_blocks() -> None:
    now = datetime.now(tz=MT)
    day = (now + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
    busy = [_busy_event("Board prep", day, day + timedelta(hours=1))]
    result = find_valid_slots(
        _calendar_context(busy),
        intent="virtual_30",
        subject="30 min teams",
    )
    for slot in result.slots:
        assert not slot_conflicts_busy(slot, busy)


def test_find_slots_respects_next_week_window() -> None:
    now = datetime(2026, 6, 23, 10, 0, tzinfo=MT)
    result = find_valid_slots(
        _calendar_context(horizon_days=30),
        intent="virtual_30",
        subject="TEST intro",
        body="30-minute intro call sometime next week",
        reference_now=now,
    )
    assert result.diagnostics.get("scheduling_window", {}).get("label") == "next week"
    for slot in result.slots:
        start = datetime.fromisoformat(slot["start"]).astimezone(MT).date()
        assert datetime(2026, 6, 29).date() <= start <= datetime(2026, 7, 5).date()


def test_find_slots_returns_at_least_two_when_calendar_open() -> None:
    result = find_valid_slots(
        _calendar_context(),
        intent="virtual_30",
        subject="Quick intro call",
    )
    assert len(result.slots) >= 2
    assert result.diagnostics.get("status", "ok") == "ok" or len(result.slots) >= 2


def test_coffee_slots_use_60_min_offer_and_90_reserve() -> None:
    result = find_valid_slots(
        _calendar_context(),
        intent="coffee",
        subject="Coffee in Cherry Creek",
    )
    if result.slots:
        start = datetime.fromisoformat(result.slots[0]["start"])
        end = datetime.fromisoformat(result.slots[0]["end"])
        minutes = int((end - start).total_seconds() // 60)
        assert minutes == 60
        assert result.diagnostics.get("reserve_minutes") == 90


def test_tuesday_830_coffee_allowed_by_kory_rules() -> None:
    ref = datetime(2026, 7, 1, 10, 0, tzinfo=MT)  # Wednesday; next week is Jul 6-12
    busy = [
        _busy_event(
            "IFG | Weekly Stand Up (Virtual)",
            datetime(2026, 7, 7, 10, 0, tzinfo=MT),
            datetime(2026, 7, 7, 12, 0, tzinfo=MT),
        )
    ]
    result = find_valid_slots(
        _calendar_context(busy, horizon_days=14),
        intent="coffee",
        subject="Coffee in Cherry Creek",
        body="Find me 2 coffee meeting times next week in Cherry Creek.",
        reference_now=ref,
    )
    starts = {
        datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).astimezone(MT).strftime("%Y-%m-%d %H:%M")
        for slot in result.slots
    }
    assert "2026-07-07 08:30" in starts


def test_find_slots_avoid_doug_and_coffee_hold() -> None:
    ref = datetime(2026, 6, 29, 10, 0, tzinfo=MT)
    busy = [
        _busy_event(
            "Doug",
            datetime(2026, 7, 6, 13, 15, tzinfo=MT),
            datetime(2026, 7, 6, 14, 30, tzinfo=MT),
        ),
        _busy_event(
            "HOLD: Coffee w/ Alejandra Harvey (copy)",
            datetime(2026, 7, 7, 16, 0, tzinfo=MT),
            datetime(2026, 7, 7, 17, 30, tzinfo=MT),
        ),
    ]
    result = find_valid_slots(
        _calendar_context(busy),
        intent="virtual_30",
        subject="TEST intro call",
        body="next week Monday through Wednesday between 9 AM and 4:30 PM Mountain Time",
        reference_now=ref,
    )
    for slot in result.slots:
        assert not slot_conflicts_busy(slot, busy)
        start = datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).astimezone(MT)
        if start.date().isoformat() == "2026-07-06" and start.hour in {13, 14}:
            if start.hour == 14 and start.minute >= 30:
                continue
            raise AssertionError(f"Monday slot overlaps Doug: {slot}")
        if start.date().isoformat() == "2026-07-07" and start.hour == 16:
            raise AssertionError(f"Tuesday slot overlaps coffee hold: {slot}")


def test_find_slots_respect_time_and_weekday_bounds() -> None:
    ref = datetime(2026, 6, 29, 10, 0, tzinfo=MT)
    result = find_valid_slots(
        _calendar_context(),
        intent="virtual_30",
        subject="TEST intro",
        body="next week Monday through Wednesday between 9 AM and 4:30 PM MT",
        reference_now=ref,
    )
    assert result.diagnostics.get("time_of_day_window")
    assert result.diagnostics.get("allowed_weekdays") == [0, 1, 2]
    for slot in result.slots:
        start = datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).astimezone(MT)
        assert start.weekday() in {0, 1, 2}
        assert start.hour >= 9
        assert start.hour < 16 or (start.hour == 16 and start.minute == 0)

"""Tests for scheduling window inference."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.scheduling.scheduling_window import infer_scheduling_window

MT = ZoneInfo("America/Denver")


def test_next_week_window():
    # Tuesday Jun 23 2026 → next week Mon Jun 29 – Sun Jul 5
    now = datetime(2026, 6, 23, 10, 0, tzinfo=MT)
    window = infer_scheduling_window(
        body="I'd love a 30-minute intro call sometime next week.",
        now=now,
    )
    assert window is not None
    assert window.start.isoformat() == "2026-06-29"
    assert window.end.isoformat() == "2026-07-05"


def test_no_window_when_unspecified():
    window = infer_scheduling_window(body="Can we meet soon?", now=datetime(2026, 6, 23, 10, 0, tzinfo=MT))
    assert window is None


def test_next_week_or_two_window():
    now = datetime(2026, 6, 23, 10, 0, tzinfo=MT)
    window = infer_scheduling_window(
        body="Would love 20 minutes in the next week or two to connect.",
        now=now,
    )
    assert window is not None
    assert window.label == "next week or two"
    assert window.start.isoformat() == "2026-06-29"
    assert window.end.isoformat() == "2026-07-12"


def test_before_travel_window():
    now = datetime(2026, 6, 23, 10, 0, tzinfo=MT)  # Tuesday
    window = infer_scheduling_window(
        body="Love to connect this week before I head to Africa Saturday.",
        now=now,
    )
    assert window is not None
    assert window.label == "before travel"
    assert window.end.isoformat() == "2026-06-26"  # Friday before Saturday


def test_time_of_day_window_between():
    from app.scheduling.scheduling_window import infer_time_of_day_window, slot_start_in_time_window

    window = infer_time_of_day_window(
        body="between 9 AM and 4:30 PM Mountain Time for a 30-minute call"
    )
    assert window is not None
    assert window.start_hour == 9
    assert window.end_hour == 16
    assert window.end_minute == 30
    ok = datetime(2026, 7, 6, 16, 0, tzinfo=MT)
    bad_early = datetime(2026, 7, 6, 8, 0, tzinfo=MT)
    assert slot_start_in_time_window(ok, window, block_minutes=30)
    assert not slot_start_in_time_window(bad_early, window, block_minutes=30)


def test_weekday_range_mon_through_wed():
    from app.scheduling.scheduling_window import infer_allowed_weekdays

    days = infer_allowed_weekdays(body="next week Monday through Wednesday afternoon")
    assert days == {0, 1, 2}

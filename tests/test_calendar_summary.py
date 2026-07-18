"""Tests for calendar window summaries."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.scheduling.calendar_summary import build_calendar_window_summary
from app.scheduling.scheduling_window import SchedulingWindow, infer_scheduling_window

MT = ZoneInfo("America/Denver")


def test_next_week_from_july_1_is_july_6_through_12() -> None:
    now = datetime(2026, 7, 1, 19, 0, tzinfo=MT)
    window = infer_scheduling_window(body="summarize my full calendar for next week", now=now)
    assert window is not None
    assert window.start.isoformat() == "2026-07-06"
    assert window.end.isoformat() == "2026-07-12"


def test_build_calendar_window_summary_groups_by_day() -> None:
    window = SchedulingWindow(
        start=datetime(2026, 7, 6, tzinfo=MT).date(),
        end=datetime(2026, 7, 7, tzinfo=MT).date(),
        source="test",
        label="next week",
    )
    busy = [
        {
            "subject": "Intro call",
            "start": {"dateTime": "2026-07-06T09:00:00", "timeZone": "America/Denver"},
            "end": {"dateTime": "2026-07-06T09:30:00", "timeZone": "America/Denver"},
        },
        {
            "subject": "Board prep",
            "start": {"dateTime": "2026-07-07T14:00:00", "timeZone": "America/Denver"},
            "end": {"dateTime": "2026-07-07T15:00:00", "timeZone": "America/Denver"},
        },
    ]
    result = build_calendar_window_summary(busy_events=busy, window=window)
    assert result["total_events"] == 2
    assert "Monday, July 6, 2026" in result["formatted_summary"]
    assert "Intro call" in result["formatted_summary"]
    assert "Board prep" in result["formatted_summary"]
    assert "IFG Team" not in result["formatted_summary"]

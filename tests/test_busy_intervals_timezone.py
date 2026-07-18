"""Outlook event datetime parsing must respect embedded timeZone."""

from zoneinfo import ZoneInfo

from app.scheduling.busy_intervals import parse_event_datetime, slot_conflicts_busy


def test_parse_event_datetime_respects_outlook_timezone():
    dt = parse_event_datetime(
        {"dateTime": "2026-06-29T10:00:00", "timeZone": "America/Denver"}
    )
    assert dt is not None
    local = dt.astimezone(ZoneInfo("America/Denver"))
    assert local.hour == 10


def test_slot_conflicts_denver_calendar_event():
    busy = [
        {
            "subject": "Project Sierra - Last Deep Dive",
            "start": {"dateTime": "2026-06-29T10:00:00", "timeZone": "America/Denver"},
            "end": {"dateTime": "2026-06-29T12:00:00", "timeZone": "America/Denver"},
        }
    ]
    slot = {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T11:00:00-06:00"}
    assert slot_conflicts_busy(slot, busy) is True

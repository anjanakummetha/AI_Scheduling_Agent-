"""Infer requested scheduling window from email subject/body (e.g. 'next week')."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings

MT = ZoneInfo(settings.scheduling_timezone)


@dataclass(frozen=True)
class SchedulingWindow:
    start: date  # inclusive (local MT)
    end: date  # inclusive (local MT)
    source: str
    label: str


def _week_bounds(anchor: date) -> tuple[date, date]:
    """Monday–Sunday week containing anchor."""
    monday = anchor - timedelta(days=anchor.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def infer_scheduling_window(
    *,
    subject: str = "",
    body: str = "",
    now: datetime | None = None,
) -> SchedulingWindow | None:
    """Return a date window when the sender names one; else None (use full horizon)."""
    combined = f"{subject}\n{body}".lower()
    today = (now or datetime.now(tz=MT)).astimezone(MT).date()

    if re.search(r"\bbefore\s+i\s+(?:take\s+off|head\s+to|leave)\b", combined):
        start = today + timedelta(days=1) if today.weekday() < 5 else today
        this_monday, this_sunday = _week_bounds(today)
        end = this_sunday
        if re.search(r"\b(?:on\s+)?saturday\b", combined):
            days_to_sat = (5 - today.weekday()) % 7
            if days_to_sat == 0:
                days_to_sat = 7
            travel_sat = today + timedelta(days=days_to_sat)
            end = min(end, travel_sat - timedelta(days=1))
        return SchedulingWindow(
            start=start,
            end=end,
            source="body",
            label="before travel",
        )

    if re.search(r"\bthis\s+week\b", combined):
        start, end = _week_bounds(today)
        if today > start:
            start = today + timedelta(days=1)  # skip today for scheduling
        return SchedulingWindow(start=start, end=end, source="body", label="this week")

    if re.search(r"\bnext\s+week\b", combined) and not re.search(
        r"\bnext\s+(?:week\s+or\s+(?:two|so)|couple\s+(?:of\s+)?weeks?)\b", combined
    ):
        this_monday, this_sunday = _week_bounds(today)
        next_monday = this_monday + timedelta(days=7)
        next_sunday = this_sunday + timedelta(days=7)
        return SchedulingWindow(
            start=next_monday,
            end=next_sunday,
            source="body",
            label="next week",
        )

    if re.search(
        r"\bnext\s+(?:week\s+or\s+(?:two|so)|couple\s+(?:of\s+)?weeks?)\b", combined
    ):
        this_monday, this_sunday = _week_bounds(today)
        next_monday = this_monday + timedelta(days=7)
        end_sunday = this_sunday + timedelta(days=14)
        return SchedulingWindow(
            start=next_monday,
            end=end_sunday,
            source="body",
            label="next week or two",
        )

    if re.search(r"\b(?:in\s+)?two\s+weeks?\b", combined) or re.search(
        r"\bweek\s+after\s+next\b", combined
    ):
        this_monday, _ = _week_bounds(today)
        start_monday = this_monday + timedelta(days=14)
        end_sunday = start_monday + timedelta(days=6)
        return SchedulingWindow(
            start=start_monday,
            end=end_sunday,
            source="body",
            label="two weeks out",
        )

    if re.search(r"\btomorrow\b", combined):
        d = today + timedelta(days=1)
        return SchedulingWindow(start=d, end=d, source="body", label="tomorrow")

    if re.search(r"\btoday\b", combined) and "not today" not in combined:
        return SchedulingWindow(start=today, end=today, source="body", label="today")

    return None


@dataclass(frozen=True)
class TimeOfDayWindow:
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    label: str = ""

    def earliest_minutes(self) -> int:
        return self.start_hour * 60 + self.start_minute

    def latest_start_minutes(self, block_minutes: int) -> int:
        return self.end_hour * 60 + self.end_minute - block_minutes


_WEEKDAY_INDEX = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
}


def _parse_clock_token(hour: int, minute: int, ampm: str | None) -> tuple[int, int]:
    h = hour
    token = (ampm or "").lower()
    if token == "pm" and h != 12:
        h += 12
    elif token == "am" and h == 12:
        h = 0
    elif not token and 1 <= h <= 7:
        h += 12
    return h, minute


def infer_time_of_day_window(
    *,
    subject: str = "",
    body: str = "",
) -> TimeOfDayWindow | None:
    """Parse 'between 9 AM and 4:30 PM' or soft preferences like 'mornings work best'."""
    combined = f"{subject}\n{body}".lower()
    match = re.search(
        r"\bbetween\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+and\s+"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        combined,
    )
    if match:
        sh, sm, sampm, eh, em, eampm = match.groups()
        start_h, start_m = _parse_clock_token(int(sh), int(sm or 0), sampm)
        end_h, end_m = _parse_clock_token(int(eh), int(em or 0), eampm or sampm)
        if end_h * 60 + end_m > start_h * 60 + start_m:
            return TimeOfDayWindow(
                start_hour=start_h,
                start_minute=start_m,
                end_hour=end_h,
                end_minute=end_m,
                label=match.group(0).strip(),
            )

    if re.search(r"\b(mornings?|morning\s+works?)\b", combined) and not re.search(
        r"\b(afternoon|evening|after\s+\d|pm)\b", combined
    ):
        return TimeOfDayWindow(
            start_hour=8,
            start_minute=0,
            end_hour=12,
            end_minute=0,
            label="mornings",
        )

    if re.search(r"\b(early\s+morning|early\s+am)\b", combined):
        return TimeOfDayWindow(
            start_hour=7,
            start_minute=0,
            end_hour=11,
            end_minute=0,
            label="early morning",
        )

    if re.search(r"\bafternoons?\b", combined) and not re.search(r"\b(morning|evening)\b", combined):
        return TimeOfDayWindow(
            start_hour=12,
            start_minute=0,
            end_hour=17,
            end_minute=0,
            label="afternoons",
        )

    if re.search(r"\b(at\s+)?6:?\s*30\s*pm\b|\b6:30\s*pm\b", combined) and not re.search(
        r"\bother\s+options\b", combined
    ):
        return TimeOfDayWindow(
            start_hour=18,
            start_minute=30,
            end_hour=19,
            end_minute=0,
            label="6:30 PM",
        )

    return None


def infer_allowed_weekdays(
    *,
    subject: str = "",
    body: str = "",
) -> set[int] | None:
    """Parse 'Monday through Wednesday' (or Tue/Wed only) weekday constraints."""
    combined = f"{subject}\n{body}".lower()
    range_match = re.search(
        r"\b("
        r"monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thur|thurs|friday|fri"
        r")\s+through\s+("
        r"monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thur|thurs|friday|fri"
        r")\b",
        combined,
    )
    if range_match:
        start = _WEEKDAY_INDEX[range_match.group(1)]
        end = _WEEKDAY_INDEX[range_match.group(2)]
        if start <= end:
            return set(range(start, end + 1))
        return set(range(start, 7)) | set(range(0, end + 1))

    days: set[int] = set()
    for token in re.findall(
        r"\b(monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thur|thurs|friday|fri)\b",
        combined,
    ):
        if token in {
            "monday",
            "mon",
            "tuesday",
            "tue",
            "tues",
            "wednesday",
            "wed",
            "thursday",
            "thu",
            "thur",
            "thurs",
            "friday",
            "fri",
        }:
            days.add(_WEEKDAY_INDEX[token])
    if len(days) >= 2 and re.search(r"\b(?:or|and)\b", combined):
        return days
    return None


def slot_start_in_time_window(
    start_local: datetime,
    window: TimeOfDayWindow,
    *,
    block_minutes: int,
) -> bool:
    start_minutes = start_local.hour * 60 + start_local.minute
    return (
        window.earliest_minutes()
        <= start_minutes
        <= window.latest_start_minutes(block_minutes)
    )


def slot_date_in_window(slot: dict[str, str], window: SchedulingWindow) -> bool:
    try:
        start = datetime.fromisoformat(str(slot.get("start", "")).replace("Z", "+00:00"))
        local = start.astimezone(MT).date()
    except (TypeError, ValueError):
        return False
    return window.start <= local <= window.end

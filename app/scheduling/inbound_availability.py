"""Parse and validate times proposed by the email sender (inbound availability)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.rules.validators import validate_proposal_slots
from app.scheduling.busy_intervals import slot_conflicts_busy
from app.scheduling.meeting_type import resolve_meeting_type
from app.scheduling.scheduling_plan import build_scheduling_plan

MT = ZoneInfo(settings.scheduling_timezone)

_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
}


def extract_inbound_time_candidates(body: str, *, reference: datetime | None = None) -> list[dict[str, str]]:
    """Heuristic parse of prospect-proposed times from email body."""
    now = (reference or datetime.now(tz=MT)).astimezone(MT)
    text = (body or "").replace("\r", "")
    prefer_next_week = bool(re.search(r"\bnext\s+week\b", text, re.I))
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    patterns = [
        re.compile(
            r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Mon|Tue|Wed|Thu|Fri)"
            r"[^.\n]{0,60}?"
            r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"
            r"(?:\s*(?:mt|mst|mdt|mountain|mountain\s+time))?",
            re.I,
        ),
        re.compile(
            r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?"
            r"[^.\n]{0,20}?"
            r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?",
            re.I,
        ),
    ]

    for pattern in patterns:
        for match in pattern.finditer(text):
            slot = _match_to_slot(
                match,
                now=now,
                pattern=pattern.pattern,
                prefer_next_week=prefer_next_week,
            )
            if slot and slot["start"] not in seen:
                seen.add(slot["start"])
                candidates.append(slot)
            if len(candidates) >= 5:
                break
    return candidates[:5]


def _match_to_slot(
    match: re.Match[str],
    *,
    now: datetime,
    pattern: str,
    prefer_next_week: bool = False,
) -> dict[str, str] | None:
    try:
        if "Monday" in pattern or "Mon" in pattern:
            weekday_token = match.group(1).lower()
            hour = int(match.group(2))
            minute = int(match.group(3) or 0)
            ampm = (match.group(4) or "").lower().replace(".", "")
            target_wd = _WEEKDAYS.get(weekday_token[:3], _WEEKDAYS.get(weekday_token))
            if target_wd is None:
                return None
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            day = now.date()
            if prefer_next_week:
                this_monday = day - timedelta(days=day.weekday())
                day = this_monday + timedelta(days=7)
            for _ in range(14):
                if day.weekday() == target_wd and day >= now.date():
                    break
                day += timedelta(days=1)
            start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MT)
            if start < now + timedelta(hours=2):
                start += timedelta(days=7)
        else:
            month = int(match.group(1))
            day_num = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else now.year
            if year < 100:
                year += 2000
            hour = int(match.group(4))
            minute = int(match.group(5) or 0)
            ampm = (match.group(6) or "").lower().replace(".", "")
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            start = datetime(year, month, day_num, hour, minute, tzinfo=MT)
        end = start + timedelta(minutes=30)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "source": "inbound_availability",
        }
    except (TypeError, ValueError):
        return None


def validate_inbound_candidates(
    candidates: list[dict[str, str]],
    *,
    calendar_context: dict[str, Any],
    intent: str | None,
    subject: str = "",
    body: str = "",
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    """Return (valid_slots, invalid_slots, violation_summaries)."""
    if not candidates:
        return [], [], []

    meeting = resolve_meeting_type(intent=intent, subject=subject, body=body)
    from app.scheduling.slot_engine import infer_meeting_format

    meeting_format = infer_meeting_format(
        meeting.type_key,
        subject=subject,
        body=body,
    )
    duration = meeting.duration_minutes
    reserve = meeting.calendar_block_minutes
    busy = list(calendar_context.get("busy_events") or [])
    valid: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []
    notes: list[str] = []

    for raw in candidates:
        try:
            start = datetime.fromisoformat(str(raw["start"]).replace("Z", "+00:00"))
            end = start + timedelta(minutes=duration)
        except (TypeError, ValueError):
            invalid.append(raw)
            notes.append("unparseable inbound time")
            continue
        slot = {"start": start.isoformat(), "end": end.isoformat(), "source": "inbound_availability"}
        if slot_conflicts_busy(slot, busy, reserve_minutes=reserve):
            invalid.append(slot)
            notes.append(f"busy at {start.strftime('%A %I:%M %p')}")
            continue
        check = validate_proposal_slots(
            [slot],
            intent=meeting.type_key,
            meeting_format=meeting_format,
            busy_events=busy,
        )
        if check.valid:
            valid.append(slot)
        else:
            invalid.append(slot)
            notes.extend(check.violations[:2])
    return valid, invalid, notes


def body_looks_like_inbound_availability(body: str) -> bool:
    combined = (body or "").lower()
    if extract_inbound_time_candidates(body):
        return True
    cues = (
        "here are my times",
        "i'm available",
        "i am available",
        "my availability",
        "works for me:",
        "how about",
        "i can do",
        "i'm free",
        "i am free",
    )
    return any(c in combined for c in cues) and bool(
        re.search(r"\b(mon|tue|wed|thu|fri|am|pm|\d:\d)\b", combined)
    )

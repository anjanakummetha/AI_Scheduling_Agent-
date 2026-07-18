"""Parse calendar busy blocks and test slot overlap (single source of truth)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from zoneinfo import ZoneInfo

from app.config import settings


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _ensure_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def parse_event_datetime(value: Any) -> datetime | None:
    if isinstance(value, dict):
        tz_name = str(value.get("timeZone") or value.get("timezone") or "").strip()
        raw_dt = value.get("dateTime") or value.get("date")
        if isinstance(raw_dt, str):
            try:
                dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                if dt.tzinfo is None and tz_name:
                    dt = dt.replace(tzinfo=ZoneInfo(tz_name))
                return _ensure_aware(dt)
            except (TypeError, ValueError, Exception):
                pass
        value = raw_dt
    if not isinstance(value, str):
        return None
    return parse_iso_datetime(value)


def slot_interval(slot: dict[str, str]) -> tuple[datetime, datetime] | None:
    start = parse_iso_datetime(str(slot.get("start") or ""))
    end = parse_iso_datetime(str(slot.get("end") or ""))
    if not start or not end or end <= start:
        return None
    return start, end


def intervals_overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    return a_start < b_end and a_end > b_start


def slot_conflicts_busy(
    slot: dict[str, str],
    busy_events: list[dict[str, Any]],
    *,
    reserve_minutes: int | None = None,
) -> bool:
    """True when slot overlaps any busy event (strict — no double-booking).

    When reserve_minutes exceeds the slot length (e.g. coffee 60m offer + 90m reserve),
  checks the full reserve window for conflicts.
    """
    interval = slot_interval(slot)
    if not interval:
        return True
    slot_start, slot_end = interval
    if reserve_minutes:
        offer_minutes = int((slot_end - slot_start).total_seconds() // 60)
        if reserve_minutes > offer_minutes:
            slot_end = slot_start + timedelta(minutes=reserve_minutes)
    for event in busy_events:
        event_start = parse_event_datetime(event.get("start"))
        event_end = parse_event_datetime(event.get("end"))
        if not event_start or not event_end:
            continue
        if intervals_overlap(slot_start, slot_end, event_start, event_end):
            return True
    return False


def slot_conflicts_any_proposed(
    slot: dict[str, str],
    other_slots: list[dict[str, str]],
    *,
    reserve_minutes: int | None = None,
) -> bool:
    interval = slot_interval(slot)
    if not interval:
        return True
    s_start, s_end = interval
    if reserve_minutes:
        offer_minutes = int((s_end - s_start).total_seconds() // 60)
        if reserve_minutes > offer_minutes:
            s_end = s_start + timedelta(minutes=reserve_minutes)
    for other in other_slots:
        other_interval = slot_interval(other)
        if not other_interval:
            continue
        if intervals_overlap(s_start, s_end, other_interval[0], other_interval[1]):
            return True
    return False


def local_dt(dt: datetime) -> datetime:
    tz = ZoneInfo(settings.scheduling_timezone)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def events_on_local_date(
    busy_events: list[dict[str, Any]],
    day: datetime,
) -> list[dict[str, Any]]:
    """Events whose start falls on the given local calendar day."""
    target = local_dt(day).date()
    matched: list[dict[str, Any]] = []
    for event in busy_events:
        start = parse_event_datetime(event.get("start"))
        if not start:
            continue
        if local_dt(start).date() == target:
            matched.append(event)
    return matched

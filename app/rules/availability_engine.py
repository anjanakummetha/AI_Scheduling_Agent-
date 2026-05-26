"""Deterministic availability: legal slots from rules + live calendar."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.integrations.outlook_calendar import is_blocking_event
from app.rules.rule_engine import load_rules

TZ = ZoneInfo("America/Denver")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def find_legal_slots(
    *,
    meeting_type: str,
    meeting_format: str,
    busy_events: list[dict[str, Any]],
    urgency: str = "normal",
    requested_duration_minutes: int | None = None,
    anchor: datetime | None = None,
    preferred_dates: list[date] | None = None,
    east_coast_contact: bool = False,
) -> list[dict[str, Any]]:
    rules = load_rules()
    scheduling = rules["scheduling"]
    meeting_cfg = rules["meeting_types"].get(meeting_type) or rules["meeting_types"]["unknown"]
    duration = requested_duration_minutes or int(meeting_cfg.get("duration_minutes", 30))
    block_minutes = int(meeting_cfg.get("calendar_block_minutes", duration))
    if meeting_type == "coffee":
        block_minutes = int(scheduling.get("buffers", {}).get("coffee_block_minutes", 90))
    preferred_times = meeting_cfg.get("preferred_times") or []

    now = (anchor or datetime.now(tz=TZ)).astimezone(TZ).replace(second=0, microsecond=0)
    search_days = _search_horizon_days(scheduling, urgency, meeting_type)
    end_date = (now + timedelta(days=search_days)).date()

    parsed_busy = [_parse_busy(event) for event in busy_events if is_blocking_event(event)]
    parsed_busy = [item for item in parsed_busy if item]

    slots: list[dict[str, Any]] = []
    search_days: list[date] = preferred_dates or []
    if not search_days:
        day = now.date()
        while day <= end_date:
            search_days.append(day)
            day += timedelta(days=1)

    for day in search_days:
        if day < now.date() or day > end_date:
            continue
        if len(slots) >= 40:
            break
        if _is_travel_day(day, parsed_busy, scheduling):
            continue

        if day.weekday() >= 5 and scheduling["availability"]["weekends"]["default_available"] is False:
            continue

        if meeting_type == "happy_hour" and day.weekday() == 4 and meeting_cfg.get("avoid_friday"):
            continue

        if not _weekly_caps_allow(day, meeting_type, parsed_busy, scheduling):
            continue

        day_start, day_end = _day_window(
            day,
            scheduling,
            meeting_format,
            meeting_type,
            meeting_cfg,
            east_coast_contact=east_coast_contact,
        )
        if not day_start or not day_end:
            continue

        busy_today = _busy_for_day(day, parsed_busy)
        busy_today.extend(_yaml_hard_blocks(day, scheduling))
        busy_today = _apply_in_person_travel_buffers(busy_today, scheduling, meeting_format)
        busy_today = _merge_intervals(busy_today)

        free = _subtract_busy((day_start, day_end), busy_today)
        day_slots = _slots_from_free(
            free,
            block_minutes=block_minutes,
            duration_minutes=duration,
            preferred_times=preferred_times,
            meeting_type=meeting_type,
            meeting_format=meeting_format,
            day=day,
            scheduling=scheduling,
        )
        slots.extend(day_slots)

    return _dedupe_slots(slots)


def slot_key(slot: dict[str, Any]) -> str:
    return f"{slot.get('start')}|{slot.get('end')}"


def _search_horizon_days(scheduling: dict[str, Any], urgency: str, meeting_type: str) -> int:
    urgency_cfg = scheduling.get("urgency", {})
    if urgency == "same_week" or meeting_type == "new_client":
        return int(urgency_cfg.get("new_client_same_week_days", 7))
    if urgency == "low" or meeting_type == "podcast":
        return int(urgency_cfg.get("podcast_min_days_out", 21))
    return int(urgency_cfg.get("default_search_days", 14))


def _parse_busy(event: dict[str, Any]) -> tuple[datetime, datetime, str] | None:
    start = _parse_dt(event.get("start"))
    end = _parse_dt(event.get("end"))
    if not start or not end or end <= start:
        return None
    subject = str(event.get("subject") or "")
    return start, end, subject


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, dict):
        raw = value.get("dateTime") or value.get("date")
        if not raw:
            return None
        value = raw
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except ValueError:
        return None


def _subject_matches(subject: str, patterns: list[str]) -> bool:
    lowered = subject.lower()
    return any(pattern in lowered for pattern in patterns)


def _is_travel_day(day, parsed_busy: list, scheduling: dict[str, Any]) -> bool:
    patterns = scheduling.get("event_patterns", {}).get("travel", [])
    for start, end, subject in parsed_busy:
        if start.date() <= day <= end.date() and _subject_matches(subject, patterns):
            if (end - start) >= timedelta(hours=20) or "all day" in subject.lower():
                return True
    return False


def _weekly_caps_allow(day, meeting_type: str, parsed_busy: list, scheduling: dict[str, Any]) -> bool:
    caps = scheduling.get("caps", {})
    week_start = day - timedelta(days=day.weekday())
    week_end = week_start + timedelta(days=6)

    if meeting_type == "happy_hour":
        count = _count_weekly(parsed_busy, week_start, week_end, ["happy hour"])
        if count >= int(caps.get("happy_hour_per_week", 2)):
            return False

    if meeting_type == "dinner":
        count = _count_weekly(parsed_busy, week_start, week_end, ["dinner"])
        if count >= int(caps.get("dinner_per_week", 1)):
            return False

    return True


def _count_weekly(parsed_busy: list, week_start, week_end, keywords: list[str]) -> int:
    count = 0
    for start, _end, subject in parsed_busy:
        if week_start <= start.date() <= week_end and any(k in subject.lower() for k in keywords):
            count += 1
    return count


def _day_window(
    day,
    scheduling: dict[str, Any],
    meeting_format: str,
    meeting_type: str,
    meeting_cfg: dict,
    *,
    east_coast_contact: bool = False,
):
    weekday = WEEKDAYS[day.weekday()]
    day_rules = scheduling["availability"]["weekdays"].get(weekday, {})
    caps = scheduling.get("caps", {})

    if meeting_type == "dinner":
        earliest = time(17, 0)
        latest = time(21, 0)
    elif meeting_type == "happy_hour":
        earliest = time(15, 30)
        latest = time(18, 0)
    elif meeting_type == "coffee":
        earliest = time(8, 30)
        latest = time(12, 0)
    else:
        earliest = _parse_time(day_rules.get("earliest_default", "09:00"))
        if meeting_format == "virtual" and day_rules.get("earliest_virtual"):
            earliest = _parse_time(day_rules["earliest_virtual"])
        if meeting_format == "in_person" and day_rules.get("earliest_in_person"):
            earliest = _parse_time(day_rules["earliest_in_person"])
        if (
            east_coast_contact
            and meeting_format == "virtual"
            and weekday in {"tuesday", "thursday"}
            and day_rules.get("earliest_exception")
        ):
            earliest = min(earliest, _parse_time(day_rules["earliest_exception"]))
        latest = _parse_time(day_rules.get("latest", caps.get("evening_cutoff", "18:00")))

    start_dt = datetime.combine(day, earliest, tzinfo=TZ)
    end_dt = datetime.combine(day, latest, tzinfo=TZ)
    if end_dt <= start_dt:
        return None, None
    return start_dt, end_dt


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _busy_for_day(day, parsed_busy: list) -> list[tuple[datetime, datetime]]:
    intervals = []
    for start, end, _subject in parsed_busy:
        if start.date() <= day <= end.date():
            intervals.append(
                (
                    max(start, datetime.combine(day, time.min, tzinfo=TZ)),
                    min(end, datetime.combine(day, time(23, 59), tzinfo=TZ)),
                )
            )
    return intervals


def _yaml_hard_blocks(day, scheduling: dict[str, Any]) -> list[tuple[datetime, datetime]]:
    weekday = WEEKDAYS[day.weekday()]
    blocks = []
    for block in scheduling.get("hard_blocks", []):
        if weekday not in block.get("days", []):
            continue
        start = datetime.combine(day, _parse_time(block["start"]), tzinfo=TZ)
        end = datetime.combine(day, _parse_time(block["end"]), tzinfo=TZ)
        blocks.append((start, end))
    return blocks


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda item: item[0])
    merged = [sorted_intervals[0]]
    for start, end in sorted_intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _subtract_busy(
    free_window: tuple[datetime, datetime],
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    start, end = free_window
    free = [(start, end)]
    for busy_start, busy_end in busy:
        next_free = []
        for free_start, free_end in free:
            if busy_end <= free_start or busy_start >= free_end:
                next_free.append((free_start, free_end))
                continue
            if free_start < busy_start:
                next_free.append((free_start, busy_start))
            if busy_end < free_end:
                next_free.append((busy_end, free_end))
        free = next_free
    return [(s, e) for s, e in free if e - s >= timedelta(minutes=15)]


def _apply_in_person_travel_buffers(
    busy: list[tuple[datetime, datetime]],
    scheduling: dict[str, Any],
    meeting_format: str,
) -> list[tuple[datetime, datetime]]:
    if meeting_format != "in_person":
        return busy
    prep = int(scheduling.get("buffers", {}).get("in_person_prep_minutes", 15))
    return [(start - timedelta(minutes=prep), end) for start, end in busy]


def _slot_dict(
    start: datetime,
    end: datetime,
    meeting_type: str,
    meeting_format: str,
    scheduling: dict[str, Any],
    extra_reason: str = "",
) -> dict[str, Any]:
    slot = {
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "timezone": "America/Denver",
        "reason": _slot_reason(meeting_type, start) + extra_reason,
    }
    if meeting_type == "coffee":
        slot["location"] = scheduling.get("coffee", {}).get("default_location", "Olive & Finch, Cherry Creek")
        slot["block_minutes"] = int(scheduling.get("buffers", {}).get("coffee_block_minutes", 90))
    return slot


def _slots_from_free(
    free: list[tuple[datetime, datetime]],
    *,
    block_minutes: int,
    duration_minutes: int,
    preferred_times: list[str],
    meeting_type: str,
    meeting_format: str,
    day,
    scheduling: dict[str, Any],
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    block_delta = timedelta(minutes=block_minutes)
    step_minutes = block_minutes if meeting_type == "coffee" else 15
    step_delta = timedelta(minutes=step_minutes)

    candidates: list[datetime] = []
    if preferred_times:
        for pref in preferred_times:
            hour, minute = pref.split(":")
            candidates.append(datetime.combine(day, time(int(hour), int(minute)), tzinfo=TZ))
    else:
        for free_start, free_end in free:
            cursor = free_start
            while cursor + block_delta <= free_end:
                candidates.append(cursor)
                cursor += step_delta

    for start in candidates:
        end = start + block_delta
        if not any(free_start <= start and end <= free_end for free_start, free_end in free):
            continue
        slots.append(_slot_dict(start, end, meeting_type, meeting_format, scheduling))

    if not slots and meeting_type == "coffee":
        morning_end = datetime.combine(day, time(12, 0), tzinfo=TZ)
        for free_start, free_end in free:
            window_end = min(free_end, morning_end)
            cursor = max(free_start, datetime.combine(day, time(8, 30), tzinfo=TZ))
            while cursor + block_delta <= window_end:
                end = cursor + block_delta
                if free_start <= cursor and end <= free_end:
                    slots.append(
                        _slot_dict(
                            cursor,
                            end,
                            meeting_type,
                            meeting_format,
                            scheduling,
                            extra_reason=" (90-minute coffee block in open morning window).",
                        )
                    )
                cursor += step_delta

    return slots


def _slot_reason(meeting_type: str, start: datetime) -> str:
    return f"Open {meeting_type.replace('_', ' ')} window on {start.strftime('%A')} per scheduling rules."


def _dedupe_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for slot in slots:
        key = slot_key(slot)
        if key in seen:
            continue
        seen.add(key)
        unique.append(slot)
    return unique

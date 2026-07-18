"""Shift scheduling windows when Kory is traveling."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.scheduling.busy_intervals import parse_event_datetime
from app.scheduling.scheduling_plan import SchedulingPlan
from app.scheduling.scheduling_window import SchedulingWindow, _week_bounds

MT = ZoneInfo(settings.scheduling_timezone)

_TRAVEL_SUBJECT_KEYS = (
    "flight to",
    "flight from",
    "stay at",
    "safari",
    "in chicago",
    "in town",
    "travel",
    "check-in",
)


def _event_local_date(event: dict[str, Any]) -> date | None:
    start = parse_event_datetime(event.get("start"))
    if not start:
        return None
    return start.astimezone(MT).date()


def _is_travel_event(event: dict[str, Any]) -> bool:
    if str(event.get("blocking_class") or "") == "travel_blocking":
        return True
    subject = str(event.get("subject") or "").lower()
    return any(key in subject for key in _TRAVEL_SUBJECT_KEYS)


def travel_date_set(busy_events: list[dict[str, Any]]) -> set[date]:
    dates: set[date] = set()
    for event in busy_events or []:
        if not _is_travel_event(event):
            continue
        day = _event_local_date(event)
        if day:
            dates.add(day)
    return dates


def infer_travel_span_end(busy_events: list[dict[str, Any]], *, anchor: date) -> date | None:
    """Last consecutive travel day on or after anchor (within 21 days)."""
    travel = travel_date_set(busy_events)
    if not travel:
        return None
    end_scan = anchor + timedelta(days=21)
    span_days = [d for d in travel if anchor <= d <= end_scan]
    if not span_days:
        return None
    return max(span_days)


def window_overlaps_travel(window: SchedulingWindow, busy_events: list[dict[str, Any]]) -> bool:
    travel = travel_date_set(busy_events)
    if not travel or not window:
        return False
    day = window.start
    while day <= window.end:
        if day in travel:
            return True
        day += timedelta(days=1)
    return False


def shift_window_after_travel(
    window: SchedulingWindow,
    busy_events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> SchedulingWindow | None:
    """If window hits travel, move to the week after travel ends."""
    today = (now or datetime.now(tz=MT)).astimezone(MT).date()
    if not window_overlaps_travel(window, busy_events):
        return window
    travel_end = infer_travel_span_end(busy_events, anchor=min(window.start, today))
    if not travel_end:
        return window
    after = travel_end + timedelta(days=1)
    while after.weekday() >= 5:
        after += timedelta(days=1)
    monday, sunday = _week_bounds(after)
    return SchedulingWindow(
        start=monday,
        end=sunday,
        source="travel_shift",
        label=f"week of {monday.strftime('%B')} {monday.day} (after travel)",
    )


def maybe_shift_plan_window(
    plan: SchedulingPlan,
    busy_events: list[dict[str, Any]] | None,
    *,
    now: datetime | None = None,
) -> SchedulingPlan:
    if not plan or not plan.window or not busy_events:
        return plan
    shifted = shift_window_after_travel(plan.window, busy_events, now=now)
    if not shifted or shifted == plan.window:
        return plan
    return SchedulingPlan(
        task_type=plan.task_type,
        window=shifted,
        duration_minutes=plan.duration_minutes,
        meeting_format=plan.meeting_format,
        urgency=plan.urgency,
        draft_context=(
            (plan.draft_context or "").strip()
            + f" Kory is traveling — searching {shifted.label}."
        ).strip(),
        source="travel_shift",
        raw={**dict(plan.raw), "travel_shifted": True, "shifted_window": shifted.label},
    )

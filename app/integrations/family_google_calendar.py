"""Read family Google Calendar blocks (Do Not Move) for scheduling conflicts."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.config import settings

logger = logging.getLogger(__name__)

DO_NOT_MOVE_PATTERN = re.compile(r"do\s*not\s*move", re.IGNORECASE)
VEVENT_BLOCK = re.compile(
    r"BEGIN:VEVENT(.*?)END:VEVENT",
    re.DOTALL | re.IGNORECASE,
)


def _env_ics_url() -> str | None:
    import os

    return (os.getenv("FAMILY_GOOGLE_CALENDAR_ICS_URL") or "").strip() or None


def _parse_ics_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    if value.endswith("Z"):
        try:
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if "T" in value and len(value) >= 15:
        try:
            return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(
                tzinfo=ZoneInfo(settings.scheduling_timezone)
            )
        except ValueError:
            return None
    try:
        day = datetime.strptime(value[:8], "%Y%m%d")
        return day.replace(tzinfo=ZoneInfo(settings.scheduling_timezone))
    except ValueError:
        return None


def _extract_field(block: str, name: str) -> str:
    match = re.search(rf"^{name}[;:](.+)$", block, flags=re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _parse_ics_events(ics_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for match in VEVENT_BLOCK.finditer(ics_text):
        block = match.group(1)
        summary = _extract_field(block, "SUMMARY")
        if not DO_NOT_MOVE_PATTERN.search(summary):
            continue
        dtstart = _parse_ics_datetime(_extract_field(block, "DTSTART"))
        dtend = _parse_ics_datetime(_extract_field(block, "DTEND"))
        if not dtstart:
            continue
        if not dtend:
            dtend = dtstart + timedelta(hours=1)
        events.append(
            {
                "id": f"family-ics-{hash(summary + dtstart.isoformat())}",
                "subject": f"[Family] {summary}",
                "start": {"dateTime": dtstart.isoformat(), "timeZone": settings.scheduling_timezone},
                "end": {"dateTime": dtend.isoformat(), "timeZone": settings.scheduling_timezone},
                "showAs": "busy",
                "source": "family_google_ics",
                "isAllDay": "VALUE=DATE" in block.upper() and "T" not in _extract_field(block, "DTSTART"),
            }
        )
    return events


def fetch_family_busy_blocks(
    start_iso: str,
    end_iso: str,
) -> list[dict[str, Any]]:
    """Return family calendar events marked Do Not Move in the requested window."""
    ics_url = _env_ics_url()
    if not ics_url:
        return []

    try:
        request = Request(ics_url, headers={"User-Agent": "LexiSchedulingAgent/1.0"})
        with urlopen(request, timeout=15) as response:
            ics_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Family Google ICS fetch failed: %s", exc)
        return []

    try:
        window_start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        window_end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except ValueError:
        window_start = datetime.now(timezone.utc)
        window_end = window_start + timedelta(days=14)

    blocks: list[dict[str, Any]] = []
    for event in _parse_ics_events(ics_text):
        start_raw = (event.get("start") or {}).get("dateTime", "")
        end_raw = (event.get("end") or {}).get("dateTime", "")
        try:
            event_start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
            event_end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            blocks.append(event)
            continue
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=timezone.utc)
        if event_end.tzinfo is None:
            event_end = event_end.replace(tzinfo=timezone.utc)
        if event_start < window_end.astimezone(event_start.tzinfo) and event_end > window_start.astimezone(event_end.tzinfo):
            blocks.append(event)
    return blocks


def fetch_family_via_composio(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """Optional: read family calendar via Composio Google Calendar connection."""
    import os

    connection_id = (os.getenv("GOOGLE_COMPOSIO_CONNECTION_ID") or "").strip()
    calendar_id = (os.getenv("FAMILY_GOOGLE_CALENDAR_ID") or "").strip()
    if not connection_id or not calendar_id:
        return []

    try:
        from app.integrations.composio_client import get_composio

        response = get_composio().tools.execute(
            "GOOGLECALENDAR_EVENTS_LIST",
            arguments={
                "calendar_id": calendar_id,
                "time_min": start_iso,
                "time_max": end_iso,
                "single_events": True,
                "order_by": "startTime",
            },
            connected_account_id=connection_id,
            dangerously_skip_version_check=True,
        )
        data = response.get("data") if isinstance(response, dict) else getattr(response, "data", {})
        items = (data or {}).get("items") or (data or {}).get("value") or []
        blocks = []
        for item in items:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or "")
            if not DO_NOT_MOVE_PATTERN.search(summary):
                continue
            start = item.get("start") or {}
            end = item.get("end") or {}
            blocks.append(
                {
                    "id": item.get("id"),
                    "subject": f"[Family] {summary}",
                    "start": start,
                    "end": end,
                    "showAs": "busy",
                    "source": "family_google_composio",
                }
            )
        return blocks
    except Exception as exc:
        logger.warning("Family Google Composio read failed: %s", exc)
        return []


def get_family_busy_events(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """ICS URL first, then optional Composio Google connection."""
    merged: dict[str, dict[str, Any]] = {}
    for event in fetch_family_busy_blocks(start_iso, end_iso):
        merged[str(event.get("id"))] = event
    for event in fetch_family_via_composio(start_iso, end_iso):
        merged[str(event.get("id"))] = event
    return list(merged.values())


def family_calendar_configured() -> bool:
    import os

    if _env_ics_url():
        return True
    return bool(
        (os.getenv("GOOGLE_COMPOSIO_CONNECTION_ID") or "").strip()
        and (os.getenv("FAMILY_GOOGLE_CALENDAR_ID") or "").strip()
    )


def family_calendar_status() -> dict[str, Any]:
    import os

    ics = bool(_env_ics_url())
    composio = bool(
        (os.getenv("GOOGLE_COMPOSIO_CONNECTION_ID") or "").strip()
        and (os.getenv("FAMILY_GOOGLE_CALENDAR_ID") or "").strip()
    )
    return {
        "configured": ics or composio,
        "ics_url_set": ics,
        "google_composio_set": composio,
        "hint": (
            "Family calendar not configured. Ask Kory to set FAMILY_GOOGLE_CALENDAR_ICS_URL "
            "or connect Google via Composio. Weekend scheduling requires family 'Do Not Move' blocks."
            if not (ics or composio)
            else "Family Do Not Move blocks are merged into availability."
        ),
    }

"""Place tentative calendar holds on the write mailbox when offering slots."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.integrations.named_calendars import create_event_on_calendar, default_write_calendar_name
from app.integrations.outlook_calendar import has_conflict, has_write_calendar_conflict


def place_tentative_hold(
    *,
    title: str,
    start_iso: str,
    end_iso: str,
    notes: str = "",
    calendar_name: str | None = None,
) -> dict[str, Any]:
    """Create a Hold - event on write calendar; returns event_id or error."""
    subject = title.strip()
    if not subject.lower().startswith("hold"):
        subject = f"Hold - {subject}"

    action = {
        "title": subject,
        "start": start_iso,
        "end": end_iso,
        "attendees": [],
        "location": "TBD",
        "body": notes or "Lexi tentative hold while options are offered.",
    }
    if settings.lexi_write_mode == "sandbox":
        conflict, conflicts, _ = has_write_calendar_conflict(action)
    else:
        conflict, conflicts, _ = has_conflict(action)
    if conflict:
        return {
            "ok": False,
            "error": "conflict",
            "conflicting_events": conflicts[:3],
        }

    target_calendar = (calendar_name or "").strip() or default_write_calendar_name()
    event_id, log_id = create_event_on_calendar(action, calendar_name=target_calendar)
    return {
        "ok": bool(event_id),
        "event_id": event_id,
        "composio_log_id": log_id,
        "action": action,
    }

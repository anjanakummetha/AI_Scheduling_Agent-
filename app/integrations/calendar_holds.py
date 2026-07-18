"""Place tentative calendar holds on the write mailbox when offering slots."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.integrations.named_calendars import create_event_on_calendar, default_write_calendar_name
from app.integrations.outlook_calendar import has_conflict, has_write_calendar_conflict


def place_tentative_hold(
    *,
    action: dict[str, Any],
    calendar_name: str | None = None,
) -> dict[str, Any]:
    """Create a Hold event on the write calendar; returns event_id or error."""
    hold_action = dict(action)
    title = str(hold_action.get("title") or "HOLD: Meeting").strip()
    if not title.upper().startswith("HOLD:"):
        hold_action["title"] = f"HOLD: {title}"
    hold_action.setdefault("attendees", [])
    hold_action.setdefault("is_online_meeting", False)
    hold_action.setdefault(
        "body",
        hold_action.get("body") or "Lexi tentative hold while options are offered.",
    )

    if settings.lexi_write_mode == "sandbox":
        conflict, conflicts, _ = has_write_calendar_conflict(hold_action)
    else:
        conflict, conflicts, _ = has_conflict(hold_action)
    if conflict:
        return {
            "ok": False,
            "error": "conflict",
            "conflicting_events": conflicts[:3],
        }

    target_calendar = (calendar_name or "").strip() or default_write_calendar_name()
    event_id, log_id = create_event_on_calendar(hold_action, calendar_name=target_calendar)
    return {
        "ok": bool(event_id),
        "event_id": event_id,
        "composio_log_id": log_id,
        "action": hold_action,
    }

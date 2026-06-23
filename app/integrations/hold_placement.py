"""Unified calendar hold placement for all offer paths (inbound + outbound)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.integrations.calendar_holds import place_tentative_hold


def hold_expires_at(intent_classification: str | None) -> str:
    intent = (intent_classification or "").lower()
    days = 1 if intent == "reschedule" else 3
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def place_offered_holds(
    conn: sqlite3.Connection,
    *,
    proposal_id: int,
    slots: list[dict[str, str]],
    intent_classification: str | None,
    meeting_subject: str | None = None,
    calendar_name: str | None = None,
) -> int:
    """Insert hold rows and create real Outlook holds on the write calendar when live."""
    expires_at = hold_expires_at(intent_classification)
    hold_title = (meeting_subject or "Meeting option").strip()
    inserted = 0

    for index, slot in enumerate(slots, start=1):
        event_id = f"hold-pending-{proposal_id}-{index:02d}-{uuid.uuid4().hex[:8]}"
        if not settings.lexi_dry_run:
            hold_result = place_tentative_hold(
                title=f"{hold_title} (option {index})",
                start_iso=slot["start"],
                end_iso=slot["end"],
                calendar_name=calendar_name,
            )
            if hold_result.get("ok") and hold_result.get("event_id"):
                event_id = str(hold_result["event_id"])
            else:
                continue

        conn.execute(
            """
            INSERT INTO holds (proposal_id, event_id, slot_start, slot_end, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (proposal_id, event_id, slot["start"], slot["end"], expires_at),
        )
        inserted += 1
    return inserted

"""Unified calendar hold placement for all offer paths (inbound + outbound)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.integrations.calendar_holds import place_tentative_hold
from app.scheduling.calendar_intelligence import resolve_write_calendar_name
from app.scheduling.invite_builder import build_hold_action


class HoldPlacementError(RuntimeError):
    """Raised when one or more offered slots could not be held."""


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
    sender: str | None = None,
    body: str = "",
) -> int:
    """Insert hold rows and create Outlook holds — every slot must succeed."""
    if not slots:
        return 0

    target_calendar = (calendar_name or "").strip() or resolve_write_calendar_name(
        intent=intent_classification
    )
    expires_at = hold_expires_at(intent_classification)
    inserted = 0
    failures: list[str] = []

    for index, slot in enumerate(slots, start=1):
        start = str(slot.get("start") or "").strip()
        end = str(slot.get("end") or "").strip()
        if not start or not end:
            failures.append(f"option {index}: missing start/end")
            continue

        action = build_hold_action(
            slot={"start": start, "end": end},
            meeting_subject=meeting_subject,
            intent=intent_classification,
            option_index=index,
            sender=sender,
            body=body,
        )
        event_id = f"hold-pending-{proposal_id}-{index:02d}-{uuid.uuid4().hex[:8]}"

        if not settings.lexi_dry_run:
            hold_result = place_tentative_hold(action=action, calendar_name=target_calendar)
            if hold_result.get("ok") and hold_result.get("event_id"):
                event_id = str(hold_result["event_id"])
            else:
                reason = hold_result.get("error") or "unknown"
                conflicts = hold_result.get("conflicting_events") or []
                detail = f"option {index} ({start}): {reason}"
                if conflicts:
                    detail += f" — conflicts: {conflicts[:2]}"
                failures.append(detail)
                continue

        conn.execute(
            """
            INSERT INTO holds (proposal_id, event_id, slot_start, slot_end, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (proposal_id, event_id, start, end, expires_at),
        )
        inserted += 1

    if failures or inserted != len(slots):
        raise HoldPlacementError(
            f"Could only place {inserted}/{len(slots)} hold(s): " + "; ".join(failures)
        )
    return inserted

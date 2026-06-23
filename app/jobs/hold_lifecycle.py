"""Hold reminder, expiry release, and Friday cleanup for offered slots."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.integrations.outlook_calendar import delete_calendar_event
from app.storage.lexi_db import get_lexi_connection

import rules as kory_rules

logger = logging.getLogger(__name__)

PENDING_APPROVAL = "pending_approval"
RELEASED_STATUS = "released"


def run_hold_lifecycle_cycle() -> dict[str, Any]:
    """Release expired holds; optional Friday cleanup for next-week slots."""
    released = _release_expired_holds()
    friday = _friday_cleanup_next_week_holds()
    return {"released_expired": released, "friday_cleanup": friday}


def _release_expired_holds() -> int:
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    with get_lexi_connection() as conn:
        rows = conn.execute(
            """
            SELECT h.id, h.proposal_id, h.event_id, h.slot_start, h.expires_at,
                   p.status AS proposal_status, e.subject, e.sender
            FROM holds AS h
            INNER JOIN proposals AS p ON p.id = h.proposal_id
            LEFT JOIN email_threads AS e ON e.thread_id = p.thread_id
            WHERE h.expires_at IS NOT NULL
              AND h.expires_at != ?
              AND h.expires_at <= ?
              AND p.status = ?
              AND h.event_id NOT LIKE 'hold-pending-%'
              AND COALESCE(h.event_id, '') != ''
            """,
            (RELEASED_STATUS, now, PENDING_APPROVAL),
        ).fetchall()

        for row in rows:
            event_id = str(row["event_id"] or "")
            if not event_id or event_id.startswith("dry-run-"):
                continue
            try:
                delete_calendar_event(event_id)
            except Exception as exc:
                logger.warning("Failed to delete expired hold event %s: %s", event_id, exc)

            conn.execute(
                "UPDATE holds SET expires_at = ? WHERE id = ?",
                (RELEASED_STATUS, row["id"]),
            )
            _audit(
                conn,
                proposal_id=row["proposal_id"],
                message=(
                    f"Released expired hold for proposal {row['proposal_id']} "
                    f"(slot {row['slot_start']})."
                ),
                payload={
                    "event_id": event_id,
                    "expires_at": row["expires_at"],
                    "subject": row["subject"],
                    "sender": row["sender"],
                    "reminder_days": kory_rules.HOLD_RULES.get("reminder_after_days"),
                },
            )
            count += 1
            _maybe_notify_hold_released(row)

        if count:
            conn.commit()
    return count


def _friday_cleanup_next_week_holds() -> int:
    """On Friday UTC, release pending holds that fall in the following calendar week."""
    now = datetime.now(timezone.utc)
    if now.weekday() != 4:  # Friday
        return 0

    week_start = (now + timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    count = 0

    with get_lexi_connection() as conn:
        rows = conn.execute(
            """
            SELECT h.id, h.proposal_id, h.event_id, h.slot_start
            FROM holds AS h
            INNER JOIN proposals AS p ON p.id = h.proposal_id
            WHERE p.status = ?
              AND h.expires_at != ?
              AND h.event_id NOT LIKE 'hold-pending-%'
              AND COALESCE(h.event_id, '') != ''
            """,
            (PENDING_APPROVAL, RELEASED_STATUS),
        ).fetchall()

        for row in rows:
            slot_start = _parse_iso(row["slot_start"])
            if not slot_start or not (week_start <= slot_start < week_end):
                continue
            event_id = str(row["event_id"] or "")
            try:
                delete_calendar_event(event_id)
            except Exception as exc:
                logger.warning("Friday cleanup failed for %s: %s", event_id, exc)
            conn.execute(
                "UPDATE holds SET expires_at = ? WHERE id = ?",
                (RELEASED_STATUS, row["id"]),
            )
            _audit(
                conn,
                proposal_id=row["proposal_id"],
                message="Friday cleanup released hold for next week.",
                payload={"event_id": event_id, "slot_start": row["slot_start"]},
            )
            count += 1

        if count:
            conn.commit()
    return count


def _maybe_notify_hold_released(row: Any) -> None:
    if not settings.lexi_teams_enabled:
        return
    try:
        from app.bot.teams_format import display_sender, display_subject
        from app.bot.teams_publisher import push_approval_text_to_teams
        import asyncio

        subject = display_subject(row["subject"] or "(no subject)")
        sender = display_sender(row["sender"] or "unknown")
        release_days = kory_rules.HOLD_RULES.get("release_hold_after_days", 3)
        text = (
            f"**Lexi — hold released (no reply)**\n"
            f"**{subject}**\n"
            f"From {sender}\n"
            f"Slot: {row['slot_start']}\n\n"
            f"Held {release_days} days with no response — calendar hold removed. "
            f"Ask me to re-offer times for **{subject}** from {sender}."
        )
        coro = push_approval_text_to_teams(text, proposal_id=row["proposal_id"])
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as exc:
        logger.debug("Teams hold-release notify skipped: %s", exc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _audit(conn, *, proposal_id: int, message: str, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (step_name, reference_id, log_level, message, payload)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "hold_lifecycle",
            str(proposal_id),
            "INFO",
            message,
            json.dumps(payload, default=str),
        ),
    )

"""24h Kory nudges and scheduled 4:45 AM MT CEO briefing."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.storage.lexi_db import get_lexi_connection

logger = logging.getLogger(__name__)

_REMINDER_HOURS = int(__import__("os").getenv("LEXI_KORY_REMINDER_HOURS", "24"))
_BRIEFING_HOUR = int(__import__("os").getenv("LEXI_DAILY_BRIEFING_HOUR_MT", "4"))
_BRIEFING_MINUTE = int(__import__("os").getenv("LEXI_DAILY_BRIEFING_MINUTE_MT", "45"))
_BRIEFING_WINDOW_MIN = int(__import__("os").getenv("LEXI_DAILY_BRIEFING_WINDOW_MIN", "20"))


def _mt_now() -> datetime:
    try:
        tz = ZoneInfo(settings.scheduling_timezone)
    except Exception:
        tz = ZoneInfo("America/Denver")
    return datetime.now(tz)


def run_kory_briefing_cycle() -> dict[str, Any]:
    """Called from orchestrator each cycle — idempotent nudges + daily brief."""
    reminders = process_kory_24h_reminders()
    daily = process_daily_ceo_briefing_if_due()
    return {
        "kory_24h_reminders": len(reminders),
        "reminders": reminders,
        "daily_briefing_sent": daily.get("sent", False),
        "daily": daily,
    }


def process_kory_24h_reminders() -> list[dict[str, Any]]:
    """Teams nudge when Kory hasn't acted on Lexi items for 24h+."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_REMINDER_HOURS)
    cutoff_sql = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    staged: list[dict[str, Any]] = []

    with get_lexi_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id AS proposal_id, p.status, p.created_at, e.subject, e.sender
            FROM proposals p
            INNER JOIN email_threads e ON e.thread_id = p.thread_id
            WHERE p.status IN ('pending_approval', 'awaiting_reply_prompt')
              AND datetime(p.created_at) <= datetime(?)
            """,
            (cutoff_sql,),
        ).fetchall()

        for row in rows:
            proposal_id = int(row["proposal_id"])
            if _kory_reminder_already_sent(conn, proposal_id):
                continue
            staged.append(
                {
                    "proposal_id": proposal_id,
                    "status": row["status"],
                    "subject": row["subject"],
                    "sender": row["sender"],
                }
            )
            _audit_reminder(conn, proposal_id, row["status"])
            _notify_kory_24h_reminder(
                proposal_id=proposal_id,
                subject=str(row["subject"] or ""),
                sender=str(row["sender"] or ""),
                status=str(row["status"] or ""),
            )
        if staged:
            conn.commit()
    return staged


def process_daily_ceo_briefing_if_due(*, now: datetime | None = None) -> dict[str, Any]:
    """Send CEO briefing once per MT day around 4:45."""
    local = now or _mt_now()
    target = local.replace(
        hour=_BRIEFING_HOUR,
        minute=_BRIEFING_MINUTE,
        second=0,
        microsecond=0,
    )
    delta_min = abs((local - target).total_seconds()) / 60.0
    if delta_min > _BRIEFING_WINDOW_MIN:
        return {"sent": False, "reason": "outside_window", "local_time": local.isoformat()}

    day_key = local.strftime("%Y-%m-%d")
    if _daily_briefing_already_sent(day_key):
        return {"sent": False, "reason": "already_sent", "day": day_key}

    from app.assistant.briefings import build_daily_ceo_briefing

    package = build_daily_ceo_briefing()
    message = package.get("kory_message", "")
    _notify_daily_briefing(message, day_key=day_key)
    _mark_daily_briefing_sent(day_key, message)
    return {"sent": True, "day": day_key, "preview": message[:400]}


def _kory_reminder_already_sent(conn, proposal_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM audit_log
        WHERE step_name = 'kory_24h_reminder' AND reference_id = ?
        LIMIT 1
        """,
        (str(proposal_id),),
    ).fetchone()
    return row is not None


def _audit_reminder(conn, proposal_id: int, status: str) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (step_name, reference_id, log_level, message, payload)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "kory_24h_reminder",
            str(proposal_id),
            "INFO",
            f"24h Kory reminder staged for {status}",
            json.dumps({"status": status}),
        ),
    )


def _daily_briefing_already_sent(day_key: str) -> bool:
    with get_lexi_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM audit_log
            WHERE step_name = 'daily_ceo_briefing' AND reference_id = ?
            LIMIT 1
            """,
            (day_key,),
        ).fetchone()
    return row is not None


def _mark_daily_briefing_sent(day_key: str, message: str) -> None:
    with get_lexi_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (step_name, reference_id, log_level, message, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "daily_ceo_briefing",
                day_key,
                "INFO",
                "Daily CEO briefing delivered",
                json.dumps({"preview": message[:500]}),
            ),
        )
        conn.commit()


def _notify_kory_24h_reminder(
    *,
    proposal_id: int,
    subject: str,
    sender: str,
    status: str,
) -> None:
    if settings.lexi_suppress_teams_push:
        logger.info("24h reminder suppressed (LEXI_SUPPRESS_TEAMS_PUSH) proposal=%s", proposal_id)
        return
    try:
        from app.bot.teams_format import display_sender, display_subject
        from app.bot.teams_publisher import push_approval_text_to_teams
        import asyncio

        who = display_sender(sender)
        topic = display_subject(subject)
        action = "approve or discard the draft" if status == "pending_approval" else "say yes/no on drafting a reply"
        text = (
            f"**Lexi — 24h reminder**\n"
            f"**{topic}** from {who}\n\n"
            f"This has been waiting 24+ hours — {action}."
        )
        coro = push_approval_text_to_teams(text, proposal_id=proposal_id)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as exc:
        logger.debug("24h Teams notify skipped: %s", exc)


def _notify_daily_briefing(message: str, *, day_key: str) -> None:
    if settings.lexi_suppress_teams_push:
        logger.info("Daily briefing suppressed for %s", day_key)
        return
    try:
        from app.bot.teams_publisher import push_approval_text_to_teams
        import asyncio

        text = f"**Lexi — morning briefing**\n\n{message}"
        coro = push_approval_text_to_teams(text, proposal_id=f"brief-{day_key}")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as exc:
        logger.debug("Daily briefing Teams notify skipped: %s", exc)

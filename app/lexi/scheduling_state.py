"""
Stateful scheduling session management for Lexi.
Tracks the lifecycle: suggest times → place holds → confirm/cancel.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database import get_connection


def init_scheduling_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scheduling_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_session_id TEXT NOT NULL,
                contact_name TEXT NOT NULL,
                contact_email TEXT,
                meeting_type TEXT NOT NULL DEFAULT 'virtual_30',
                status TEXT NOT NULL DEFAULT 'holds_placed',
                offered_slots_json TEXT NOT NULL DEFAULT '[]',
                hold_event_ids_json TEXT NOT NULL DEFAULT '[]',
                confirmed_event_id TEXT,
                confirmed_slot_json TEXT,
                reminder_sent_at TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_sched_sessions_chat
            ON scheduling_sessions(chat_session_id);

            CREATE TABLE IF NOT EXISTS lexi_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT 'dashboard',
                outcome TEXT NOT NULL,
                situation_summary TEXT NOT NULL,
                action_taken TEXT NOT NULL,
                was_correct INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)


def create_hold_session(
    chat_session_id: str,
    contact_name: str,
    meeting_type: str,
    offered_slots: list[dict],
    hold_event_ids: list[str],
    contact_email: str | None = None,
    expires_in_days: int = 3,
) -> int:
    from datetime import timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO scheduling_sessions
              (chat_session_id, contact_name, contact_email, meeting_type,
               status, offered_slots_json, hold_event_ids_json, expires_at)
            VALUES (?, ?, ?, ?, 'holds_placed', ?, ?, ?)
            """,
            (
                chat_session_id,
                contact_name,
                contact_email,
                meeting_type,
                json.dumps(offered_slots),
                json.dumps(hold_event_ids),
                expires_at,
            ),
        )
        return cur.lastrowid


def get_active_sessions(chat_session_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM scheduling_sessions
            WHERE chat_session_id = ?
              AND status IN ('holds_placed', 'reminder_sent')
            ORDER BY created_at DESC
            """,
            (chat_session_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_session(session_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM scheduling_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def confirm_session(
    session_id: int,
    confirmed_event_id: str,
    confirmed_slot: dict,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduling_sessions
            SET status = 'confirmed',
                confirmed_event_id = ?,
                confirmed_slot_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (confirmed_event_id, json.dumps(confirmed_slot), session_id),
        )


def cancel_session(session_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduling_sessions
            SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (session_id,),
        )


def mark_reminder_sent(session_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduling_sessions
            SET status = 'reminder_sent',
                reminder_sent_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (session_id,),
        )


def get_expired_sessions() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM scheduling_sessions
            WHERE status IN ('holds_placed', 'reminder_sent')
              AND expires_at < ?
            ORDER BY expires_at ASC
            """,
            (now,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_all_active_for_expiry_check() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM scheduling_sessions
            WHERE status IN ('holds_placed', 'reminder_sent')
            ORDER BY created_at ASC
            """,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    for key in ("offered_slots_json", "hold_event_ids_json", "confirmed_slot_json"):
        if d.get(key):
            try:
                d[key.replace("_json", "")] = json.loads(d[key])
            except Exception:
                d[key.replace("_json", "")] = []
    return d

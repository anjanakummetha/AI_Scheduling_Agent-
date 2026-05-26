"""SQLite setup for demo state and audit history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import settings


def get_connection() -> sqlite3.Connection:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outlook_message_id TEXT,
                sender_email TEXT NOT NULL,
                sender_name TEXT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                received_at TEXT,
                raw_payload_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                email_execution_status TEXT NOT NULL DEFAULT 'not_started',
                calendar_execution_status TEXT NOT NULL DEFAULT 'not_started',
                outlook_draft_message_id TEXT,
                outlook_calendar_event_id TEXT,
                detected_intent TEXT NOT NULL,
                meeting_type TEXT,
                priority_contact INTEGER NOT NULL DEFAULT 0,
                proposed_reply TEXT NOT NULL,
                proposed_slots_json TEXT NOT NULL,
                proposed_calendar_action_json TEXT NOT NULL,
                validation_result_json TEXT NOT NULL,
                approved_at TEXT,
                rejected_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(email_id) REFERENCES emails(id)
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                composio_log_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(decision_id) REFERENCES decisions(id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_emails_outlook_message_id
            ON emails(outlook_message_id)
            WHERE outlook_message_id IS NOT NULL;
            """
        )


def reset_demo_data() -> None:
    db_path: Path = settings.database_path
    if db_path.exists():
        db_path.unlink()
    init_db()

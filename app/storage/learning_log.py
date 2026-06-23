"""Approval outcomes for long-term quality tuning (not chat thread memory)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.storage.lexi_db import get_lexi_connection


def ensure_approval_feedback_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_feedback (
            id TEXT PRIMARY KEY,
            proposal_id INTEGER NOT NULL,
            decision TEXT NOT NULL,
            intent TEXT,
            voice_mode TEXT,
            send_channel TEXT,
            draft_chars INTEGER NOT NULL DEFAULT 0,
            slot_selected TEXT,
            had_modification_notes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_approval_feedback_proposal
        ON approval_feedback (proposal_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_approval_feedback_created
        ON approval_feedback (created_at)
        """
    )


def record_approval_outcome(
    *,
    proposal_id: int,
    decision: str,
    intent: str | None = None,
    voice_mode: str | None = None,
    send_channel: str | None = None,
    drafted_reply: str = "",
    selected_slot: str = "",
    modification_notes: str | None = None,
) -> None:
    """Persist one approval/reject for later accuracy review."""
    try:
        with get_lexi_connection() as conn:
            ensure_approval_feedback_table(conn)
            conn.execute(
                """
                INSERT INTO approval_feedback (
                    id, proposal_id, decision, intent, voice_mode, send_channel,
                    draft_chars, slot_selected, had_modification_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex[:16],
                    proposal_id,
                    decision.strip().lower(),
                    (intent or "").strip() or None,
                    (voice_mode or "kory").strip().lower(),
                    (send_channel or "kory").strip().lower(),
                    len((drafted_reply or "").strip()),
                    (selected_slot or "").strip() or None,
                    1 if (modification_notes or "").strip() else 0,
                ),
            )
            conn.commit()
    except sqlite3.Error:
        pass  # never block execution on feedback logging


def recent_feedback_summary(*, limit: int = 10) -> str:
    """Short block for agent context — edit rate and common intents."""
    try:
        with get_lexi_connection() as conn:
            ensure_approval_feedback_table(conn)
            rows = conn.execute(
                """
                SELECT decision, intent, had_modification_notes, COUNT(*) AS c
                FROM approval_feedback
                WHERE created_at >= datetime('now', '-30 days')
                GROUP BY decision, intent, had_modification_notes
                ORDER BY c DESC
                LIMIT ?
                """,
                (max(1, min(limit, 30)),),
            ).fetchall()
    except sqlite3.Error:
        return ""
    if not rows:
        return ""
    lines = ["RECENT APPROVAL PATTERNS (30d — use to improve drafts):"]
    for row in rows:
        edited = "edited" if row["had_modification_notes"] else "as-is"
        lines.append(f"- {row['decision']} / {row['intent'] or 'general'} / {edited}: {row['c']}")
    return "\n".join(lines)


def prune_old_feedback(*, days: int = 365) -> int:
    with get_lexi_connection() as conn:
        ensure_approval_feedback_table(conn)
        cursor = conn.execute(
            "DELETE FROM approval_feedback WHERE created_at < datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        conn.commit()
        return cursor.rowcount

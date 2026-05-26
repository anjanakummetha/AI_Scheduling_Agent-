"""
Feedback-training pipeline for Lexi.
Stores approved/rejected scheduling outcomes and injects the most
relevant learned examples into Lexi's context window.
"""

from __future__ import annotations

from typing import Any

from app.database import get_connection


def record_feedback(
    outcome: str,
    situation_summary: str,
    action_taken: str,
    was_correct: bool = True,
    notes: str | None = None,
    source: str = "dashboard",
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO lexi_feedback
              (source, outcome, situation_summary, action_taken, was_correct, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source, outcome, situation_summary, action_taken, int(was_correct), notes),
        )
        return cur.lastrowid


def get_feedback_context(limit: int = 6) -> str:
    """
    Return a formatted string of recent feedback examples suitable for
    injection into Lexi's system prompt context window.
    """
    with get_connection() as conn:
        good = conn.execute(
            """
            SELECT situation_summary, action_taken, notes
            FROM lexi_feedback
            WHERE was_correct = 1
            ORDER BY created_at DESC LIMIT ?
            """,
            (limit // 2 + 1,),
        ).fetchall()
        bad = conn.execute(
            """
            SELECT situation_summary, action_taken, notes
            FROM lexi_feedback
            WHERE was_correct = 0
            ORDER BY created_at DESC LIMIT ?
            """,
            (limit // 2,),
        ).fetchall()

    if not good and not bad:
        return ""

    lines = ["\n--- LEARNED FROM PAST DECISIONS ---"]
    if good:
        lines.append("APPROVED (do more of this):")
        for row in good:
            lines.append(f"  • Situation: {row['situation_summary']}")
            lines.append(f"    Action: {row['action_taken']}")
            if row["notes"]:
                lines.append(f"    Note: {row['notes']}")
    if bad:
        lines.append("REJECTED (avoid this):")
        for row in bad:
            lines.append(f"  • Situation: {row['situation_summary']}")
            lines.append(f"    Action: {row['action_taken']}")
            if row["notes"]:
                lines.append(f"    Note: {row['notes']}")
    lines.append("--- END LEARNED EXAMPLES ---\n")
    return "\n".join(lines)


def record_from_dashboard_approval(decision: dict[str, Any]) -> None:
    """Called when a scheduling decision is approved in the dashboard."""
    record_feedback(
        outcome="approved",
        situation_summary=f"Email from {decision.get('sender_name') or decision.get('sender_email')}: {decision.get('subject')}",
        action_taken=f"Proposed {len(decision.get('proposed_slots', []))} time slots. Reply drafted.",
        was_correct=True,
        source="dashboard",
    )


def record_from_dashboard_rejection(decision: dict[str, Any], reason: str | None = None) -> None:
    """Called when a scheduling decision is rejected in the dashboard."""
    record_feedback(
        outcome="rejected",
        situation_summary=f"Email from {decision.get('sender_name') or decision.get('sender_email')}: {decision.get('subject')}",
        action_taken=f"Proposed {len(decision.get('proposed_slots', []))} time slots.",
        was_correct=False,
        notes=reason,
        source="dashboard",
    )

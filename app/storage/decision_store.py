"""Persistence helpers for emails, decisions, and audit events."""

from __future__ import annotations

import json
from typing import Any

from app.database import get_connection


def _row_to_dict(row) -> dict[str, Any] | None:
    return dict(row) if row else None


def create_email(email: dict[str, Any]) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO emails (
                outlook_message_id, sender_email, sender_name, subject,
                body, received_at, raw_payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email.get("outlook_message_id"),
                email["sender_email"],
                email.get("sender_name"),
                email["subject"],
                email["body"],
                email.get("received_at"),
                json.dumps(email.get("raw_payload", {})),
            ),
        )
        return int(cursor.lastrowid)


def email_exists(outlook_message_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM emails WHERE outlook_message_id = ? LIMIT 1",
            (outlook_message_id,),
        ).fetchone()
        return row is not None


def get_decision_id_by_outlook_message_id(outlook_message_id: str) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT decisions.id
            FROM decisions
            JOIN emails ON emails.id = decisions.email_id
            WHERE emails.outlook_message_id = ?
            ORDER BY decisions.created_at ASC
            LIMIT 1
            """,
            (outlook_message_id,),
        ).fetchone()
        return int(row["id"]) if row else None


def create_decision(email_id: int, proposal: dict[str, Any], validation: dict[str, Any]) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO decisions (
                email_id, status, detected_intent, meeting_type, priority_contact,
                proposed_reply, proposed_slots_json, proposed_calendar_action_json,
                validation_result_json
            )
            VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email_id,
                proposal.get("intent", "needs_review"),
                proposal.get("meeting_type"),
                1 if proposal.get("priority_contact") else 0,
                proposal.get("draft_reply", ""),
                json.dumps(proposal.get("proposed_slots", [])),
                json.dumps(proposal.get("calendar_action", {})),
                json.dumps(validation),
            ),
        )
        return int(cursor.lastrowid)


def update_decision_proposal(
    decision_id: int,
    proposal: dict[str, Any],
    validation: dict[str, Any],
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE decisions
            SET detected_intent = ?,
                meeting_type = ?,
                priority_contact = ?,
                proposed_reply = ?,
                proposed_slots_json = ?,
                proposed_calendar_action_json = ?,
                validation_result_json = ?,
                calendar_execution_status = CASE
                    WHEN calendar_execution_status = 'failed' THEN 'not_started'
                    ELSE calendar_execution_status
                END,
                outlook_calendar_event_id = CASE
                    WHEN calendar_execution_status = 'failed' THEN NULL
                    ELSE outlook_calendar_event_id
                END
            WHERE id = ?
            """,
            (
                proposal.get("intent", "needs_review"),
                proposal.get("meeting_type"),
                1 if proposal.get("priority_contact") else 0,
                proposal.get("draft_reply", ""),
                json.dumps(proposal.get("proposed_slots", [])),
                json.dumps(proposal.get("calendar_action", {})),
                json.dumps(validation),
                decision_id,
            ),
        )


def update_decision_reply(
    decision_id: int,
    proposed_reply: str,
    validation: dict[str, Any],
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE decisions
            SET proposed_reply = ?,
                validation_result_json = ?
            WHERE id = ?
            """,
            (
                proposed_reply,
                json.dumps(validation),
                decision_id,
            ),
        )


def add_audit_event(
    event_type: str,
    message: str,
    decision_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    composio_log_id: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_events (
                decision_id, event_type, message, metadata_json, composio_log_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                event_type,
                message,
                json.dumps(metadata or {}),
                composio_log_id,
            ),
        )


def list_decisions(status: str | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT
            decisions.*,
            emails.sender_email,
            emails.sender_name,
            emails.outlook_message_id,
            emails.subject,
            emails.body,
            emails.received_at,
            emails.raw_payload_json
        FROM decisions
        JOIN emails ON emails.id = decisions.email_id
    """
    params: tuple[Any, ...] = ()
    if status:
        query += " WHERE decisions.status = ?"
        params = (status,)
    query += " ORDER BY decisions.created_at DESC"

    with get_connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_decision(decision_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        decision = _row_to_dict(
            conn.execute(
                """
                SELECT
                    decisions.*,
                    emails.sender_email,
                    emails.sender_name,
                    emails.outlook_message_id,
                    emails.subject,
                    emails.body,
                    emails.received_at,
                    emails.raw_payload_json
                FROM decisions
                JOIN emails ON emails.id = decisions.email_id
                WHERE decisions.id = ?
                """,
                (decision_id,),
            ).fetchone()
        )
        if not decision:
            return None

        decision["audit_events"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM audit_events WHERE decision_id = ? ORDER BY created_at",
                (decision_id,),
            ).fetchall()
        ]
        return decision


def mark_approved(decision_id: int, message: str = "Approved from dashboard") -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE decisions SET status = 'approved', approved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (decision_id,),
        )
    add_audit_event("approval.approved", message, decision_id)


def mark_rejected(decision_id: int, message: str = "Rejected from dashboard") -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE decisions SET status = 'rejected', rejected_at = CURRENT_TIMESTAMP WHERE id = ?",
            (decision_id,),
        )
    add_audit_event("approval.rejected", message, decision_id)


def mark_email_executed(decision_id: int, draft_message_id: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE decisions
            SET email_execution_status = 'completed',
                outlook_draft_message_id = COALESCE(?, outlook_draft_message_id)
            WHERE id = ?
            """,
            (draft_message_id, decision_id),
        )
    add_audit_event(
        "execution.email_completed",
        "Approved email draft was created and sent through Outlook.",
        decision_id,
        {"draft_message_id": draft_message_id},
    )


def mark_email_failed(decision_id: int, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE decisions SET email_execution_status = 'failed' WHERE id = ?",
            (decision_id,),
        )
    add_audit_event("execution.email_failed", reason, decision_id)


def mark_calendar_executed(decision_id: int, event_id: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE decisions
            SET calendar_execution_status = 'completed',
                outlook_calendar_event_id = COALESCE(?, outlook_calendar_event_id)
            WHERE id = ?
            """,
            (event_id, decision_id),
        )
    add_audit_event(
        "execution.calendar_completed",
        "Approved calendar event was created in Outlook.",
        decision_id,
        {"event_id": event_id},
    )


def mark_calendar_failed(decision_id: int, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE decisions SET calendar_execution_status = 'failed' WHERE id = ?",
            (decision_id,),
        )
    add_audit_event("execution.calendar_failed", reason, decision_id)

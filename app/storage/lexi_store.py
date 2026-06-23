"""Read helpers for Lexi dashboard and reporting."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.storage.lexi_db import get_lexi_connection


def list_proposals(status: str | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT
            p.id,
            p.thread_id,
            p.status,
            p.intent_classification,
            p.priority_tier,
            p.proposed_slots,
            p.drafted_reply,
            p.confidence_score,
            p.justification,
            p.rule_reasoning,
            p.created_at,
            p.updated_at,
            e.subject,
            e.sender,
            e.received_at,
            e.raw_body
        FROM proposals AS p
        INNER JOIN email_threads AS e ON e.thread_id = p.thread_id
    """
    params: tuple[Any, ...] = ()
    if status:
        query += " WHERE p.status = ?"
        params = (status,)
    query += " ORDER BY p.id DESC"

    with get_lexi_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_proposal_row_to_dict(row, conn) for row in rows]


def get_proposal(proposal_id: int) -> dict[str, Any] | None:
    with get_lexi_connection() as conn:
        row = conn.execute(
            """
            SELECT
                p.id,
                p.thread_id,
                p.status,
                p.intent_classification,
                p.priority_tier,
                p.proposed_slots,
                p.drafted_reply,
                p.confidence_score,
                p.justification,
                p.rule_reasoning,
                p.created_at,
                p.updated_at,
                e.subject,
                e.sender,
                e.received_at,
                e.raw_body
            FROM proposals AS p
            INNER JOIN email_threads AS e ON e.thread_id = p.thread_id
            WHERE p.id = ?
            """,
            (proposal_id,),
        ).fetchone()
        if not row:
            return None
        return _proposal_row_to_dict(row, conn)


def list_audit_log_for_proposal(proposal_id: int) -> list[dict[str, Any]]:
    with get_lexi_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, step_name, reference_id, log_level, message, payload, timestamp
            FROM audit_log
            WHERE reference_id = ? OR reference_id = (
                SELECT thread_id FROM proposals WHERE id = ?
            )
            ORDER BY id ASC
            """,
            (str(proposal_id), proposal_id),
        ).fetchall()
        return [dict(row) for row in rows]


def update_drafted_reply(proposal_id: int, drafted_reply: str) -> None:
    with get_lexi_connection() as conn:
        conn.execute(
            """
            UPDATE proposals
            SET drafted_reply = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (drafted_reply, proposal_id),
        )
        conn.commit()


def _proposal_row_to_dict(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    proposal = dict(row)
    proposal_id = int(proposal["id"])
    proposal["proposed_slots"] = _parse_json_list(proposal.get("proposed_slots"))
    proposal["rule_reasoning"] = _parse_json_object(proposal.get("rule_reasoning"))
    proposal["holds"] = [
        dict(hold)
        for hold in conn.execute(
            """
            SELECT id, event_id, slot_start, slot_end, expires_at, created_at
            FROM holds
            WHERE proposal_id = ?
            ORDER BY id ASC
            """,
            (proposal_id,),
        ).fetchall()
    ]
    return proposal


def _parse_json_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}

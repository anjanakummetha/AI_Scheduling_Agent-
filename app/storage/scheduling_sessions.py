"""Multi-turn Hermes / chat scheduling session state."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from app.storage.lexi_db import get_lexi_connection

SESSION_CONTEXT_MAX_CHARS = int(os.getenv("LEXI_SESSION_CONTEXT_MAX_CHARS", "32000"))
_SESSION_ESSENTIAL_KEYS = (
    "attendee",
    "company",
    "topic",
    "intent",
    "thread_id",
    "proposal_id",
    "selected_slot",
    "voice_mode",
    "send_channel",
    "timezone",
    "notes",
)


def _compact_context(context: dict[str, Any]) -> dict[str, Any]:
    """Keep session JSON under LEXI_SESSION_CONTEXT_MAX_CHARS for long Hermes threads."""
    if not context:
        return {}
    serialized = json.dumps(context, default=str)
    if len(serialized) <= SESSION_CONTEXT_MAX_CHARS:
        return context

    compact: dict[str, Any] = {}
    for key in _SESSION_ESSENTIAL_KEYS:
        if key in context:
            compact[key] = context[key]

    # Preserve short scalar fields; drop large blobs (search results, raw email).
    for key, value in context.items():
        if key in compact:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value)
            if len(text) <= 500:
                compact[key] = value
        elif isinstance(value, list) and len(value) <= 8:
            compact[key] = value[:8]

    if len(json.dumps(compact, default=str)) > SESSION_CONTEXT_MAX_CHARS:
        compact["_truncated"] = True
        compact["_note"] = "Session context compacted — re-fetch thread/calendar if needed."
    return compact


def create_session(
    *,
    channel: str = "hermes",
    context: dict[str, Any] | None = None,
) -> str:
    session_id = f"sess-{uuid.uuid4().hex[:12]}"
    with get_lexi_connection() as conn:
        conn.execute(
            """
            INSERT INTO scheduling_sessions (id, channel, status, context_json)
            VALUES (?, ?, 'active', ?)
            """,
            (session_id, channel, json.dumps(_compact_context(context or {}), default=str)),
        )
        conn.commit()
    return session_id


def get_session(session_id: str) -> dict[str, Any] | None:
    with get_lexi_connection() as conn:
        row = conn.execute(
            "SELECT id, channel, status, context_json, created_at, updated_at "
            "FROM scheduling_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        context = {}
        if row["context_json"]:
            try:
                context = json.loads(row["context_json"])
            except json.JSONDecodeError:
                context = {}
        return {
            "id": row["id"],
            "channel": row["channel"],
            "status": row["status"],
            "context": context,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def update_session(
    session_id: str,
    *,
    context: dict[str, Any] | None = None,
    status: str | None = None,
) -> bool:
    fields: list[str] = ["updated_at = datetime('now')"]
    params: list[Any] = []
    if context is not None:
        fields.append("context_json = ?")
        params.append(json.dumps(_compact_context(context), default=str))
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    params.append(session_id)
    with get_lexi_connection() as conn:
        cursor = conn.execute(
            f"UPDATE scheduling_sessions SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0


def list_active_sessions(channel: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    query = (
        "SELECT id, channel, status, context_json, created_at, updated_at "
        "FROM scheduling_sessions WHERE status = 'active'"
    )
    params: list[Any] = []
    if channel:
        query += " AND channel = ?"
        params.append(channel)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    with get_lexi_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    sessions: list[dict[str, Any]] = []
    for row in rows:
        session = get_session(str(row["id"]))
        if session:
            sessions.append(session)
    return sessions

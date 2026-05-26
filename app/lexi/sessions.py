"""Chat session persistence for Lexi conversations."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.database import get_connection


def create_session_id() -> str:
    return str(uuid.uuid4())


def save_message(
    session_id: str,
    role: str,
    content: str,
    channel: str = "web",
    tool_calls: list[dict] | None = None,
    metadata: dict | None = None,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO chat_messages
                (session_id, channel, role, content, tool_calls_json, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                channel,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                json.dumps(metadata or {}),
            ),
        )
        return cursor.lastrowid


def get_session_history(session_id: str, limit: int = 40) -> list[dict[str, Any]]:
    """
    Return conversation history suitable for injection into an LLM context.

    Tool-call infrastructure messages (role=tool, role=assistant with tool_calls)
    are deliberately stripped from the returned history: the tool_call_id linkage
    is not persisted, so re-sending raw tool messages to the API causes 500 errors
    from providers that validate the call-id chain.

    The assistant's plain-text summaries (saved alongside tool calls) are preserved
    so Lexi retains conversational context about what she did.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content, tool_calls_json, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    rows = list(reversed(rows))
    messages = []
    for row in rows:
        role = row["role"]
        # Skip raw tool result messages — they require tool_call_id linkage we don't persist
        if role == "tool":
            continue
        content = row["content"] or ""
        # For assistant messages that only issued tool calls with no text, skip them
        # (they contribute nothing to conversation context without their tool results)
        if role == "assistant" and not content.strip() and row["tool_calls_json"]:
            continue
        # Include user and assistant messages; strip tool_calls metadata
        messages.append({"role": role, "content": content})
    return messages


def list_sessions(channel: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent sessions with their last message preview."""
    where = "WHERE channel = ?" if channel else ""
    params: tuple = (channel,) if channel else ()
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                session_id,
                channel,
                MAX(created_at) AS last_at,
                COUNT(*) AS msg_count
            FROM chat_messages
            {where}
            GROUP BY session_id
            ORDER BY last_at DESC
            LIMIT ?
            """,
            params + (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_messages_for_display(
    session_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM chat_messages
            WHERE session_id = ? AND role IN ('user', 'assistant')
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]

"""Read Kory inbox via Composio (search + thread fetch)."""

from __future__ import annotations

from typing import Any

from app.integrations.composio_client import execute_read_tool
from app.integrations.outlook_email import get_message, normalize_message


def search_inbox(
    *,
    query: str = "",
    top: int = 10,
) -> tuple[list[dict[str, Any]], str | None]:
    """List recent inbox messages, optionally filtered by subject/body keyword."""
    limit = max(1, min(top, 25))
    arguments: dict[str, Any] = {
        "user_id": "me",
        "folder": "inbox",
        "top": limit,
        "orderby": ["receivedDateTime desc"],
        "select": ["id", "subject", "from", "receivedDateTime", "bodyPreview", "conversationId"],
    }
    if query.strip():
        arguments["search"] = query.strip()

    result = execute_read_tool("OUTLOOK_LIST_MESSAGES", arguments)
    messages = _extract_messages(result.get("data"))
    summaries: list[dict[str, Any]] = []
    for message in messages:
        sender = message.get("from") or {}
        email_address = sender.get("emailAddress", {}) if isinstance(sender, dict) else {}
        summaries.append(
            {
                "message_id": message.get("id"),
                "thread_id": message.get("conversationId") or message.get("id"),
                "subject": message.get("subject"),
                "sender": email_address.get("address"),
                "sender_name": email_address.get("name"),
                "received_at": message.get("receivedDateTime"),
                "preview": message.get("bodyPreview"),
            }
        )
    return summaries, result.get("log_id")


def get_thread_message(message_id: str) -> dict[str, Any]:
    """Fetch a single message by id from Kory's inbox."""
    raw_message, log_id = get_message(message_id)
    normalized = normalize_message(
        raw_message,
        {"source": "outlook_inbox", "message_id": message_id},
    )
    return {
        "message_id": message_id,
        "thread_id": message_id,
        "conversation_id": normalized.get("conversation_id") or "",
        "subject": normalized.get("subject"),
        "sender": normalized.get("sender_email"),
        "received_at": normalized.get("received_at"),
        "body": normalized.get("body"),
        "composio_log_id": log_id,
    }


def _extract_messages(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("value", "messages", "data"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []

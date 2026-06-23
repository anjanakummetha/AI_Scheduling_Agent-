"""Outlook conversation thread context for chained email replies."""

from __future__ import annotations

from typing import Any

from app.integrations.composio_client import execute_read_tool
from app.integrations.outlook_email import _plain_text


def _extract_messages(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("value", "messages", "data"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def fetch_conversation_context(
    conversation_id: str,
    *,
    exclude_message_id: str | None = None,
    max_messages: int = 4,
) -> str:
    """Load prior messages in the same Outlook conversation for triage/drafting."""
    if not conversation_id.strip():
        return ""

    try:
        result = execute_read_tool(
            "OUTLOOK_LIST_MESSAGES",
            {
                "user_id": "me",
                "folder": "inbox",
                "top": 25,
                "orderby": ["receivedDateTime desc"],
                "select": ["id", "subject", "from", "receivedDateTime", "bodyPreview", "conversationId"],
                "filter": f"conversationId eq '{conversation_id}'",
            },
        )
        messages = _extract_messages(result.get("data"))
    except Exception:
        return ""

    if not messages:
        return ""

    blocks: list[str] = []
    for message in messages:
        mid = str(message.get("id") or "")
        if exclude_message_id and mid == exclude_message_id:
            continue
        sender = message.get("from") or {}
        email_address = sender.get("emailAddress", {}) if isinstance(sender, dict) else {}
        from_addr = email_address.get("address") or "unknown"
        received = message.get("receivedDateTime") or ""
        subject = message.get("subject") or ""
        preview = _plain_text(str(message.get("bodyPreview") or ""))[:500]
        blocks.append(
            f"--- Earlier in thread ({received}) ---\n"
            f"From: {from_addr}\n"
            f"Subject: {subject}\n"
            f"{preview}"
        )
        if len(blocks) >= max_messages:
            break

    if not blocks:
        return ""
    return "\n\n".join(reversed(blocks))

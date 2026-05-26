"""Outlook email helpers backed by Composio tools."""

from __future__ import annotations

import html
import re
from typing import Any

from app.integrations.composio_client import execute_tool


def get_message(message_id: str) -> tuple[dict[str, Any], str | None]:
    result = execute_tool(
        "OUTLOOK_GET_MESSAGE",
        {
            "message_id": message_id,
            "user_id": "me",
            "select": [
                "id",
                "subject",
                "from",
                "toRecipients",
                "receivedDateTime",
                "body",
                "bodyPreview",
            ],
        },
    )
    return _coerce_data(result["data"]), result.get("log_id")


def create_draft_reply(message_id: str, body: str) -> tuple[str | None, str | None]:
    result = execute_tool(
        "OUTLOOK_CREATE_DRAFT_REPLY",
        {
            "message_id": message_id,
            "user_id": "me",
            "comment": body,
        },
    )
    data = _coerce_data(result["data"])
    return _extract_id(data), result.get("log_id")


def send_draft(draft_message_id: str) -> str | None:
    result = execute_tool(
        "OUTLOOK_SEND_DRAFT",
        {
            "message_id": draft_message_id,
            "user_id": "me",
        },
    )
    return result.get("log_id")


def normalize_message(message: dict[str, Any], raw_payload: dict[str, Any]) -> dict[str, Any]:
    sender = message.get("from") or {}
    email_address = sender.get("emailAddress", {}) if isinstance(sender, dict) else {}
    body = message.get("body") or {}
    raw_body = body.get("content") if isinstance(body, dict) else message.get("bodyPreview", "")
    body_text = _plain_text(raw_body or "")
    if not body_text.strip() and message.get("bodyPreview"):
        body_text = str(message.get("bodyPreview"))
    apparent_sender_name = _extract_signature_name(body_text)

    return {
        "outlook_message_id": message.get("id") or raw_payload.get("message_id"),
        "sender_email": email_address.get("address", "unknown@example.com"),
        "sender_name": apparent_sender_name or email_address.get("name"),
        "mailbox_sender_name": email_address.get("name"),
        "subject": message.get("subject") or "(no subject)",
        "body": body_text,
        "received_at": message.get("receivedDateTime"),
        "raw_payload": raw_payload,
    }


def _extract_id(data: dict[str, Any]) -> str | None:
    if data.get("id"):
        return data["id"]
    if isinstance(data.get("message"), dict):
        return data["message"].get("id")
    if isinstance(data.get("draft"), dict):
        return data["draft"].get("id")
    return None


def _coerce_data(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if hasattr(data, "model_dump"):
        return data.model_dump()
    return {"value": data}


def _extract_signature_name(body: str) -> str | None:
    text = _plain_text(body)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    signoffs = {"cheers", "best", "thanks", "thank you", "regards", "sincerely"}

    for index, line in enumerate(lines):
        normalized = line.lower().strip(" ,.!-")
        if normalized not in signoffs:
            continue
        for candidate in lines[index + 1 : index + 4]:
            name = _clean_name_candidate(candidate)
            if name:
                return name
    for candidate in reversed(lines[-5:]):
        if _looks_like_reply_artifact(candidate):
            continue
        name = _clean_name_candidate(candidate)
        if name:
            return name
    return None


def _plain_text(body: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def _clean_name_candidate(candidate: str) -> str | None:
    cleaned = candidate.strip().strip(",.!-")
    if not cleaned or "@" in cleaned or len(cleaned) > 40:
        return None
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,38}", cleaned):
        return None
    words = cleaned.split()
    if len(words) > 3:
        return None
    return " ".join(word.capitalize() for word in words)


def _looks_like_reply_artifact(line: str) -> bool:
    lowered = line.lower()
    return (
        lowered.startswith(("from:", "sent:", "to:", "subject:", "on "))
        or "wrote:" in lowered
        or lowered in {"hi kory", "hello kory", "hey kory", "dear kory"}
    )

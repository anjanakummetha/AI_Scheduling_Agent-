"""Read Kory's sent mail via Composio for voice / tone learning."""

from __future__ import annotations

import re
from typing import Any

from app.integrations.composio_client import execute_read_tool
from app.integrations.outlook_email import _plain_text


def list_sent_messages(*, top: int = 40) -> list[dict[str, Any]]:
    """Recent messages from Kory's Sent Items folder."""
    limit = max(5, min(top, 50))
    result = execute_read_tool(
        "OUTLOOK_LIST_MESSAGES",
        {
            "user_id": "me",
            "folder": "sentitems",
            "top": limit,
            "orderby": ["sentDateTime desc"],
            "select": [
                "id",
                "subject",
                "toRecipients",
                "sentDateTime",
                "bodyPreview",
                "body",
            ],
        },
    )
    return _extract_messages(result.get("data"))


def fetch_sent_samples(*, top: int = 25) -> list[dict[str, str]]:
    """Normalized sent-mail snippets for tone prompts."""
    samples: list[dict[str, str]] = []
    for message in list_sent_messages(top=top):
        body = message.get("body") or {}
        if isinstance(body, dict):
            raw = _plain_text(body.get("content") or "")
        else:
            raw = _plain_text(str(body))
        preview = str(message.get("bodyPreview") or "").strip()
        text = (raw or preview).strip()
        if len(text) < 20 or not _is_kory_reply_sample(text):
            continue
        recipients = message.get("toRecipients") or []
        to_addrs: list[str] = []
        for recipient in recipients:
            if not isinstance(recipient, dict):
                continue
            addr = (recipient.get("emailAddress") or {}).get("address")
            if addr:
                to_addrs.append(str(addr))
        samples.append(
            {
                "subject": str(message.get("subject") or ""),
                "to": ", ".join(to_addrs),
                "sent_at": str(message.get("sentDateTime") or ""),
                "body": _trim_body(text),
            }
        )
    return samples


def fetch_sent_to_recipient(recipient_email: str, *, top: int = 5) -> list[dict[str, str]]:
    """Sent messages whose To line includes recipient_email (case-insensitive)."""
    needle = recipient_email.strip().lower()
    if not needle:
        return []
    matched: list[dict[str, str]] = []
    for sample in fetch_sent_samples(top=max(top * 4, 20)):
        if needle in sample.get("to", "").lower():
            matched.append(sample)
        if len(matched) >= top:
            break
    return matched


def _trim_body(text: str, *, max_chars: int = 900) -> str:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _is_kory_reply_sample(text: str) -> bool:
    """Keep real Kory replies; drop forwards, newsletters, and bulk blasts."""
    lower = text.lower()
    if any(
        marker in lower
        for marker in (
            "unsubscribe",
            "view in browser",
            "no longer wish to receive",
            "linkedin",
            "marketplace digest",
        )
    ):
        return False
    if len(text) > 3500:
        return False
    tail = "\n".join(text.strip().splitlines()[-4:]).lower()
    if "kory" not in tail and "let's win" not in tail:
        return False
    return True


def _extract_messages(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("value", "messages", "data"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []

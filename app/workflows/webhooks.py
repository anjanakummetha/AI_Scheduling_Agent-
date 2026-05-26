"""Composio webhook processing."""

from __future__ import annotations

from typing import Any

from app.integrations.outlook_email import get_message, normalize_message
from app.storage.decision_store import add_audit_event, email_exists
from app.workflows.inbound_email import process_inbound_email


OUTLOOK_MESSAGE_TRIGGER = "OUTLOOK_MESSAGE_TRIGGER"


def process_composio_webhook(payload: dict[str, Any]) -> int | None:
    event_type = payload.get("type")
    metadata = payload.get("metadata") or {}
    trigger_slug = metadata.get("trigger_slug")

    if event_type != "composio.trigger.message":
        add_audit_event(
            "webhook.ignored",
            f"Ignored non-trigger Composio webhook event: {event_type}",
            metadata=payload,
        )
        return None

    if trigger_slug != OUTLOOK_MESSAGE_TRIGGER:
        add_audit_event(
            "webhook.ignored",
            f"Ignored unsupported trigger: {trigger_slug}",
            metadata=payload,
        )
        return None

    data = payload.get("data") or {}
    message_id = _extract_message_id(data)
    if not message_id:
        add_audit_event(
            "webhook.error",
            "OUTLOOK_MESSAGE_TRIGGER payload did not include a message ID.",
            metadata=payload,
        )
        return None
    if email_exists(message_id):
        add_audit_event(
            "webhook.duplicate",
            "Outlook message trigger skipped because message was already processed.",
            metadata={"message_id": message_id},
        )
        return None

    message, log_id = get_message(message_id)
    email = normalize_message(message, {"message_id": message_id, "webhook": payload})
    decision_id = process_inbound_email(email)
    add_audit_event(
        "webhook.message_processed",
        "Outlook message trigger fetched and processed.",
        decision_id,
        {"message_id": message_id},
        log_id,
    )
    return decision_id


def _extract_message_id(data: dict[str, Any]) -> str | None:
    for key in ("message_id", "messageId", "id", "resource_id", "resourceId"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value

    message = data.get("message")
    if isinstance(message, dict):
        return _extract_message_id(message)

    resource_data = data.get("resourceData")
    if isinstance(resource_data, dict):
        return _extract_message_id(resource_data)

    value = data.get("value")
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return _extract_message_id(value[0])

    return None

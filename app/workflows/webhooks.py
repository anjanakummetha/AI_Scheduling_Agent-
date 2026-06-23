"""Composio webhook ingress for the Lexi orchestrator queue."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.orchestrator import composio_webhook_to_lexi_email, enqueue_inbound
from app.storage.lexi_db import get_lexi_connection

logger = logging.getLogger(__name__)

OUTLOOK_MESSAGE_TRIGGER = "OUTLOOK_MESSAGE_TRIGGER"


def accept_composio_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a Composio trigger payload and enqueue Lexi inbound processing.

    Returns a JSON-serializable acceptance envelope suitable for HTTP 202 responses.
    """
    event_type = payload.get("type")
    metadata = payload.get("metadata") or {}
    trigger_slug = metadata.get("trigger_slug")

    if event_type != "composio.trigger.message":
        result = {
            "ok": True,
            "queued": False,
            "ignored": True,
            "reason": f"unsupported_event:{event_type}",
        }
        _audit_webhook("INFO", "Webhook ignored (unsupported event type).", result, payload)
        return result

    if trigger_slug != OUTLOOK_MESSAGE_TRIGGER:
        result = {
            "ok": True,
            "queued": False,
            "ignored": True,
            "reason": f"unsupported_trigger:{trigger_slug}",
        }
        _audit_webhook("INFO", "Webhook ignored (unsupported trigger slug).", result, payload)
        return result

    try:
        lexi_email = composio_webhook_to_lexi_email(payload)
    except Exception as exc:
        logger.exception("Composio webhook normalization failed.")
        result = {
            "ok": False,
            "queued": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        _audit_webhook("ERROR", "Webhook normalization raised an exception.", result, payload)
        return result

    if not lexi_email:
        result = {
            "ok": False,
            "queued": False,
            "error": "normalization_failed",
        }
        _audit_webhook("ERROR", "Webhook payload could not be normalized to Lexi email.", result, payload)
        return result

    try:
        enqueue_inbound(lexi_email)
    except Exception as exc:
        logger.exception("Failed to enqueue Lexi inbound email.")
        result = {
            "ok": False,
            "queued": False,
            "thread_id": lexi_email.get("thread_id"),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _audit_webhook("ERROR", "Failed to enqueue Lexi inbound email.", result, payload)
        return result

    result = {
        "ok": True,
        "queued": True,
        "thread_id": lexi_email.get("thread_id"),
    }
    _audit_webhook("INFO", "Composio webhook accepted and queued for Lexi orchestrator.", result, payload)
    return result


def _audit_webhook(
    level: str,
    message: str,
    result: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    try:
        with get_lexi_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (step_name, reference_id, log_level, message, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "webhook_ingress",
                    str(result.get("thread_id") or "unknown"),
                    level,
                    message,
                    json.dumps(
                        {"result": result, "webhook": payload},
                        default=str,
                    ),
                ),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to write Lexi webhook audit log entry.")

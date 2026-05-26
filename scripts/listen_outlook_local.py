"""Local Composio trigger listener for demo runs without ngrok.

Production should use the FastAPI `/webhooks/composio` endpoint. This script is
only a local fallback for receiving Outlook trigger events over the Composio SDK
websocket subscription.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import sys
import threading
import time
from typing import Any

from composio import Composio
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.integrations.composio_client import execute_tool
from app.integrations.outlook_email import get_message, normalize_message
from app.storage.decision_store import email_exists
from app.workflows.inbound_email import process_inbound_email
from app.workflows.webhooks import OUTLOOK_MESSAGE_TRIGGER, process_composio_webhook


PROCESSING_LOCK = threading.Lock()


def main() -> None:
    load_dotenv(".env")
    api_key = os.getenv("COMPOSIO_API_KEY")
    user_id = os.getenv("COMPOSIO_USER_ID", "kory")
    started_at = datetime.now(timezone.utc)
    if not api_key:
        raise SystemExit("COMPOSIO_API_KEY is missing.")

    print(f"Connecting to Composio trigger stream for user_id={user_id}...", flush=True)
    composio = Composio(api_key=api_key)
    listener = composio.triggers.subscribe(timeout=30.0)
    print("Composio trigger stream connected.", flush=True)

    @listener.handle()
    def on_any_trigger(event):
        raw_payload = event.get("original_payload")
        if isinstance(raw_payload, dict) and raw_payload.get("type") == "composio.trigger.message":
            trigger_slug = (raw_payload.get("metadata") or {}).get("trigger_slug")
            print(
                "Received raw Composio trigger event: "
                f"trigger_slug={trigger_slug} user_id={(raw_payload.get('metadata') or {}).get('user_id')}",
                flush=True,
            )
            with PROCESSING_LOCK:
                decision_id = process_composio_webhook(raw_payload)
            print(f"Processed raw Outlook trigger into decision_id={decision_id}", flush=True)
            return

        print(
            "Received trigger event: "
            f"trigger_slug={event.get('trigger_slug')} user_id={event.get('user_id')}",
            flush=True,
        )
        if event.get("trigger_slug") != OUTLOOK_MESSAGE_TRIGGER:
            print("Ignoring non-Outlook-message trigger.", flush=True)
            return

        payload = {
            "type": "composio.trigger.message",
            "metadata": {
                "trigger_slug": event["trigger_slug"],
                "trigger_id": event["metadata"]["id"],
                "user_id": event["user_id"],
            },
            "data": event.get("payload", {}),
        }
        with PROCESSING_LOCK:
            decision_id = process_composio_webhook(payload)
        print(f"Processed Outlook trigger into decision_id={decision_id}", flush=True)

    print(f"Listening for {OUTLOOK_MESSAGE_TRIGGER} events for user_id={user_id}.", flush=True)
    print("Also polling inbox for new messages as a local demo fallback.", flush=True)
    print("Leave this running while sending demo Outlook emails. Press Ctrl+C to stop.", flush=True)
    try:
        while listener.is_alive() and not listener.has_errored():
            _poll_recent_inbox(started_at)
            time.sleep(15)
    except KeyboardInterrupt:
        print("\nListener stopped.")
        listener.stop()


def _poll_recent_inbox(started_at: datetime) -> None:
    try:
        result = execute_tool(
            "OUTLOOK_LIST_MESSAGES",
            {
                "user_id": "me",
                "folder": "inbox",
                "top": 10,
                "orderby": ["receivedDateTime desc"],
                "select": ["id", "subject", "from", "receivedDateTime", "bodyPreview"],
            },
        )
        messages = _extract_messages(result["data"])
        for message in reversed(messages):
            message_id = message.get("id")
            if not message_id or email_exists(message_id):
                continue

            # Process any unprocessed message in the recent inbox window, not only
            # mail received after this listener started (avoids missing emails sent
            # just before a restart).
            received_at = _parse_received_at(message.get("receivedDateTime"))
            poll_window_start = started_at - timedelta(hours=24)
            if received_at and received_at < poll_window_start:
                continue

            with PROCESSING_LOCK:
                if email_exists(message_id):
                    continue
                full_message, _ = get_message(message_id)
                email = normalize_message(
                    full_message,
                    {"source": "local_inbox_poll", "message_id": message_id},
                )
                decision_id = process_inbound_email(email)
            print(
                "Polled new Outlook inbox message into "
                f"decision_id={decision_id} subject={email['subject']}",
                flush=True,
            )
    except Exception as exc:
        print(f"Inbox poll failed: {type(exc).__name__}: {exc}", flush=True)


def _extract_messages(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        messages = data.get("value") or data.get("messages") or data.get("data") or []
        return messages if isinstance(messages, list) else []
    return []


def _parse_received_at(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


if __name__ == "__main__":
    main()

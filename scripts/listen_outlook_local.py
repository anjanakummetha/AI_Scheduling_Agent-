#!/usr/bin/env python3
"""Local Composio trigger listener that feeds the Lexi orchestrator directly.

Production ingress should use the FastAPI endpoint:
    POST /webhooks/composio

This script is a local fallback for Composio trigger websocket events and inbox polling
without running the full FastAPI server.
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
    sys.path.insert(0, str(ROOT))

from app.integrations.composio_client import execute_tool, require_composio_connection_id
from app.integrations.outlook_email import get_message, normalize_message
from app.orchestrator import composio_webhook_to_lexi_email, handle_inbound_stream
from app.workflows.webhooks import OUTLOOK_MESSAGE_TRIGGER


PROCESSING_LOCK = threading.Lock()


def main() -> None:
    load_dotenv(".env")
    api_key = os.getenv("COMPOSIO_API_KEY")
    connection_id = require_composio_connection_id()
    user_id = os.getenv("COMPOSIO_ENTITY_ID", "").strip() or connection_id
    started_at = datetime.now(timezone.utc)
    if not api_key:
        raise SystemExit("COMPOSIO_API_KEY is missing.")

    print(f"Connecting to Composio trigger stream for connection_id={connection_id}...", flush=True)
    composio = Composio(api_key=api_key)
    listener = composio.triggers.subscribe(timeout=30.0)
    print("Composio trigger stream connected (Lexi ingress).", flush=True)

    @listener.handle()
    def on_any_trigger(event: dict[str, Any]) -> None:
        raw_payload = event.get("original_payload")
        if isinstance(raw_payload, dict) and raw_payload.get("type") == "composio.trigger.message":
            trigger_slug = (raw_payload.get("metadata") or {}).get("trigger_slug")
            print(
                "Received raw Composio trigger event: "
                f"trigger_slug={trigger_slug} user_id={(raw_payload.get('metadata') or {}).get('user_id')}",
                flush=True,
            )
            _process_trigger_payload(raw_payload)
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
        _process_trigger_payload(payload)

    print(f"Listening for {OUTLOOK_MESSAGE_TRIGGER} events for user_id={user_id}.", flush=True)
    print("Also polling inbox for new messages as a local Lexi fallback.", flush=True)
    print("Leave this running while sending demo Outlook emails. Press Ctrl+C to stop.", flush=True)
    try:
        while listener.is_alive() and not listener.has_errored():
            _poll_recent_inbox(started_at)
            time.sleep(15)
    except KeyboardInterrupt:
        print("\nListener stopped.")
        listener.stop()


def _process_trigger_payload(payload: dict[str, Any]) -> None:
    with PROCESSING_LOCK:
        try:
            raw_email = composio_webhook_to_lexi_email(payload)
            if not raw_email:
                print("Skipped trigger: could not normalize payload for Lexi.", flush=True)
                return
            result = handle_inbound_stream(raw_email)
            print(f"Lexi processed trigger: {result}", flush=True)
        except Exception as exc:
            print(
                f"Lexi trigger processing failed: {type(exc).__name__}: {exc}",
                flush=True,
            )


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
            message_id = str(message.get("id") or "").strip()
            if not message_id:
                continue

            subject_preview = str(message.get("subject") or "")
            if os.getenv("LEXI_LOCAL_MODE", "").strip().lower() in {"1", "true", "yes"}:
                if "test" not in subject_preview.lower():
                    continue

            from app.orchestrator import _thread_already_ingested

            if _thread_already_ingested(message_id):
                continue

            received_at = _parse_received_at(message.get("receivedDateTime"))
            poll_window_start = started_at - timedelta(hours=24)
            if received_at and received_at < poll_window_start:
                continue

            with PROCESSING_LOCK:
                try:
                    full_message, _ = get_message(message_id)
                    normalized = normalize_message(
                        full_message,
                        {"source": "local_inbox_poll", "message_id": message_id},
                    )
                    raw_email = {
                        "thread_id": message_id,
                        "subject": normalized["subject"],
                        "sender": normalized["sender_email"],
                        "received_at": normalized.get("received_at") or "",
                        "raw_body": normalized["body"],
                    }
                    result = handle_inbound_stream(raw_email)
                    if result.get("skipped"):
                        continue
                    print(
                        "Polled new Outlook inbox message into Lexi: "
                        f"proposal_id={result.get('proposal_id')} "
                        f"status={result.get('final_status')} "
                        f"subject={normalized['subject']}",
                        flush=True,
                    )
                except Exception as exc:
                    print(
                        f"Lexi inbox poll failed for message {message_id}: "
                        f"{type(exc).__name__}: {exc}",
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

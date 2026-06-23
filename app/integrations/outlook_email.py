"""Outlook email helpers backed by Composio tools (read Kory / write sandbox)."""

from __future__ import annotations

import html
import re
from typing import Any, Literal

import logging

from app.config import settings
from app.integrations.composio_client import (
    ComposioNotConfiguredError,
    ConnectionRole,
    execute_read_tool,
    execute_tool,
    execute_write_tool,
)
from app.integrations.outlook_profile import get_write_mailbox_email

logger = logging.getLogger(__name__)

SendChannel = Literal["kory", "lexi"]


def _sandbox_loopback_recipient(requested: str, *, send_channel: str = "kory") -> str:
    """In sandbox pilot, send to operator mailbox instead of external recipients."""
    if (send_channel or "kory").strip().lower() == "lexi":
        return requested.strip()
    if settings.lexi_write_mode != "sandbox" or not settings.sandbox_email_loopback:
        return requested.strip()

    configured = (settings.sandbox_mailbox_email or "").strip().lower()
    connected = (get_write_mailbox_email() or "").strip().lower()

    # Deliver to the Composio-connected mailbox so messages are visible in that account.
    # Cross-sending to a different @outlook.com login often never hits Inbox.
    if connected:
        if configured and configured != connected:
            logger.warning(
                "SANDBOX_MAILBOX_EMAIL=%s but Composio write connection is %s — "
                "loopback delivers to connected account. Reconnect Composio or update .env.",
                configured,
                connected,
            )
        return connected

    if configured:
        return configured
    return requested.strip()


def sandbox_mailbox_mismatch() -> dict[str, str | bool]:
    """True when .env mailbox does not match the Composio write connection."""
    configured = (settings.sandbox_mailbox_email or "").strip().lower()
    connected = (get_write_mailbox_email() or "").strip().lower()
    return {
        "configured": configured,
        "connected": connected,
        "mismatch": bool(configured and connected and configured != connected),
    }


def get_message(message_id: str) -> tuple[dict[str, Any], str | None]:
    result = execute_read_tool(
        "OUTLOOK_GET_MESSAGE",
        {
            "message_id": message_id,
            "user_id": "me",
            "select": [
                "id",
                "subject",
                "from",
                "toRecipients",
                "ccRecipients",
                "bccRecipients",
                "receivedDateTime",
                "body",
                "bodyPreview",
            ],
        },
    )
    return _coerce_data(result["data"]), result.get("log_id")


def create_draft_reply(message_id: str, body: str) -> tuple[str | None, str | None]:
    if settings.lexi_dry_run:
        logger.info("[DRY RUN] Would create draft reply for thread/message %s", message_id)
        print(
            "\n[Lexi DRY RUN] Email NOT sent. Draft reply preview:\n"
            "─" * 60 + "\n"
            f"{body}\n"
            "─" * 60 + "\n",
            flush=True,
        )
        return f"dry-run-draft-{message_id[:24]}", "dry-run-no-log"

    if settings.lexi_write_mode == "sandbox" and settings.sandbox_email_loopback:
        subject = f"[Lexi pilot draft] Reply re message {message_id[:12]}"
        return send_outbound_email(
            to_email=settings.sandbox_mailbox_email or "",
            subject=subject,
            body=body,
            approved_send=True,
        )

    result = execute_write_tool(
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
    if settings.lexi_dry_run:
        logger.info("[DRY RUN] Would send draft %s (skipped)", draft_message_id)
        print(f"\n[Lexi DRY RUN] Would send draft id={draft_message_id} (not sent)\n", flush=True)
        return "dry-run-no-log"

    if draft_message_id.startswith("dry-run-"):
        return "dry-run-no-log"
    if settings.lexi_write_mode == "sandbox" and settings.sandbox_email_loopback:
        return "sandbox-already-sent"

    result = execute_write_tool(
        "OUTLOOK_SEND_DRAFT",
        {
            "message_id": draft_message_id,
            "user_id": "me",
        },
    )
    return result.get("log_id")


OUTBOUND_SEND_TOOL_CANDIDATES = (
    "OUTLOOK_SEND_EMAIL",
    "OUTLOOK_SEND_MAIL",
    "MICROSOFT_OUTLOOK_SEND_EMAIL",
    "OUTLOOK_CREATE_DRAFT_EMAIL_AND_SEND",
)


def _extract_draft_message_id(data: Any) -> str | None:
    payload = _coerce_data(data)
    if payload.get("id"):
        return str(payload["id"])
    message = payload.get("message")
    if isinstance(message, dict) and message.get("id"):
        return str(message["id"])
    response = payload.get("response_data")
    if isinstance(response, dict) and response.get("id"):
        return str(response["id"])
    return None


def _send_lexi_html_via_draft(
    *,
    recipient: str,
    subject: str,
    html_body: str,
    inline_attachment: dict[str, Any],
    write_role: ConnectionRole,
) -> tuple[str | None, str | None]:
    """Create draft, attach inline logo (CID), send — required for Gmail-compatible images."""
    draft_result = execute_tool(
        "OUTLOOK_CREATE_DRAFT",
        {
            "user_id": "me",
            "subject": subject,
            "body": html_body,
            "is_html": True,
            "to_recipients": [recipient],
        },
        role=write_role,
    )
    message_id = _extract_draft_message_id(draft_result.get("data"))
    if not message_id:
        raise RuntimeError("OUTLOOK_CREATE_DRAFT did not return a message id.")

    execute_tool(
        "OUTLOOK_ADD_MAIL_ATTACHMENT",
        {
            "user_id": "me",
            "message_id": message_id,
            "odata_type": inline_attachment["@odata.type"],
            "name": inline_attachment["name"],
            "contentType": inline_attachment["contentType"],
            "content_bytes": inline_attachment["contentBytes"],
            "isInline": True,
            "contentId": inline_attachment["contentId"],
        },
        role=write_role,
    )
    send_result = execute_tool(
        "OUTLOOK_SEND_DRAFT",
        {"user_id": "me", "message_id": message_id},
        role=write_role,
    )
    from app.safety.operation_verify import verify_send_ack

    ack = verify_send_ack(message_id=message_id, status_code=202)
    if not ack.ok and send_result.get("error"):
        raise RuntimeError(str(send_result.get("error")))
    return message_id, send_result.get("log_id")


def send_outbound_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    approved_send: bool = False,
    send_channel: SendChannel = "kory",
) -> tuple[str | None, str | None]:
    """Send email via write mailbox (sandbox loopback in pilot) or Lexi mailbox.

    approved_send must be True unless LEXI_REQUIRE_KORY_APPROVAL=false (tests only).
    Production path: execute_lexi_approval → comms_agent, or Hermes confirm_send=true.
    """
    from app.safety.approval_gate import assert_outbound_send_authorized, kory_outbound_email_blocked

    channel = (send_channel or "kory").strip().lower()
    if channel not in {"kory", "lexi"}:
        channel = "kory"

    assert_outbound_send_authorized(approved_send=approved_send, send_channel=channel)
    if channel == "kory" and kory_outbound_email_blocked():
        raise PermissionError(
            "Kory outbound email is DISABLED. No messages will leave Kory's mailbox."
        )
    if channel == "lexi" and not settings.lexi_composio_connection_id:
        raise ComposioNotConfiguredError(
            "LEXI_COMPOSIO_CONNECTION_ID is missing — cannot send from Lexi mailbox."
        )
    recipient = _sandbox_loopback_recipient(to_email, send_channel=channel)
    if not recipient:
        raise ValueError("to_email is required for outbound send.")

    pilot_subject = subject
    if settings.lexi_write_mode == "sandbox" and settings.sandbox_email_loopback:
        if not pilot_subject.startswith("[Lexi pilot]"):
            pilot_subject = f"[Lexi pilot] {subject}"

    if settings.lexi_dry_run:
        logger.info("[DRY RUN] Would send outbound email to %s subject=%s", recipient, pilot_subject)
        print(
            f"\n[Lexi DRY RUN] Outbound email NOT sent.\n  To: {recipient}\n  Subject: {pilot_subject}\n",
            flush=True,
        )
        return f"dry-run-outbound-{recipient[:16]}", "dry-run-no-log"

    configured_target = (settings.sandbox_mailbox_email or "").strip().lower()
    from app.scheduling.email_format import finalize_lexi_email_body, finalize_outbound_email_body

    if channel == "lexi":
        pilot_body = finalize_lexi_email_body(body)
    else:
        pilot_body = finalize_outbound_email_body(body)
    if (
        settings.lexi_write_mode == "sandbox"
        and settings.sandbox_email_loopback
        and configured_target
        and recipient.lower() != configured_target
    ):
        pilot_body = (
            f"[Lexi pilot — configured target: {configured_target}]\n"
            f"[Delivered via Composio-connected mailbox: {recipient}]\n\n"
            f"{body}"
        )

    send_body = pilot_body
    is_html = False
    inline_attachments: list[dict[str, Any]] = []
    use_draft_inline_send = False
    if channel == "lexi":
        from app.scheduling.lexi_html_signature import (
            lexi_html_email_package,
            lexi_html_signature_enabled,
        )

        if lexi_html_signature_enabled():
            send_body, inline_attachments, use_draft_inline_send = lexi_html_email_package(pilot_body)
            is_html = True

    write_role: ConnectionRole = "lexi" if channel == "lexi" else "write"

    if use_draft_inline_send and inline_attachments:
        return _send_lexi_html_via_draft(
            recipient=recipient,
            subject=pilot_subject,
            html_body=send_body,
            inline_attachment=inline_attachments[0],
            write_role=write_role,
        )

    arguments: dict[str, Any] = {
        "user_id": "me",
        "to": recipient,
        "subject": pilot_subject,
        "body": send_body,
        "is_html": is_html,
        "save_to_sent_items": True,
    }
    if (
        settings.lexi_write_mode == "sandbox"
        and configured_target
        and recipient.lower() != configured_target
    ):
        arguments["bcc_emails"] = [configured_target]

    last_error: Exception | None = None
    for tool_slug in OUTBOUND_SEND_TOOL_CANDIDATES:
        try:
            result = execute_tool(tool_slug, arguments, role=write_role)
            data = _coerce_data(result.get("data"))
            message_id = _extract_id(data)
            status_code = data.get("status_code") if isinstance(data, dict) else None
            if not message_id and status_code in {200, 201, 202}:
                message_id = f"sent-{tool_slug.lower()}"
            if message_id or status_code in {200, 201, 202}:
                from app.safety.operation_verify import verify_send_ack

                ack = verify_send_ack(message_id=message_id, status_code=status_code)
                if not ack.ok:
                    raise RuntimeError("; ".join(ack.errors))
                return message_id, result.get("log_id")
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error
    raise RuntimeError("No outbound Outlook send tool succeeded.")


def send_pilot_reply_for_proposal(
    *,
    original_subject: str | None,
    body: str,
    intended_recipient: str | None = None,
    send_channel: SendChannel = "kory",
) -> tuple[str | None, str | None]:
    """Send approved reply to the actual recipient (reply-to sender)."""
    subject = original_subject or "Scheduling reply"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    recipient = (intended_recipient or "").strip()
    if not recipient:
        raise ValueError("intended_recipient is required for approved reply send.")
    return send_outbound_email(
        to_email=recipient,
        subject=subject,
        body=body,
        approved_send=True,
        send_channel=send_channel,
    )


def extract_recipient_list(message: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Normalize Outlook recipient fields for delegation detection."""
    result: dict[str, list[dict[str, Any]]] = {
        "to_recipients": [],
        "cc_recipients": [],
        "bcc_recipients": [],
    }
    key_map = {
        "toRecipients": "to_recipients",
        "ccRecipients": "cc_recipients",
        "bccRecipients": "bcc_recipients",
    }
    for graph_key, out_key in key_map.items():
        value = message.get(graph_key) or message.get(out_key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result[out_key].append(item)
    return result


def build_inbound_raw_email(
    *,
    message_id: str,
    normalized: dict[str, Any],
    recipients: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Lexi inbound dict with CC/BCC for delegation detection."""
    payload: dict[str, Any] = {
        "thread_id": message_id,
        "message_id": message_id,
        "conversation_id": normalized.get("conversation_id") or "",
        "subject": normalized["subject"],
        "sender": normalized["sender_email"],
        "received_at": normalized.get("received_at") or "",
        "raw_body": normalized["body"],
    }
    if recipients:
        payload.update(recipients)
    return payload


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
        "conversation_id": message.get("conversationId") or message.get("conversation_id"),
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

"""Tests for Outlook inbound recipient extraction (CC delegation)."""

from app.integrations.outlook_email import build_inbound_raw_email, extract_recipient_list, normalize_message


def test_extract_cc_recipients():
    message = {
        "ccRecipients": [
            {"emailAddress": {"address": "lexi@ifg.vc", "name": "Lexi"}},
        ],
        "toRecipients": [
            {"emailAddress": {"address": "guest@example.com"}},
        ],
    }
    recipients = extract_recipient_list(message)
    assert len(recipients["cc_recipients"]) == 1
    assert recipients["cc_recipients"][0]["emailAddress"]["address"] == "lexi@ifg.vc"


def test_build_inbound_raw_email_includes_cc():
    normalized = {
        "subject": "Intro",
        "sender_email": "kory@iconicfounders.com",
        "body": "Lexi will help schedule.",
        "conversation_id": "conv-1",
        "received_at": "2026-06-16T10:00:00Z",
    }
    recipients = {
        "cc_recipients": [{"emailAddress": {"address": "lexi@ifg.vc"}}],
        "to_recipients": [],
        "bcc_recipients": [],
    }
    raw = build_inbound_raw_email(
        message_id="msg-123",
        normalized=normalized,
        recipients=recipients,
    )
    assert raw["cc_recipients"]
    assert raw["thread_id"] == "msg-123"


def test_normalize_message_conversation_id():
    message = {
        "id": "abc",
        "conversationId": "conv-xyz",
        "from": {"emailAddress": {"address": "a@b.com"}},
        "subject": "Hello",
        "bodyPreview": "Hi",
    }
    out = normalize_message(message, {})
    assert out["conversation_id"] == "conv-xyz"

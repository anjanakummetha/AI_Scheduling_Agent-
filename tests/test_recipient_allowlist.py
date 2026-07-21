"""Recipient allowlist — structural send guard (plan Phase 1)."""

from __future__ import annotations

import pytest

from app.safety.recipient_allowlist import (
    assert_recipients_allowed,
    extract_recipients,
)


def test_extract_from_graph_shape():
    args = {
        "message": {
            "toRecipients": [{"emailAddress": {"address": "A@Example.com"}}],
            "ccRecipients": [{"emailAddress": {"address": "b@example.com"}}],
        }
    }
    assert extract_recipients(args) == {"a@example.com", "b@example.com"}


def test_extract_from_simple_shapes_and_attendees():
    assert extract_recipients({"to": "x@y.com, z@y.com"}) == {"x@y.com", "z@y.com"}
    assert extract_recipients(
        {"attendees": [{"emailAddress": {"address": "guest@corp.com"}}]}
    ) == {"guest@corp.com"}


def test_body_email_is_not_treated_as_recipient():
    # An email mentioned in the body must not count as a recipient.
    args = {"to": "ok@sandbox.test", "body": "reply to real.person@outside.com please"}
    assert extract_recipients(args) == {"ok@sandbox.test"}


def test_blocks_offlist_recipient_outside_production(monkeypatch):
    monkeypatch.setenv("LEXI_ENV", "testing")
    monkeypatch.setenv("LEXI_ALLOWED_RECIPIENTS", "ok@sandbox.test")
    with pytest.raises(PermissionError):
        assert_recipients_allowed(
            "OUTLOOK_SEND_EMAIL",
            {"message": {"toRecipients": [{"emailAddress": {"address": "stranger@outside.com"}}]}},
        )


def test_allows_listed_recipient(monkeypatch):
    monkeypatch.setenv("LEXI_ENV", "testing")
    monkeypatch.setenv("LEXI_ALLOWED_RECIPIENTS", "ok@sandbox.test")
    # Should not raise.
    assert_recipients_allowed(
        "OUTLOOK_SEND_EMAIL",
        {"message": {"toRecipients": [{"emailAddress": {"address": "ok@sandbox.test"}}]}},
    )


def test_read_tools_are_ignored(monkeypatch):
    monkeypatch.setenv("LEXI_ENV", "testing")
    monkeypatch.setenv("LEXI_ALLOWED_RECIPIENTS", "")
    # A read/list tool has no recipient semantics — never blocked.
    assert_recipients_allowed("OUTLOOK_LIST_MESSAGES", {"folder": "inbox", "top": 10})


def test_production_bypasses_allowlist(monkeypatch):
    monkeypatch.setenv("LEXI_ENV", "production")
    monkeypatch.setenv("LEXI_ALLOWED_RECIPIENTS", "")
    # In production the allowlist does not apply (real recipients are the point).
    assert_recipients_allowed(
        "OUTLOOK_SEND_EMAIL",
        {"message": {"toRecipients": [{"emailAddress": {"address": "anyone@outside.com"}}]}},
    )

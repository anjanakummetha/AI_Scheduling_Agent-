"""Email-to-lexi@ intent routing."""

from __future__ import annotations

from unittest.mock import patch

from app.agents.lexi_mail_intent import (
    handle_lexi_direct_mail,
    is_mail_to_lexi,
    parse_lexi_mail_intent,
)


def test_is_mail_to_lexi(monkeypatch):
    # Hermetic: pin the Lexi address set so the test doesn't depend on a loaded
    # env file (CI runs keyless, so settings.lexi_mailbox_email would be empty).
    # settings is a frozen dataclass, so patch the module-level reader instead.
    import app.agents.lexi_mail_intent as m

    monkeypatch.setattr(m, "_lexi_addresses", lambda: {"lexi@iconicfounders.com"})
    assert is_mail_to_lexi({"to_recipients": ["lexi@iconicfounders.com"]})
    assert not is_mail_to_lexi({"to_recipients": ["kory@iconicfounders.com"], "cc_recipients": ["lexi@iconicfounders.com"]})


def test_parse_dont_schedule():
    intent = parse_lexi_mail_intent(
        subject="FW: Bad fit",
        body="Lexi — don't schedule any meetings with this person.",
    )
    assert intent.intent == "dont_schedule"


def test_parse_briefing():
    intent = parse_lexi_mail_intent(subject="Brief", body="Send me a morning briefing please")
    assert intent.intent == "briefing"


@patch("app.storage.kory_memory.upsert_fact")
def test_handle_dont_schedule(mock_upsert):
    out = handle_lexi_direct_mail(
        {
            "thread_id": "t-lexi-1",
            "subject": "No",
            "raw_body": "Don't schedule with them",
            "to_recipients": ["lexi@iconicfounders.com"],
            "sender": "kory@iconicfounders.com",
        }
    )
    assert out["action"] == "dont_schedule"
    mock_upsert.assert_called_once()

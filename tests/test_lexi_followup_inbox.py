"""Lexi thread follow-up and inbox review tests."""

from datetime import datetime, timezone
from unittest.mock import patch

from app.assistant.inbox_review import build_inbox_review
from app.scheduling.recipient_slot import match_recipient_slot_choice


def test_match_time_works_pattern() -> None:
    slots = [
        {"start": "2026-07-01T17:30:00-06:00", "end": "2026-07-01T18:00:00-06:00"},
    ]
    chosen = match_recipient_slot_choice("5:30 works for me — see you then", slots)
    assert chosen == slots[0]


@patch("app.integrations.outlook_inbox.search_inbox")
def test_inbox_review_from_outlook(mock_search) -> None:
    mock_search.return_value = (
        [
            {
                "subject": "Brentwood Roofing intro",
                "sender": "brent@example.com",
                "sender_name": "Brent",
                "received_at": datetime.now(timezone.utc).isoformat(),
                "preview": "Good to meet you — let me know what works to connect.",
                "thread_id": "conv-1",
            }
        ],
        "log-1",
    )
    review = build_inbox_review(hours=48)
    assert review["ok"] is True
    assert "Brentwood" in review["kory_message"]
    assert "Intros" in review["kory_message"] or "Scheduling" in review["kory_message"]
    assert "proposal_id" not in review["kory_message"].lower()

"""Chat-initiated draft without CC Lexi."""

import uuid
from unittest.mock import patch

from app.agents.inbound_reply import (
    NO_REPLY_NEEDED,
    begin_draft_reply,
    find_proposal_by_subject,
)


def test_find_proposal_by_subject() -> None:
    from app.storage.lexi_db import get_lexi_connection

    token = uuid.uuid4().hex[:8]
    thread_id = f"t-chat-{token}"
    subject = f"TEST — slot verify intro {token}"
    with get_lexi_connection() as conn:
        conn.execute(
            """
            INSERT INTO email_threads (thread_id, subject, sender, raw_body)
            VALUES (?, ?, 'anjana@iconicfounders.com', 'Hi')
            """,
            (thread_id, subject),
        )
        conn.execute(
            """
            INSERT INTO proposals (thread_id, status, intent_classification, priority_tier)
            VALUES (?, ?, 'referral_or_intro', 'medium')
            """,
            (thread_id, NO_REPLY_NEEDED),
        )
        conn.commit()
        pid = conn.execute("SELECT id FROM proposals WHERE thread_id=?", (thread_id,)).fetchone()["id"]

    match = find_proposal_by_subject(token)
    assert match is not None
    assert int(match["proposal_id"]) == int(pid)


def test_begin_draft_reply_reactivates_no_reply_needed() -> None:
    from app.storage.lexi_db import get_lexi_connection

    thread_id = f"t-chat-{uuid.uuid4().hex[:8]}"
    with get_lexi_connection() as conn:
        conn.execute(
            """
            INSERT INTO email_threads (thread_id, subject, sender, raw_body)
            VALUES (?, 'TEST — chat draft', 'anjana@iconicfounders.com', 'intro next week')
            """,
            (thread_id,),
        )
        conn.execute(
            """
            INSERT INTO proposals (thread_id, status, intent_classification, priority_tier)
            VALUES (?, ?, 'referral_or_intro', 'medium')
            """,
            (thread_id, NO_REPLY_NEEDED),
        )
        conn.commit()
        pid = int(conn.execute("SELECT id FROM proposals WHERE thread_id=?", (thread_id,)).fetchone()["id"])

    with patch("app.agents.inbound_reply.process_proposal_schedule", return_value=True):
        with patch("app.bot.teams_publisher.schedule_teams_approval_push"):
            result = begin_draft_reply(pid, voice_mode="kory")
    assert result["ok"]
    assert result["status"] == "pending_approval"
    with get_lexi_connection() as conn:
        row = conn.execute("SELECT voice_mode FROM proposals WHERE id=?", (pid,)).fetchone()
    assert row["voice_mode"] == "kory"

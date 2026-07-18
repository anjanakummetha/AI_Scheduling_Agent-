"""Regression: already-ingested path must not NameError before delegation replay."""

from __future__ import annotations

from unittest.mock import patch

from app import orchestrator as orch


def test_already_ingested_delegation_replay_does_not_nameerror():
    raw = {
        "thread_id": "phase-a-already-ingested-001",
        "outlook_message_id": "phase-a-already-ingested-001",
        "sender": "kory@iconicfounders.com",
        "subject": "Find us a time",
        "raw_body": "Lexi can help schedule",
        "cc_recipients": ["lexi@iconicfounders.com"],
    }
    with (
        patch.object(orch, "_thread_already_ingested", return_value=True),
        patch.object(orch, "_handle_delegation_followup", return_value=None) as followup,
    ):
        out = orch._handle_inbound_stream_locked(raw)

    assert out.get("skipped") is True
    assert out.get("action") == "already_ingested"
    followup.assert_called_once()

#!/usr/bin/env python3
"""Re-run rules-first pipeline for an existing decision (fixes stale proposals)."""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.integrations.outlook_email import get_message, normalize_message
from app.llm.proposal_generator import draft_proposal_from_decision
from app.rules.policy_engine import build_scheduling_decision
from app.rules.validators import validate_proposal
from app.storage.decision_store import get_decision, update_decision_proposal
from app.workflows.inbound_email import (
    _add_live_conflict_validation,
    _filter_scheduling_decision_for_outlook,
    _load_calendar_context,
    _sync_proposal_with_decision,
)
from app.database import get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("decision_id", type=int)
    args = parser.parse_args()

    decision = get_decision(args.decision_id)
    if not decision:
        raise SystemExit(f"Decision {args.decision_id} not found.")

    message_id = decision.get("outlook_message_id")
    if message_id and not str(message_id).startswith("demo-"):
        message, _ = get_message(message_id)
        email = normalize_message(message, {"source": "reprocess", "message_id": message_id})
    else:
        email = {
            "outlook_message_id": message_id,
            "sender_email": decision["sender_email"],
            "sender_name": decision.get("sender_name"),
            "subject": decision["subject"],
            "body": decision["body"],
            "received_at": decision.get("received_at"),
            "raw_payload": {},
        }
        if "<" in email["body"] and ">" in email["body"]:
            from app.integrations.outlook_email import _plain_text

            email["body"] = _plain_text(email["body"])

    with get_connection() as conn:
        conn.execute(
            "UPDATE emails SET body = ? WHERE id = ?",
            (email["body"], decision["email_id"]),
        )

    calendar_context = _load_calendar_context()
    scheduling_decision = build_scheduling_decision(email, calendar_context)
    scheduling_decision = _filter_scheduling_decision_for_outlook(email, scheduling_decision)
    proposal = draft_proposal_from_decision(email, scheduling_decision)
    proposal, scheduling_decision = _sync_proposal_with_decision(proposal, scheduling_decision)
    validation = validate_proposal(
        proposal,
        expected_recipient_name=email.get("sender_name"),
        scheduling_decision=scheduling_decision,
    )
    validation = _add_live_conflict_validation(proposal, validation)
    update_decision_proposal(args.decision_id, proposal, validation)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE decisions
            SET calendar_execution_status = 'not_started',
                outlook_calendar_event_id = NULL
            WHERE id = ?
              AND calendar_execution_status IN ('completed', 'failed')
            """,
            (args.decision_id,),
        )
    holds = (proposal.get("calendar_action") or {}).get("holds") or []
    print(
        json.dumps(
            {
                "decision_id": args.decision_id,
                "validation": validation,
                "slots": proposal["proposed_slots"],
                "hold_titles": [h.get("title") for h in holds],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

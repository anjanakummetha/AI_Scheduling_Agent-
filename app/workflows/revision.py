"""Dashboard-driven proposal edits and Hermes revisions."""

from __future__ import annotations

import json
from typing import Any

from app.llm.proposal_generator import draft_proposal_from_decision
from app.rules.policy_engine import build_scheduling_decision
from app.rules.validators import validate_proposal
from app.storage.decision_store import (
    add_audit_event,
    get_decision,
    update_decision_proposal,
    update_decision_reply,
)
from app.workflows.inbound_email import (
    _add_live_conflict_validation,
    _filter_scheduling_decision_for_outlook,
    _load_calendar_context,
    _sync_proposal_with_decision,
)


def save_manual_reply(decision_id: int, proposed_reply: str) -> None:
    from app.llm.proposal_generator import _format_reply_spacing

    decision = _require_decision(decision_id)
    proposal = _proposal_from_decision(decision)
    proposal["draft_reply"] = _format_reply_spacing(proposed_reply)
    validation = validate_proposal(
        proposal,
        expected_recipient_name=decision.get("sender_name"),
    )
    validation = _add_live_conflict_validation(proposal, validation)
    update_decision_reply(decision_id, proposal["draft_reply"], validation)
    add_audit_event(
        "proposal.reply_edited",
        "Dashboard reviewer manually edited the proposed reply.",
        decision_id,
        {"validation": validation},
    )


def request_proposal_changes(decision_id: int, change_request: str) -> None:
    decision = _require_decision(decision_id)
    email = _email_from_decision(decision)
    existing_proposal = _proposal_from_decision(decision)
    calendar_context = _load_calendar_context()
    scheduling_decision = build_scheduling_decision(email, calendar_context)
    scheduling_decision = _filter_scheduling_decision_for_outlook(email, scheduling_decision)
    proposal = draft_proposal_from_decision(
        email,
        scheduling_decision,
        change_request=change_request,
        existing_proposal=existing_proposal,
    )
    proposal, scheduling_decision = _sync_proposal_with_decision(proposal, scheduling_decision)
    validation = validate_proposal(
        proposal,
        expected_recipient_name=decision.get("sender_name"),
        scheduling_decision=scheduling_decision,
    )
    validation = _add_live_conflict_validation(proposal, validation)
    update_decision_proposal(decision_id, proposal, validation)
    add_audit_event(
        "proposal.revised",
        "Hermes revised the reply using rules-first engine slots.",
        decision_id,
        {
            "change_request": change_request,
            "validation": validation,
            "reasoning": scheduling_decision.get("reasoning"),
        },
    )


def _require_decision(decision_id: int) -> dict[str, Any]:
    decision = get_decision(decision_id)
    if not decision:
        raise ValueError(f"Decision {decision_id} not found.")
    return decision


def _proposal_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": decision.get("detected_intent"),
        "meeting_type": decision.get("meeting_type"),
        "priority_contact": bool(decision.get("priority_contact")),
        "proposed_slots": json.loads(decision["proposed_slots_json"]),
        "draft_reply": decision["proposed_reply"],
        "calendar_action": json.loads(decision["proposed_calendar_action_json"]),
        "needs_approval": True,
    }


def _email_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "outlook_message_id": decision.get("outlook_message_id"),
        "sender_email": decision["sender_email"],
        "sender_name": decision.get("sender_name"),
        "subject": decision["subject"],
        "body": decision["body"],
        "received_at": decision.get("received_at"),
        "raw_payload": json.loads(decision.get("raw_payload_json") or "{}"),
    }

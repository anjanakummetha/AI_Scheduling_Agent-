"""Inbound email workflow: email -> policy engine -> draft -> validation -> pending approval."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.integrations.outlook_calendar import get_calendar_events, has_conflict, is_blocking_event
from app.llm.proposal_generator import draft_proposal_from_decision
from app.rules.policy_engine import build_scheduling_decision
from app.rules.validators import validate_proposal
from app.storage.decision_store import (
    add_audit_event,
    create_decision,
    create_email,
    get_decision_id_by_outlook_message_id,
)


def process_inbound_email(email: dict[str, Any]) -> int:
    outlook_message_id = email.get("outlook_message_id")
    if outlook_message_id:
        existing_decision_id = get_decision_id_by_outlook_message_id(outlook_message_id)
        if existing_decision_id is not None:
            add_audit_event(
                event_type="workflow.duplicate_skipped",
                message="Inbound email skipped because this Outlook message was already processed.",
                decision_id=existing_decision_id,
                metadata={"outlook_message_id": outlook_message_id},
            )
            return existing_decision_id

    email_id = create_email(email)
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
    decision_id = create_decision(email_id, proposal, validation)

    add_audit_event(
        event_type="workflow.proposal_created",
        message="Inbound email processed with rules-first scheduling engine.",
        decision_id=decision_id,
        metadata={
            "validation": validation,
            "summary": proposal.get("summary"),
            "reasoning": scheduling_decision.get("reasoning"),
            "calendar_context_status": calendar_context.get("status"),
        },
    )
    return decision_id


def _filter_scheduling_decision_for_outlook(
    email: dict[str, Any],
    scheduling_decision: dict[str, Any],
) -> dict[str, Any]:
    from app.rules.policy_engine import _calendar_action
    from app.rules.rule_engine import load_rules

    safe_slots = [
        slot for slot in scheduling_decision.get("proposed_slots") or [] if not _slot_has_conflict(slot)
    ]
    if len(safe_slots) != len(scheduling_decision.get("proposed_slots") or []):
        scheduling_decision["reasoning"].append(
            "Removed slot(s) that overlap live Outlook events before drafting reply."
        )
    scheduling_decision["proposed_slots"] = safe_slots

    if not safe_slots:
        scheduling_decision["calendar_action"] = {"type": "none"}
        if scheduling_decision.get("should_offer_times"):
            scheduling_decision["intent"] = "needs_review"
        return scheduling_decision

    classification = {
        "meeting_type": scheduling_decision.get("meeting_type", "unknown"),
        "meeting_format": scheduling_decision.get("meeting_format", "virtual"),
    }
    scheduling_decision["calendar_action"] = _calendar_action(
        email,
        classification,
        safe_slots,
        load_rules()["scheduling"],
    )
    return scheduling_decision


def _sync_proposal_with_decision(
    proposal: dict[str, Any],
    scheduling_decision: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    proposal["proposed_slots"] = scheduling_decision.get("proposed_slots", [])
    proposal["calendar_action"] = scheduling_decision.get("calendar_action", {"type": "none"})
    proposal["intent"] = scheduling_decision.get("intent", proposal.get("intent"))
    return proposal, scheduling_decision


def _verify_slots_against_outlook(
    email: dict[str, Any],
    proposal: dict[str, Any],
    scheduling_decision: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    scheduling_decision = _filter_scheduling_decision_for_outlook(email, scheduling_decision)
    proposal = draft_proposal_from_decision(email, scheduling_decision)
    return _sync_proposal_with_decision(proposal, scheduling_decision)


def create_mock_inbound_email() -> int:
    email = {
        "outlook_message_id": "demo-message-001",
        "sender_email": "priority@example.com",
        "sender_name": "Priority Contact",
        "subject": "Finding time with Kory",
        "body": (
            "Hi Kory, I would love to find 30 minutes next week to compare notes. "
            "A Teams call works well for me. Are there any times that work on your end?"
        ),
        "received_at": "demo",
        "raw_payload": {"source": "dashboard-demo"},
    }
    return process_inbound_email(email)


def _add_live_conflict_validation(proposal: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    calendar_action = proposal.get("calendar_action") or {}
    for slot in proposal.get("proposed_slots") or []:
        _append_slot_conflict(slot, validation)

    if calendar_action.get("type") == "create_holds":
        for hold in calendar_action.get("holds") or []:
            _append_slot_conflict(hold, validation)
        validation["valid"] = not validation.get("errors")
        return validation

    if calendar_action.get("type") != "create_event":
        validation["valid"] = not validation.get("errors")
        return validation

    try:
        conflict, events, _log_id = has_conflict(calendar_action)
    except Exception as exc:
        validation["errors"].append(f"Could not verify Outlook availability before approval: {exc}")
        validation["valid"] = False
        return validation

    if conflict:
        subjects = ", ".join(str(event.get("subject") or "busy event") for event in events[:5])
        validation["errors"].append(f"Proposed calendar time overlaps existing Outlook event(s): {subjects}.")

    validation["valid"] = not validation.get("errors")
    return validation


def _slot_has_conflict(slot: dict[str, Any]) -> bool:
    if not slot.get("start") or not slot.get("end"):
        return True
    try:
        conflict, _events, _log_id = has_conflict(slot)
        return conflict
    except Exception:
        return True


def _append_slot_conflict(slot: dict[str, Any], validation: dict[str, Any]) -> None:
    if not slot.get("start") or not slot.get("end"):
        return
    try:
        conflict, events, _log_id = has_conflict(slot)
    except Exception as exc:
        validation["errors"].append(f"Could not verify suggested time against Outlook: {exc}")
        return
    if conflict:
        subjects = ", ".join(str(event.get("subject") or "busy event") for event in events[:3])
        validation["errors"].append(
            f"Suggested time {slot['start']} to {slot['end']} overlaps existing Outlook event(s): {subjects}."
        )


def _load_calendar_context() -> dict[str, Any]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=21)
    try:
        events, log_id = get_calendar_events(start.isoformat(), end.isoformat())
        busy_events = [
            {
                "subject": event.get("subject"),
                "start": event.get("start"),
                "end": event.get("end"),
                "showAs": event.get("showAs"),
            }
            for event in events
            if is_blocking_event(event)
        ]
        return {
            "status": "available",
            "range_start": start.isoformat(),
            "range_end": end.isoformat(),
            "busy_events": busy_events,
            "composio_log_id": log_id,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "range_start": start.isoformat(),
            "range_end": end.isoformat(),
            "busy_events": [],
        }


# Backward-compatible exports for revision workflow
def _enforce_live_calendar_safety(email: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    scheduling_decision = {
        "proposed_slots": proposal.get("proposed_slots", []),
        "meeting_format": "virtual",
        "meeting_type": proposal.get("meeting_type", "unknown"),
    }
    proposal, _ = _verify_slots_against_outlook(email, proposal, scheduling_decision)
    return proposal

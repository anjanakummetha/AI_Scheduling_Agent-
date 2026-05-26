"""Approved Outlook execution workflows."""

from __future__ import annotations

import json

from app.integrations.outlook_calendar import create_calendar_event, has_conflict
from app.integrations.outlook_email import create_draft_reply, send_draft
from app.storage.decision_store import (
    add_audit_event,
    get_decision,
    mark_calendar_executed,
    mark_calendar_failed,
    mark_email_executed,
    mark_email_failed,
)


def execute_approved_email(decision_id: int) -> None:
    decision = get_decision(decision_id)
    if not decision:
        raise ValueError(f"Decision {decision_id} not found.")
    if decision["status"] == "rejected":
        raise ValueError("Rejected decisions cannot be executed.")
    if str(decision["outlook_message_id"]).startswith("demo-"):
        mark_email_failed(decision_id, "Mock dashboard emails are local-only and cannot be sent through Outlook.")
        return
    if not decision["outlook_message_id"]:
        mark_email_failed(decision_id, "Cannot create reply draft: missing Outlook message ID.")
        return

    try:
        draft_id, draft_log_id = create_draft_reply(
            decision["outlook_message_id"],
            decision["proposed_reply"],
        )
        add_audit_event(
            "execution.email_draft_created",
            "Outlook reply draft created after approval.",
            decision_id,
            {"draft_message_id": draft_id},
            draft_log_id,
        )
        if not draft_id:
            mark_email_failed(decision_id, "Draft was created but Composio did not return a draft message ID.")
            return

        send_log_id = send_draft(draft_id)
        add_audit_event(
            "execution.email_sent",
            "Approved Outlook draft sent.",
            decision_id,
            {"draft_message_id": draft_id},
            send_log_id,
        )
        mark_email_executed(decision_id, draft_id)
    except Exception as exc:
        mark_email_failed(decision_id, f"Email execution failed: {exc}")


def execute_approved_calendar(decision_id: int) -> None:
    decision = get_decision(decision_id)
    if not decision:
        raise ValueError(f"Decision {decision_id} not found.")
    if decision["status"] == "rejected":
        raise ValueError("Rejected decisions cannot be executed.")
    if str(decision["outlook_message_id"]).startswith("demo-"):
        mark_calendar_failed(decision_id, "Mock dashboard emails are local-only and cannot create Outlook events.")
        return

    calendar_action = json.loads(decision["proposed_calendar_action_json"])
    action_type = calendar_action.get("type")

    if action_type == "none":
        mark_calendar_failed(decision_id, "No calendar action exists for this proposal.")
        return

    if action_type == "create_holds":
        _execute_holds(decision_id, calendar_action)
        return

    if action_type != "create_event":
        mark_calendar_failed(decision_id, f"Unsupported calendar action type: {action_type}")
        return

    try:
        conflict, events, availability_log_id = has_conflict(calendar_action)
        add_audit_event(
            "execution.calendar_conflict_check",
            "Checked Outlook calendar before approved write.",
            decision_id,
            {"conflict": conflict, "events": events},
            availability_log_id,
        )
        if conflict:
            mark_calendar_failed(decision_id, "Calendar event was not created because Outlook shows a conflict.")
            return

        event_id, create_log_id = create_calendar_event(calendar_action)
        add_audit_event(
            "execution.calendar_created",
            "Outlook calendar event created after approval.",
            decision_id,
            {"event_id": event_id},
            create_log_id,
        )
        mark_calendar_executed(decision_id, event_id)
    except Exception as exc:
        mark_calendar_failed(decision_id, f"Calendar execution failed: {exc}")


def _execute_holds(decision_id: int, calendar_action: dict) -> None:
    holds = calendar_action.get("holds") or []
    if not holds:
        mark_calendar_failed(decision_id, "create_holds action is missing hold entries.")
        return

    created_ids: list[str] = []
    failed_holds: list[str] = []
    try:
        for hold in holds:
            conflict, events, availability_log_id = has_conflict(
                hold,
                ignore_event_ids=created_ids,
            )
            add_audit_event(
                "execution.calendar_conflict_check",
                "Checked Outlook before creating a hold.",
                decision_id,
                {"conflict": conflict, "hold": hold.get("title"), "events": events},
                availability_log_id,
            )
            if conflict:
                failed_holds.append(hold.get("title") or "hold")
                continue

            event_id, create_log_id = create_calendar_event(hold)
            add_audit_event(
                "execution.calendar_hold_created",
                "Outlook hold event created after approval.",
                decision_id,
                {"event_id": event_id, "title": hold.get("title")},
                create_log_id,
            )
            if event_id:
                created_ids.append(event_id)

        if not created_ids:
            mark_calendar_failed(
                decision_id,
                "No calendar holds were created because all proposed times conflicted.",
            )
            return

        mark_calendar_executed(decision_id, created_ids[0])
        add_audit_event(
            "execution.calendar_holds_completed",
            f"Created {len(created_ids)} calendar hold(s) in Outlook.",
            decision_id,
            {"event_ids": created_ids, "failed_holds": failed_holds},
        )
        if failed_holds:
            add_audit_event(
                "execution.calendar_partial",
                "Some holds could not be created due to conflicts.",
                decision_id,
                {"failed_holds": failed_holds, "created": len(created_ids)},
            )
    except Exception as exc:
        mark_calendar_failed(decision_id, f"Calendar hold execution failed: {exc}")

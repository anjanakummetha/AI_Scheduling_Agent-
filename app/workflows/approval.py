"""Approval workflow boundary."""

from app.storage.decision_store import mark_approved, mark_rejected
from app.workflows.execution import execute_approved_calendar, execute_approved_email


def approve_decision(decision_id: int) -> None:
    mark_approved(decision_id, "Approved from dashboard.")


def approve_email(decision_id: int) -> None:
    mark_approved(decision_id, "Email send approved from dashboard.")
    execute_approved_email(decision_id)


def approve_calendar(decision_id: int) -> None:
    mark_approved(decision_id, "Calendar write approved from dashboard.")
    execute_approved_calendar(decision_id)


def approve_all(decision_id: int) -> None:
    mark_approved(decision_id, "Email send and calendar write approved from dashboard.")
    execute_approved_calendar(decision_id)
    execute_approved_email(decision_id)


def reject_decision(decision_id: int) -> None:
    mark_rejected(decision_id, "Rejected from dashboard. No Outlook action taken.")

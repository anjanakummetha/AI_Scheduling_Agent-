"""Unified propose_schedule() — single path for webhook, poll, console, and Hermes."""

from __future__ import annotations

from typing import Any

from app.agents.scheduler_agent import process_proposal_schedule
from app.agents.triage_agent import process_new_email
from app.orchestrator import handle_inbound_stream


def propose_schedule(
    *,
    raw_email: dict[str, Any] | None = None,
    proposal_id: int | None = None,
    run_triage: bool = True,
) -> dict[str, Any]:
    """Run triage + scheduler (or scheduler-only) and return a structured result."""
    if raw_email is not None:
        return handle_inbound_stream(raw_email)

    if proposal_id is not None:
        advanced = process_proposal_schedule(proposal_id)
        return {
            "proposal_id": proposal_id,
            "scheduler_processed": advanced,
            "final_status": "pending_approval" if advanced else "pending_triage",
        }

    raise ValueError("propose_schedule requires raw_email or proposal_id.")


def triage_only(raw_email: dict[str, Any]) -> dict[str, Any]:
    """Triage without advancing scheduler (for tests)."""
    proposal_id = process_new_email(raw_email)
    return {"proposal_id": proposal_id, "status": "pending_triage" if proposal_id else "ignored"}

#!/usr/bin/env python3
"""Live end-to-end tests: real Composio + Anthropic (no Teams, no Asana).

Usage:
    .venv/bin/python scripts/test_live_e2e.py
    .venv/bin/python scripts/test_live_e2e.py --skip-approval   # staging only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from _live_guard import require_live_confirmation
from app.agents.comms_agent import execute_lexi_approval
from app.agents.inbound_reply import AWAITING_REPLY_PROMPT, begin_draft_reply
from app.agents.triage_agent import process_new_email
from app.assistant.actions import get_calendar_availability, get_lexi_system_status
from app.config import settings
from app.integrations.calendar_holds import place_tentative_hold
from app.integrations.outlook_calendar import (
    delete_calendar_event,
    get_calendar_events,
    get_write_calendar_events,
)
from app.integrations.outlook_email import send_outbound_email
from app.orchestrator import handle_inbound_stream
from app.storage.lexi_store import get_proposal, list_proposals
from scripts.init_lexi_db import init_lexi_db

Results: list[dict] = []


def record(case_id: str, name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    Results.append({"id": case_id, "name": name, "status": status, "detail": detail})
    line = f"  [{status}] {case_id}: {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def tc01_config() -> None:
    status = get_lexi_system_status()
    ok = (
        status.get("composio_configured")
        and status.get("read_connection") == settings.kory_composio_connection_id
        and status.get("write_connection") == settings.sandbox_composio_connection_id
        and status.get("sandbox_mailbox_email") == settings.sandbox_mailbox_email
        and not status.get("lexi_dry_run")
    )
    record(
        "TC-01",
        "Runtime config (read Kory, write sandbox, live mode)",
        ok,
        f"mailbox={status.get('sandbox_mailbox_email')}",
    )


def tc02_kory_calendar_read() -> None:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=7)
    try:
        events, log_id = get_calendar_events(start.isoformat(), end.isoformat())
        record(
            "TC-02",
            "Read Kory Outlook calendar (Composio)",
            True,
            f"{len(events)} events in 7d (log={log_id})",
        )
    except Exception as exc:
        record("TC-02", "Read Kory Outlook calendar (Composio)", False, str(exc))


def tc03_sandbox_hold() -> tuple[str | None]:
    """Place and verify a tentative hold on sandbox calendar; return event id for cleanup."""
    slot_start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    slot_end = slot_start + timedelta(minutes=30)
    hold = place_tentative_hold(
        action={
            "title": "Lexi E2E hold (auto-cleanup)",
            "start": slot_start.isoformat(),
            "end": slot_end.isoformat(),
            "attendees": [],
            "body": "E2E test hold",
            "is_online_meeting": False,
        },
    )
    event_id = hold.get("event_id") if hold.get("ok") else None
    record(
        "TC-03",
        "Create sandbox calendar hold",
        bool(hold.get("ok") and event_id),
        str(event_id or hold.get("error") or hold),
    )
    return str(event_id) if event_id else None


def tc04_loopback_email() -> None:
    try:
        msg_id, log_id = send_outbound_email(
            approved_send=True,
            to_email="partner@example.com",
            subject="Lexi E2E loopback test",
            body="Pilot loopback — should arrive at sandbox mailbox only.",
        )
        record(
            "TC-04",
            f"Sandbox loopback email → {settings.sandbox_mailbox_email}",
            bool(msg_id),
            f"msg_id={msg_id} log={log_id}",
        )
    except Exception as exc:
        record("TC-04", "Sandbox loopback email", False, str(exc))


def tc05_live_triage_scheduler(skip_approval: bool) -> int | None:
    """Full LLM triage + scheduler with real Kory calendar."""
    thread_id = f"e2e-live-{uuid.uuid4().hex[:10]}"
    email = {
        "thread_id": thread_id,
        "subject": "Coffee next week to discuss partnership?",
        "sender": "founder@startup.io",
        "received_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "raw_body": (
            "Hi Kory, would love to grab coffee for 30 minutes next week "
            "to walk through a potential partnership. Flexible on timing — "
            "what works on your end?"
        ),
    }
    try:
        proposal_id = process_new_email(email)
        if not proposal_id:
            record("TC-05a", "Live LLM triage → scheduling intent", False, "no proposal created")
            return None
        proposal = get_proposal(proposal_id)
        intent = (proposal or {}).get("intent_classification", "")
        status = (proposal or {}).get("status", "")
        label = "Live LLM triage" if settings.llm_api_key else "Heuristic triage (no API key)"
        record(
            "TC-05a",
            f"{label} → awaiting_reply_prompt (ask before draft)",
            status == AWAITING_REPLY_PROMPT,
            f"proposal={proposal_id} intent={intent} status={status}",
        )
    except Exception as exc:
        record("TC-05a", "Live LLM triage", False, str(exc))
        return None

    try:
        draft_result = begin_draft_reply(proposal_id)
        ok = draft_result.get("ok") is True
        proposal = get_proposal(proposal_id) or {}
        slots = proposal.get("proposed_slots") or []
        holds = proposal.get("holds") or []
        sched_label = (
            "Live LLM scheduler"
            if settings.llm_api_key
            else "Scheduler (LLM or engine fallback)"
        )
        record(
            "TC-05b",
            f"{sched_label} after Kory yes → slots + holds",
            ok and len(slots) >= 2 and proposal.get("status") == "pending_approval",
            f"path={draft_result.get('path')} slots={len(slots)} holds={len(holds)} "
            f"reply_len={len(proposal.get('drafted_reply') or '')}",
        )
        if skip_approval:
            return proposal_id

        slot_start = ""
        if holds:
            slot_start = str(holds[0].get("slot_start") or "")
        elif slots:
            slot_start = str(slots[0].get("start") or "")

        result = execute_lexi_approval(
            proposal_id=proposal_id,
            decision="approved",
            selected_slot=slot_start,
            authorized_by="e2e_test",
            decision_source="console",
        )
        record(
            "TC-05c",
            "Live approval → calendar confirm + email",
            result.ok and result.status == "executed",
            json.dumps(
                {
                    "calendar_event_id": result.calendar_event_id,
                    "email_sent": result.email_sent,
                    "holds_released": result.holds_released,
                },
                default=str,
            ),
        )
        return proposal_id
    except Exception as exc:
        record("TC-05b", "Live LLM scheduler", False, str(exc))
        return proposal_id


def tc06_orchestrator_inject() -> None:
    thread_id = f"e2e-orch-{uuid.uuid4().hex[:10]}"
    payload = {
        "thread_id": thread_id,
        "subject": "Quick sync Thursday?",
        "sender": "colleague@iconicfounders.com",
        "received_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "raw_body": "Kory — can we do a 30-min internal sync Thursday afternoon?",
    }
    try:
        result = handle_inbound_stream(payload)
        ok = bool(result.get("proposal_id")) and result.get("final_status") == AWAITING_REPLY_PROMPT
        record(
            "TC-06",
            "Orchestrator inbound stream (triage→ask before draft)",
            ok,
            f"status={result.get('final_status')} proposal={result.get('proposal_id')}",
        )
    except Exception as exc:
        record("TC-06", "Orchestrator inbound stream", False, str(exc))


def tc07_calendar_mcp_helper() -> None:
    try:
        data = get_calendar_availability(days=14)
        ok = data.get("calendar_status") == "available" and data.get("busy_event_count", 0) >= 0
        record(
            "TC-07",
            "Calendar availability helper (MCP action)",
            ok,
            f"busy={data.get('busy_event_count')} status={data.get('calendar_status')}",
        )
    except Exception as exc:
        record("TC-07", "Calendar availability helper", False, str(exc))


def tc08_conflict_check() -> None:
    """Verify write calendar is readable for hold conflict detection."""
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=5)
    try:
        events, log_id = get_write_calendar_events(start.isoformat(), end.isoformat())
        record(
            "TC-08",
            "Read sandbox write calendar",
            True,
            f"{len(events)} events (log={log_id})",
        )
    except Exception as exc:
        record("TC-08", "Read sandbox write calendar", False, str(exc))


def cleanup_hold(event_id: str | None) -> None:
    if not event_id:
        return
    try:
        delete_calendar_event(event_id)
        print(f"  [cleanup] deleted hold event {event_id[:24]}...")
    except Exception as exc:
        print(f"  [cleanup] could not delete hold: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lexi live E2E test suite")
    parser.add_argument(
        "--skip-approval",
        action="store_true",
        help="Stop after scheduler staging (no calendar confirm/email send).",
    )
    args = parser.parse_args()

    # This suite places real sandbox holds and sends a loopback email — gate it.
    require_live_confirmation(
        f"place holds and send email against the sandbox mailbox "
        f"{settings.sandbox_mailbox_email or settings.sandbox_composio_connection_id}"
    )

    llm_live = bool(settings.llm_api_key)
    if not llm_live:
        print("WARN: ANTHROPIC_API_KEY not set — LLM cases use keyword/heuristic fallback.\n")

    print("\n=== Lexi Live E2E Test Suite ===\n")
    print(f"  read  : {settings.kory_composio_connection_id}")
    print(f"  write : {settings.sandbox_composio_connection_id}")
    print(f"  mailbox: {settings.sandbox_mailbox_email}")
    print(f"  model : {settings.llm_model}\n")

    init_lexi_db()
    hold_event_id: str | None = None

    tc01_config()
    tc02_kory_calendar_read()
    hold_event_id = tc03_sandbox_hold()
    tc04_loopback_email()
    tc07_calendar_mcp_helper()
    tc08_conflict_check()
    tc05_live_triage_scheduler(skip_approval=args.skip_approval)
    tc06_orchestrator_inject()

    cleanup_hold(hold_event_id)

    passed = sum(1 for r in Results if r["status"] == "PASS")
    failed = sum(1 for r in Results if r["status"] == "FAIL")
    print(f"\n=== Summary: {passed} passed, {failed} failed / {len(Results)} total ===\n")

    if failed:
        print("Failed cases:")
        for r in Results:
            if r["status"] == "FAIL":
                print(f"  - {r['id']}: {r['name']} — {r['detail']}")
        print()
        return 1

    pending = list_proposals("pending_approval")
    if pending:
        print(f"Note: {len(pending)} proposal(s) still pending_approval (approve via dashboard).\n")
    print("Scheduling agent is fully functional for pilot mode.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

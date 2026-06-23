#!/usr/bin/env python3
"""End-to-end integration test for the unified Lexi scheduling pipeline.

Runs triage → scheduler → comms queue → executive approval with deterministic
LLM/Composio mocks so each execution is repeatable without live API keys.

Usage:
    .venv/bin/python scripts/test_lexi_pipeline.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.comms_agent import execute_lexi_approval, get_lexi_pending_queue
from app.agents.inbound_reply import AWAITING_REPLY_PROMPT, begin_draft_reply
from app.agents.scheduler_agent import ScheduleResult
from app.agents.triage_agent import TriageResult, process_new_email
from app.config import settings
from scripts.init_lexi_db import init_lexi_db

MOCK_THREAD_ID = "test-thread-xyz-789"
MOCK_EMAIL = {
    "thread_id": MOCK_THREAD_ID,
    "subject": "Urgent: M&A Diligence Review & Dinner Strategy Session",
    "sender": "strategic-investor@venturecapital.com",
    "received_at": "2026-05-28 10:00:00",
    "raw_body": (
        "Hi Kory, we need to get together for a 60-minute session next week to finalize "
        "the diligence checkpoints and grab dinner. Let me know what days work best for you."
    ),
}

MOCK_TRIAGE = TriageResult(
    intent="dinner_request",
    priority="high",
    confidence_score=0.91,
    justification="Investor diligence + dinner language signals a high-priority strategic session.",
    source="test_mock",
)

MOCK_SCHEDULE = ScheduleResult(
    slots=[
        {"start": "2026-06-09T18:00:00-06:00", "end": "2026-06-09T19:00:00-06:00"},
        {"start": "2026-06-10T18:30:00-06:00", "end": "2026-06-10T19:30:00-06:00"},
        {"start": "2026-06-11T19:00:00-06:00", "end": "2026-06-11T20:00:00-06:00"},
    ],
    drafted_reply=(
        "Hi Strategic,\n\n"
        "Thanks for reaching out — a few dinner windows that work on my end:\n\n"
        "- Tuesday, June 9 at 6:00 PM MT\n"
        "- Wednesday, June 10 at 6:30 PM MT\n"
        "- Thursday, June 11 at 7:00 PM MT\n\n"
        "Let me know which works best and I can send a calendar invite.\n\n"
        "Let's Win,\n"
        "Kory"
    ),
    confidence_score=0.87,
    source="test_mock",
)

MOCK_CALENDAR_CONTEXT = {
    "status": "available",
    "source": "test_mock",
    "busy_events": [],
    "range_start": "2026-05-28T00:00:00+00:00",
    "range_end": "2026-06-11T00:00:00+00:00",
}


def _banner(title: str) -> None:
    width = 72
    print()
    print("=" * width)
    print(title.center(width))
    print("=" * width)


def _subheader(title: str) -> None:
    print(f"\n--- {title} ---")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.lexi_database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _assert_true(condition: bool, message: str) -> None:
    if not condition:
        print(f"\n[FAIL] {message}")
        raise SystemExit(1)
    print(f"[PASS] {message}")


def cleanup_lexi_db() -> None:
    _banner("ENVIRONMENT CLEANUP & SETUP")
    init_lexi_db()
    conn = _connect()
    try:
        for table in ("approvals", "holds", "audit_log", "proposals", "email_threads"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN (?, ?, ?, ?, ?)", (
            "approvals",
            "holds",
            "audit_log",
            "proposals",
            "email_threads",
        ))
        conn.commit()
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            for table in ("approvals", "holds", "audit_log", "proposals", "email_threads")
        }
        print(f"Cleared lexi.db at {settings.lexi_database_path}")
        print(f"Row counts after cleanup: {counts}")
        _assert_true(all(value == 0 for value in counts.values()), "All Lexi tables are empty.")
    finally:
        conn.close()


def step_1_triage() -> int:
    _banner("STEP 1: TRIAGE — INBOUND EMAIL INGESTION")
    print("Mock email payload:")
    print(json.dumps(MOCK_EMAIL, indent=2))

    with patch("app.agents.triage_agent._call_llm_triage", return_value=MOCK_TRIAGE):
        proposal_id = process_new_email(MOCK_EMAIL)

    print(f"\nTriage returned proposal_id={proposal_id}")

    conn = _connect()
    try:
        thread = conn.execute(
            "SELECT * FROM email_threads WHERE thread_id = ?",
            (MOCK_THREAD_ID,),
        ).fetchone()
        proposal = conn.execute(
            "SELECT * FROM proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()

        _assert_true(thread is not None, f"email_threads row exists for {MOCK_THREAD_ID}.")
        _assert_true(proposal is not None, f"proposals row exists for id={proposal_id}.")
        _assert_true(
            proposal["status"] == AWAITING_REPLY_PROMPT,
            f"proposal status is awaiting_reply_prompt (got {proposal['status']}).",
        )
        _assert_true(
            proposal["intent_classification"] == MOCK_TRIAGE.intent,
            "intent_classification persisted from triage.",
        )
        _assert_true(
            proposal["priority_tier"] == "high",
            "priority_tier elevated to high via investor keyword rules.",
        )

        _subheader("Triage snapshot")
        print(f"  thread subject : {thread['subject']}")
        print(f"  intent         : {proposal['intent_classification']}")
        print(f"  priority       : {proposal['priority_tier']}")
        print(f"  confidence     : {proposal['confidence_score']}")
        print(f"  justification  : {proposal['justification']}")
    finally:
        conn.close()

    return proposal_id


def step_2_scheduler(expected_proposal_id: int) -> None:
    _banner("STEP 2: KORY SAYS YES → SCHEDULER (slots + holds)")

    with (
        patch("app.agents.scheduler_agent._load_calendar_context", return_value=MOCK_CALENDAR_CONTEXT),
        patch("app.agents.scheduler_agent._call_llm_scheduler", return_value=MOCK_SCHEDULE),
        patch(
            "app.integrations.hold_placement.place_tentative_hold",
            side_effect=lambda **kwargs: {"ok": True, "event_id": f"hold-mock-{kwargs.get('start_iso', '')[:10]}"},
        ),
    ):
        draft_result = begin_draft_reply(expected_proposal_id)

    print(f"\nbegin_draft_reply result: {draft_result}")
    _assert_true(
        draft_result.get("ok") is True and draft_result.get("path") == "scheduling",
        f"Expected scheduling draft path (got {draft_result}).",
    )

    conn = _connect()
    try:
        proposal = conn.execute(
            "SELECT * FROM proposals WHERE id = ?",
            (expected_proposal_id,),
        ).fetchone()
        holds = conn.execute(
            "SELECT * FROM holds WHERE proposal_id = ? ORDER BY id ASC",
            (expected_proposal_id,),
        ).fetchall()

        _assert_true(proposal is not None, "Proposal row still exists after scheduling.")
        _assert_true(
            proposal["status"] == "pending_approval",
            f"proposal status is pending_approval (got {proposal['status']}).",
        )
        _assert_true(
            bool((proposal["drafted_reply"] or "").strip()),
            "drafted_reply is populated.",
        )

        slots = json.loads(proposal["proposed_slots"] or "[]")
        _assert_true(len(slots) >= 2, f"proposed_slots has >= 2 entries (got {len(slots)}).")
        _assert_true(len(holds) == len(slots), "holds table has one row per proposed slot.")

        _subheader("Proposal adjustments")
        print(f"  status          : {proposal['status']}")
        print(f"  confidence      : {proposal['confidence_score']}")
        print(f"  proposed_slots  : {json.dumps(slots, indent=2)}")
        print(f"  drafted_reply   :\n{proposal['drafted_reply']}")

        _subheader("Tentative holds")
        for hold in holds:
            print(
                f"  hold #{hold['id']} | event_id={hold['event_id']} | "
                f"{hold['slot_start']} → {hold['slot_end']}"
            )
    finally:
        conn.close()


def step_3_comms_queue(expected_proposal_id: int) -> str:
    _banner("STEP 3: COMMS — TEAMS APPROVAL QUEUE")

    queue = get_lexi_pending_queue()
    print(f"\nPending queue size: {len(queue)}")
    _assert_true(len(queue) >= 1, "Lexi pending queue is not empty.")

    selected_slot_start = ""
    for item in queue:
        _assert_true(
            item.thread_id == MOCK_THREAD_ID,
            f"Queue item {item.proposal_id} matches thread {MOCK_THREAD_ID}.",
        )
        print(f"\n  teams_summary_line:\n  {item.teams_summary_line()}")
        if item.proposal_id == expected_proposal_id and item.proposed_slots:
            selected_slot_start = str(item.proposed_slots[0]["start"])

    _assert_true(
        selected_slot_start != "",
        "Captured a selected slot start time from the queue.",
    )
    return selected_slot_start


def step_4_execute_approval(proposal_id: int, selected_slot_start: str) -> None:
    _banner("STEP 4: EXECUTIVE APPROVAL EXECUTION")
    print(f"  proposal_id   : {proposal_id}")
    print(f"  selected_slot : {selected_slot_start}")
    print("  authorized_by : kory-teams-id-001")

    with (
        patch("app.agents.comms_agent.create_calendar_event", return_value=("outlook-confirmed-event-001", "log-cal")),
        patch("app.agents.comms_agent.delete_calendar_event", return_value="log-del"),
        patch("app.agents.comms_agent.create_draft_reply", return_value=("draft-msg-001", "log-draft")),
        patch("app.agents.comms_agent.send_draft", return_value="log-send"),
        patch(
            "app.agents.comms_agent.send_pilot_reply_for_proposal",
            return_value=("dry-run-pilot-reply", "log-send"),
        ),
    ):
        result = execute_lexi_approval(
            proposal_id=proposal_id,
            decision="approved",
            selected_slot=selected_slot_start,
            authorized_by="kory-teams-id-001",
        )

    _subheader("Execution result")
    print(json.dumps(result.to_dict(), indent=2))
    _assert_true(result.ok, "execute_lexi_approval returned ok=True.")
    _assert_true(result.status == "executed", f"execution status is executed (got {result.status}).")


def step_5_final_validation(proposal_id: int, selected_slot_start: str) -> None:
    _banner("STEP 5: FINAL DATABASE VALIDATION & AUDIT TRAIL")

    conn = _connect()
    try:
        proposal = conn.execute(
            "SELECT status, proposed_slots FROM proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        _assert_true(proposal is not None, "Final proposal row exists.")
        _assert_true(
            proposal["status"] == "executed",
            f"Final proposal status is executed (got {proposal['status']}).",
        )

        holds = conn.execute(
            "SELECT id, event_id, slot_start, slot_end FROM holds WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchall()
        unselected = [
            hold for hold in holds
            if _normalize_slot(str(hold["slot_start"])) != _normalize_slot(selected_slot_start)
        ]
        _assert_true(
            len(unselected) == 0,
            "Unselected holds were released/deleted (only confirmed hold may remain).",
        )
        print(f"\nRemaining holds for proposal {proposal_id}: {len(holds)}")
        for hold in holds:
            print(
                f"  hold #{hold['id']} | event_id={hold['event_id']} | "
                f"{hold['slot_start']} → {hold['slot_end']}"
            )

        approval = conn.execute(
            "SELECT decision, decision_source, authorized_by FROM approvals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        _assert_true(approval is not None, "Approval record was persisted.")
        print(
            f"\nApproval: decision={approval['decision']} "
            f"source={approval['decision_source']} by={approval['authorized_by']}"
        )

        _subheader("Audit log (chronological)")
        audit_rows = conn.execute(
            """
            SELECT timestamp, step_name, log_level, message
            FROM audit_log
            ORDER BY id ASC
            """
        ).fetchall()
        _assert_true(len(audit_rows) >= 3, "Audit log contains pipeline events.")

        for row in audit_rows:
            print(
                f"  {row['timestamp']} | {row['step_name']:20} | "
                f"{row['log_level']:7} | {row['message']}"
            )
    finally:
        conn.close()


def _normalize_slot(value: str) -> str:
    return value.replace(" ", "").lower()


def main() -> int:
    _banner("LEXI PIPELINE — END-TO-END INTEGRATION TEST")
    print(f"Database: {settings.lexi_database_path}")

    try:
        cleanup_lexi_db()
        proposal_id = step_1_triage()
        step_2_scheduler(proposal_id)
        selected_slot = step_3_comms_queue(proposal_id)
        step_4_execute_approval(proposal_id, selected_slot)
        step_5_final_validation(proposal_id, selected_slot)

        _banner("ALL STEPS PASSED")
        print("Lexi pipeline integration test completed successfully.\n")
        return 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        _banner("TEST RUN FAILED")
        return code
    except Exception as exc:
        _banner("TEST RUN FAILED")
        print(f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

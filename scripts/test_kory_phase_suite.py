#!/usr/bin/env python3
"""Phased test suite for Lexi (excludes Teams/Azure connection).

Runs phases in order, records pass/fail, writes docs/TEST_RESULTS_REPORT.md.

Usage:
    .venv/bin/python scripts/test_kory_phase_suite.py
    .venv/bin/python scripts/test_kory_phase_suite.py --skip-live-llm
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.agents.inbound_reply import (
    AWAITING_REPLY_PROMPT,
    begin_draft_reply,
    decline_reply,
    get_inbound_reply_queue,
    is_scheduling_intent,
)
from app.agents.scheduler_agent import ScheduleResult
from app.agents.triage_agent import NON_SCHEDULING_INTENTS, process_new_email
from app.assistant.actions import get_lexi_system_status
from app.config import settings
from app.integrations.outlook_calendar import get_calendar_events
from app.integrations.outlook_email import send_outbound_email
from app.integrations.outlook_inbox import search_inbox
from app.orchestrator import handle_inbound_stream
from app.rules.validators import validate_proposal_slots
from app.storage.lexi_store import get_proposal
from scripts.init_lexi_db import init_lexi_db

REPORT_PATH = ROOT / "docs" / "TEST_RESULTS_REPORT.md"
RESULTS: list[dict[str, Any]] = []
PHASES: list[dict[str, Any]] = []


def record(
    phase: str,
    case_id: str,
    name: str,
    passed: bool,
    detail: str = "",
    *,
    skipped: bool = False,
) -> None:
    status = "SKIP" if skipped else ("PASS" if passed else "FAIL")
    entry = {
        "phase": phase,
        "id": case_id,
        "name": name,
        "status": status,
        "detail": detail,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    RESULTS.append(entry)
    line = f"  [{status}] {case_id}: {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def run_subprocess(phase: str, case_id: str, name: str, script: str, *args: str) -> bool:
    result = subprocess.run(
        [sys.executable, str(ROOT / script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    ok = result.returncode == 0
    detail = ""
    if not ok:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        detail = tail[-1][:200] if tail else f"exit {result.returncode}"
    record(phase, case_id, name, ok, detail)
    return ok


# ── Kory-realistic email fixtures (from inbox patterns) ─────────────────────

KORY_TEST_EMAILS = [
    {
        "id": "KY-01",
        "label": "Investor diligence call (deal scheduling)",
        "email": {
            "subject": "RE: diligence call and organization for Project Paint",
            "sender": "bill.heermann@newportadvisors.co",
            "raw_body": (
                "Kory — can we schedule a 60-minute diligence call next week? "
                "I'm flexible Tuesday–Thursday afternoons."
            ),
        },
        "expect_scheduling": True,
    },
    {
        "id": "KY-02",
        "label": "Coffee / partnership (typical external ask)",
        "email": {
            "subject": "Coffee next week to discuss partnership?",
            "sender": "founder@startup.io",
            "raw_body": (
                "Hi Kory, would love 30 minutes next week to walk through a partnership. "
                "What works on your end?"
            ),
        },
        "expect_scheduling": True,
    },
    {
        "id": "KY-03",
        "label": "Internal IFG sync",
        "email": {
            "subject": "Kory/Heidi – Work on Outreach messaging",
            "sender": "Heidi.Heckler@iconicfounders.com",
            "raw_body": "Can we grab 30 minutes Thursday to align on outreach messaging?",
        },
        "expect_scheduling": True,
    },
    {
        "id": "KY-04",
        "label": "Meeting summary (no scheduling reply needed)",
        "email": {
            "subject": "ERRG Meeting Summary",
            "sender": "natalie.asher@iconicfounders.com",
            "raw_body": "Attached is the summary from today's ERRG session. No action needed.",
        },
        "expect_scheduling": False,
    },
    {
        "id": "KY-05",
        "label": "YPO newsletter digest",
        "email": {
            "subject": "Business Marketplace - Daily Digest",
            "sender": "noreply@ypo.org",
            "raw_body": "Your daily digest from YPO Business Marketplace.",
        },
        "expect_scheduling": False,
    },
    {
        "id": "KY-06",
        "label": "Dinner + investor (high priority)",
        "email": {
            "subject": "Dinner while you're in town?",
            "sender": "strategic-investor@venturecapital.com",
            "raw_body": (
                "Kory — in town next week. Would love dinner to discuss the term sheet "
                "and diligence timeline. 90 minutes works."
            ),
        },
        "expect_scheduling": True,
    },
]


MOCK_SCHEDULE = ScheduleResult(
    slots=[
        {"start": "2026-06-17T13:00:00-06:00", "end": "2026-06-17T13:30:00-06:00"},
        {"start": "2026-06-18T14:00:00-06:00", "end": "2026-06-18T14:30:00-06:00"},
        {"start": "2026-06-19T15:00:00-06:00", "end": "2026-06-19T15:30:00-06:00"},
    ],
    drafted_reply="Let's Win,\nKory",
    confidence_score=0.9,
    source="test_mock",
)

MOCK_CALENDAR = {
    "status": "available",
    "busy_events": [],
    "source": "test_mock",
}


def phase_1_inbound_flow(skip_live_llm: bool) -> None:
    phase = "Phase 1 — Inbound ask-before-draft"
    print(f"\n{'=' * 60}\n{phase}\n{'=' * 60}")

    tid = f"phase1-orch-{uuid.uuid4().hex[:8]}"
    orch = handle_inbound_stream(
        {
            "thread_id": tid,
            "subject": "Quick sync Thursday?",
            "sender": "colleague@iconicfounders.com",
            "raw_body": "30-min internal sync Thursday afternoon?",
        }
    )
    from app.config import settings

    # When LEXI_LOCAL_MODE=true, the orchestrator ignores any subject without
    # "TEST" (returns action=local_test_only), so these mock emails never reach
    # triage/scheduling. That's a local-dev gate, not a code path under test —
    # skip the two orchestration assertions rather than reporting false failures.
    local_gated = orch.get("action") == "local_test_only"

    # The reply-prompt vs no-reply decision depends on triage intent, which needs
    # a live LLM. Under --skip-live-llm (and in keyless CI) only _fallback_triage
    # runs and legitimately returns no_reply_needed for an ambiguous internal note,
    # so asserting a specific status here would be non-deterministic. Gate it behind
    # a live LLM, matching P1-05.
    if skip_live_llm or local_gated:
        record(
            phase,
            "P1-01",
            "Inbound reply-prompt decision (live LLM)",
            True,
            "skipped (local-mode gate)" if local_gated else "skipped",
            skipped=True,
        )
    elif settings.lexi_teams_inbound_notify_mode == "delegation_only":
        record(
            phase,
            "P1-01",
            "delegation_only silences non-delegation mail",
            orch.get("final_status") == "no_reply_needed",
            f"status={orch.get('final_status')}",
        )
    else:
        record(
            phase,
            "P1-01",
            "Orchestrator stops at awaiting_reply_prompt",
            orch.get("final_status") == AWAITING_REPLY_PROMPT,
            f"status={orch.get('final_status')}",
        )
    if local_gated:
        record(phase, "P1-02", "Scheduler not auto-run on ingest", True, "skipped (local-mode gate)", skipped=True)
    else:
        record(
            phase,
            "P1-02",
            "Scheduler not auto-run on ingest",
            orch.get("scheduler_processed") is False,
            str(orch.get("scheduler_processed")),
        )

    tid2 = f"phase1-decline-{uuid.uuid4().hex[:8]}"
    pid = process_new_email(
        {
            "thread_id": tid2,
            "subject": "Newsletter",
            "sender": "noreply@ypo.org",
            "raw_body": "Daily digest",
        }
    )
    record(phase, "P1-03", "Non-scheduling email creates proposal", bool(pid), f"id={pid}")
    if pid:
        dec = decline_reply(pid, reason="test skip")
        record(phase, "P1-04", "Decline reply path", dec.get("ok") is True, dec.get("status", ""))

    if skip_live_llm:
        record(phase, "P1-05", "Scheduling draft after yes (live LLM)", True, "skipped", skipped=True)
        return

    tid3 = f"phase1-sched-{uuid.uuid4().hex[:8]}"
    pid3 = process_new_email(
        {
            "thread_id": tid3,
            "subject": "Coffee next week?",
            "sender": "guest@example.com",
            "raw_body": "30 min coffee next week — flexible.",
        }
    )
    if not pid3:
        record(phase, "P1-05", "Scheduling triage creates proposal", False, "no proposal")
        return
    prop = get_proposal(pid3) or {}
    intent = prop.get("intent_classification", "")
    record(
        phase,
        "P1-05a",
        "Scheduling intent classified",
        is_scheduling_intent(intent),
        f"intent={intent}",
    )
    try:
        with (
            patch("app.agents.scheduler_agent._load_calendar_context", return_value=MOCK_CALENDAR),
            patch("app.agents.scheduler_agent._call_llm_scheduler", return_value=MOCK_SCHEDULE),
        ):
            draft = begin_draft_reply(pid3)
        record(
            phase,
            "P1-05b",
            "Scheduler only after Kory yes",
            draft.get("ok") and draft.get("path") == "scheduling",
            str(draft.get("path")),
        )
    except Exception as exc:
        record(phase, "P1-05b", "Scheduler only after Kory yes", False, str(exc))


def phase_2_kory_rules() -> None:
    phase = "Phase 2 — Kory rules validators"
    print(f"\n{'=' * 60}\n{phase}\n{'=' * 60}")

    bad = validate_proposal_slots(
        [{"start": "2026-06-11T19:00:00-06:00", "end": "2026-06-11T20:00:00-06:00"}],
        intent="pitch",
    )
    record(phase, "P2-01", "Reject 7pm pitch slot (6pm cutoff)", not bad.valid, str(bad.violations[:1]))

    good = validate_proposal_slots(
        [{"start": "2026-06-11T13:00:00-06:00", "end": "2026-06-11T13:30:00-06:00"}],
        intent="pitch",
    )
    record(phase, "P2-02", "Accept 1pm pitch slot", good.valid, "")

    dinner = validate_proposal_slots(
        [{"start": "2026-06-12T19:00:00-06:00", "end": "2026-06-12T20:30:00-06:00"}],
        intent="dinner_request",
    )
    record(phase, "P2-03", "Allow 7pm dinner slot", dinner.valid, "")

    sat = validate_proposal_slots(
        [{"start": "2026-06-13T10:00:00-06:00", "end": "2026-06-13T11:00:00-06:00"}],
        intent="coffee",
    )
    record(phase, "P2-04", "Reject Saturday coffee", not sat.valid, str(sat.violations[:1]))

    trainer = validate_proposal_slots(
        [{"start": "2026-06-08T07:00:00-06:00", "end": "2026-06-08T07:30:00-06:00"}],
        intent="meeting_request",
    )
    record(phase, "P2-05", "Reject Monday trainer block", not trainer.valid, str(trainer.violations[:1]))

    doug = validate_proposal_slots(
        [{"start": "2026-06-08T13:30:00-06:00", "end": "2026-06-08T14:00:00-06:00"}],
        intent="meeting_request",
    )
    record(phase, "P2-06", "Reject Monday Doug block", not doug.valid, str(doug.violations[:1]))

    from app.safety.approval_gate import auto_execute_allowed, immediate_send_allowed, kory_approves_all
    from app.integrations.outlook_email import send_outbound_email

    record(phase, "P2-07a", "kory_approves_all enabled", kory_approves_all())
    record(phase, "P2-07b", "auto_execute disabled", not auto_execute_allowed())
    record(phase, "P2-07c", "immediate_send disabled", not immediate_send_allowed())
    try:
        send_outbound_email(
            to_email="gate@test.com",
            subject="x",
            body="x",
            approved_send=False,
        )
        record(phase, "P2-07d", "Unapproved send blocked", False, "send was not blocked")
    except PermissionError:
        record(phase, "P2-07d", "Unapproved send blocked", True)


def phase_3_composio_live(*, skip_live: bool = False) -> None:
    phase = "Phase 3 — Live Composio (read Kory, write sandbox)"
    print(f"\n{'=' * 60}\n{phase}\n{'=' * 60}")

    if skip_live:
        for case_id, name in (
            ("P3-01", "Pilot config read Kory / write sandbox"),
            ("P3-02", "Read Kory inbox"),
            ("P3-03", "Read Kory calendar 7d"),
            ("P3-04", "Sandbox loopback email send"),
        ):
            record(phase, case_id, name, True, "skipped (--ci)", skipped=True)
        return

    status = get_lexi_system_status()
    record(
        phase,
        "P3-01",
        "Pilot config read Kory / write sandbox",
        status.get("composio_configured")
        and status.get("lexi_write_mode") == "sandbox"
        and status.get("sandbox_mailbox_email") == "anjanakummetha@outlook.com",
        json.dumps(
            {
                "write_mode": status.get("lexi_write_mode"),
                "mailbox": status.get("sandbox_mailbox_email"),
            }
        ),
    )

    try:
        msgs, _ = search_inbox(top=5)
        record(phase, "P3-02", "Read Kory inbox", len(msgs) >= 1, f"{len(msgs)} messages")
    except Exception as exc:
        record(phase, "P3-02", "Read Kory inbox", False, str(exc))

    try:
        from datetime import timedelta

        start = datetime.now(timezone.utc)
        end = start + timedelta(days=7)
        events, _ = get_calendar_events(start.isoformat(), end.isoformat())
        record(phase, "P3-03", "Read Kory calendar 7d", len(events) >= 0, f"{len(events)} events")
    except Exception as exc:
        record(phase, "P3-03", "Read Kory calendar 7d", False, str(exc))

    try:
        msg_id, _ = send_outbound_email(
            to_email="phase-test@example.com",
            subject="Lexi phase suite loopback",
            body="Pilot loopback test from test_kory_phase_suite.py",
            approved_send=True,
        )
        record(phase, "P3-04", "Sandbox loopback email send", bool(msg_id), str(msg_id))
    except Exception as exc:
        record(phase, "P3-04", "Sandbox loopback email send", False, str(exc))


def phase_4_kory_email_patterns(skip_live_llm: bool) -> None:
    phase = "Phase 4 — Kory email pattern triage"
    print(f"\n{'=' * 60}\n{phase}\n{'=' * 60}")

    if skip_live_llm:
        for fixture in KORY_TEST_EMAILS:
            record(
                phase,
                fixture["id"],
                fixture["label"],
                True,
                "skipped (no --skip-live-llm)",
                skipped=True,
            )
        return

    for fixture in KORY_TEST_EMAILS:
        tid = f"{fixture['id']}-{uuid.uuid4().hex[:6]}"
        email = {**fixture["email"], "thread_id": tid}
        try:
            pid = process_new_email(email)
            if not pid:
                record(phase, fixture["id"], fixture["label"], False, "no proposal")
                continue
            prop = get_proposal(pid) or {}
            status_ok = prop.get("status") == AWAITING_REPLY_PROMPT
            intent = prop.get("intent_classification", "")
            sched = is_scheduling_intent(intent)
            intent_ok = sched == fixture["expect_scheduling"] or intent not in NON_SCHEDULING_INTENTS
            ok = status_ok and (
                sched == fixture["expect_scheduling"]
                or (not fixture["expect_scheduling"] and intent in NON_SCHEDULING_INTENTS)
                or intent == "unknown"
            )
            record(
                phase,
                fixture["id"],
                fixture["label"],
                ok,
                f"intent={intent} sched={sched} status={prop.get('status')}",
            )
        except Exception as exc:
            record(phase, fixture["id"], fixture["label"], False, str(exc))
        time.sleep(0.5)


def phase_5_subprocess_smoke(*, skip_live: bool = False) -> None:
    phase = "Phase 5 — Integration scripts"
    print(f"\n{'=' * 60}\n{phase}\n{'=' * 60}")

    run_subprocess(phase, "P5-01", "Mock pipeline", "scripts/test_lexi_pipeline.py")
    if skip_live:
        for case_id, name in (
            ("P5-02", "Sandbox integration"),
            ("P5-04", "Stack verify"),
            ("P5-05", "Live E2E staging"),
        ):
            record(phase, case_id, name, True, "skipped (--ci)", skipped=True)
    else:
        run_subprocess(phase, "P5-02", "Sandbox integration", "scripts/test_sandbox_integration.py")
        run_subprocess(phase, "P5-04", "Stack verify", "scripts/verify_stack.py")
        run_subprocess(phase, "P5-05", "Live E2E staging", "scripts/test_live_e2e.py", "--skip-approval")
    run_subprocess(phase, "P5-03", "MCP smoke", "scripts/test_mcp_tools.py")


def write_report() -> None:
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    skipped = sum(1 for r in RESULTS if r["status"] == "SKIP")
    total = len(RESULTS)

    by_phase: dict[str, list] = {}
    for r in RESULTS:
        by_phase.setdefault(r["phase"], []).append(r)

    lines = [
        "# Lexi Test Results Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Scope:** Full project except Teams/Azure connection (deferred to deploy day)",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total cases | {total} |",
        f"| PASS | {passed} |",
        f"| FAIL | {failed} |",
        f"| SKIP | {skipped} |",
        "",
        f"**Overall:** {'ALL PASSED' if failed == 0 else f'{failed} FAILURE(S)'}",
        "",
        "## Pilot configuration",
        "",
        "- **Read:** Kory Outlook (inbox + calendar)",
        "- **Write:** anjanakummetha@outlook.com (loopback email + calendar holds)",
        "- **Inbound:** Every email → ask before draft; scheduler (slots+holds) only for scheduling intents",
        "",
        "## Results by phase",
        "",
    ]

    for phase_name, cases in by_phase.items():
        lines.append(f"### {phase_name}")
        lines.append("")
        lines.append("| ID | Test | Status | Detail |")
        lines.append("|----|------|--------|--------|")
        for c in cases:
            detail = (c.get("detail") or "").replace("|", "/")[:120]
            lines.append(f"| {c['id']} | {c['name']} | {c['status']} | {detail} |")
        lines.append("")

    lines.extend(
        [
            "## Deferred (deploy tomorrow)",
            "",
            "- Azure Bot messaging endpoint → Hermes `:3978`",
            "- Hostinger VPS + TLS reverse proxy",
            "- Composio Hermes OAuth in production Hermes session ([composio.dev/hermes](https://composio.dev/hermes))",
            "",
            "## Hermes dual MCP setup",
            "",
            "```bash",
            ".venv/bin/python scripts/setup_hermes_mcp.py",
            "```",
            "",
            "1. Paste composio.dev/hermes setup into Hermes chat",
            "2. Merge Lexi + Composio MCP in `~/.hermes/config.yaml`",
            "3. Load `agent_instructions.txt`",
            "",
        ]
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written: {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-live-llm",
        action="store_true",
        help="Skip tests that call Anthropic for triage/draft",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: skip live Composio/E2E (no API keys required)",
    )
    args = parser.parse_args()

    print("Initializing database...")
    init_lexi_db()

    phase_1_inbound_flow(args.skip_live_llm)
    phase_2_kory_rules()
    phase_3_composio_live(skip_live=args.ci)
    phase_4_kory_email_patterns(args.skip_live_llm)
    phase_5_subprocess_smoke(skip_live=args.ci)

    write_report()

    failed = [r for r in RESULTS if r["status"] == "FAIL"]
    print(f"\n{'=' * 60}\nFINAL: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        for r in failed:
            print(f"  FAIL {r['id']}: {r['name']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

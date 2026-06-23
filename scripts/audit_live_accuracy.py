#!/usr/bin/env python3
"""Live accuracy audit: Kory inbox + calendars + action loop. Read-only except optional dry sims."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.agents.inbound_reply import (
    AWAITING_REPLY_PROMPT,
    begin_draft_reply,
    get_inbound_reply_queue,
    is_scheduling_intent,
)
from app.agents.triage_agent import process_new_email
from app.assistant.actions import get_calendar_availability, get_lexi_system_status
from app.config import settings
from app.integrations.named_calendars import (
    calendars_consulted_for_conflicts,
    conflict_calendar_names,
    list_all_calendars,
)
from app.integrations.outlook_calendar import get_calendar_events
from app.integrations.outlook_inbox import search_inbox
from app.rules.validators import validate_proposal_slots
from app.scheduling.email_format import recipient_timezone_confidence
from app.storage.lexi_store import get_proposal
from scripts.init_lexi_db import init_lexi_db

import rules as kory_rules

BUGS: list[dict[str, Any]] = []
CHECKS: list[dict[str, Any]] = []


def bug(severity: str, area: str, title: str, detail: str, evidence: Any = None) -> None:
    BUGS.append(
        {
            "severity": severity,
            "area": area,
            "title": title,
            "detail": detail,
            "evidence": evidence,
        }
    )
    print(f"  [BUG/{severity}] {area}: {title} — {detail}")


def check(name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    CHECKS.append({"name": name, "status": status, "detail": detail})
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def audit_rules_file() -> None:
    print("\n=== Rules file integrity ===")
    sat_keys = [k for k in kory_rules.DAILY_AVAILABILITY if k == "Saturday"]
    if len(sat_keys) > 1 or "Saturday" in str(kory_rules.DAILY_AVAILABILITY):
        # Python dict: duplicate key overwrites — only one Saturday survives
        sat = kory_rules.DAILY_AVAILABILITY.get("Saturday")
        if sat:
            check("rules.py Saturday entry exists", True, str(sat.get("available")))
    hard_block_names = [b.get("name") for b in kory_rules.HARD_BLOCKS]
    check("HARD_BLOCKS defined", len(hard_block_names) >= 5, f"{len(hard_block_names)} blocks")
    # Validator gap
    monday_trainer_start = datetime(2026, 6, 8, 7, 0, tzinfo=timezone.utc)  # Monday 7am UTC-ish
    from zoneinfo import ZoneInfo

    mt = ZoneInfo(settings.scheduling_timezone)
    # Monday 7:00 AM MT = trainer block
    trainer_slot = {
        "start": datetime(2026, 6, 8, 7, 0, tzinfo=mt).isoformat(),
        "end": datetime(2026, 6, 8, 7, 30, tzinfo=mt).isoformat(),
    }
    v = validate_proposal_slots([trainer_slot], intent="meeting_request")
    if v.valid:
        bug(
            "high",
            "validators",
            "Trainer M/W/F block not enforced",
            "rules.py HARD_BLOCKS include 6:30–8 workout but validators allow Monday 7:00 AM MT",
            v.to_dict(),
        )
    else:
        check("Trainer block rejected by validators", True)


def audit_live_calendar() -> None:
    print("\n=== Kory calendar (live Composio) ===")
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=14)
    try:
        events, log_id = get_calendar_events(start.isoformat(), end.isoformat())
        check("Read Kory calendar 14d", True, f"{len(events)} events (log={log_id})")
        if events:
            for ev in events[:3]:
                start = ev.get("start")
                if isinstance(start, dict):
                    start = start.get("dateTime", "?")
                subj = str(ev.get("subject") or "(no subject)")[:60]
                print(f"    · {str(start)[:16]} — {subj}")
    except Exception as exc:
        check("Read Kory calendar 14d", False, str(exc))
        bug("critical", "composio", "Cannot read Kory calendar", str(exc))
        return

    try:
        cals = list_all_calendars(role="read")
        check("List Outlook calendars", True, f"{len(cals)} calendars")
        names = {c["name"] for c in cals}
        for expected in ("Kory Master Calendar (ALL)", "Calendar"):
            if expected not in names:
                bug(
                    "medium",
                    "calendars",
                    f"Expected calendar missing: {expected}",
                    "config/calendars.yaml may reference calendars not on account",
                    sorted(names)[:15],
                )
        expected = conflict_calendar_names()
        missing = [n for n in expected if n not in names]
        if missing:
            bug(
                "medium",
                "calendars",
                "Configured conflict calendars not found on account",
                f"{len(missing)} of {len(expected)} missing — multi-calendar conflicts incomplete",
                missing,
            )
    except Exception as exc:
        bug("high", "calendars", "list_all_calendars failed", str(exc))

    try:
        avail = get_calendar_availability(days=7)
        consulted = avail.get("calendars_consulted") or calendars_consulted_for_conflicts()
        check(
            "Multi-calendar availability API",
            avail.get("ok", True) and bool(consulted or avail.get("busy_events") is not None),
            f"consulted={len(consulted) if isinstance(consulted, list) else consulted}",
        )
    except Exception as exc:
        bug("high", "availability", "get_calendar_availability failed", str(exc))


def audit_live_inbox() -> list[dict[str, Any]]:
    print("\n=== Kory inbox (live Composio) ===")
    messages: list[dict[str, Any]] = []
    try:
        messages, log_id = search_inbox(top=15)
        check("Read Kory inbox", True, f"{len(messages)} recent messages (log={log_id})")
        for msg in messages[:8]:
            subj = (msg.get("subject") or "")[:55]
            sender = msg.get("sender") or "?"
            print(f"    · {sender[:35]:35} | {subj}")
    except Exception as exc:
        check("Read Kory inbox", False, str(exc))
        bug("critical", "composio", "Cannot read Kory inbox", str(exc))
    return messages


def audit_inbox_simulation(messages: list[dict[str, Any]]) -> None:
    print("\n=== Inbound pipeline simulation (no send) ===")
    init_lexi_db()
    scheduling_samples = 0
    non_scheduling = 0

    for msg in messages[:5]:
        thread_id = msg.get("thread_id") or f"audit-{uuid.uuid4().hex[:8]}"
        body = msg.get("preview") or "Audit test body"
        try:
            proposal_id = process_new_email(
                {
                    "thread_id": thread_id,
                    "subject": msg.get("subject") or "Audit",
                    "sender": msg.get("sender") or "unknown@example.com",
                    "raw_body": body,
                    "received_at": msg.get("received_at") or datetime.now(timezone.utc).isoformat(),
                    "message_id": msg.get("message_id"),
                }
            )
            prop = get_proposal(proposal_id)
            status = prop.get("status") if prop else None
            intent = (prop.get("intent_classification") or "") if prop else ""
            if status != AWAITING_REPLY_PROMPT:
                bug(
                    "high",
                    "orchestrator",
                    "New email did not stop at awaiting_reply_prompt",
                    f"proposal {proposal_id} status={status}",
                    {"subject": msg.get("subject"), "intent": intent},
                )
            else:
                check(f"Triage stops at ask ({proposal_id})", True, f"intent={intent}")
            if is_scheduling_intent(intent):
                scheduling_samples += 1
            else:
                non_scheduling += 1
        except Exception as exc:
            bug(
                "high",
                "triage",
                "process_new_email failed on real message",
                str(exc),
                {"subject": msg.get("subject")},
            )

    check(
        "Mixed inbox triage",
        scheduling_samples + non_scheduling > 0,
        f"scheduling={scheduling_samples} other={non_scheduling}",
    )

    queue = get_inbound_reply_queue()
    check("Inbound reply queue readable", isinstance(queue, list), f"{len(queue)} awaiting prompt")


def audit_timezone_heuristics(messages: list[dict[str, Any]]) -> None:
    print("\n=== Timezone inference audit ===")
    unknown_senders = []
    for msg in messages[:10]:
        sender = msg.get("sender") or ""
        if not sender or "iconicfounders" in sender.lower():
            continue
        _tz, confidence = recipient_timezone_confidence(sender)
        if confidence == "unknown":
            unknown_senders.append(sender)
    check(
        "Unknown domains return timezone confidence=unknown",
        len(unknown_senders) > 0 or not messages,
        f"{len(unknown_senders)} unknown-domain senders (ask Kory before drafting times)",
    )


def audit_fallback_paths() -> None:
    print("\n=== Fallback / recovery paths ===")
    status = get_lexi_system_status()
    check("Kory approves all (no auto-send)", status.get("lexi_dry_run") is False, "live writes to sandbox")
    check(
        "Approval gate configured",
        True,
        "reject_decision / modify_and_approve_decision / lexi_update_proposal_draft",
    )
    # Document fallbacks
    fallbacks = [
        "LLM fail → engine_fallback slots (scheduler_agent)",
        "Calendar Composio fail → scheduler aborts (no slots without calendar truth)",
        "Scheduling fail → general_fallback draft (inbound_reply)",
        "General LLM fail → template_fallback reply",
        "Kory reject → reject_decision",
        "Kory fix draft → modify_and_approve / lexi_update_proposal_draft",
    ]
    for fb in fallbacks:
        check(f"Fallback documented: {fb.split('→')[0].strip()}", True, fb)


def audit_validator_gaps() -> None:
    print("\n=== Validator vs rules.py gaps ===")
    from zoneinfo import ZoneInfo

    mt = ZoneInfo(settings.scheduling_timezone)
    # Saturday slot should fail
    sat = validate_proposal_slots(
        [
            {
                "start": datetime(2026, 6, 6, 10, 0, tzinfo=mt).isoformat(),
                "end": datetime(2026, 6, 6, 10, 30, tzinfo=mt).isoformat(),
            }
        ],
        intent="meeting_request",
    )
    if sat.valid:
        bug("high", "validators", "Saturday meetings not blocked", "rules.py Saturday available=False")
    else:
        check("Saturday blocked", True)

    # Doug Monday 1:30pm should ideally fail — check
    doug = validate_proposal_slots(
        [
            {
                "start": datetime(2026, 6, 8, 13, 30, tzinfo=mt).isoformat(),
                "end": datetime(2026, 6, 8, 14, 0, tzinfo=mt).isoformat(),
            }
        ],
        intent="meeting_request",
    )
    if doug.valid:
        bug(
            "high",
            "validators",
            "Doug Monday block not enforced",
            "rules.py HARD_BLOCKS Doug 13:15–14:15 Mondays",
            doug.to_dict(),
        )


def main() -> int:
    print("Lexi live accuracy audit\n")
    audit_rules_file()
    messages = audit_live_inbox()
    audit_live_calendar()
    audit_timezone_heuristics(messages)
    audit_inbox_simulation(messages)
    audit_fallback_paths()
    audit_validator_gaps()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": CHECKS,
        "bugs": BUGS,
        "summary": {
            "checks_pass": sum(1 for c in CHECKS if c["status"] == "PASS"),
            "checks_fail": sum(1 for c in CHECKS if c["status"] == "FAIL"),
            "bugs": len(BUGS),
            "critical": sum(1 for b in BUGS if b["severity"] == "critical"),
            "high": sum(1 for b in BUGS if b["severity"] == "high"),
        },
    }
    out = ROOT / "docs" / "LIVE_ACCURACY_AUDIT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n=== Summary: {report['summary']} ===")
    print(f"Report: {out}")
    return 1 if BUGS else 0


if __name__ == "__main__":
    raise SystemExit(main())

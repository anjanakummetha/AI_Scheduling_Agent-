#!/usr/bin/env python3
"""Live scheduling scenario audit — cross-check proposed slots vs Master+work calendars."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import settings
from app.rules.validators import validate_proposal_slots
from app.scheduling.busy_intervals import (
    intervals_overlap,
    local_dt,
    parse_event_datetime,
    slot_conflicts_busy,
    slot_interval,
)
from app.scheduling.calendar_context import load_scheduling_calendar_context
from app.scheduling.calendar_intelligence import resolve_write_calendar_name
from app.scheduling.meeting_type import resolve_meeting_type
from app.scheduling.schedule_from_context import schedule_from_context
from app.scheduling.slot_engine import infer_meeting_format

import rules as kory_rules

MT = ZoneInfo(settings.scheduling_timezone)


@dataclass
class Scenario:
    id: str
    label: str
    subject: str
    body: str
    sender: str = "prospect@example.com"
    intent: str | None = None
    expect_ok: bool = True
    expect_inbound: bool = False
    notes: str = ""


SCENARIOS: list[Scenario] = [
    Scenario(
        id="intro_denver",
        label="30m virtual intro — Denver family office",
        subject="TEST — intro call — Denver family office",
        body=(
            "I'm with a Denver-based family office. Would you have 30 minutes "
            "sometime next week? Mornings work best."
        ),
        sender="bill.heermann@newportadvisors.co",
        intent="referral_or_intro",
    ),
    Scenario(
        id="intro_east_coast",
        label="30m intro — East Coast requester",
        subject="TEST — intro — NYC connection",
        body=(
            "Quick 30-minute intro on Teams next week? I'm on the East Coast — "
            "early morning your time works well."
        ),
        sender="braden@example.com",
        intent="referral_or_intro",
    ),
    Scenario(
        id="new_client_60",
        label="60m new client diligence",
        subject="TEST — Project Sierra diligence call",
        body="Can we schedule a 60-minute diligence call next week? Happy to do Teams.",
        sender="travis@portfolio.com",
        intent="new_client",
    ),
    Scenario(
        id="coffee_cherry_creek",
        label="Coffee Cherry Creek mornings",
        subject="TEST — coffee in Cherry Creek",
        body="Would love to grab coffee in Cherry Creek next week — mornings are best.",
        sender="jordan@evergreen.com",
        intent="coffee",
    ),
    Scenario(
        id="happy_hour",
        label="Happy hour intro",
        subject="TEST — happy hour intro",
        body="Could we do a happy hour intro next week? Afternoons work — Cherry Creek area.",
        sender="george@bokfinancial.com",
        intent="happy_hour",
    ),
    Scenario(
        id="dinner",
        label="Dinner meeting request",
        subject="TEST — dinner while you're in town",
        body="Any chance for a dinner meeting next week? Evening works — Cherry Creek preferred.",
        sender="michelle@example.com",
        intent="dinner",
        expect_ok=False,
        notes="Calendar has dinner cap filled every week in horizon — should escalate",
    ),
    Scenario(
        id="podcast",
        label="The Turn podcast recording",
        subject="TEST — The Turn podcast",
        body="Would Kory have 30 minutes to record an episode for The Turn next week?",
        sender="producer@podcast.com",
        intent="podcast",
    ),
    Scenario(
        id="inbound_specific_time",
        label="Inbound proposes specific time (should match or fall through)",
        subject="TEST — intro Tuesday 2pm MT",
        body=(
            "Would Tuesday at 2:00 PM Mountain work for a 30-minute Teams intro next week? "
            "If not, happy to hear other options."
        ),
        sender="kd@blooma.com",
        intent="referral_or_intro",
        expect_inbound=True,
    ),
    Scenario(
        id="inbound_bad_time",
        label="Inbound proposes time during known busy window",
        subject="TEST — intro Monday 1:30pm",
        body="Does Monday at 1:30 PM MT work for a quick 30-minute intro call?",
        sender="intro@firstbank.com",
        intent="referral_or_intro",
        expect_inbound=True,
        notes="Should reject Doug block or offer alternatives",
    ),
    Scenario(
        id="virtual_back_to_back",
        label="Virtual intro — must respect 2hr B2B cap",
        subject="TEST — intro after heavy meeting day",
        body="30-minute Teams intro next week — flexible on timing.",
        sender="ramzi@firstbank.com",
        intent="referral_or_intro",
    ),
    Scenario(
        id="lunch_exception",
        label="Lunch request (exception-only)",
        subject="TEST — lunch meeting request",
        body="Only time I can meet is lunch next Tuesday — 12:30 PM?",
        sender="client@example.com",
        intent="lunch",
        expect_ok=False,
        notes="Lunch blocked unless urgent/override",
    ),
    Scenario(
        id="after_six_virtual",
        label="After 6pm virtual only (should fail or find no valid 6:30 slots)",
        subject="TEST — evening intro",
        body="Could we do a 30-minute call at 6:30 PM MT next Thursday only?",
        sender="evening@example.com",
        intent="referral_or_intro",
        expect_ok=False,
        notes="6:30 PM violates 6 PM cutoff — should not offer valid slots",
    ),
]


@dataclass
class SlotVerdict:
    slot: dict[str, str]
    calendar_conflict: bool
    conflict_events: list[str] = field(default_factory=list)
    validator_ok: bool = True
    validator_violations: list[str] = field(default_factory=list)
    reserve_conflict: bool = False
    write_calendar: str = "Calendar"


@dataclass
class ScenarioResult:
    scenario: Scenario
    ok: bool
    path: str
    slots: list[dict[str, str]]
    slot_verdicts: list[SlotVerdict]
    failure_message: str = ""
    meeting_type: str = ""
    write_calendar: str = ""
    issues: list[str] = field(default_factory=list)
    draft_preview: str = ""


def _event_label(event: dict[str, Any]) -> str:
    subj = str(event.get("subject") or "(no subject)")[:50]
    start = parse_event_datetime(event.get("start"))
    if start:
        return f"{local_dt(start).strftime('%a %m/%d %H:%M')} {subj}"
    return subj


def _reserve_minutes(intent: str, subject: str, body: str) -> int:
    spec = resolve_meeting_type(intent=intent, subject=subject, body=body)
    return spec.calendar_block_minutes


def _offer_minutes(intent: str, subject: str, body: str) -> int:
    spec = resolve_meeting_type(intent=intent, subject=subject, body=body)
    return spec.duration_minutes


def verify_slots(
    slots: list[dict[str, str]],
    *,
    busy: list[dict[str, Any]],
    intent: str,
    subject: str,
    body: str,
) -> list[SlotVerdict]:
    fmt = infer_meeting_format(intent, subject=subject, body=body)
    reserve = _reserve_minutes(intent, subject, body)
    verdicts: list[SlotVerdict] = []
    write_cal = resolve_write_calendar_name(intent=intent)

    for slot in slots:
        conflict_events: list[str] = []
        interval = slot_interval(slot)
        if interval:
            s_start, s_end = interval
            check_end = s_end
            offer = int((s_end - s_start).total_seconds() // 60)
            if reserve > offer:
                check_end = s_start + timedelta(minutes=reserve)
            for event in busy:
                es = parse_event_datetime(event.get("start"))
                ee = parse_event_datetime(event.get("end"))
                if es and ee and intervals_overlap(s_start, check_end, es, ee):
                    conflict_events.append(_event_label(event))

        cal_conflict = bool(conflict_events) or slot_conflicts_busy(
            slot, busy, reserve_minutes=reserve
        )
        val = validate_proposal_slots(
            [slot],
            intent=intent,
            meeting_format=fmt,
            busy_events=busy,
            batch_slots=slots,
        )
        verdicts.append(
            SlotVerdict(
                slot=slot,
                calendar_conflict=cal_conflict,
                conflict_events=conflict_events,
                validator_ok=val.valid,
                validator_violations=list(val.violations),
                reserve_conflict=bool(conflict_events),
                write_calendar=write_cal,
            )
        )
    return verdicts


def run_scenario(scenario: Scenario, calendar_context: dict[str, Any]) -> ScenarioResult:
    result = schedule_from_context(
        subject=scenario.subject,
        body=scenario.body,
        intent=scenario.intent,
        sender_email=scenario.sender,
        use_llm_plan=False,
        try_inbound_availability=True,
        format_slots=True,
        calendar_context=calendar_context,
    )
    intent_key = (
        resolve_meeting_type(
            intent=scenario.intent,
            subject=scenario.subject,
            body=scenario.body,
        ).type_key
    )
    write_cal = resolve_write_calendar_name(intent=scenario.intent or intent_key)

    issues: list[str] = []
    if result.ok != scenario.expect_ok:
        issues.append(
            f"expected ok={scenario.expect_ok}, got ok={result.ok} ({result.status})"
        )

    if scenario.expect_ok and len(result.slots) < 2:
        issues.append(f"expected 2-3 slots, got {len(result.slots)}")

    verdicts = verify_slots(
        result.slots,
        busy=list(calendar_context.get("busy_events") or []),
        intent=intent_key,
        subject=scenario.subject,
        body=scenario.body,
    )

    for index, verdict in enumerate(verdicts, start=1):
        if verdict.calendar_conflict:
            issues.append(
                f"slot {index} overlaps calendar: {verdict.conflict_events[:2]}"
            )
        if not verdict.validator_ok:
            issues.append(
                f"slot {index} failed validators: {verdict.validator_violations[:2]}"
            )

    if scenario.expect_inbound and result.path == "inbound_availability" and result.ok:
        issues.append("used inbound_availability path (prospect time matched)")

    draft = ""
    if result.ok and result.formatted_slots:
        draft = "\n".join(result.formatted_slots[:3])

    return ScenarioResult(
        scenario=scenario,
        ok=result.ok and not any(v.calendar_conflict or not v.validator_ok for v in verdicts),
        path=result.path,
        slots=result.slots,
        slot_verdicts=verdicts,
        failure_message=result.failure_message or "",
        meeting_type=intent_key,
        write_calendar=write_cal,
        issues=issues,
        draft_preview=draft,
    )


def main() -> int:
    print("Loading calendar context (Master + work Calendar)...")
    calendar_context = load_scheduling_calendar_context()
    if calendar_context.get("status") != "available":
        print("FATAL: calendar unavailable", calendar_context.get("error"))
        return 1

    busy_count = len(calendar_context.get("busy_events") or [])
    print(
        f"Calendar OK — {busy_count} blocking events, "
        f"horizon {calendar_context.get('horizon_days')}d, "
        f"consulted: {calendar_context.get('calendars_consulted')}"
    )

    results: list[ScenarioResult] = []
    passed = 0
    failed = 0

    for scenario in SCENARIOS:
        print(f"\n{'='*72}\n[{scenario.id}] {scenario.label}\n{'='*72}")
        print(f"SUBJECT: {scenario.subject}")
        print(f"BODY: {scenario.body[:200]}{'...' if len(scenario.body) > 200 else ''}")
        print(f"SENDER: {scenario.sender}")

        sr = run_scenario(scenario, calendar_context)
        results.append(sr)

        print(f"\nRESULT: ok={sr.ok} path={sr.path} type={sr.meeting_type} write→{sr.write_calendar}")
        if sr.failure_message and not sr.slots:
            print(f"FAILURE: {sr.failure_message[:300]}")

        for i, verdict in enumerate(sr.slot_verdicts, start=1):
            interval = slot_interval(verdict.slot)
            if interval:
                s, e = interval
                label = f"{local_dt(s).strftime('%a %b %d %I:%M %p')}–{local_dt(e).strftime('%I:%M %p')} MT"
            else:
                label = str(verdict.slot)
            status = "OK" if not verdict.calendar_conflict and verdict.validator_ok else "BAD"
            print(f"  Slot {i} [{status}]: {label}")
            if verdict.conflict_events:
                print(f"    conflicts: {verdict.conflict_events[:3]}")
            if verdict.validator_violations:
                print(f"    violations: {verdict.validator_violations[:3]}")

        if sr.draft_preview:
            print(f"  Formatted: {sr.draft_preview[:120]}...")

        if sr.issues:
            print(f"  ISSUES: {sr.issues}")
            failed += 1
        else:
            passed += 1
            print("  PASS")

    report = {
        "generated_at": datetime.now(MT).isoformat(),
        "calendar": {
            "busy_events": busy_count,
            "horizon_days": calendar_context.get("horizon_days"),
            "calendars_consulted": calendar_context.get("calendars_consulted"),
        },
        "summary": {"passed": passed, "failed": failed, "total": len(SCENARIOS)},
        "scenarios": [
            {
                "id": r.scenario.id,
                "label": r.scenario.label,
                "subject": r.scenario.subject,
                "body": r.scenario.body,
                "sender": r.scenario.sender,
                "ok": r.ok,
                "path": r.path,
                "meeting_type": r.meeting_type,
                "write_calendar": r.write_calendar,
                "slots": r.slots,
                "issues": r.issues,
                "failure_message": r.failure_message,
                "slot_checks": [
                    {
                        "slot": v.slot,
                        "calendar_conflict": v.calendar_conflict,
                        "conflict_events": v.conflict_events,
                        "validator_ok": v.validator_ok,
                        "violations": v.validator_violations,
                    }
                    for v in r.slot_verdicts
                ],
            }
            for r in results
        ],
    }

    out = ROOT / "docs" / "SCHEDULING_SCENARIO_AUDIT.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n{'='*72}\nSUMMARY: {passed}/{len(SCENARIOS)} passed, {failed} failed")
    print(f"Report: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

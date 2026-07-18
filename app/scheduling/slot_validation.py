"""Batch slot validation against live calendar + Kory rules (chat-safe summaries)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.rules.validators import validate_proposal_slots
from app.scheduling.calendar_context import load_scheduling_calendar_context
from app.scheduling.meeting_type import resolve_meeting_type
from app.scheduling.slot_engine import infer_meeting_format

# Fixed UAT preset — server-side ISO times, no LLM guessing.
PRESET_CASES: dict[str, list[dict[str, Any]]] = {
    "july_slot_check": [
        {
            "label": "Coffee · Tue Jul 7 · 8:30 AM MT",
            "intent": "coffee",
            "start_iso": "2026-07-07T08:30:00-06:00",
            "meeting_format": "in_person",
        },
        {
            "label": "Coffee · Tue Jul 7 · 9:00 AM MT",
            "intent": "coffee",
            "start_iso": "2026-07-07T09:00:00-06:00",
            "meeting_format": "in_person",
        },
        {
            "label": "Happy hour · Fri Jul 10 · 4:00 PM MT",
            "intent": "happy_hour",
            "start_iso": "2026-07-10T16:00:00-06:00",
            "meeting_format": "in_person",
        },
        {
            "label": "Dinner · Thu Jul 9 · 7:00 PM MT",
            "intent": "dinner",
            "start_iso": "2026-07-09T19:00:00-06:00",
            "meeting_format": "in_person",
        },
        {
            "label": "Virtual intro · Sat Jul 11 · 10:00 AM MT",
            "intent": "referral_or_intro",
            "start_iso": "2026-07-11T10:00:00-06:00",
            "meeting_format": "virtual",
        },
    ],
}


def _slot_from_case(case: dict[str, Any]) -> dict[str, str]:
    intent = str(case.get("intent") or "unknown")
    spec = resolve_meeting_type(intent=intent)
    start_raw = str(case.get("start_iso") or "").strip()
    if not start_raw:
        raise ValueError(f"start_iso required for case: {case.get('label')}")
    start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
    duration = int(case.get("duration_minutes") or spec.duration_minutes)
    end = start + timedelta(minutes=duration)
    return {"start": start.isoformat(), "end": end.isoformat()}


def _horizon_for_cases(cases: list[dict[str, Any]]) -> int:
    latest: datetime | None = None
    for case in cases:
        slot = _slot_from_case(case)
        end = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        else:
            end = end.astimezone(timezone.utc)
        if latest is None or end > latest:
            latest = end
    if latest is None:
        return 14
    now_utc = datetime.now(timezone.utc)
    return max(7, min(settings.lexi_calendar_search_days_max, (latest - now_utc).days + 3))


def _plain_reason(violations: list[str], warnings: list[str]) -> str:
    parts: list[str] = []
    for text in violations + warnings:
        cleaned = text.strip()
        if "): " in cleaned:
            cleaned = cleaned.split("): ", 1)[1].strip()
        elif ": " in cleaned:
            cleaned = cleaned.rsplit(": ", 1)[-1].strip()
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    return "; ".join(parts[:3]) if parts else "Passes calendar and rule checks."


def validate_scheduling_cases(
    *,
    cases: list[dict[str, Any]] | None = None,
    preset: str = "",
) -> dict[str, Any]:
    """Validate each proposed slot; return formatted_summary for Hermes to relay."""
    preset_key = (preset or "").strip().lower()
    if preset_key:
        if preset_key not in PRESET_CASES:
            return {
                "ok": False,
                "error": f"Unknown preset '{preset}'. Available: {', '.join(sorted(PRESET_CASES))}",
            }
        case_list = [dict(c) for c in PRESET_CASES[preset_key]]
    else:
        case_list = [dict(c) for c in (cases or [])]

    if not case_list:
        return {"ok": False, "error": "Provide cases_json or a preset name."}

    horizon = _horizon_for_cases(case_list)
    calendar_context = load_scheduling_calendar_context(horizon_days=horizon)
    if calendar_context.get("status") != "available":
        detail = calendar_context.get("error") or "unavailable"
        return {"ok": False, "error": f"Calendar unavailable: {detail}"}

    busy = calendar_context.get("busy_events") or []
    rows: list[dict[str, Any]] = []
    lines: list[str] = ["Slot validation (live calendar + Kory rules):", ""]

    for index, case in enumerate(case_list, start=1):
        intent = str(case.get("intent") or "unknown")
        label = str(case.get("label") or f"Case {index}")
        fmt = str(case.get("meeting_format") or "").strip() or infer_meeting_format(
            intent, subject=label, body=label
        )
        slot = _slot_from_case(case)
        check = validate_proposal_slots(
            [slot],
            intent=intent,
            meeting_format=fmt,
            busy_events=busy,
        )
        status = "valid" if check.valid else "invalid"
        reason = _plain_reason(check.violations, check.warnings)
        rows.append(
            {
                "index": index,
                "label": label,
                "intent": intent,
                "meeting_format": fmt,
                "slot": slot,
                "valid": check.valid,
                "violations": check.violations,
                "warnings": check.warnings,
                "reason": reason,
            }
        )
        icon = "✅" if check.valid else "❌"
        lines.append(f"{index}. {label} — {icon} {status.upper()}")
        lines.append(f"   {reason}")
        lines.append("")

    valid_count = sum(1 for row in rows if row["valid"])
    lines.append(f"Summary: {valid_count}/{len(rows)} slots valid.")
    formatted = "\n".join(lines).strip()

    return {
        "ok": True,
        "preset": preset_key or None,
        "calendar_status": calendar_context.get("status"),
        "busy_event_count": len(busy),
        "results": rows,
        "valid_count": valid_count,
        "total_count": len(rows),
        "formatted_summary": formatted,
        "kory_chat": (
            "Reply using formatted_summary only. Do NOT re-validate in prose or change valid/invalid. "
            "Do NOT invent earliest-start rules; coffee at 8:30 AM Tue is allowed when the tool says valid."
        ),
    }

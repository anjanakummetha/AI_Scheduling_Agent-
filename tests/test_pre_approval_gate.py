"""Pre-approval gate — calendar fail-closed and validator integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.scheduling.pre_approval_gate import verify_before_kory_approval

MT = ZoneInfo("America/Denver")


def _slot(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    *,
    duration_min: int = 30,
) -> dict[str, str]:
    start = datetime(year, month, day, hour, minute, tzinfo=MT)
    end = start + timedelta(minutes=duration_min)
    return {"start": start.isoformat(), "end": end.isoformat()}


def _calendar(*, busy: list[dict] | None = None, status: str = "available") -> dict:
    return {
        "status": status,
        "busy_events": busy or [],
        "error": "composio timeout" if status != "available" else None,
    }


def test_blocks_when_calendar_unavailable() -> None:
    gate = verify_before_kory_approval(
        slots=[_slot(2026, 7, 7, 10, 0), _slot(2026, 7, 8, 10, 0)],
        calendar_context=_calendar(status="unavailable"),
        intent="referral_or_intro",
    )
    assert not gate.ok
    assert any("calendar unavailable" in c for c in gate.checks)


def test_blocks_insufficient_slots() -> None:
    gate = verify_before_kory_approval(
        slots=[_slot(2026, 7, 7, 10, 0)],
        calendar_context=_calendar(),
        intent="referral_or_intro",
    )
    assert not gate.ok
    assert any("at least 2 slots" in c for c in gate.checks)


def test_blocks_calendar_conflict() -> None:
    busy = [
        {
            "subject": "Existing call",
            "start": {"dateTime": "2026-07-07T10:00:00-06:00"},
            "end": {"dateTime": "2026-07-07T10:30:00-06:00"},
        }
    ]
    gate = verify_before_kory_approval(
        slots=[_slot(2026, 7, 7, 10, 0), _slot(2026, 7, 8, 10, 0)],
        calendar_context=_calendar(busy=busy),
        intent="referral_or_intro",
    )
    assert not gate.ok
    assert any("conflicts" in c for c in gate.checks)


def test_blocks_wrong_block_duration_for_coffee() -> None:
    gate = verify_before_kory_approval(
        slots=[_slot(2026, 7, 7, 10, 0, duration_min=30), _slot(2026, 7, 8, 10, 0, duration_min=30)],
        calendar_context=_calendar(),
        intent="coffee",
        subject="Coffee in Cherry Creek",
        body="Would love to grab coffee",
        meeting_format="in_person",
    )
    assert not gate.ok
    assert any("60 min" in c for c in gate.checks)


def test_passes_valid_coffee_slots() -> None:
    gate = verify_before_kory_approval(
        slots=[_slot(2026, 7, 9, 9, 0, duration_min=60), _slot(2026, 7, 10, 9, 30, duration_min=60)],
        calendar_context=_calendar(),
        intent="coffee",
        subject="Coffee in Cherry Creek",
        body="Would love to grab coffee",
        meeting_format="in_person",
    )
    assert gate.ok
    assert gate.meeting_type_key == "coffee"


def test_passes_valid_intro_slots() -> None:
    gate = verify_before_kory_approval(
        slots=[_slot(2026, 7, 7, 10, 0), _slot(2026, 7, 8, 11, 0)],
        calendar_context=_calendar(),
        intent="referral_or_intro",
        subject="TEST intro call",
        body="30-minute intro on Teams",
        meeting_format="virtual",
    )
    assert gate.ok
    assert gate.meeting_type_key == "referral_or_intro"
    assert gate.rules_passed
    assert gate.rules_status_line() == "Rules: pass"


def test_unavailable_calendars_never_shown_on_teams_line() -> None:
    gate = verify_before_kory_approval(
        slots=[_slot(2026, 7, 7, 10, 0), _slot(2026, 7, 8, 11, 0)],
        calendar_context={
            **_calendar(),
            "calendars_unavailable": [
                {"configured_name": "IFG Team"},
                {"configured_name": "Deal Activity"},
            ],
        },
        intent="referral_or_intro",
        subject="TEST intro call",
        body="30-minute intro on Teams",
        meeting_format="virtual",
    )
    assert gate.ok
    line = gate.rules_status_line()
    assert line == "Rules: pass"
    assert "Composio" not in line
    assert "IFG Team" not in line
    assert "Deal Activity" not in line


def test_rules_status_line_when_blocked() -> None:
    gate = verify_before_kory_approval(
        slots=[_slot(2026, 7, 7, 10, 0)],
        calendar_context=_calendar(),
        intent="referral_or_intro",
    )
    assert gate.rules_status_line().startswith("Rules: blocked")

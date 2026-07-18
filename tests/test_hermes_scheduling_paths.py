"""Tests for Heidi escalation, travel shift, outbound guard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.safety.outbound_guard import outbound_writes_allowed, teams_push_allowed
from app.scheduling.scheduling_window import SchedulingWindow, infer_scheduling_window
from app.scheduling.travel_window import shift_window_after_travel


MT = ZoneInfo("America/Denver")


def test_infer_two_weeks_window() -> None:
    window = infer_scheduling_window(
        subject="TEST",
        body="Can we meet in two weeks?",
        now=datetime(2026, 6, 10, 10, 0, tzinfo=MT),
    )
    assert window is not None
    assert window.label == "two weeks out"


def test_travel_shift_moves_window_after_trip() -> None:
    today = date(2026, 6, 10)
    window = SchedulingWindow(
        start=today,
        end=today + timedelta(days=6),
        source="body",
        label="next week",
    )
    busy = [
        {
            "subject": "Flight to Chicago",
            "start": datetime(2026, 6, 11, 8, 0, tzinfo=MT).isoformat(),
            "end": datetime(2026, 6, 11, 12, 0, tzinfo=MT).isoformat(),
            "blocking_class": "travel_blocking",
        },
        {
            "subject": "Stay at Hyatt Chicago",
            "start": datetime(2026, 6, 12, 0, 0, tzinfo=MT).isoformat(),
            "end": datetime(2026, 6, 14, 23, 59, tzinfo=MT).isoformat(),
        },
    ]
    shifted = shift_window_after_travel(window, busy, now=datetime(2026, 6, 10, 9, 0, tzinfo=MT))
    assert shifted is not None
    assert shifted.start > date(2026, 6, 14)
    assert "after travel" in shifted.label


@patch("app.safety.outbound_guard.settings")
def test_teams_suppressed_when_dry_run(mock_settings) -> None:
    mock_settings.lexi_dry_run = True
    mock_settings.lexi_teams_enabled = True
    mock_settings.lexi_suppress_teams_push = False
    assert outbound_writes_allowed() is False
    assert teams_push_allowed() is False


@patch("app.integrations.outlook_email.send_outbound_email")
def test_escalate_to_heidi_stages_when_dry_run(mock_send) -> None:
    from app.scheduling.heidi_escalation import compose_heidi_briefing

    briefing = compose_heidi_briefing(
        {
            "ok": True,
            "subject": "TEST — intro",
            "sender": "guest@example.com",
            "meeting_type_label": "Intro call",
            "latest_inbound_body": "Can we meet next week?",
            "scheduling_rules_summary": "30 minutes virtual",
        },
        failure_error="No slots next week",
    )
    assert "Anjana" in briefing
    assert "guest@example.com" in briefing
    assert "No slots" in briefing

"""Tests for batch slot validation (chat-safe summaries)."""

from __future__ import annotations

from unittest.mock import patch

from app.scheduling.slot_validation import PRESET_CASES, validate_scheduling_cases


def _fake_calendar():
    return {
        "status": "available",
        "busy_events": [
            {
                "start": "2026-07-07T10:00:00-06:00",
                "end": "2026-07-07T10:30:00-06:00",
                "subject": "Standup",
            },
            {
                "start": "2026-07-11T10:00:00-06:00",
                "end": "2026-07-11T11:00:00-06:00",
                "subject": "Family block",
            },
        ],
    }


@patch("app.scheduling.slot_validation.load_scheduling_calendar_context", return_value=_fake_calendar())
def test_july_preset_returns_formatted_summary(mock_load):
    result = validate_scheduling_cases(preset="july_slot_check")
    assert result["ok"] is True
    assert result["total_count"] == 5
    assert "formatted_summary" in result
    assert "Slot validation" in result["formatted_summary"]
    assert mock_load.called


@patch("app.scheduling.slot_validation.load_scheduling_calendar_context", return_value=_fake_calendar())
def test_july_preset_coffee_830_valid(mock_load):
    result = validate_scheduling_cases(preset="july_slot_check")
    coffee_830 = result["results"][0]
    assert coffee_830["label"].startswith("Coffee")
    assert "08:30" in coffee_830["slot"]["start"] or "8:30" in coffee_830["label"]


@patch("app.scheduling.slot_validation.load_scheduling_calendar_context", return_value=_fake_calendar())
def test_unknown_preset_errors(mock_load):
    result = validate_scheduling_cases(preset="not_a_preset")
    assert result["ok"] is False
    assert "Unknown preset" in result["error"]


def test_preset_cases_has_five_entries():
    assert len(PRESET_CASES["july_slot_check"]) == 5

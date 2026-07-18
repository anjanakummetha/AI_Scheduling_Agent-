"""Tests for canonical meeting-type resolution (Section A)."""

from __future__ import annotations

from app.scheduling.meeting_type import (
    calendar_block_minutes_for_context,
    infer_triage_intent_from_text,
    resolve_meeting_type,
)
from app.scheduling.slot_engine import find_valid_slots
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MT = ZoneInfo("America/Denver")


def test_intro_email_resolves_30_min_virtual():
    spec = resolve_meeting_type(
        intent="referral_or_intro",
        subject="TEST — Quick intro call next week",
        body="I'd love 30 minutes for a quick intro call on Teams.",
    )
    assert spec.type_key == "referral_or_intro"
    assert spec.duration_minutes == 30
    assert spec.calendar_block_minutes == 30


def test_diligence_email_resolves_60_min_new_client():
    spec = resolve_meeting_type(
        intent="pitch",
        subject="RE: diligence call — Project Sierra",
        body="Can we schedule a 60-minute diligence call next week?",
    )
    assert spec.type_key == "new_client"
    assert spec.duration_minutes == 60
    assert spec.calendar_block_minutes == 60


def test_coffee_uses_90_min_calendar_block():
    spec = resolve_meeting_type(
        intent="coffee",
        subject="Coffee in Cherry Creek",
        body="Would love coffee next week.",
    )
    assert spec.type_key == "coffee"
    assert spec.duration_minutes == 60
    assert spec.calendar_block_minutes == 90


def test_30_min_coffee_still_blocks_90():
    spec = resolve_meeting_type(
        intent="coffee",
        subject="30 min coffee",
        body="30 minutes for coffee next week.",
    )
    assert spec.type_key == "coffee"
    assert spec.calendar_block_minutes >= 90


def test_denver_family_office_email_requests_scheduling():
    from app.scheduling.meeting_type import email_requests_scheduling, effective_scheduling_intent

    subject = "TEST — intro call — Denver family office"
    body = (
        "I'm with a Denver-based family office. "
        "Would you have 30 minutes sometime next week? Mornings work best."
    )
    assert email_requests_scheduling(subject, body)
    assert effective_scheduling_intent("non_scheduling", subject=subject, body=body) == "referral_or_intro"


def test_intro_subject_wins_over_podcast_signature_in_body():
    spec = resolve_meeting_type(
        intent="referral_or_intro",
        subject="TEST — intro call — Denver family office",
        body=(
            "Would you have 30 minutes next week?\n\n"
            "Kory\nSee amazing founders who sold their businesses on my podcast The Turn"
        ),
    )
    assert spec.type_key == "referral_or_intro"
    assert spec.duration_minutes == 30


def test_generic_schedule_maps_to_intro_not_pitch():
    intent = infer_triage_intent_from_text(
        "Quick sync",
        "Can we find 30 minutes next week for a call?",
    )
    assert intent == "referral_or_intro"
    spec = resolve_meeting_type(intent=intent, subject="Quick sync", body="30 min call")
    assert spec.type_key == "referral_or_intro"


def test_podcast_intent():
    spec = resolve_meeting_type(
        intent="podcast",
        subject="The Turn podcast",
        body="Recording next week, 30 minutes.",
    )
    assert spec.type_key == "podcast"
    assert spec.duration_minutes == 30


def test_happy_hour_block():
    block = calendar_block_minutes_for_context(
        intent="happy_hour",
        subject="Happy hour next week",
        body="",
    )
    assert block == 90


def test_intro_slots_are_30_minutes():
    now = datetime(2026, 6, 23, 10, 0, tzinfo=MT)
    result = find_valid_slots(
        {
            "status": "available",
            "horizon_days": 21,
            "busy_events": [],
        },
        intent="referral_or_intro",
        subject="TEST intro",
        body="30-minute intro call next week",
        reference_now=now,
    )
    assert len(result.slots) >= 2
    for slot in result.slots:
        start = datetime.fromisoformat(slot["start"])
        end = datetime.fromisoformat(slot["end"])
        minutes = int((end - start).total_seconds() // 60)
        assert minutes == 30


def test_coffee_slots_are_60_minutes_with_90_reserve():
    result = find_valid_slots(
        {"status": "available", "horizon_days": 21, "busy_events": []},
        intent="coffee",
        subject="Coffee Cherry Creek",
        body="Coffee next week mornings",
    )
    if result.slots:
        start = datetime.fromisoformat(result.slots[0]["start"])
        end = datetime.fromisoformat(result.slots[0]["end"])
        assert int((end - start).total_seconds() // 60) == 60
        assert result.diagnostics.get("reserve_minutes") == 90


def test_doug_block_rejects_monday_130():
    from app.rules.validators import validate_proposal_slots

    slot = {
        "start": "2026-06-29T13:00:00-06:00",
        "end": "2026-06-29T13:30:00-06:00",
    }
    result = validate_proposal_slots(
        [slot],
        intent="referral_or_intro",
        meeting_format="virtual",
        busy_events=[],
    )
    assert not result.valid
    assert any("Doug" in v for v in result.violations)


def test_weekend_rejected():
    from app.rules.validators import validate_proposal_slots

    slot = {
        "start": "2026-06-27T10:00:00-06:00",
        "end": "2026-06-27T10:30:00-06:00",
    }
    result = validate_proposal_slots(
        [slot],
        intent="referral_or_intro",
        meeting_format="virtual",
        busy_events=[],
    )
    assert not result.valid

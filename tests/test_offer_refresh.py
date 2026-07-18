"""Tests for offer refresh and duration parsing."""

from __future__ import annotations

from app.scheduling.calendar_intelligence import (
    infer_duration_from_email,
    parse_duration_from_text,
    slot_duration_minutes,
)
from app.scheduling.offer_refresh import _draft_needs_repair, _stored_offer_is_valid


def test_parse_duration_variants():
    assert parse_duration_from_text("30-minute intro call") == 30
    assert parse_duration_from_text("40 minute meeting") == 40
    assert parse_duration_from_text("45 min sync") == 45
    assert parse_duration_from_text("half hour chat") == 30
    assert parse_duration_from_text("1 hour discussion") == 60
    assert parse_duration_from_text("90-minute diligence session") == 90


def test_infer_duration_email_text_overrides_pitch_default():
    duration = infer_duration_from_email(
        subject="Intro call",
        body="Could we do a 40-minute zoom?",
        intent="pitch",
        plan_duration_minutes=30,
    )
    assert duration == 40


def test_draft_needs_repair_for_stale_lexi_opening():
    slots = [
        {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T10:30:00-06:00"},
    ]
    draft = (
        "Hi — I'm Lexi, Kory's assistant.\n\n"
        "• Monday, June 29 at 10:00 AM–11:00 AM MT\n"
    )
    assert _draft_needs_repair(draft, slots, "lexi") is True


def test_stored_offer_invalid_when_slot_duration_wrong():
    proposal = {
        "proposed_slots": [
            {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T11:00:00-06:00"},
        ],
        "drafted_reply": "Hi Anju,\n\n• Monday, June 29 at 10:00 AM–11:00 AM MT",
        "intent_classification": "pitch",
        "voice_mode": "lexi",
    }
    email = {
        "subject": "TEST — 30-minute intro call next week",
        "raw_body": "Would love to connect.",
    }
    assert _stored_offer_is_valid(proposal, email) is False


def test_slot_duration_minutes():
    slot = {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T10:30:00-06:00"}
    assert slot_duration_minutes(slot) == 30

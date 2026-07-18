"""Slot line formatting — MT-only when timezone unknown."""

from __future__ import annotations

from app.scheduling.email_format import (
    format_offer_slot_block,
    format_slot_for_email,
    lexi_unknown_timezone_note,
    should_note_mt_only_timezone,
    should_use_us_equivalent_slot_format,
)
from app.scheduling.hermes_compose import _enforce_offered_times_block


def test_should_not_use_us_equivalents_anymore():
    assert not should_use_us_equivalent_slot_format(
        sender_email="prospect@gmail.com",
        uncertain=True,
    )
    assert not should_use_us_equivalent_slot_format(
        sender_email="anjana.kummetha@iconicfounders.com",
        uncertain=False,
        tz_confidence="inferred",
        tz_source="internal_default",
        intent="referral_or_intro",
        meeting_format="virtual",
    )


def test_should_note_mt_only_for_unknown_external():
    assert should_note_mt_only_timezone(
        sender_email="prospect@gmail.com",
        uncertain=True,
    )
    assert not should_note_mt_only_timezone(
        sender_email="anjana.kummetha@iconicfounders.com",
        uncertain=False,
        tz_confidence="known",
        tz_source="body",
    )


def test_mt_only_slot_line_has_no_us_parentheticals():
    from app.config import settings
    from zoneinfo import ZoneInfo

    slot = {
        "start": "2026-07-07T15:00:00+00:00",
        "end": "2026-07-07T15:30:00+00:00",
    }
    mt = ZoneInfo(settings.scheduling_timezone)
    line = format_slot_for_email(slot, recipient_tz=mt)
    assert "MT" in line
    assert "ET" not in line
    assert "CT" not in line
    assert "PT" not in line


def test_lexi_unknown_timezone_note():
    note = lexi_unknown_timezone_note(voice_mode="lexi")
    assert "couldn't identify your time zone" in note
    assert "Mountain Time" in note


def test_enforce_offered_times_block_replaces_bullets():
    draft = (
        "Hi Anju,\n\n"
        "Here are times:\n\n"
        "• Tuesday, July 7 at 9:00 AM–9:30 AM MT\n"
        "• Friday, July 10 at 9:00 AM–9:30 AM MT\n\n"
        "Thank you,\nLexi"
    )
    slot_block = format_offer_slot_block(
        [
            {"start": "2026-07-07T15:00:00+00:00", "end": "2026-07-07T15:30:00+00:00"},
            {"start": "2026-07-10T15:00:00+00:00", "end": "2026-07-10T15:30:00+00:00"},
        ],
        recipient_tz=__import__("zoneinfo").ZoneInfo("America/Denver"),
    )
    fixed = _enforce_offered_times_block(draft, slot_block)
    assert "11:00 AM" not in fixed
    assert "• Tuesday" in fixed
    assert "MT" in fixed

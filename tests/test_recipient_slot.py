"""Tests for parsing recipient slot choices from reply emails."""

from app.scheduling.recipient_slot import match_recipient_slot_choice

SLOTS = [
    {
        "start": "2026-06-17T16:00:00-04:00",
        "end": "2026-06-17T16:30:00-04:00",
    },
    {
        "start": "2026-06-18T17:00:00-04:00",
        "end": "2026-06-18T17:30:00-04:00",
    },
    {
        "start": "2026-06-19T15:00:00-04:00",
        "end": "2026-06-19T15:30:00-04:00",
    },
]


def test_option_2_picks_second_slot():
    chosen = match_recipient_slot_choice("Option 2 works for me — thanks!", SLOTS)
    assert chosen == SLOTS[1]


def test_weekday_picks_matching_slot():
    chosen = match_recipient_slot_choice("Wednesday at 4 works great.", SLOTS)
    assert chosen == SLOTS[0]


def test_monday_time_with_quoted_offer_body():
    slots = [
        {"start": "2026-07-01T11:00:00-06:00", "end": "2026-07-01T11:30:00-06:00"},
        {"start": "2026-06-29T16:00:00-06:00", "end": "2026-06-29T16:30:00-06:00"},
        {"start": "2026-06-30T14:00:00-06:00", "end": "2026-06-30T14:30:00-06:00"},
    ]
    body = (
        "I can do Monday 4:00 PM. Thanks.\n"
        "________________________________\n"
        "From: Lexi <lexi@iconicfounders.com>\n"
        "• Wednesday, July 1 at 11:00 AM–11:30 AM MT\n"
        "• Monday, June 29 at 4:00 PM–4:30 PM MT\n"
    )
    chosen = match_recipient_slot_choice(body, slots)
    assert chosen == slots[1]


def test_unrecognized_returns_none():
    assert match_recipient_slot_choice("Still checking with my team.", SLOTS) is None


def test_recipient_times_rejected():
    from app.scheduling.recipient_slot import recipient_times_rejected

    assert recipient_times_rejected("None of those times work for me unfortunately.") is True
    assert recipient_times_rejected("Option 2 works great.") is False

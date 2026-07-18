"""Tests for calendar title formatting."""

from zoneinfo import ZoneInfo

from app.scheduling.calendar_title import (
    build_confirmed_calendar_title,
    build_hold_calendar_title,
    parse_guest_profile,
)


def test_hold_podcast_example():
    guest = parse_guest_profile(
        sender="Anthony Garcia <guest@example.com>",
        subject="Podcast guest",
        body="guest on The Turn",
    )
    title = build_hold_calendar_title(
        intent="podcast",
        guest=guest,
        subject="Podcast guest",
        body="The Turn",
    )
    assert title == "HOLD: Intro call w/ Anthony Garcia (podcast guest)"


def test_confirmed_braden_no_company_pipe_time():
    guest = parse_guest_profile(sender="Braden Edwards <braden@example.com>")
    title = build_confirmed_calendar_title(
        intent="referral_or_intro",
        guest=guest,
        slot_start="2026-06-17T15:30:00-04:00",
        recipient_timezone=ZoneInfo("America/New_York"),
    )
    assert "Intro: Braden Edwards <> Kory Mitchell (IFG) |" in title
    assert "ET" in title

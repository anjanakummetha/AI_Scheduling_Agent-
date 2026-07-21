"""Weekly protection self-audit (plan Phase 2)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.jobs.protection_audit import audit_upcoming_protection, format_digest

MT = ZoneInfo("America/Denver")


def _ev(subject: str, day: str, start: str, end: str) -> dict:
    return {
        "subject": subject,
        "start": {"dateTime": f"{day}T{start}:00", "timeZone": "America/Denver"},
        "end": {"dateTime": f"{day}T{end}:00", "timeZone": "America/Denver"},
        "showAs": "busy",
    }


# Monday 2026-07-20 anchors the horizon.
NOW = datetime(2026, 7, 20, 6, 0, tzinfo=MT)


def test_matched_protected_counted():
    events = [_ev("KM Personal Training Session", "2026-07-20", "06:30", "08:00")]
    report = audit_upcoming_protection(events, NOW, horizon_days=1)
    assert report.matched_protected == 1


def test_expected_trainer_missing_flagged():
    # No trainer event on this Monday → expected-missing for the trainer block.
    report = audit_upcoming_protection([], NOW, horizon_days=1)
    names = {m["name"] for m in report.expected_missing}
    assert "Trainer Workout" in names


def test_present_recurring_blocks_not_flagged():
    # Both of Monday's timed blocks present → neither flagged missing.
    events = [
        _ev("KM Personal Training Session", "2026-07-20", "06:30", "08:00"),
        _ev("Doug", "2026-07-20", "13:15", "14:15"),
    ]
    report = audit_upcoming_protection(events, NOW, horizon_days=1)
    assert report.clean, report.expected_missing


def test_renamed_block_still_counts_as_present():
    # The conservative classifier blocks a renamed trainer event, so an
    # overlapping event keeps the window from being flagged missing.
    events = [
        _ev("Gym w/ Danny", "2026-07-20", "06:30", "08:00"),
        _ev("Doug 1:1", "2026-07-20", "13:15", "14:15"),
    ]
    report = audit_upcoming_protection(events, NOW, horizon_days=1)
    trainer = [m for m in report.expected_missing if m["name"] == "Trainer Workout"]
    assert not trainer


def test_digest_empty_when_clean():
    events = [
        _ev("KM Personal Training Session", "2026-07-20", "06:30", "08:00"),
        _ev("Doug", "2026-07-20", "13:15", "14:15"),
    ]
    report = audit_upcoming_protection(events, NOW, horizon_days=1)
    assert format_digest(report) == ""


def test_digest_names_missing_block():
    report = audit_upcoming_protection([], NOW, horizon_days=1)
    digest = format_digest(report)
    assert "Trainer Workout" in digest

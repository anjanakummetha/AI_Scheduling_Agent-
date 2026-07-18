"""Tests for strict hold placement."""

from unittest.mock import patch

import pytest

from app.integrations.hold_placement import HoldPlacementError, place_offered_holds


def test_place_offered_holds_requires_all_slots():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE holds (
            id INTEGER PRIMARY KEY,
            proposal_id INTEGER,
            event_id TEXT,
            slot_start TEXT,
            slot_end TEXT,
            expires_at TEXT
        )
        """
    )
    slots = [
        {"start": "2026-06-17T16:00:00-04:00", "end": "2026-06-17T16:30:00-04:00"},
        {"start": "2026-06-18T17:00:00-04:00", "end": "2026-06-18T17:30:00-04:00"},
    ]
    with patch("app.integrations.hold_placement.settings") as mock_settings:
        mock_settings.lexi_dry_run = True
        count = place_offered_holds(
            conn,
            proposal_id=1,
            slots=slots,
            intent_classification="virtual_30",
            meeting_subject="Test meeting",
        )
    assert count == 2
    rows = conn.execute("SELECT COUNT(*) FROM holds").fetchone()[0]
    assert rows == 2


def test_place_offered_holds_raises_on_conflict():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE holds (
            id INTEGER PRIMARY KEY,
            proposal_id INTEGER,
            event_id TEXT,
            slot_start TEXT,
            slot_end TEXT,
            expires_at TEXT
        )
        """
    )
    slots = [
        {"start": "2026-06-17T16:00:00-04:00", "end": "2026-06-17T16:30:00-04:00"},
        {"start": "2026-06-18T17:00:00-04:00", "end": "2026-06-18T17:30:00-04:00"},
    ]

    def fake_hold(*, action, calendar_name=None):
        if "option 2" in action.get("title", ""):
            return {"ok": False, "error": "conflict", "conflicting_events": ["busy"]}
        return {"ok": True, "event_id": "evt-1"}

    with patch("app.integrations.hold_placement.settings") as mock_settings:
        mock_settings.lexi_dry_run = False
        with patch("app.integrations.hold_placement.place_tentative_hold", side_effect=fake_hold):
            with pytest.raises(HoldPlacementError):
                place_offered_holds(
                    conn,
                    proposal_id=1,
                    slots=slots,
                    intent_classification="virtual_30",
                )

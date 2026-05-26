"""Unit tests for rules-first scheduling engine."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.rules.availability_engine import find_legal_slots, slot_key
from app.rules.classifier import classify_email
from app.rules.policy_engine import build_scheduling_decision

TZ = ZoneInfo("America/Denver")


class SchedulingEngineTests(unittest.TestCase):
    def test_classify_new_client(self) -> None:
        email = {
            "sender_email": "prospect@example.com",
            "subject": "New client intro",
            "body": "We are a prospective client and need 60 minutes this week.",
        }
        result = classify_email(email)
        self.assertEqual(result["meeting_type"], "new_client")
        self.assertTrue(result["should_offer_times"])

    def test_classify_vague_connect(self) -> None:
        email = {
            "sender_email": "friend@example.com",
            "subject": "Catch up",
            "body": "Would love to connect sometime.",
        }
        result = classify_email(email)
        self.assertFalse(result["should_offer_times"])

    def test_availability_respects_workout_block(self) -> None:
        anchor = datetime(2026, 5, 4, 12, 0, tzinfo=TZ)  # Monday
        busy = [
            {
                "subject": "KM Personal Training",
                "start": {"dateTime": "2026-05-04T06:30:00"},
                "end": {"dateTime": "2026-05-04T08:00:00"},
                "showAs": "busy",
                "isCancelled": False,
            }
        ]
        slots = find_legal_slots(
            meeting_type="referral_or_intro",
            meeting_format="in_person",
            busy_events=busy,
            anchor=anchor,
        )
        for slot in slots:
            start = datetime.fromisoformat(slot["start"]).astimezone(TZ)
            if start.date().isoformat() == "2026-05-04":
                self.assertGreaterEqual(start.hour * 60 + start.minute, 9 * 60 + 30)

    def test_policy_selects_two_or_three_slots(self) -> None:
        email = {
            "sender_email": "joe@example.com",
            "sender_name": "Joe",
            "subject": "Teams meeting",
            "body": "Can we find 30 minutes next week for a Teams call?",
        }
        decision = build_scheduling_decision(email, {"status": "available", "busy_events": []})
        self.assertGreaterEqual(len(decision["proposed_slots"]), 2)
        self.assertLessEqual(len(decision["proposed_slots"]), 3)

    def test_policy_creates_holds_for_new_client(self) -> None:
        email = {
            "sender_email": "prospect@example.com",
            "sender_name": "Prospect",
            "subject": "Intro",
            "body": "We are a new client and need time this week.",
        }
        decision = build_scheduling_decision(email, {"status": "available", "busy_events": []})
        self.assertEqual(decision["calendar_action"]["type"], "create_holds")
        self.assertGreaterEqual(len(decision["calendar_action"].get("holds", [])), 2)

    def test_slot_keys_unique(self) -> None:
        slots = [
            {
                "start": "2026-05-10T10:00:00",
                "end": "2026-05-10T10:30:00",
                "timezone": "America/Denver",
            },
            {
                "start": "2026-05-10T10:00:00",
                "end": "2026-05-10T10:30:00",
                "timezone": "America/Denver",
            },
        ]
        self.assertEqual(len({slot_key(slot) for slot in slots}), 1)


if __name__ == "__main__":
    unittest.main()

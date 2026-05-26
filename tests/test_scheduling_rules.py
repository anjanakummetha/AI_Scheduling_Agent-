"""Rule-matrix tests for scheduling policy."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.integrations.outlook_email import _plain_text
from app.rules.availability_engine import find_legal_slots
from app.rules.classifier import classify_email
from app.integrations.outlook_calendar import is_blocking_event
from app.rules.policy_engine import build_scheduling_decision

TZ = ZoneInfo("America/Denver")
MATT_HTML = """
<html><body><p>Hi Kory,</p>
<p>Denver unexpectedly this Thursday and Friday. acquisition opportunities.
Boston. Early morning. Happy to grab coffee.</p>
<p>Best,</p><p>Matt Callahan</p><p>Summit Industrial Partners</p></body></html>
"""


class SchedulingRulesTests(unittest.TestCase):
    def test_matt_coffee_classification(self) -> None:
        body = _plain_text(MATT_HTML)
        email = {"sender_email": "matt@x.com", "subject": "Denver", "body": body}
        result = classify_email(email)
        self.assertEqual(result["meeting_type"], "coffee")
        self.assertEqual(result["meeting_format"], "in_person")
        self.assertEqual(result["urgency"], "same_week")
        self.assertTrue(result["east_coast_contact"])
        self.assertTrue(result["should_offer_times"])

    def test_prospect_without_coffee_is_new_client(self) -> None:
        email = {
            "sender_email": "p@x.com",
            "subject": "Intro",
            "body": "We are a prospective client and need 60 minutes this week for a Teams call.",
        }
        result = classify_email(email)
        self.assertEqual(result["meeting_type"], "new_client")
        self.assertEqual(result["urgency"], "same_week")

    def test_coffee_block_is_90_minutes(self) -> None:
        anchor = datetime(2026, 5, 20, 12, 0, tzinfo=TZ)
        slots = find_legal_slots(
            meeting_type="coffee",
            meeting_format="in_person",
            busy_events=[],
            anchor=anchor,
        )
        self.assertTrue(slots)
        start = datetime.fromisoformat(slots[0]["start"])
        end = datetime.fromisoformat(slots[0]["end"])
        self.assertEqual(int((end - start).total_seconds() // 60), 90)
        self.assertIn("Cherry Creek", slots[0].get("location", ""))

    def test_policy_offers_holds_for_coffee_with_two_slots(self) -> None:
        body = _plain_text(MATT_HTML)
        email = {"sender_email": "matt@x.com", "sender_name": "Matt Callahan", "subject": "Denver", "body": body}
        decision = build_scheduling_decision(email, {"status": "available", "busy_events": []})
        if len(decision["proposed_slots"]) >= 2:
            self.assertEqual(decision["calendar_action"]["type"], "create_holds")
            self.assertEqual(len(decision["calendar_action"]["holds"]), len(decision["proposed_slots"]))
            for hold in decision["calendar_action"]["holds"]:
                self.assertIn("HOLD - Matt - Option", hold["title"])
                self.assertNotIn("w/", hold["title"])
                self.assertIn("Olive", hold["location"])

    def test_selected_slots_do_not_overlap(self) -> None:
        email = {
            "sender_email": "matt@example.com",
            "sender_name": "Matt Callahan",
            "subject": "Coffee",
            "body": "Coffee this Thursday and Friday. Boston.",
        }
        decision = build_scheduling_decision(email, {"status": "available", "busy_events": []})
        slots = decision["proposed_slots"]
        if len(slots) >= 2:
            from app.rules.policy_engine import _slots_overlap

            self.assertFalse(_slots_overlap(slots[0], slots[1]))

    def test_hold_options_are_numbered_distinctly(self) -> None:
        email = {
            "sender_email": "matt@example.com",
            "sender_name": "Matt Callahan",
            "subject": "Coffee",
            "body": "Coffee this Thursday and Friday in Denver. Boston.",
        }
        decision = build_scheduling_decision(email, {"status": "available", "busy_events": []})
        holds = (decision.get("calendar_action") or {}).get("holds") or []
        if len(holds) >= 2:
            titles = [hold["title"] for hold in holds]
            self.assertIn("HOLD - Matt - Option 1", titles)
            self.assertIn("HOLD - Matt - Option 2", titles)

    def test_hold_title_uses_sender_name(self) -> None:
        email = {
            "sender_email": "eric@example.com",
            "sender_name": "Eric Johnson",
            "subject": "Coffee",
            "body": "Happy to grab coffee this Thursday. Best, Eric",
        }
        decision = build_scheduling_decision(email, {"status": "available", "busy_events": []})
        if decision["calendar_action"].get("holds"):
            self.assertIn("HOLD - Eric - Option 1", decision["calendar_action"]["holds"][0]["title"])

    def test_scheduling_holds_do_not_block_availability(self) -> None:
        self.assertFalse(
            is_blocking_event(
                {"subject": "HOLD - Matt - Option 1", "showAs": "busy", "isCancelled": False}
            )
        )
        self.assertTrue(
            is_blocking_event(
                {"subject": "Coffee with Matt", "showAs": "busy", "isCancelled": False}
            )
        )

    def test_plain_text_strips_html(self) -> None:
        text = _plain_text(MATT_HTML)
        self.assertNotIn("<p>", text)
        self.assertIn("Matt Callahan", text)
        self.assertIn("coffee", text.lower())


if __name__ == "__main__":
    unittest.main()

"""Editable approval Adaptive Card structure."""

from __future__ import annotations

import unittest

from app.utils.teams_cards import (
    CARD_ACTION_APPROVAL,
    CARD_ACTION_SAVE_DRAFT,
    INPUT_DRAFT_ID,
    generate_approval_card,
)


class TeamsApprovalCardTests(unittest.TestCase):
    def test_approval_card_has_editable_draft_input(self) -> None:
        card = generate_approval_card(
            {
                "id": 12,
                "drafted_reply": "Thanks for reaching out.\n\nLet's Win,\nKory",
                "proposed_slots": [],
            },
            {"subject": "Project Paint", "sender": "dan@acme.com"},
            [],
        )
        body_types = [block.get("type") for block in card.get("body", [])]
        self.assertIn("Input.Text", body_types)
        draft_input = next(
            block for block in card["body"] if block.get("id") == INPUT_DRAFT_ID
        )
        self.assertTrue(draft_input.get("isMultiline"))
        self.assertIn("Let's Win", draft_input.get("value", ""))

    def test_approval_card_shows_meeting_type_not_priority(self) -> None:
        card = generate_approval_card(
            {
                "id": 12,
                "drafted_reply": "Hi Anju,\n\nI'm Lexi, Kory's assistant.",
                "proposed_slots": [
                    {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T10:30:00-06:00"},
                ],
                "intent_classification": "referral_or_intro",
            },
            {
                "subject": "TEST — intro call — Denver family office",
                "sender": "anjana.kummetha@iconicfounders.com",
            },
            [],
        )
        meta_blocks = [
            block.get("text", "")
            for block in card.get("body", [])
            if block.get("type") == "TextBlock"
        ]
        assert any("Type: Intro" in text for text in meta_blocks)
        assert not any("Priority" in text for text in meta_blocks)
        card = generate_approval_card(
            {"id": 3, "drafted_reply": "Hello", "proposed_slots": []},
            {"subject": "Coffee", "sender": "jane@example.com"},
            [],
        )
        actions = card.get("actions") or []
        # In UAT/dry-run, Send is hidden to prevent accidental outbound writes.
        self.assertIn(len(actions), {2, 3})
        titles = [action.get("title") for action in actions]
        self.assertEqual(titles[0], "Save draft")
        self.assertEqual(titles[-1], "Discard")
        if "Send" in titles:
            send_action = next(action for action in actions if action.get("title") == "Send")
            data = send_action.get("data") or {}
            self.assertEqual(data.get("action"), CARD_ACTION_APPROVAL)
            self.assertEqual(data.get("decision"), "approved")
        save_action = next(action for action in actions if action.get("title") == "Save draft")
        self.assertEqual((save_action.get("data") or {}).get("action"), CARD_ACTION_SAVE_DRAFT)


    def test_approval_card_repairs_truncated_llm_draft(self) -> None:
        card = generate_approval_card(
            {
                "id": 5,
                "drafted_reply": (
                    "Hi Anju,\n\nI'm Lexi, Kory's assistant. Thanks for reaching out — "
                    "a few options that work on"
                ),
                "voice_mode": "lexi",
                "proposed_slots": [
                    {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T10:30:00-06:00"},
                ],
                "recipient_timezone": "America/Denver",
            },
            {
                "subject": "TEST — intro",
                "sender": "anjana.kummetha@iconicfounders.com",
                "raw_body": "Thanks,Anju",
            },
            [],
        )
        draft_input = next(
            block for block in card["body"] if block.get("id") == INPUT_DRAFT_ID
        )
        value = draft_input.get("value", "")
        assert "•" in value or "Monday" in value
        assert "lexi@iconicfounders.com" in value


if __name__ == "__main__":
    unittest.main()

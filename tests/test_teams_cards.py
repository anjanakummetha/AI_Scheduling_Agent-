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

    def test_approval_card_actions_use_submit(self) -> None:
        card = generate_approval_card(
            {"id": 3, "drafted_reply": "Hello", "proposed_slots": []},
            {"subject": "Coffee", "sender": "jane@example.com"},
            [],
        )
        actions = card.get("actions") or []
        self.assertEqual(len(actions), 3)
        titles = [action.get("title") for action in actions]
        self.assertEqual(titles, ["Save draft", "Send", "Discard"])
        send_action = next(action for action in actions if action.get("title") == "Send")
        data = send_action.get("data") or {}
        self.assertEqual(data.get("action"), CARD_ACTION_APPROVAL)
        self.assertEqual(data.get("decision"), "approved")
        save_action = next(action for action in actions if action.get("title") == "Save draft")
        self.assertEqual((save_action.get("data") or {}).get("action"), CARD_ACTION_SAVE_DRAFT)


if __name__ == "__main__":
    unittest.main()

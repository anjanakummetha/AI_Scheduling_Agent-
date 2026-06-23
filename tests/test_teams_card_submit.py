"""Card submit handler for editable drafts."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.teams.commands import handle_teams_card_submit
from app.utils.teams_cards import CARD_ACTION_APPROVAL, CARD_ACTION_SAVE_DRAFT, INPUT_DRAFT_ID


class TeamsCardSubmitTests(unittest.TestCase):
    @patch("app.teams.commands._fetch_bundle")
    @patch("app.agents.inbound_reply.update_proposal_draft")
    def test_save_draft_from_card(self, mock_update, mock_bundle) -> None:
        mock_bundle.return_value = {"subject": "Paint", "sender": "dan@acme.com"}
        mock_update.return_value = {"ok": True, "proposal_id": 5}

        result = handle_teams_card_submit(
            {
                "action": CARD_ACTION_SAVE_DRAFT,
                "proposal_id": 5,
                INPUT_DRAFT_ID: "Updated body\n\nLet's Win,\nKory",
            }
        )
        self.assertTrue(result["ok"])
        self.assertIn("Saved draft", result["message"])
        mock_update.assert_called_once()

    @patch("app.teams.commands._run_approval")
    @patch("app.teams.commands._fetch_bundle")
    @patch("app.agents.inbound_reply.update_proposal_draft")
    def test_send_applies_edited_draft_first(
        self,
        mock_update,
        mock_bundle,
        mock_run,
    ) -> None:
        mock_bundle.return_value = {"subject": "Paint", "sender": "dan@acme.com"}
        mock_update.return_value = {"ok": True, "proposal_id": 5}
        mock_run.return_value = {"ok": True, "handled": True, "message": "sent"}

        result = handle_teams_card_submit(
            {
                "action": CARD_ACTION_APPROVAL,
                "decision": "approved",
                "proposal_id": 5,
                INPUT_DRAFT_ID: "Edited before send",
                "selected_slot": "",
            }
        )
        self.assertTrue(result["ok"])
        mock_update.assert_called_once()
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()

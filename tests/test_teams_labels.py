"""Teams human-readable command tokens."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.bot.teams_labels import (
    email_thread_label,
    format_discard_token,
    format_draft_no_token,
    format_draft_yes_token,
    format_send_token,
    parse_human_teams_command,
)
from app.bot.teams_text import parse_teams_command


class TeamsLabelsTests(unittest.TestCase):
    def test_token_round_trip(self) -> None:
        subject = "Project Paint diligence"
        sender = "dan.smith@acme.com"
        yes_token = format_draft_yes_token(subject=subject, sender=sender)
        self.assertIn("Dan Smith", yes_token)
        self.assertIn("Project Paint", yes_token)
        self.assertNotIn("draft 12", yes_token.lower())

        parsed = parse_human_teams_command(yes_token)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["action"], "draft_yes")
        self.assertIn("paint", parsed["subject"].lower())

    def test_send_and_discard_tokens(self) -> None:
        send = format_send_token(subject="Coffee next week", sender="Jane Doe")
        discard = format_discard_token(subject="Coffee next week", sender="Jane Doe")
        self.assertTrue(send.startswith("Send reply to "))
        self.assertTrue(discard.startswith("Discard draft for "))

    def test_parse_teams_command_human_send(self) -> None:
        token = format_send_token(subject="Term sheet", sender="investor@fund.com")
        with patch(
            "app.bot.teams_labels.resolve_proposal_id",
            return_value=7,
        ):
            cmd = parse_teams_command(token)
        self.assertIsNotNone(cmd)
        assert cmd is not None
        self.assertEqual(cmd["action"], "approve")
        self.assertEqual(cmd["proposal_id"], 7)

    def test_email_thread_label(self) -> None:
        label = email_thread_label(subject="Re: Dinner", sender="kory@ifg.com")
        self.assertIn("—", label)
        self.assertNotIn("#", label)

    def test_skip_token_action(self) -> None:
        token = format_draft_no_token(subject="Weekly digest", sender="news@ypo.org")
        parsed = parse_human_teams_command(token)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["action"], "draft_no")


if __name__ == "__main__":
    unittest.main()

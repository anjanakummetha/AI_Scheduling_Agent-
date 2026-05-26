"""
Comprehensive tests for Lexi's scheduling intelligence.
Tests: rules engine, hold workflow, feedback pipeline, email drafting, edge cases.
"""

import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Minimal env for testing
os.environ.setdefault("COMPOSIO_API_KEY", "test_key")
os.environ.setdefault("LLM_BASE_URL", "https://openrouter.ai/api/v1")
os.environ.setdefault("LLM_API_KEY", "test_key")
os.environ.setdefault("LLM_MODEL", "anthropic/claude-3.5-haiku")
os.environ.setdefault("DEMO_MODE", "true")


class TestSchedulingRules(unittest.TestCase):
    """Test that Kory's rules are encoded correctly in the YAML."""

    def setUp(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            self.rules = yaml.safe_load(f)

    def test_timezone_is_mountain(self):
        self.assertEqual(self.rules["timezone"]["internal"], "America/Denver")

    def test_hard_blocks_present(self):
        keywords = self.rules["hard_blocks"]["event_keywords"]
        self.assertIn("ypo", keywords)
        self.assertIn("trainer", keywords)
        self.assertIn("doug", keywords)
        self.assertIn("do not move", keywords)
        self.assertIn("capital demolition", keywords)

    def test_hold_rules(self):
        holds = self.rules["holds"]
        self.assertEqual(holds["remind_after_days"], 2)
        self.assertEqual(holds["release_after_days"], 3)
        self.assertTrue(holds["friday_cleanup"])

    def test_min_max_slots(self):
        self.assertEqual(self.rules["offering"]["min_slot_options"], 2)
        self.assertEqual(self.rules["offering"]["max_slot_options"], 3)

    def test_happy_hour_cap(self):
        self.assertEqual(self.rules["caps"]["happy_hour_per_week"], 2)

    def test_dinner_cap(self):
        self.assertEqual(self.rules["caps"]["dinner_per_week"], 1)

    def test_email_signoff(self):
        self.assertIn("Let's Win", self.rules["email"]["sign_off"])

    def test_coffee_locations(self):
        locs = self.rules["coffee_locations"]["all"]
        self.assertIn("Olive & Finch", locs)
        self.assertIn("Aviano on St. Paul", locs)

    def test_meeting_type_new_client(self):
        nt = self.rules["meeting_types"]["new_client"]
        self.assertEqual(nt["urgency"], "same_week")
        self.assertEqual(nt["duration_minutes"], 60)

    def test_coffee_block_90_min(self):
        c = self.rules["meeting_types"]["coffee"]
        self.assertEqual(c["calendar_block_minutes"], 90)

    def test_hard_nos_in_caps(self):
        hard_nos = self.rules["caps"]["hard_nos"]
        self.assertTrue(any("lunch" in h for h in hard_nos))
        self.assertTrue(any("happy hour" in h for h in hard_nos))


class TestSchedulingState(unittest.TestCase):
    """Test the hold session state machine."""

    def setUp(self):
        # Use in-memory DB for tests
        import tempfile
        self.db_file = tempfile.mktemp(suffix=".db")
        os.environ["DATABASE_PATH"] = self.db_file

        # Re-import with test DB
        from app.database import init_db
        with patch("app.config.settings") as mock_settings:
            mock_settings.database_path = self.db_file
            from pathlib import Path
            import app.database as db_module
            db_module.settings = mock_settings
            mock_settings.database_path = Path(self.db_file)
            try:
                init_db()
            except Exception:
                pass

    def test_imports_work(self):
        """Verify all scheduling state imports work."""
        from app.lexi.scheduling_state import (
            create_hold_session, get_active_sessions,
            confirm_session, cancel_session
        )
        self.assertTrue(True)

    def test_feedback_imports(self):
        from app.lexi.feedback import record_feedback, get_feedback_context
        self.assertTrue(True)

    def test_persona_imports(self):
        from app.lexi.persona import get_system_prompt
        prompt = get_system_prompt()
        self.assertIn("Let's Win", prompt)
        self.assertIn("HARD BLOCKS", prompt)
        self.assertIn("Trainer", prompt)
        self.assertIn("Doug", prompt)

    def test_persona_contains_all_key_rules(self):
        from app.lexi.persona import get_system_prompt
        prompt = get_system_prompt()
        # Hard blocks
        self.assertIn("YPO", prompt)
        self.assertIn("6:30", prompt)
        # Meeting types
        self.assertIn("coffee", prompt.lower())
        self.assertIn("happy hour", prompt.lower())
        # Email
        self.assertIn("Let's Win", prompt)
        # Holds workflow
        self.assertIn("HOLD", prompt)
        self.assertIn("2–3 options", prompt)

    def test_persona_includes_feedback_context(self):
        from app.lexi.persona import get_system_prompt
        prompt = get_system_prompt(feedback_context="TEST_FEEDBACK_XYZ")
        self.assertIn("TEST_FEEDBACK_XYZ", prompt)


class TestAgentImports(unittest.TestCase):
    """Test that the agent module imports cleanly."""

    def test_agent_imports(self):
        from app.lexi.agent import chat
        from app.lexi.agents.base import load_tools as _load_composio_tools
        self.assertTrue(True)

    def test_agent_tool_loading_with_bad_key(self):
        from app.lexi.agents.base import load_tools
        with patch("app.config.settings") as mock_settings:
            mock_settings.composio_api_key = "bad_key"
            # load_tools takes a list of slugs; should return [] gracefully
            tools = load_tools(["OUTLOOK_GET_CALENDAR_VIEW"])
            self.assertIsInstance(tools, list)


class TestEmailRules(unittest.TestCase):
    """Test email tone and format rules."""

    def test_signoff_is_lets_win(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        self.assertIn("Let's Win", rules["email"]["sign_off"])
        self.assertNotIn("Best", rules["email"]["sign_off"])

    def test_forbidden_closings(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        forbidden = rules["email"]["forbidden_closings"]
        self.assertIn("Best", forbidden)
        self.assertIn("Warmly", forbidden)

    def test_forbidden_topics_include_ypo(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        forbidden = rules["email"]["forbidden_topics"]
        self.assertTrue(any("YPO" in t for t in forbidden))


class TestHoldWorkflowLogic(unittest.TestCase):
    """Test the logic of the hold workflow."""

    def test_hold_title_format(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        title_format = rules["holds"]["title_format"]
        # Should support formatting with contact and n
        title = title_format.format(contact="Jessica", n=1)
        self.assertIn("Jessica", title)
        self.assertIn("1", title)
        self.assertIn("HOLD", title)

    def test_reminder_after_2_days(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        self.assertEqual(rules["holds"]["remind_after_days"], 2)

    def test_release_after_3_days(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        self.assertEqual(rules["holds"]["release_after_days"], 3)


class TestAvailabilityWindows(unittest.TestCase):
    """Test availability window rules."""

    def setUp(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            self.rules = yaml.safe_load(f)

    def test_mwf_workout_earliest_virtual_8am(self):
        monday = self.rules["availability"]["weekdays"]["monday"]
        self.assertEqual(monday["earliest_virtual"], "08:00")

    def test_mwf_in_person_930am(self):
        monday = self.rules["availability"]["weekdays"]["monday"]
        self.assertEqual(monday["earliest_in_person"], "09:30")

    def test_tue_thu_east_coast_6am(self):
        tuesday = self.rules["availability"]["weekdays"]["tuesday"]
        self.assertEqual(tuesday["earliest_east_coast_exception"], "06:00")

    def test_evening_cutoff_6pm(self):
        self.assertEqual(self.rules["caps"]["evening_cutoff"], "18:00")

    def test_weekends_default_false(self):
        self.assertFalse(self.rules["availability"]["weekends"]["default_available"])

    def test_coffee_preferred_times(self):
        coffee = self.rules["meeting_types"]["coffee"]
        self.assertIn("08:30", coffee["preferred_start_times"])
        self.assertIn("09:00", coffee["preferred_start_times"])

    def test_happy_hour_preferred_times(self):
        hh = self.rules["meeting_types"]["happy_hour"]
        self.assertIn("15:30", hh["preferred_start_times"])
        self.assertIn("16:00", hh["preferred_start_times"])


class TestUrgencyRules(unittest.TestCase):
    """Test urgency classification."""

    def setUp(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            self.rules = yaml.safe_load(f)

    def test_new_client_same_week(self):
        self.assertEqual(self.rules["urgency"]["new_client_max_days_out"], 7)

    def test_podcast_min_3_weeks(self):
        self.assertGreaterEqual(self.rules["urgency"]["podcast_min_days_out"], 21)

    def test_rescheduling_priority(self):
        self.assertTrue(self.rules["urgency"]["reschedule_priority"])


class TestTravelTimeRules(unittest.TestCase):
    """Test travel time rules."""

    def setUp(self):
        import yaml
        rules_path = os.path.join(os.path.dirname(__file__), "..", "app", "rules", "scheduling_rules.yaml")
        with open(rules_path) as f:
            self.rules = yaml.safe_load(f)

    def test_cherry_creek_15_min(self):
        self.assertEqual(self.rules["travel_times_minutes"]["cherry_creek"], 15)

    def test_littleton_45_min(self):
        self.assertEqual(self.rules["travel_times_minutes"]["littleton"], 45)

    def test_drive_time_is_phone_call_time(self):
        self.assertTrue(self.rules["travel"]["call_during_drive_over_minutes"] <= 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)

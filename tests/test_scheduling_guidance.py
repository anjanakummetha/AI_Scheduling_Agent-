"""Delegation blocked — minimal Kory-facing copy."""

from app.agents.inbound_reply import humanize_scheduler_failure
from app.bot.teams_text import format_scheduling_guidance_notification


def test_humanize_insufficient_coffee_slots() -> None:
    error = (
        "ValueError: No valid meeting slots found. "
        "Engine diagnostics: {'block_minutes': 90, 'status': 'insufficient_slots', "
        "'scheduling_window': {'label': 'next week'}}"
    )
    text = humanize_scheduler_failure(error, intent="coffee")
    assert "coffee slot" in text.lower()
    assert "should i try a different week" in text.lower()


def test_guidance_notification_is_minimal() -> None:
    text = format_scheduling_guidance_notification(
        subject="TEST — coffee in Cherry Creek",
        sender="anjana@iconicfounders.com",
        summary="I couldn't find a coffee slot for next week. Should I try a different week?",
        intent="coffee",
    )
    assert "Cherry Creek" in text
    assert "coffee slot for next week" in text.lower()
    assert "should i try a different week" in text.lower()
    assert "Composio" not in text
    assert "scheduling engine" not in text.lower()
    assert "need your help" not in text.lower()

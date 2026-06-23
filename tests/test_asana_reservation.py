"""Asana reservation reminder detection."""

from app.integrations.asana_manager import (
    dispatch_reservation_reminder_for_proposal,
    meal_from_intent,
    reservation_needed_for_proposal,
)


def test_meal_from_intent() -> None:
    assert meal_from_intent("lunch_request") == "lunch"
    assert meal_from_intent("dinner_request") == "dinner"
    assert meal_from_intent("coffee") is None


def test_reservation_needed_for_lunch_intent() -> None:
    assert reservation_needed_for_proposal(intent="lunch_request") is True


def test_reservation_needed_from_draft_wording() -> None:
    assert reservation_needed_for_proposal(
        intent="coffee",
        drafted_reply="I'll book a table at Mercantile — does 7pm work?",
    ) is True


def test_dispatch_simulated_booking_task(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.asana_manager._should_simulate_asana",
        lambda: True,
    )
    result = dispatch_reservation_reminder_for_proposal(
        intent="dinner_request",
        meeting_subject="Dinner with investor",
        thread_id="t-1",
        sender="guest@example.com",
        drafted_reply="Looking forward to dinner Thursday.",
        time_slot="2026-06-12T19:00:00-06:00",
        approved=True,
    )
    assert result is not None
    assert result.get("simulated") is True
    assert result.get("ok") is True

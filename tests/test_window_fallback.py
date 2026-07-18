"""Window fallback when requested scheduling window has no slots."""

from unittest.mock import patch

from app.scheduling.scheduling_plan import SchedulingPlan
from app.scheduling.scheduling_window import SchedulingWindow
from app.scheduling.slot_engine import SlotProposal
from app.scheduling.window_fallback import (
    build_failure_kory_message,
    propose_with_window_fallback,
)


def test_build_failure_asks_kory_first() -> None:
    msg = build_failure_kory_message(
        intent="coffee",
        requested_label="next week",
    )
    assert "coffee slot for next week" in msg.lower()
    assert "should i try a different week" in msg.lower()


def test_propose_with_window_fallback_does_not_auto_shift() -> None:
    """Window fallback module is reserved; scheduler uses primary window only."""
    from app.scheduling.window_fallback import propose_with_window_fallback

    empty = SlotProposal(slots=[], diagnostics={"status": "insufficient_slots"})
    plan = SchedulingPlan(
        window=SchedulingWindow(
            start=__import__("datetime").date(2026, 6, 29),
            end=__import__("datetime").date(2026, 7, 5),
            source="body",
            label="next week",
        )
    )
    ctx = {"status": "available", "busy_events": []}

    with patch(
        "app.scheduling.window_fallback.propose_meeting_slots",
        return_value=empty,
    ):
        result = propose_with_window_fallback(
            ctx,
            intent="coffee",
            subject="TEST coffee",
            body="coffee next week",
            plan=plan,
        )
    assert result.shifted is False
    assert len(result.proposal.slots) == 0

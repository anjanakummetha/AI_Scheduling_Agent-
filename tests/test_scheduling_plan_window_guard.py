"""Regression: the LLM planner must not invent a scheduling window the sender never
stated. A hallucinated single-day window (e.g. "today") on a date-less request used to
hard-narrow scheduling to one day and force a needless defer to Kory.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.scheduling.scheduling_plan import SchedulingPlan, _merge_llm_plan
from app.scheduling.scheduling_window import infer_scheduling_window

MT = ZoneInfo("America/Denver")
NOW = datetime(2026, 7, 20, 15, 0, tzinfo=MT)


def test_ungrounded_single_day_llm_window_is_rejected():
    # Sender named no date; the LLM hallucinated window_label="today".
    plan = SchedulingPlan(window=None, source="default")
    merged = _merge_llm_plan(
        plan,
        {"task_type": "offer_times", "window_label": "today"},
        subject="Dinner sometime?",
        body="Let's finally do that dinner in Cherry Creek. What evening works for you?",
        now=NOW,
    )
    # The hallucinated single-day window is ignored → open horizon.
    assert merged.window is None


def test_sender_stated_window_is_honored():
    rule_window = infer_scheduling_window(subject="", body="can we meet next week?", now=NOW)
    plan = SchedulingPlan(window=rule_window, source="rules")
    merged = _merge_llm_plan(
        plan,
        {"window_label": "next week"},
        subject="Intro",
        body="can we meet next week?",
        now=NOW,
    )
    assert merged.window is not None
    assert merged.window.label == "next week"


def test_ungrounded_multiday_llm_window_is_honored():
    # A multi-day LLM window doesn't hard-block a single day, so it's still applied.
    plan = SchedulingPlan(window=None, source="default")
    merged = _merge_llm_plan(
        plan,
        {"window_label": "next week or two"},
        subject="Coffee?",
        body="whenever works for you",
        now=NOW,
    )
    assert merged.window is not None
    assert merged.window.start != merged.window.end

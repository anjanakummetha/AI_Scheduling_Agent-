"""Regression: the scheduler must gate against the plan the engine actually used.

The engine (`schedule_from_context`) applies a travel shift to its plan
(`maybe_shift_plan_window`) so meetings land in the week *after* Kory's travel.
`scheduler_agent` used to rebuild a fresh plan for its pre-approval gate, re-parsing
relative windows like "next week" WITHOUT the travel shift. The gate then rejected the
valid post-travel slots as "outside requested window" and over-deferred to Kory.

These tests lock the fix: (1) `_build_schedule` threads the engine's plan onto the
`ScheduleResult`; (2) the gate accepts slots that fall inside a travel-shifted window.
"""

from datetime import date

from app.scheduling.scheduling_plan import SchedulingPlan
from app.scheduling.scheduling_window import SchedulingWindow

_SHIFTED = SchedulingWindow(
    start=date(2026, 7, 27),
    end=date(2026, 8, 2),
    source="travel_shift",
    label="week of July 27 (after travel)",
)
_IN_WINDOW_SLOTS = [
    {"start": "2026-07-28T09:00:00-06:00", "end": "2026-07-28T09:30:00-06:00"},
    {"start": "2026-07-29T10:00:00-06:00", "end": "2026-07-29T10:30:00-06:00"},
]


def test_build_schedule_threads_engine_plan(monkeypatch):
    import app.agents.scheduler_agent as sa
    import app.scheduling.reply_composer as rc
    import app.scheduling.schedule_from_context as sfc

    engine_plan = SchedulingPlan(task_type="offer_times", window=_SHIFTED, duration_minutes=30)
    fake_result = sfc.ScheduleFromContextResult(
        ok=True,
        slots=list(_IN_WINDOW_SLOTS),
        path="slot_engine",
        status="ok",
        plan=engine_plan,
        meeting_format="virtual",
    )
    monkeypatch.setattr(sfc, "schedule_from_context", lambda **kw: fake_result)
    monkeypatch.setattr(rc, "compose_scheduling_reply", lambda **kw: ("draft body", "composer"))

    proposal = sa.PendingProposal(
        proposal_id=1,
        thread_id="t1",
        intent_classification="referral_or_intro",
        priority_tier="medium",
        triage_confidence=0.9,
        justification="",
        rule_reasoning="",
        subject="Intro next week",
        sender="x@example.com",
        received_at="2026-07-20T15:00:00Z",
        raw_body="Could we grab 30 minutes on Teams next week?",
    )
    schedule = sa._build_schedule(proposal, {"status": "available", "busy_events": []})

    # The travel-shifted engine plan must flow onto the ScheduleResult so the
    # scheduler gates against the same window the engine scheduled into.
    assert schedule.plan is engine_plan
    assert schedule.plan.window.source == "travel_shift"


def test_gate_accepts_slots_inside_travel_shifted_window():
    from app.scheduling.pre_approval_gate import verify_before_kory_approval

    plan = SchedulingPlan(task_type="offer_times", window=_SHIFTED, duration_minutes=30)
    report = verify_before_kory_approval(
        slots=list(_IN_WINDOW_SLOTS),
        calendar_context={"status": "available", "busy_events": []},
        plan=plan,
        intent="referral_or_intro",
        subject="Intro",
        body="30 minute Teams intro next week",
        window_expanded=False,
    )
    # Slots fall inside the travel-shifted window — the window check must not fire,
    # regardless of any unrelated rule outcome.
    assert not any(
        "outside requested window" in check for check in report.checks
    ), report.checks

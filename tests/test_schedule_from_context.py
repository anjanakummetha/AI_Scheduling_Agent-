"""Tests for unified schedule_from_context."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.scheduling.schedule_from_context import merge_scheduling_body

MT = ZoneInfo(settings.scheduling_timezone)


def _calendar_context(*, horizon_days: int = 21, busy: list | None = None) -> dict:
    now = datetime.now(tz=MT)
    return {
        "status": "available",
        "horizon_days": horizon_days,
        "range_start": now.isoformat(),
        "range_end": (now + timedelta(days=horizon_days)).isoformat(),
        "busy_events": busy or [],
        "calendars_consulted": [],
        "calendars_unavailable": [],
    }


def test_merge_scheduling_body_appends_guidance():
    merged = merge_scheduling_body("Can we meet?", "Try next week afternoons")
    assert "Kory (scheduling guidance)" in merged
    assert "next week afternoons" in merged


def test_schedule_from_context_uses_engine(monkeypatch):
    monkeypatch.setattr(
        "app.scheduling.calendar_context.load_scheduling_calendar_context",
        lambda **_: _calendar_context(),
    )
    monkeypatch.setattr(
        "app.scheduling.scheduling_plan.build_scheduling_plan",
        lambda **_: type(
            "Plan",
            (),
            {
                "task_type": "offer_times",
                "window": None,
                "duration_minutes": 30,
                "meeting_format": "virtual",
                "urgency": False,
                "draft_context": "",
                "source": "rules",
                "raw": {},
            },
        )(),
    )
    monkeypatch.setattr(
        "app.scheduling.travel_window.maybe_shift_plan_window",
        lambda plan, _: plan,
    )

    slot_start = (datetime.now(tz=MT) + timedelta(days=3)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    slot_end = slot_start + timedelta(minutes=30)
    fake_slots = [
        {"start": slot_start.isoformat(), "end": slot_end.isoformat()},
        {
            "start": (slot_start + timedelta(days=1)).isoformat(),
            "end": (slot_end + timedelta(days=1)).isoformat(),
        },
    ]

    class FakeEngine:
        slots = fake_slots
        meeting_format = "virtual"
        diagnostics = {"status": "ok"}

    import importlib

    sched_ctx = importlib.import_module("app.scheduling.schedule_from_context")

    monkeypatch.setattr(
        sched_ctx,
        "propose_meeting_slots",
        lambda *a, **k: FakeEngine(),
    )
    monkeypatch.setattr(
        sched_ctx,
        "verify_before_kory_approval",
        lambda **_: type("Gate", (), {"ok": True, "summary": lambda self: "ok"})(),
    )

    result = sched_ctx.schedule_from_context(
        subject="Intro call",
        body="Can we schedule a 30-minute call next week?",
        sender_email="bill@newportadvisors.co",
        use_llm_plan=False,
        try_inbound_availability=False,
    )
    assert result.ok is True
    assert result.path == "slot_engine"
    assert len(result.slots) == 2
    assert result.formatted_slots
    assert result.recipient_timezone is not None


def test_schedule_from_context_calendar_unavailable(monkeypatch):
    import importlib

    sched_ctx = importlib.import_module("app.scheduling.schedule_from_context")
    monkeypatch.setattr(
        "app.scheduling.calendar_context.load_scheduling_calendar_context",
        lambda **_: {"status": "unavailable", "error": "composio_down"},
    )
    result = sched_ctx.schedule_from_context(subject="Meet", body="next week?")
    assert result.ok is False
    assert result.path == "calendar_unavailable"

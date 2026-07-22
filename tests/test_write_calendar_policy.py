"""Lexi only writes to the work calendar; Master is read-only (plan Phase 2)."""

from __future__ import annotations

from app.integrations import named_calendars as nc


def test_master_name_detected():
    assert nc._is_master_calendar_name("Kory Master Calendar (ALL)")
    assert nc._is_master_calendar_name("kory master calendar")
    assert not nc._is_master_calendar_name("Calendar")


def test_master_write_coerced_to_work():
    assert nc._coerce_write_target("Kory Master Calendar (ALL)") == nc.work_calendar_name()
    assert nc.work_calendar_name().lower() != "kory master calendar (all)"


def test_work_target_unchanged():
    assert nc._coerce_write_target("Calendar") == "Calendar"

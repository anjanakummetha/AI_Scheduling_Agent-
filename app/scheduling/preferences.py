"""Merge rules.py defaults with explicit Kory memory overrides from Teams/Hermes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import rules as kory_rules
from app.storage.kory_memory import list_facts


@dataclass
class SchedulingPreferences:
    """Effective scheduling preferences (defaults + Kory memory)."""

    happy_hour_max_per_week: int = field(
        default_factory=lambda: int(kory_rules.CAPACITY_LIMITS.get("happy_hour_per_week", 2))
    )
    dinner_max_per_week: int = field(
        default_factory=lambda: int(kory_rules.CAPACITY_LIMITS.get("dinner_per_week", 1))
    )
    travel_week_max_meetings: int = 3
    lunch_allowed: bool = False
    memory_facts: list[dict[str, Any]] = field(default_factory=list)

    def memory_prompt_block(self) -> str:
        if not self.memory_facts:
            return ""
        lines = ["KORY PREFERENCE OVERRIDES (from Teams — supersede defaults when relevant):"]
        for item in self.memory_facts:
            lines.append(f"- {item.get('fact_key')}: {item.get('fact_value')}")
        return "\n".join(lines)


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _parse_bool(value: str) -> bool | None:
    v = value.strip().lower()
    if v in {"1", "true", "yes", "on", "allowed"}:
        return True
    if v in {"0", "false", "no", "off", "disallowed", "never"}:
        return False
    return None


def load_scheduling_preferences() -> SchedulingPreferences:
    """Load defaults merged with kory_memory scheduling facts."""
    prefs = SchedulingPreferences()
    facts = list_facts(limit=100)
    prefs.memory_facts = facts

    for item in facts:
        key = str(item.get("fact_key") or "").strip().lower()
        value = str(item.get("fact_value") or "").strip()
        if not key or not value:
            continue
        if key in {"happy_hour_max_per_week", "happy_hour_per_week", "max_happy_hours"}:
            prefs.happy_hour_max_per_week = _parse_int(value, prefs.happy_hour_max_per_week)
        elif key in {"dinner_max_per_week", "dinner_per_week", "max_dinners"}:
            prefs.dinner_max_per_week = _parse_int(value, prefs.dinner_max_per_week)
        elif key in {"travel_week_max_meetings", "travel_check_ins"}:
            prefs.travel_week_max_meetings = _parse_int(value, prefs.travel_week_max_meetings)
        elif key in {"lunch_meetings", "allow_lunch"}:
            parsed = _parse_bool(value)
            if parsed is not None:
                prefs.lunch_allowed = parsed

    return prefs

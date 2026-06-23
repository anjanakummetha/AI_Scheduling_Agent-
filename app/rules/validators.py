"""Deterministic Kory scheduling validators (rules.py → runtime checks)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings

import rules as kory_rules

DINNER_INTENTS = frozenset({"dinner_request", "dinner"})
EVENING_INTENTS = frozenset(DINNER_INTENTS | {"happy_hour"})


@dataclass
class ValidationResult:
    valid: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rules_checked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "violations": self.violations,
            "warnings": self.warnings,
            "rules_checked": self.rules_checked,
        }


def _parse_slot(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _local_dt(dt: datetime) -> datetime:
    tz = ZoneInfo(settings.scheduling_timezone)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = (int(x) for x in value.split(":"))
    return hour, minute


def _slot_overlaps_block(
    start_local: datetime,
    end_local: datetime,
    *,
    block_start: str,
    block_end: str,
) -> bool:
    """True if [start_local, end_local) overlaps [block_start, block_end) on same day."""
    bs_h, bs_m = _parse_hhmm(block_start)
    be_h, be_m = _parse_hhmm(block_end)
    block_start_dt = start_local.replace(hour=bs_h, minute=bs_m, second=0, microsecond=0)
    block_end_dt = start_local.replace(hour=be_h, minute=be_m, second=0, microsecond=0)
    return start_local < block_end_dt and end_local > block_start_dt


def _check_timed_hard_blocks(
    start_local: datetime,
    end_local: datetime,
    weekday: str,
    prefix: str,
    result: ValidationResult,
) -> None:
    """Reject slots overlapping rules.py HARD_BLOCKS with fixed day/time windows."""
    result.rules_checked.append("hard_blocks")
    for block in kory_rules.HARD_BLOCKS:
        days = block.get("days")
        block_start = block.get("start")
        block_end = block.get("end")
        if not days or not block_start or not block_end:
            continue
        if weekday not in days:
            continue
        if _slot_overlaps_block(
            start_local,
            end_local,
            block_start=block_start,
            block_end=block_end,
        ):
            result.valid = False
            result.violations.append(
                f"{prefix}: overlaps hard block '{block.get('name')}' "
                f"({block_start}–{block_end} {weekday})."
            )


def validate_proposal_slots(
    slots: list[dict[str, str]],
    *,
    intent: str | None = None,
) -> ValidationResult:
    """Validate proposed slots against Kory rules before staging approval."""
    result = ValidationResult(valid=True)
    intent_key = (intent or "unknown").lower().replace(" ", "_")

    if not slots:
        result.valid = False
        result.violations.append("No slots proposed.")
        return result

    for index, slot in enumerate(slots, start=1):
        start_raw = str(slot.get("start") or "")
        end_raw = str(slot.get("end") or "")
        start = _parse_slot(start_raw)
        end = _parse_slot(end_raw)
        if not start or not end:
            result.valid = False
            result.violations.append(f"Option {index}: invalid ISO start/end.")
            continue

        start_local = _local_dt(start)
        end_local = _local_dt(end)
        weekday = start_local.strftime("%A")
        prefix = f"Option {index} ({weekday} {start_local.strftime('%H:%M')} MT)"

        _check_timed_hard_blocks(start_local, end_local, weekday, prefix, result)

        result.rules_checked.append("weekend_availability")
        day_rules = kory_rules.DAILY_AVAILABILITY.get(weekday, {})
        if day_rules.get("available") is False and intent_key not in DINNER_INTENTS:
            result.valid = False
            result.violations.append(f"{prefix}: weekend meetings are not allowed by default.")

        result.rules_checked.append("six_pm_cutoff")
        if intent_key not in DINNER_INTENTS:
            if start_local.hour >= 18 or (end_local.hour == 18 and end_local.minute > 0):
                result.valid = False
                result.violations.append(
                    f"{prefix}: after 6 PM is only allowed for planned dinners."
                )
            elif end_local.hour > 18:
                result.valid = False
                result.violations.append(f"{prefix}: ends after 6 PM (non-dinner).")

        result.rules_checked.append("daily_latest_window")
        latest = day_rules.get("latest")
        if latest and intent_key not in DINNER_INTENTS:
            latest_hour, latest_min = (int(x) for x in latest.split(":"))
            if start_local.hour > latest_hour or (
                start_local.hour == latest_hour and start_local.minute >= latest_min
            ):
                result.warnings.append(
                    f"{prefix}: starts at or after daily latest ({latest})."
                )

        result.rules_checked.append("workout_day_formal")
        if weekday in kory_rules.WORKOUT_DAYS and intent_key in {
            "coffee",
            "lunch_request",
            "lunch",
            "dinner_request",
            "dinner",
            "happy_hour",
            "pitch",
            "new_client",
        }:
            formal_earliest = day_rules.get("earliest_formal_inperson", "09:30")
            fe_h, fe_m = _parse_hhmm(formal_earliest)
            if start_local.hour < fe_h or (
                start_local.hour == fe_h and start_local.minute < fe_m
            ):
                result.valid = False
                result.violations.append(
                    f"{prefix}: M/W/F in-person/formal meetings earliest {formal_earliest} "
                    f"(virtual informal OK from 8:00)."
                )

        result.rules_checked.append("happy_hour_end")
        if intent_key in {"happy_hour"}:
            if end_local.hour > 18 or (end_local.hour == 18 and end_local.minute > 0):
                result.valid = False
                result.violations.append(f"{prefix}: happy hour must end by 6:00 PM.")

        duration_min = int((end_local - start_local).total_seconds() // 60)
        result.rules_checked.append("meeting_duration")
        if intent_key in {"lunch_request", "lunch"}:
            result.warnings.append(
                f"{prefix}: lunch meetings are exception-only per Kory rules."
            )
        if intent_key in {"coffee"} and duration_min < 45:
            result.warnings.append(f"{prefix}: coffee meetings usually need ~60–90 min block.")

    return result


def filter_slots_by_rules(
    slots: list[dict[str, str]],
    *,
    intent: str | None = None,
) -> tuple[list[dict[str, str]], ValidationResult]:
    """Return slots that pass hard validators; attach aggregate result."""
    safe: list[dict[str, str]] = []
    aggregate = ValidationResult(valid=True)

    for slot in slots:
        check = validate_proposal_slots([slot], intent=intent)
        aggregate.rules_checked.extend(check.rules_checked)
        aggregate.warnings.extend(check.warnings)
        if check.valid:
            safe.append(slot)
        else:
            aggregate.violations.extend(check.violations)

    aggregate.valid = len(safe) >= 2
    if len(safe) < 2:
        aggregate.violations.append(
            f"Only {len(safe)} slot(s) passed Kory rule validation; need at least 2."
        )
    return safe, aggregate

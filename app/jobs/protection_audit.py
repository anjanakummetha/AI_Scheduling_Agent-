"""Weekly protection self-audit (plan Phase 2).

Context: Lexi's event classifier (`calendar_intelligence.classify_event`) is
deliberately conservative — it treats essentially every event on Kory's calendar
as blocking (UNKNOWN_BLOCKING catch-all), so a *renamed* protected block still
blocks. That means title drift does NOT silently break protection for events that
are on the calendar. The residual risk is a recurring timed block (trainer, Doug,
Capital Demolition) that has been moved or removed: the time-of-day rule in
rules.py still protects the window, but if the real event has actually shifted,
that rule may now guard the wrong time. This job scans the upcoming calendar and
tells Kory when an expected recurring block is missing so the rule can be kept
aligned with reality.

Deterministic and free (no LLM). Delivered to Kory in Teams.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import rules as kory_rules
from app.config import settings
from app.scheduling.busy_intervals import local_dt, parse_event_datetime
from app.scheduling.calendar_intelligence import classify_event

_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class AuditReport:
    horizon_days: int
    matched_protected: int = 0
    expected_missing: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.expected_missing


def _timed_hard_blocks() -> list[dict[str, Any]]:
    """HARD_BLOCKS carrying days+start+end — the recurrences we can check for presence."""
    return [
        b
        for b in kory_rules.HARD_BLOCKS
        if b.get("days") and b.get("start") and b.get("end")
    ]


def _hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def _overlaps_window(event: dict[str, Any], win_start: datetime, win_end: datetime) -> bool:
    es = parse_event_datetime(event.get("start"))
    ee = parse_event_datetime(event.get("end"))
    if not es or not ee:
        return False
    es, ee = local_dt(es), local_dt(ee)
    return es < win_end and ee > win_start


def audit_upcoming_protection(
    events: list[dict[str, Any]],
    now_mt: datetime,
    *,
    horizon_days: int = 14,
) -> AuditReport:
    """Pure audit over already-fetched events (testable; no I/O)."""
    report = AuditReport(horizon_days=horizon_days)

    classified = [(ev, classify_event(ev)) for ev in events]
    report.matched_protected = sum(1 for _, c in classified if c.blocks_kory)

    for block in _timed_hard_blocks():
        days = set(block.get("days") or [])
        sh, sm = _hhmm(block["start"])
        eh, em = _hhmm(block["end"])
        for offset in range(horizon_days):
            day = (now_mt + timedelta(days=offset)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if _WEEKDAY_NAMES[day.weekday()] not in days:
                continue
            win_start = day.replace(hour=sh, minute=sm)
            win_end = day.replace(hour=eh, minute=em)
            present = any(
                c.blocks_kory and _overlaps_window(ev, win_start, win_end)
                for ev, c in classified
            )
            if not present:
                report.expected_missing.append(
                    {
                        "name": block.get("name"),
                        "date": day.date().isoformat(),
                        "window": f"{block['start']}–{block['end']}",
                    }
                )
    return report


def format_digest(report: AuditReport) -> str:
    """Short Kory-facing Teams digest. Empty string when nothing needs attention."""
    if report.clean:
        return ""
    lines = [
        "Weekly calendar check — a recurring block looks like it may have moved "
        "(the time is still protected by rule; confirm it hasn't shifted):"
    ]
    by_name: dict[str, list[str]] = {}
    for m in report.expected_missing:
        by_name.setdefault(str(m["name"]), []).append(m["date"])
    for name, dates in by_name.items():
        shown = ", ".join(dates[:4]) + ("…" if len(dates) > 4 else "")
        lines.append(f"  • {name} — no event found on: {shown}")
    lines.append("\nReply if it moved and I'll update your rules.")
    return "\n".join(lines)


def run_protection_audit(*, push_to_kory: bool = True) -> dict[str, Any]:
    """Read the real calendar, audit it, and (optionally) push a digest to Kory."""
    from app.scheduling.calendar_context import load_scheduling_calendar_context

    ctx = load_scheduling_calendar_context(horizon_days=14)
    events = ctx.get("busy_events") or []
    now_mt = datetime.now(ZoneInfo(settings.scheduling_timezone))
    report = audit_upcoming_protection(events, now_mt, horizon_days=14)

    digest = format_digest(report)
    pushed = False
    if push_to_kory and digest:
        from app.safety.outbound_guard import teams_push_allowed

        if teams_push_allowed():
            from app.bot.teams_publisher import schedule_teams_scheduling_guidance_push

            schedule_teams_scheduling_guidance_push(0, summary=digest)
            pushed = True
    return {
        "matched_protected": report.matched_protected,
        "expected_missing": report.expected_missing,
        "digest": digest,
        "pushed_to_kory": pushed,
    }

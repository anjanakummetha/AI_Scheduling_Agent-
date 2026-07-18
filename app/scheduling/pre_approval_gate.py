"""Verify slots + draft before Kory sees a Teams approval card."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.rules.validators import ValidationResult, validate_proposal_slots
from app.scheduling.busy_intervals import slot_conflicts_busy, slot_interval
from app.scheduling.meeting_type import (
    calendar_block_minutes_for_context,
    offer_duration_minutes_for_context,
    resolve_meeting_type,
)
from app.scheduling.scheduling_plan import SchedulingPlan
from app.scheduling.scheduling_window import slot_date_in_window
from app.scheduling.slot_engine import infer_meeting_format

MIN_SLOT_OPTIONS = 2


@dataclass
class PreApprovalReport:
    ok: bool
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meeting_type_key: str = ""
    meeting_type_label: str = ""
    rules_passed: bool = False

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return "Calendar verified — slots clear conflicts, rules pass, and match requested window."
        parts = []
        if not self.ok:
            parts.append("BLOCKED: " + "; ".join(self.checks))
        if self.warnings:
            parts.append("Warnings: " + "; ".join(self.warnings))
        return " ".join(parts) or "ok"

    def rules_status_line(self) -> str:
        """User-facing Teams line — never show Composio calendar-visibility noise."""
        if not self.ok:
            return f"Rules: blocked — {'; '.join(self.checks[:2])}"
        visible = [
            w
            for w in self.warnings
            if "not visible via Composio" not in w
            and "configured calendars" not in w.lower()
        ]
        if visible:
            return f"Rules: pass (with warnings — {'; '.join(visible[:2])})"
        if self.rules_passed or self.ok:
            return "Rules: pass"
        return "Rules: not verified"


def verify_before_kory_approval(
    *,
    slots: list[dict[str, str]],
    calendar_context: dict[str, Any],
    plan: SchedulingPlan | None = None,
    intent: str | None = None,
    subject: str = "",
    body: str = "",
    meeting_format: str | None = None,
    window_expanded: bool = False,
) -> PreApprovalReport:
    """Fail closed unless calendar is readable and slots pass conflict + Kory rules."""
    busy = list(calendar_context.get("busy_events") or [])
    report = PreApprovalReport(ok=True)

    meeting_spec = resolve_meeting_type(
        intent=intent,
        subject=subject,
        body=body,
    )
    report.meeting_type_key = meeting_spec.type_key
    report.meeting_type_label = meeting_spec.label

    if calendar_context.get("status") != "available":
        report.ok = False
        detail = calendar_context.get("error") or calendar_context.get("source") or "unknown"
        report.checks.append(f"calendar unavailable ({detail})")
        return report

    # Missing named calendars are operational noise for Kory's Teams card —
    # keep them out of user-facing warnings (still available on calendar_context).
    _ = list(calendar_context.get("calendars_unavailable") or [])

    if len(slots) < MIN_SLOT_OPTIONS:
        report.ok = False
        report.checks.append(f"need at least {MIN_SLOT_OPTIONS} slots (got {len(slots)})")
        return report

    fmt = meeting_format or infer_meeting_format(
        meeting_spec.type_key,
        subject=subject,
        body=body,
    )
    expected_block = offer_duration_minutes_for_context(
        intent=intent,
        subject=subject,
        body=body,
        plan_duration_minutes=(plan.duration_minutes if plan else None),
    )

    for index, slot in enumerate(slots, start=1):
        if slot_conflicts_busy(slot, busy):
            report.ok = False
            report.checks.append(f"slot {index} conflicts with Kory calendar")

        interval = slot_interval(slot)
        if interval:
            start, end = interval
            actual_minutes = int((end - start).total_seconds() // 60)
            if actual_minutes != expected_block:
                report.ok = False
                report.checks.append(
                    f"slot {index} block is {actual_minutes} min; expected {expected_block} min "
                    f"for {meeting_spec.label}"
                )

    if plan and plan.window and not window_expanded:
        for index, slot in enumerate(slots, start=1):
            if not slot_date_in_window(slot, plan.window):
                report.ok = False
                report.checks.append(
                    f"slot {index} outside requested window ({plan.window.label})"
                )

    rule_check = ValidationResult(valid=True)
    for slot in slots:
        check = validate_proposal_slots(
            [slot],
            intent=meeting_spec.type_key,
            meeting_format=fmt,
            urgent=bool(plan.urgency if plan else False),
            busy_events=busy,
            batch_slots=[slot],
        )
        if not check.valid:
            rule_check.valid = False
        rule_check.rules_checked.extend(check.rules_checked)
        rule_check.warnings.extend(check.warnings)
        for violation in check.violations:
            if violation not in rule_check.violations:
                rule_check.violations.append(violation)
    report.rules_passed = rule_check.valid
    if not rule_check.valid:
        report.ok = False
        for violation in rule_check.violations[:4]:
            if violation not in report.checks:
                report.checks.append(violation)
    report.warnings.extend(rule_check.warnings)

    return report

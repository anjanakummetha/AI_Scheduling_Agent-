#!/usr/bin/env python3
"""Comprehensive pre-deploy test runner."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PY = sys.executable


def _run(label: str, cmd: list[str]) -> bool:
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    result = subprocess.run(cmd, cwd=ROOT)
    ok = result.returncode == 0
    print(f"\n>>> {'PASS' if ok else 'FAIL'}: {label}")
    return ok


def _run_inline(label: str, fn) -> bool:
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    try:
        fn()
        print(f"\n>>> PASS: {label}")
        return True
    except Exception as exc:
        print(f"\n>>> FAIL: {label} — {exc}")
        return False


def main() -> int:
    results: list[tuple[str, bool]] = []

    suites: list[tuple[str, list[str]]] = [
        ("Read-only UAT locks", ["scripts/verify_read_only_deploy.py"]),
        (
            "Pre-Kory switch (read-only UAT)",
            ["scripts/verify_pre_kory_switch.py", "--read-only-uat"],
        ),
        ("Approval safety", ["scripts/test_approval_safety.py"]),
        ("MCP tools", ["scripts/test_mcp_tools.py"]),
        ("Lexi pipeline (mocked)", ["scripts/test_lexi_pipeline.py"]),
    ]
    for label, script_parts in suites:
        results.append((label, _run(label, [PY, str(ROOT / script_parts[0]), *script_parts[1:]])))

    def inline_units() -> None:
        from tests.test_inbound_filter import (
            test_calendar_accept_not_notified,
            test_delegation_always_notifies,
            test_scheduling_investor_notified_when_important_mode,
            test_scheduling_investor_not_notified_in_delegation_only_mode,
            test_ypo_digest_not_notified,
        )
        from tests.test_delegation import (
            test_delegation_cc_and_phrase,
            test_delegation_phrase_from_kory,
            test_not_delegation_random_mail,
        )
        from tests.test_read_only_safety import (
            test_execute_outlook_deny_permanent_delete,
            test_execute_outlook_write_requires_confirm,
            test_write_slug_detection,
        )
        from tests.test_email_format import (
            test_adds_sign_off_when_missing,
            test_paragraph_spacing,
            test_sign_off_on_separate_lines,
        )
        from tests.test_asana_reservation import (
            test_meal_from_intent,
            test_reservation_needed_for_lunch_intent,
            test_reservation_needed_from_draft_wording,
        )
        from app.integrations import asana_manager as am

        test_ypo_digest_not_notified()
        test_calendar_accept_not_notified()
        test_scheduling_investor_not_notified_in_delegation_only_mode()
        test_delegation_always_notifies()
        test_scheduling_investor_notified_when_important_mode()
        test_delegation_phrase_from_kory()
        test_delegation_cc_and_phrase()
        test_not_delegation_random_mail()
        test_write_slug_detection()
        test_kory_space_write_blocked_when_read_only()
        test_execute_outlook_write_requires_confirm()
        test_execute_outlook_deny_permanent_delete()
        test_sign_off_on_separate_lines()
        test_paragraph_spacing()
        test_adds_sign_off_when_missing()
        test_meal_from_intent()
        test_reservation_needed_for_lunch_intent()
        test_reservation_needed_from_draft_wording()

        original_sim = am._should_simulate_asana
        try:
            am._should_simulate_asana = lambda: True  # type: ignore[method-assign]
            out = am.dispatch_reservation_reminder_for_proposal(
                intent="dinner_request",
                meeting_subject="Deploy unit test",
                thread_id="t-deploy",
                sender="guest@example.com",
                drafted_reply="Dinner Thursday works.",
                time_slot="2026-06-12T19:00:00-06:00",
            )
            assert out and out.get("ok")
        finally:
            am._should_simulate_asana = original_sim  # type: ignore[method-assign]

    results.append(("Unit tests", _run_inline("Unit tests", inline_units)))

    def asana_live_smoke() -> None:
        from app.config import settings
        from app.integrations.asana_manager import create_booking_reminder_task

        if not settings.asana_enabled:
            raise RuntimeError("ASANA_ENABLED is false")
        result = create_booking_reminder_task(
            meal="dinner",
            meeting_subject="[Lexi deploy test — safe to delete] Reservation smoke",
            thread_id="deploy-test",
            sender="lexi@test",
            body_excerpt="Automated deploy readiness check.",
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "Asana create failed")
        if result.get("simulated"):
            raise RuntimeError("Asana was simulated — check ASANA_PROJECT_GID and Composio connection")
        print(f"Asana task created: {result.get('task_id')}")

    results.append(("Asana live smoke", _run_inline("Asana live smoke", asana_live_smoke)))

    def teams_commands() -> None:
        from app.teams.commands import handle_teams_command

        assert handle_teams_command("pending").get("handled") is True
        assert handle_teams_command("help").get("handled") is True

    results.append(("Teams commands", _run_inline("Teams commands", teams_commands)))

    print("\n" + "=" * 60)
    print("DEPLOY READY SUMMARY")
    print("=" * 60)
    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if failed:
        print(f"\n{len(failed)} suite(s) failed.")
        return 1
    print("\nAll automated deploy checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

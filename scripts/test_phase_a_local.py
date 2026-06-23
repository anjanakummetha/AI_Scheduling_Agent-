#!/usr/bin/env python3
"""Phase A local test battery — read-only UAT (no sends, no calendar writes).

Runs automated suites, unit tests, DB health probes, and graceful-failure checks.
Writes docs/PHASE_A_LOCAL_TEST_REPORT.json and docs/PHASE_A_LOCAL_TEST_REPORT.md.

Usage:
    .venv/bin/python scripts/test_phase_a_local.py
    .venv/bin/python scripts/test_phase_a_local.py --with-stack-verify
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

PY = sys.executable
REPORT_JSON = ROOT / "docs" / "PHASE_A_LOCAL_TEST_REPORT.json"
REPORT_MD = ROOT / "docs" / "PHASE_A_LOCAL_TEST_REPORT.md"


def _run_script(label: str, script: str, *args: str) -> dict[str, Any]:
    t0 = time.monotonic()
    cmd = [PY, str(ROOT / script), *args]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    elapsed = round(time.monotonic() - t0, 2)
    ok = result.returncode == 0
    return {
        "label": label,
        "ok": ok,
        "elapsed_s": elapsed,
        "cmd": " ".join(cmd),
        "stdout_tail": (result.stdout or "")[-2000:],
        "stderr_tail": (result.stderr or "")[-1000:] if not ok else "",
    }


def _run_inline(label: str, fn) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        fn()
        return {"label": label, "ok": True, "elapsed_s": round(time.monotonic() - t0, 2)}
    except Exception as exc:
        import traceback

        return {
            "label": label,
            "ok": False,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "error": str(exc),
            "traceback": traceback.format_exc()[-1500:],
        }


def _safety_env_check() -> dict[str, Any]:
    from app.config import settings

    required = {
        "LEXI_DRY_RUN": True,
        "LEXI_KORY_OUTBOUND_BLOCKED": True,
        "LEXI_KORY_SPACE_READ_ONLY": True,
    }
    actual = {
        "LEXI_DRY_RUN": settings.lexi_dry_run,
        "LEXI_KORY_OUTBOUND_BLOCKED": settings.lexi_kory_outbound_blocked,
        "LEXI_KORY_SPACE_READ_ONLY": settings.lexi_kory_space_read_only,
    }
    ok = all(actual[k] == v for k, v in required.items())
    return {"ok": ok, "required": required, "actual": actual}


def _db_health() -> dict[str, Any]:
    from app.config import settings

    db_path = Path(settings.lexi_database_path)
    if not db_path.exists():
        return {"ok": False, "error": f"DB missing: {db_path}"}

    size_mb = round(db_path.stat().st_size / (1024 * 1024), 3)
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for table in tables:
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            except sqlite3.Error:
                counts[table] = -1
        audit_rows = counts.get("audit_log", 0)
        proposals = counts.get("proposals", 0)
        warnings: list[str] = []
        if audit_rows > 50_000:
            warnings.append("audit_log >50k rows — add retention/archival job")
        if proposals > 10_000:
            warnings.append("proposals >10k — consider archival policy")
        if size_mb > 500:
            warnings.append(f"DB size {size_mb}MB — plan VACUUM + archival")
        return {
            "ok": True,
            "path": str(db_path),
            "size_mb": size_mb,
            "table_counts": counts,
            "warnings": warnings,
        }
    finally:
        conn.close()


def _graceful_failure_probes() -> None:
    from app.integrations.outlook_actions import execute_outlook_action
    from app.teams.commands import handle_teams_command

    bad = handle_teams_command("approve 999999999")
    assert bad.get("handled") is True
    assert bad.get("ok") is False

    help_r = handle_teams_command("help")
    assert help_r.get("handled") is True
    assert help_r.get("ok") is True

    try:
        execute_outlook_action(
            "OUTLOOK_DELETE_EMAIL",
            {"message_id": "fake"},
            confirm=False,
        )
        raise AssertionError("expected PermissionError for write without confirm")
    except PermissionError:
        pass


def _unit_tests() -> None:
    import unittest

    from tests.test_asana_reservation import (
        test_meal_from_intent,
        test_reservation_needed_for_lunch_intent,
        test_reservation_needed_from_draft_wording,
    )
    from tests.test_composio_search import (
        test_reject_non_search_slug,
        test_search_allowlist_includes_web_and_travel,
        test_search_enabled_is_bool,
    )
    from tests.test_delegation import (
        test_delegation_cc_and_phrase,
        test_delegation_phrase_from_kory,
        test_not_delegation_random_mail,
    )
    from tests.test_email_format import (
        test_adds_sign_off_when_missing,
        test_paragraph_spacing,
        test_sign_off_on_separate_lines,
    )
    from tests.test_inbound_filter import (
        test_calendar_accept_not_notified,
        test_delegation_always_notifies,
        test_scheduling_investor_not_notified_in_delegation_only_mode,
        test_scheduling_investor_notified_when_important_mode,
        test_ypo_digest_not_notified,
    )
    from tests.test_lexi_email_format import (
        test_lexi_dedupes_double_signoff,
        test_lexi_replaces_old_best_closing,
        test_lexi_signoff_block,
        test_lexi_strips_outlook_rich_signature_before_append,
        test_lexi_verify,
    )
    from tests.test_outlook_recipients import test_extract_cc_recipients
    from tests.test_person_research import test_scholar_slug_on_allowlist
    from tests.test_read_only_safety import (
        test_execute_outlook_deny_permanent_delete,
        test_execute_outlook_write_requires_confirm,
        test_kory_space_write_blocked_when_read_only,
        test_write_slug_detection,
    )

    for fn in (
        test_ypo_digest_not_notified,
        test_calendar_accept_not_notified,
        test_scheduling_investor_not_notified_in_delegation_only_mode,
        test_delegation_always_notifies,
        test_scheduling_investor_notified_when_important_mode,
        test_delegation_phrase_from_kory,
        test_delegation_cc_and_phrase,
        test_not_delegation_random_mail,
        test_write_slug_detection,
        test_kory_space_write_blocked_when_read_only,
        test_execute_outlook_write_requires_confirm,
        test_execute_outlook_deny_permanent_delete,
        test_sign_off_on_separate_lines,
        test_paragraph_spacing,
        test_adds_sign_off_when_missing,
        test_meal_from_intent,
        test_reservation_needed_for_lunch_intent,
        test_reservation_needed_from_draft_wording,
        test_lexi_signoff_block,
        test_lexi_replaces_old_best_closing,
        test_lexi_verify,
        test_lexi_dedupes_double_signoff,
        test_lexi_strips_outlook_rich_signature_before_append,
        test_extract_cc_recipients,
        test_search_enabled_is_bool,
        test_search_allowlist_includes_web_and_travel,
        test_reject_non_search_slug,
        test_scholar_slug_on_allowlist,
    ):
        fn()

    for suite_cls in (
        __import__("tests.test_teams_cards", fromlist=["TeamsApprovalCardTests"]).TeamsApprovalCardTests,
        __import__("tests.test_teams_card_submit", fromlist=["TeamsCardSubmitTests"]).TeamsCardSubmitTests,
        __import__("tests.test_teams_labels", fromlist=["TeamsLabelsTests"]).TeamsLabelsTests,
    ):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(suite_cls)
        result = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(suite)
        if not result.wasSuccessful():
            raise AssertionError(f"{suite_cls.__name__} failed: {result.failures} {result.errors}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-stack-verify",
        action="store_true",
        help="Include live Composio calendar/inbox reads (read-only)",
    )
    args = parser.parse_args()

    started = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []

    safety = _safety_env_check()
    results.append({"label": "UAT safety env locks", "ok": safety["ok"], "detail": safety})

    script_suites = [
        ("Read-only deploy locks", "scripts/verify_read_only_deploy.py"),
        ("Pre-Kory switch (read-only)", "scripts/verify_pre_kory_switch.py", "--read-only-uat"),
        ("Approval safety", "scripts/test_approval_safety.py"),
        ("MCP tools smoke", "scripts/test_mcp_tools.py"),
        ("Lexi pipeline (mocked)", "scripts/test_lexi_pipeline.py"),
        ("Kory phase suite", "scripts/test_kory_phase_suite.py", "--skip-live-llm", "--ci"),
        ("Context + rate limits", "scripts/test_context_rate_limits.py"),
        ("Long context + retention", "scripts/test_long_context.py"),
    ]
    if args.with_stack_verify:
        script_suites.append(("Stack verify (read Composio)", "scripts/verify_stack.py"))

    for entry in script_suites:
        label, script, *rest = entry
        results.append(_run_script(label, script, *rest))

    results.append(_run_inline("Unit tests (all)", _unit_tests))
    results.append(_run_inline("Graceful failure probes", _graceful_failure_probes))

    db = _db_health()
    results.append({"label": "DB health", "ok": db.get("ok", False), "detail": db})

    failed = [r for r in results if not r.get("ok")]
    passed = len(results) - len(failed)

    report: dict[str, Any] = {
        "generated_at": started,
        "phase": "A_local_read_only",
        "safety_env": safety,
        "summary": {
            "total_suites": len(results),
            "passed": passed,
            "failed": len(failed),
            "all_pass": len(failed) == 0,
        },
        "results": results,
        "skipped_intentionally": [
            "test_live_e2e.py (may place holds / send in non-UAT)",
            "test_deploy_ready.py Asana live smoke",
            "test_inbound_live.py",
            "Teams/Hermes interactive UAT (Phase B)",
        ],
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md_lines = [
        "# Phase A Local Test Report",
        "",
        f"Generated: `{started}`",
        "",
        "## Safety locks",
        "",
        f"- UAT env OK: **{'yes' if safety['ok'] else 'NO — fix .env'}**",
        "",
        "## Summary",
        "",
        f"- **{passed}/{len(results)}** suites passed",
        "",
    ]
    for r in results:
        mark = "PASS" if r.get("ok") else "FAIL"
        md_lines.append(f"- [{mark}] {r['label']}")
    if failed:
        md_lines.extend(["", "## Failures", ""])
        for r in failed:
            md_lines.append(f"### {r['label']}")
            if r.get("error"):
                md_lines.append(f"- Error: `{r['error']}`")
            if r.get("stderr_tail"):
                md_lines.append(f"```\n{r['stderr_tail'][-800:]}\n```")

    if db.get("warnings"):
        md_lines.extend(["", "## DB warnings", ""])
        for w in db["warnings"]:
            md_lines.append(f"- {w}")

    REPORT_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"PHASE A: {passed}/{len(results)} passed")
    print(f"Report: {REPORT_MD}")
    print("=" * 60)
    for r in results:
        print(f"  [{'PASS' if r.get('ok') else 'FAIL'}] {r['label']}")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

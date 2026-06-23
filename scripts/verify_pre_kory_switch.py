#!/usr/bin/env python3
"""Pre-flight before LEXI_WRITE_MODE=kory or production Teams cutover."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.assistant.actions import get_lexi_system_status
from app.config import settings
from app.integrations.named_calendars import (
    calendars_consulted_for_conflicts,
    list_all_calendars,
    primary_calendar_name,
)
from app.safety.approval_gate import (
    auto_execute_allowed,
    immediate_send_allowed,
    kory_approves_all,
    require_kory_approval_env,
)


def _check(name: str, ok: bool, detail: str = "") -> dict:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return {"name": name, "status": status, "detail": detail}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Pre-Kory-switch / Teams+Hermes readiness")
    parser.add_argument(
        "--read-only-uat",
        action="store_true",
        help="Check read-only UAT locks (dry_run ON) — use before thorough testing",
    )
    parser.add_argument(
        "--production-cutover",
        action="store_true",
        help="Check production cutover readiness (dry_run OFF, sends unlocked)",
    )
    args = parser.parse_args()
    read_only_uat = args.read_only_uat or not args.production_cutover

    if read_only_uat:
        print("\n=== Read-only UAT mode (recommended before live cutover) ===\n")
        print("  Run: .venv/bin/python scripts/verify_read_only_deploy.py\n")
        results: list[dict] = []
        results.append(_check("LEXI_DRY_RUN on", settings.lexi_dry_run))
        results.append(_check("LEXI_KORY_OUTBOUND_BLOCKED", settings.lexi_kory_outbound_blocked))
        results.append(_check("LEXI_KORY_SPACE_READ_ONLY", settings.lexi_kory_space_read_only))
        results.append(
            _check(
                "delegation_only inbound",
                settings.lexi_teams_inbound_notify_mode == "delegation_only",
                settings.lexi_teams_inbound_notify_mode,
            )
        )
        results.append(
            _check(
                "Read connection = Kory",
                bool(settings.kory_composio_connection_id),
                settings.kory_composio_connection_id or "missing",
            )
        )
        status = get_lexi_system_status()
        results.append(_check("Composio configured", bool(status.get("composio_configured"))))
        failed = sum(1 for r in results if r["status"] == "FAIL")
        out = ROOT / "docs" / "PRE_KORY_SWITCH_REPORT.json"
        out.write_text(
            json.dumps({"mode": "read_only_uat", "checks": results, "failed": failed}, indent=2),
            encoding="utf-8",
        )
        print(f"\nReport: {out}")
        print(f"Summary: {len(results) - failed}/{len(results)} passed\n")
        return 1 if failed else 0

    print("\n=== Production cutover readiness (LEXI_WRITE_MODE=kory) ===\n")
    results: list[dict] = []

    results.append(
        _check(
            "LEXI_WRITE_MODE",
            settings.lexi_write_mode in {"sandbox", "kory"},
            settings.lexi_write_mode,
        )
    )
    results.append(
        _check(
            "Read connection = Kory",
            bool(settings.kory_composio_connection_id),
            settings.kory_composio_connection_id or "missing",
        )
    )
    if settings.lexi_write_mode == "sandbox":
        results.append(
            _check(
                "Write connection = sandbox",
                bool(settings.sandbox_composio_connection_id),
                settings.sandbox_composio_connection_id or "missing",
            )
        )
    else:
        results.append(
            _check(
                "Write connection = Kory (real recipient sends)",
                bool(settings.kory_composio_connection_id),
                settings.kory_composio_connection_id or "missing",
            )
        )
    results.append(
        _check(
            "No email loopback",
            not settings.sandbox_email_loopback,
            "loopback off — sends go to actual recipient after approve",
        )
    )
    results.append(_check("LEXI_DRY_RUN off", not settings.lexi_dry_run))
    results.append(_check("kory_approves_all", kory_approves_all()))
    results.append(_check("LEXI_REQUIRE_KORY_APPROVAL", require_kory_approval_env()))
    results.append(_check("auto_execute off", not auto_execute_allowed()))
    results.append(_check("immediate_send off", not immediate_send_allowed()))
    poll_on = os.getenv("LEXI_ORCHESTRATOR_POLL_OUTLOOK", "true").lower() in {"1", "true", "yes"}
    webhook_on = os.getenv("LEXI_WEBHOOK_ENABLED", "false").lower() in {"1", "true", "yes"}
    results.append(
        _check(
            "Kory inbox ingress (poll or webhook)",
            poll_on or webhook_on,
            "poll" if poll_on else ("webhook" if webhook_on else "enable LEXI_ORCHESTRATOR_POLL_OUTLOOK"),
        )
    )

    status = get_lexi_system_status()
    results.append(_check("Composio configured", bool(status.get("composio_configured"))))

    try:
        cals = list_all_calendars(role="read")
        results.append(_check("Kory calendars visible", len(cals) >= 1, f"{len(cals)} calendars"))
        consulted = calendars_consulted_for_conflicts()
        resolved = sum(1 for c in consulted if c.get("resolved"))
        primary = primary_calendar_name()
        primary_ok = any(c.get("resolved") and c.get("primary") for c in consulted)
        results.append(
            _check(
                f"Primary calendar resolved ({primary})",
                primary_ok,
                "required for holds/events",
            )
        )
        optional_missing = [
            c["configured_name"]
            for c in consulted
            if not c.get("resolved") and not c.get("primary")
        ]
        results.append(
            _check(
                "Secondary conflict calendars (optional)",
                resolved >= 1,
                f"{resolved}/{len(consulted)} on account",
            )
        )
        if optional_missing:
            print(
                f"    Optional calendars not on Composio read (OK): {', '.join(optional_missing)}"
            )
    except Exception as exc:
        results.append(_check("Kory calendars visible", False, str(exc)))

    print("\n--- Teams → Hermes only ---")
    print("  Azure Bot messaging URL → https://<your-host>/api/messages  (Hermes :3978)")
    print("  ~/.hermes/.env + project .env: same TEAMS_CLIENT_ID/SECRET (cards)")
    print("  TEAMS_CONVERSATION_ID or lexi_register_teams_conversation after first DM")
    print("  Lexi worker: embedded in hermes_mcp_server.py (poll Kory inbox)")
    print("  Optional webhook: python -m app.worker --webhook  → :8780/webhooks/composio")

    print("\n--- Before LEXI_WRITE_MODE=kory ---")
    print("  1. Full test: .venv/bin/python scripts/test_kory_phase_suite.py")
    print("  2. Approval:  .venv/bin/python scripts/test_approval_safety.py")
    print("  3. E2E:       .venv/bin/python scripts/test_live_e2e.py --skip-approval")
    print("  4. UAT on sandbox with real scheduling threads")
    print("  5. Then only: LEXI_WRITE_MODE=kory + reconnect write Composio to Kory mailbox")

    failed = sum(1 for r in results if r["status"] == "FAIL")
    out = ROOT / "docs" / "PRE_KORY_SWITCH_REPORT.json"
    out.write_text(json.dumps({"checks": results, "failed": failed}, indent=2), encoding="utf-8")
    print(f"\nReport: {out}")
    print(f"Summary: {len(results) - failed}/{len(results)} passed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

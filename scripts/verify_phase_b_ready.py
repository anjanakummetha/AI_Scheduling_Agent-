#!/usr/bin/env python3
"""Phase B readiness gate — run before Teams/Hermes UAT.

Usage:
    .venv/bin/python scripts/verify_phase_b_ready.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

PY = sys.executable
REPORT = ROOT / "docs" / "PHASE_B_READY_REPORT.json"


def _run(script: str, *args: str) -> tuple[str, bool]:
    r = subprocess.run([PY, str(ROOT / script), *args], cwd=ROOT)
    return script, r.returncode == 0


def main() -> int:
    from app.config import settings

    print("\n" + "=" * 60)
    print("PHASE B READINESS GATE")
    print("=" * 60 + "\n")

    checks: list[dict] = []

    # Config expectations for Phase B
    config_checks = [
        ("LEXI_DRY_RUN", settings.lexi_dry_run, True, "blocks all writes during UAT"),
        ("LEXI_KORY_SPACE_READ_ONLY", settings.lexi_kory_space_read_only, True, "Kory mailbox/calendar protected"),
        ("LEXI_KORY_OUTBOUND_BLOCKED", settings.lexi_kory_outbound_blocked, True, "no send from Kory"),
        ("LEXI_WRITE_MODE=sandbox (recommended)", settings.lexi_write_mode == "sandbox" or settings.lexi_dry_run, True, f"mode={settings.lexi_write_mode} dry_run={settings.lexi_dry_run}"),
        ("SANDBOX_EMAIL_LOOPBACK", settings.sandbox_email_loopback or settings.lexi_dry_run, True, f"loopback={settings.sandbox_email_loopback}"),
        ("LEXI_DEFAULT_SEND_CHANNEL=kory", settings.lexi_default_send_channel == "kory", True, "lexi@ not configured"),
        ("No LEXI_COMPOSIO_CONNECTION_ID", not settings.lexi_composio_connection_id, True, "lexi mailbox off"),
        ("LLM_MODEL", bool(settings.llm_model), True, settings.llm_model),
        ("delegation_only inbound", settings.lexi_teams_inbound_notify_mode == "delegation_only", True, settings.lexi_teams_inbound_notify_mode),
        ("kory read connection", bool(settings.kory_composio_connection_id), True, "set"),
        ("LEXI_TEAMS_ENABLED", settings.lexi_teams_enabled, True, "proactive Adaptive Cards"),
    ]
    for name, actual, expected, detail in config_checks:
        ok = actual == expected if isinstance(expected, bool) else bool(actual)
        checks.append({"name": name, "ok": ok, "detail": str(detail)})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")

    suites = [
        "scripts/verify_read_only_deploy.py",
        "scripts/test_phase_a_local.py",
        "scripts/test_long_context.py",
        "scripts/verify_calendars_read.py",
        "scripts/verify_asana_board.py",
        "scripts/test_context_rate_limits.py",
        "scripts/verify_teams_connection.py",
    ]
    for script in suites:
        label, ok = _run(script)
        checks.append({"name": label, "ok": ok, "detail": "automated suite"})
        print(f"\n>>> {'PASS' if ok else 'FAIL'}: {label}")

    failed = [c for c in checks if not c["ok"]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready_for_phase_b": len(failed) == 0,
        "checks": checks,
        "failed_count": len(failed),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    if failed:
        print(f"NOT READY — {len(failed)} check(s) failed")
        print(f"Report: {REPORT}")
        return 1
    print("READY FOR PHASE B (Teams/Hermes UAT)")
    print("Locks remain ON — no Kory sends, no lexi@ sends.")
    print(f"Report: {REPORT}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

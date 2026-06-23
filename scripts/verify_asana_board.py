#!/usr/bin/env python3
"""Verify Asana Reservation Reminders board (read-only or dry-run create)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import ASANA_BOARD_NAME, ASANA_PARENT_PROJECT_NAME, settings
from app.integrations.asana_manager import create_booking_reminder_task


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def main() -> int:
    print(f"\n=== Asana board: {ASANA_BOARD_NAME} ({ASANA_PARENT_PROJECT_NAME}) ===\n")
    ok = True
    ok &= _check("ASANA_ENABLED", settings.asana_enabled)
    ok &= _check("ASANA_PROJECT_GID set", bool(settings.asana_project_gid), settings.asana_project_gid or "")
    ok &= _check(
        "ASANA_COMPOSIO_CONNECTION_ID set",
        bool(settings.asana_composio_connection_id),
        (settings.asana_composio_connection_id or "")[:12] + "...",
    )

    # Dry-run path: validates logic without live task when simulate triggers
    result = create_booking_reminder_task(
        meal="dinner",
        meeting_subject="[Lexi verify — safe to delete]",
        thread_id="verify-asana",
        sender="verify@test.local",
        body_excerpt="Automated board connectivity check.",
        approved=True,
    )
    ok &= _check(
        "create_booking_reminder_task",
        result.get("ok") is True,
        f"simulated={result.get('simulated')} dry_run_task={str(result.get('task_id', '')).startswith('asana-dry-run')}",
    )
    if result.get("error"):
        print(f"  note: {result['error']}")

    if settings.lexi_dry_run and not result.get("simulated"):
        print("\n  (LEXI_DRY_RUN blocks live Asana writes at Composio layer — logic path OK)")

    print(f"\n{'ALL PASS' if ok else 'SOME CHECKS FAILED'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

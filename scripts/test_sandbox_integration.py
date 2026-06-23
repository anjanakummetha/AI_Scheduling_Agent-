#!/usr/bin/env python3
"""Integration test: read Kory calendar, write sandbox hold + loopback email."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import settings
from app.integrations.calendar_holds import place_tentative_hold
from app.integrations.outlook_calendar import get_calendar_events
from app.integrations.outlook_email import send_outbound_email


def main() -> int:
    print("\n=== Lexi Sandbox Integration ===\n")
    print(f"  write_mode={settings.lexi_write_mode} dry_run={settings.lexi_dry_run}")
    print(f"  read={settings.kory_composio_connection_id}")
    print(f"  write={settings.sandbox_composio_connection_id} → {settings.sandbox_mailbox_email}\n")

    start = datetime.now(timezone.utc)
    end = start + timedelta(days=3)
    events, log_id = get_calendar_events(start.isoformat(), end.isoformat())
    print(f"[ok] Kory calendar read: {len(events)} events (log={log_id})")

    slot_start = (start + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    slot_end = slot_start + timedelta(hours=1)
    hold = place_tentative_hold(
        title="Lexi integration test hold",
        start_iso=slot_start.isoformat(),
        end_iso=slot_end.isoformat(),
    )
    print(f"[{'ok' if hold.get('ok') else 'FAIL'}] Sandbox hold: {hold}")

    msg_id, send_log = send_outbound_email(
        to_email="external@example.com",
        subject="Lexi sandbox loopback test",
        body="This email should arrive at your sandbox mailbox only.",
        approved_send=True,
    )
    print(f"[{'ok' if msg_id else 'FAIL'}] Loopback email: id={msg_id} log={send_log}")

    if settings.asana_enabled and settings.asana_project_gid:
        from app.integrations.asana_manager import create_booking_reminder_task

        asana = create_booking_reminder_task(
            meal="lunch",
            meeting_subject="Integration test reservation",
            thread_id="test",
            sender="test",
        )
        print(f"[{'ok' if asana.get('ok') else 'warn'}] Asana: {asana.get('error') or asana.get('task_id')}")
    else:
        print("[skip] Asana — set ASANA_ENABLED=true to test (paused for now)")

    print("\nDone.\n")
    return 0 if hold.get("ok") and msg_id else 1


if __name__ == "__main__":
    raise SystemExit(main())

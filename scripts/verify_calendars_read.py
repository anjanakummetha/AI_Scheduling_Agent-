#!/usr/bin/env python3
"""Verify configured conflict calendars resolve on Kory's Composio read connection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.integrations.named_calendars import (
    calendars_consulted_for_conflicts,
    get_calendar_events_by_name,
    list_all_calendars,
    primary_calendar_name,
    resolve_calendar_name,
)


def main() -> int:
    print("\n=== Calendar read/write resolution (read-only) ===\n")
    primary = primary_calendar_name()
    print(f"Primary / default write: {primary}\n")

    try:
        all_cals = list_all_calendars(role="read")
        print(f"Kory account calendars visible: {len(all_cals)}")
        for cal in all_cals[:15]:
            edit = cal.get("can_edit")
            print(f"  • {cal['name']} (can_edit={edit})")
        if len(all_cals) > 15:
            print(f"  … and {len(all_cals) - 15} more")
    except Exception as exc:
        print(f"FAIL list calendars: {exc}")
        return 1

    print("\n--- Conflict calendars (config/calendars.yaml) ---")
    consulted = calendars_consulted_for_conflicts()
    failed = 0
    for entry in consulted:
        name = entry.get("configured_name") or entry.get("name")
        if entry.get("resolved"):
            status = "PASS"
            detail = f"id={entry.get('id')} can_edit={entry.get('can_edit')}"
        else:
            status = "FAIL"
            detail = entry.get("reason", "not_on_account")
            if not entry.get("primary"):
                failed += 1
        print(f"  [{status}] {name} — {detail}")

    print("\n--- Sample 7-day read per resolved calendar ---")
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Denver")
    start = datetime.now(tz=tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    for entry in consulted:
        if not entry.get("resolved"):
            continue
        name = entry.get("name") or entry.get("configured_name")
        events, _ = get_calendar_events_by_name(name, start_iso, end_iso, role="read")
        print(f"  {name}: {len(events)} blocking events in next 7d (read)")

    write_cal = resolve_calendar_name(primary, role="write")
    print(f"\n--- Write target (dry-run only; no events created) ---")
    if write_cal:
        print(f"  PASS resolved write calendar: {write_cal['name']} can_edit={write_cal.get('can_edit')}")
    else:
        print(f"  WARN write calendar '{primary}' not resolved on write connection")
        failed += 1

    out = ROOT / "docs" / "CALENDAR_VERIFY_REPORT.json"
    out.write_text(
        json.dumps({"consulted": consulted, "failed": failed, "primary": primary}, indent=2),
        encoding="utf-8",
    )
    print(f"\nReport: {out}")
    print(f"Summary: {len(consulted) - failed}/{len(consulted)} conflict calendars OK\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Long-context and session compaction stress tests (no sends).

Usage:
    .venv/bin/python scripts/test_long_context.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def main() -> int:
    from app.config import settings
    from app.jobs.db_maintenance import db_health_snapshot, run_db_maintenance_cycle
    from app.storage.scheduling_sessions import (
        SESSION_CONTEXT_MAX_CHARS,
        create_session,
        get_session,
        update_session,
    )

    print("\n=== Long-context + retention safeguards ===\n")
    passed = 0
    total = 0

    # 1. Oversized session context compacts
    sid = create_session(channel="longctx-test", context={"attendee": "Jane"})
    huge = {
        "attendee": "Jane Doe",
        "topic": "diligence",
        "search_dump": "x" * 50_000,
        "email_body": "y" * 30_000,
        "slots": [{"start": "2026-06-20T14:00:00", "end": "2026-06-20T15:00:00"}] * 20,
    }
    update_session(sid, context=huge)
    row = get_session(sid)
    serialized = json.dumps(row.get("context") or {}, default=str)
    total += 1
    if _check(
        "session context compacted under cap",
        len(serialized) <= SESSION_CONTEXT_MAX_CHARS + 500,
        f"len={len(serialized)} cap={SESSION_CONTEXT_MAX_CHARS}",
    ):
        passed += 1
    total += 1
    if _check(
        "essential keys preserved after compaction",
        (row.get("context") or {}).get("attendee") == "Jane Doe",
    ):
        passed += 1

    # 2. Calendar cap
    from app.assistant.actions import get_calendar_availability

    avail = get_calendar_availability(days=30)
    busy = avail.get("busy_events") or []
    total += 1
    if _check("calendar returns <=80 events", len(busy) <= 80, f"count={len(busy)}"):
        passed += 1

    # 3. DB maintenance runs without error
    maint = run_db_maintenance_cycle()
    total += 1
    if _check("db maintenance cycle", "error" not in maint, str(maint)[:120]):
        passed += 1

    # 4. Health snapshot
    health = db_health_snapshot()
    total += 1
    if _check("db health snapshot", health.get("ok") is True, f"size={health.get('size_mb')}MB"):
        passed += 1

    # 5. LLM model configured
    total += 1
    if _check(
        "LLM model set for production agent",
        bool(settings.llm_model),
        settings.llm_model,
    ):
        passed += 1

    # 6. Per-session limits documented
    instructions = (ROOT / "agent_instructions.txt").read_text(encoding="utf-8")
    total += 1
    if _check(
        "agent_instructions per-session limits",
        "32k" in instructions and "80 busy" in instructions.lower(),
    ):
        passed += 1

    limits = {
        "hermes_model_window_tokens": "~200000 (Claude Sonnet 4.6)",
        "scheduling_session_max_chars": SESSION_CONTEXT_MAX_CHARS,
        "calendar_busy_events_max": 80,
        "search_min_interval_sec": 1.0,
        "recommended_max_tool_turns_per_chat": 25,
        "llm_model": settings.llm_model,
    }
    out = ROOT / "docs" / "LONG_CONTEXT_LIMITS.json"
    out.write_text(json.dumps({"passed": passed, "total": total, "limits": limits}, indent=2))

    print(f"\nSummary: {passed}/{total} passed")
    print(f"Limits: {json.dumps(limits, indent=2)}")
    print(f"Report: {out}\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

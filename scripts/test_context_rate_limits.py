#!/usr/bin/env python3
"""Context limits + search throttle checks (no Anthropic 429 hammering).

Usage:
    .venv/bin/python scripts/test_context_rate_limits.py
    .venv/bin/python scripts/test_context_rate_limits.py --live-research "Jane Doe Acme Corp"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-research", default="", help="Optional live lexi_research_person name")
    args = parser.parse_args()

    print("\n=== Context + rate-limit safeguards ===\n")
    passed = 0
    total = 0

    # 1. Scheduling session round-trip (long-context substitute)
    from app.storage.scheduling_sessions import create_session, get_session, update_session

    sid = create_session(channel="test", context={"attendee": "Jane Doe", "topic": "diligence"})
    total += 1
    if _check("scheduling_session create", bool(sid), sid[:20]):
        passed += 1
    update_session(sid, context={"attendee": "Jane Doe", "company": "Acme", "draft_v2": "..."})
    row = get_session(sid)
    total += 1
    if _check(
        "scheduling_session persists context",
        row is not None and row.get("context", {}).get("company") == "Acme",
    ):
        passed += 1

    # 2. Calendar payload cap (token bloat guard)
    from app.assistant.actions import get_calendar_availability

    avail = get_calendar_availability(days=14)
    busy = avail.get("busy_events") or []
    total += 1
    if _check("calendar busy_events capped at 80", len(busy) <= 80, f"count={len(busy)}"):
        passed += 1

    # 3. Search throttle spacing
    from app.integrations.person_research import SEARCH_MIN_INTERVAL_SEC, throttle_search_calls

    t0 = time.monotonic()
    throttle_search_calls()
    throttle_search_calls()
    elapsed = time.monotonic() - t0
    total += 1
    if _check(
        "search throttle enforces min interval",
        elapsed >= SEARCH_MIN_INTERVAL_SEC * 0.9,
        f"{elapsed:.2f}s >= ~{SEARCH_MIN_INTERVAL_SEC}s",
    ):
        passed += 1

    # 4. MCP tool registered
    server = (ROOT / "hermes_mcp_server.py").read_text(encoding="utf-8")
    total += 1
    if _check("lexi_research_person in MCP server", "lexi_research_person" in server):
        passed += 1

    # 5. Agent instructions mention sessions + throttle
    instructions = (ROOT / "agent_instructions.txt").read_text(encoding="utf-8")
    total += 1
    if _check(
        "agent_instructions: scheduling_sessions + rate limits",
        "scheduling_session" in instructions
        and ("1 second between" in instructions or "Composio Search" in instructions),
    ):
        passed += 1

    if args.live_research.strip():
        print("\n--- Live attendee research (Composio API calls) ---")
        from app.integrations.person_research import research_person

        try:
            out = research_person(args.live_research.strip(), company="", include_inbox=True)
            preview = json.dumps(out, default=str)[:2500]
            print(preview)
            total += 1
            if _check("live research_person", bool(out.get("web_summary"))):
                passed += 1
        except Exception as exc:
            total += 1
            _check("live research_person", False, str(exc))

    print(f"\nSummary: {passed}/{total} passed\n")
    out_path = ROOT / "docs" / "CONTEXT_RATE_LIMIT_REPORT.json"
    out_path.write_text(
        json.dumps({"passed": passed, "total": total}, indent=2),
        encoding="utf-8",
    )
    print(f"Report: {out_path}\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

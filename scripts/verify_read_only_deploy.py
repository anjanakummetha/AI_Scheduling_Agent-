#!/usr/bin/env python3
"""Verify Lexi is locked for read-only UAT (no sends, no Kory space writes).

Usage:
    .venv/bin/python scripts/verify_read_only_deploy.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import settings
from app.safety.kory_read_only import (
    assert_kory_space_write_allowed,
    is_outlook_write_slug,
    read_only_safety_snapshot,
)


def _check(name: str, ok: bool, detail: str = "") -> dict:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return {"name": name, "status": status, "detail": detail}


def main() -> int:
    print("\n=== Read-only UAT deploy verification ===\n")
    results: list[dict] = []

    snap = read_only_safety_snapshot()
    results.append(_check("LEXI_DRY_RUN=true", snap["lexi_dry_run"]))
    results.append(
        _check("LEXI_KORY_OUTBOUND_BLOCKED=true", snap["lexi_kory_outbound_blocked"])
    )
    results.append(
        _check("LEXI_KORY_SPACE_READ_ONLY=true", snap["lexi_kory_space_read_only"])
    )
    results.append(
        _check(
            "Inbound notify = delegation_only",
            settings.lexi_teams_inbound_notify_mode == "delegation_only",
            settings.lexi_teams_inbound_notify_mode,
        )
    )
    results.append(
        _check(
            "Delegation auto-draft enabled",
            settings.lexi_delegation_auto_draft,
        )
    )
    results.append(
        _check(
            "Kory read connection configured",
            bool(settings.kory_composio_connection_id),
            settings.kory_composio_connection_id or "missing (OK for mock tests)",
        )
    )

    # Runtime guard: writes to Kory connection must raise.
    kory_id = settings.kory_composio_connection_id or "ca_test_kory"
    blocked = False
    try:
        assert_kory_space_write_allowed(
            tool_slug="OUTLOOK_SEND_EMAIL",
            connection_id=kory_id,
        )
    except PermissionError:
        blocked = True
    results.append(_check("Kory write guard blocks OUTLOOK_SEND_EMAIL", blocked))

    read_ok = False
    try:
        assert_kory_space_write_allowed(
            tool_slug="OUTLOOK_LIST_MESSAGES",
            connection_id=kory_id,
        )
        read_ok = True
    except PermissionError:
        pass
    results.append(_check("Read slugs allowed through guard", read_ok))

    results.append(
        _check(
            "Write slug detection",
            is_outlook_write_slug("OUTLOOK_CREATE_CALENDAR_EVENT"),
        )
    )

    failed = sum(1 for r in results if r["status"] == "FAIL")
    critical = [r for r in results[:3] + [results[6]] if r["status"] == "FAIL"]

    out = ROOT / "docs" / "READ_ONLY_DEPLOY_REPORT.json"
    out.write_text(
        json.dumps({"checks": results, "failed": failed, "critical_failed": len(critical)}, indent=2),
        encoding="utf-8",
    )
    print(f"\nReport: {out}")
    print(f"Summary: {len(results) - failed}/{len(results)} passed")
    if critical:
        print(f"\n{len(critical)} CRITICAL safety check(s) failed — do not UAT until fixed.\n")
        return 1
    print("\nRead-only UAT locks are ON. Safe for thorough testing (no live sends/writes).\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

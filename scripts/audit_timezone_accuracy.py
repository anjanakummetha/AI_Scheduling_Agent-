#!/usr/bin/env python3
"""Audit recipient timezone detection against Kory inbox + known fixtures."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.integrations.outlook_inbox import get_thread_message, search_inbox
from app.scheduling.timezone_intel import (
    detect_recipient_timezone,
    extract_internet_headers,
    is_timezone_uncertain,
)

# Expected IANA substring per sender/domain (manual labels from Kory scheduling threads).
KNOWN_EXPECTATIONS: dict[str, str] = {
    "newportadvisors.co": "New_York",
    "solamerecapital.com": "New_York",
    "daybreakadvisory.com": "Los_Angeles",
    "price.co": "Los_Angeles",
}

FIXTURES: list[dict[str, Any]] = [
    {
        "label": "Newport Advisors (domain)",
        "sender": "bill.heermann@newportadvisors.co",
        "body": "Kory — can we schedule a diligence call next week?",
        "expect": "New_York",
    },
    {
        "label": "Chicago signature",
        "sender": "mike@constructioncpa.com",
        "body": "Thanks!\n\nMike Smith\nChicago, IL 60601\nO: (312) 555-0100",
        "expect": "Chicago",
    },
    {
        "label": "Austin area code",
        "sender": "founder@startup.io",
        "body": "Happy to meet.\n\nJane\n(512) 270-4805",
        "expect": "Chicago",
    },
    {
        "label": "Eastern explicit",
        "sender": "x@unknown.io",
        "body": "I'm in Eastern time — Tuesday works.",
        "expect": "New_York",
    },
    {
        "label": "Unknown startup",
        "sender": "sam@unknown-startup.io",
        "body": "Thanks — any time next week works.",
        "expect": None,
    },
    {
        "label": "Quoted Kory Denver must not leak",
        "sender": "cnbrymer@gmail.com",
        "body": (
            "Sounds good.\n\nFrom: Kory Mitchell <kory@iconicfounders.com>\n"
            "Denver, Colorado\n"
        ),
        "expect": None,
    },
]


def _domain_expectation(sender: str) -> str | None:
    if not sender or "@" not in sender:
        return None
    domain = sender.split("@", 1)[1].lower()
    for pattern, iana_part in KNOWN_EXPECTATIONS.items():
        if domain == pattern or domain.endswith("." + pattern):
            return iana_part
    return None


def _matches_expectation(result_tz: str | None, expect: str | None) -> bool:
    if expect is None:
        return result_tz is None
    if not result_tz:
        return False
    return expect in result_tz


def audit_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    result = detect_recipient_timezone(
        sender_email=fixture.get("sender"),
        body=str(fixture.get("body") or ""),
        allow_prior_threads=False,
    )
    tz_name = result.tz_name()
    expect = fixture.get("expect")
    ok = _matches_expectation(tz_name, expect)
    return {
        "label": fixture.get("label"),
        "sender": fixture.get("sender"),
        "expected": expect,
        "detected": tz_name,
        "source": result.source,
        "confidence": result.confidence,
        "uncertain": is_timezone_uncertain(result),
        "ok": ok,
    }


def audit_live_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    sender = str(msg.get("sender") or "")
    if not sender or "iconicfounders" in sender.lower() or "ifg.vc" in sender.lower():
        return None
    if str(msg.get("sender") or "").startswith("noreply@"):
        return None

    body = str(msg.get("preview") or "")
    headers: list[dict[str, Any]] = []
    message_id = msg.get("message_id")
    if message_id:
        try:
            full = get_thread_message(str(message_id))
            body = str(full.get("body") or body)
        except Exception:
            pass

    result = detect_recipient_timezone(
        sender_email=sender,
        body=body,
        internet_headers=headers,
        received_at=str(msg.get("received_at") or "") or None,
        allow_prior_threads=True,
    )
    domain_expect = _domain_expectation(sender)
    tz_name = result.tz_name()
    uncertain = is_timezone_uncertain(result)

    ok: bool | None = None
    if domain_expect and not uncertain:
        ok = _matches_expectation(tz_name, domain_expect)
    elif uncertain and domain_expect is None:
        ok = True  # correctly unknown for generic domains
    elif domain_expect and uncertain:
        ok = False  # missed known domain

    return {
        "subject": (msg.get("subject") or "")[:80],
        "sender": sender,
        "domain_expect": domain_expect,
        "detected": tz_name,
        "source": result.source,
        "confidence": result.confidence,
        "uncertain": uncertain,
        "ok": ok,
        "body_snippet": re.sub(r"\s+", " ", body[:200]).strip(),
    }


def main() -> int:
    print("Timezone detection audit\n")

    fixture_rows = [audit_fixture(f) for f in FIXTURES]
    fixture_pass = sum(1 for r in fixture_rows if r["ok"])
    print(f"Fixtures: {fixture_pass}/{len(fixture_rows)} passed")
    for row in fixture_rows:
        status = "PASS" if row["ok"] else "FAIL"
        print(
            f"  [{status}] {row['label']}: {row['detected']} "
            f"({row['source']}, expect={row['expected']})"
        )

    live_rows: list[dict[str, Any]] = []
    try:
        messages, log_id = search_inbox(top=25)
        print(f"\nLive inbox: {len(messages)} messages (log={log_id})")
        for msg in messages:
            row = audit_live_message(msg)
            if row:
                live_rows.append(row)
    except Exception as exc:
        print(f"\nLive inbox skipped: {exc}")

    scored = [r for r in live_rows if r.get("ok") is not None]
    live_pass = sum(1 for r in scored if r["ok"])
    print(f"Live scored: {live_pass}/{len(scored)} (of {len(live_rows)} external messages)")
    for row in live_rows[:12]:
        flag = "?" if row.get("ok") is None else ("PASS" if row["ok"] else "FAIL")
        print(
            f"  [{flag}] {row['sender'][:40]:40} | {row['detected']} "
            f"({row['source']}) | {(row.get('subject') or '')[:45]}"
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixtures": fixture_rows,
        "fixture_accuracy": fixture_pass / len(fixture_rows) if fixture_rows else 0,
        "live": live_rows,
        "live_accuracy_scored": live_pass / len(scored) if scored else None,
        "summary": {
            "fixture_pass": fixture_pass,
            "fixture_total": len(fixture_rows),
            "live_pass": live_pass,
            "live_scored": len(scored),
        },
    }
    out = ROOT / "docs" / "TIMEZONE_ACCURACY_AUDIT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nReport: {out}")

    fixture_ok = fixture_pass == len(fixture_rows)
    live_ok = not scored or live_pass / len(scored) >= 0.7
    return 0 if fixture_ok and live_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

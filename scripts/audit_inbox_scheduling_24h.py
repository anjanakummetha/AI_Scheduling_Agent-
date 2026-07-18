#!/usr/bin/env python3
"""Audit scheduling pipeline against Kory inbox — past 24 hours (no send, no holds)."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.agents.inbound_reply import is_scheduling_intent
from app.agents.triage_agent import _infer_intent_from_text
from app.integrations.outlook_inbox import get_thread_message, search_inbox
from app.scheduling.hermes_orchestrator import preview_scheduling_draft

SCHEDULING_SUBJECT_HINTS = re.compile(
    r"\b(?:schedule|scheduling|meet(?:ing)?\s+(?:with|next|up)|coffee|intro call|"
    r"catch[- ]?up|grab (?:time|30)|set up a call|find time|availability)\b",
    re.I,
)

NOT_SCHEDULING_HINTS = re.compile(
    r"\b(?:just messaged you|linkedin|newsletter|digest|unsubscribe|"
    r"payment|invoice|receipt|netsuite)\b",
    re.I,
)


def _is_external(sender: str | None) -> bool:
    if not sender:
        return False
    lower = sender.lower()
    return "iconicfounders.com" not in lower and "ifg.vc" not in lower


def _looks_scheduling(msg: dict[str, Any], body: str) -> tuple[bool, str]:
    subject = str(msg.get("subject") or "")
    sender = str(msg.get("sender") or "")
    if not _is_external(sender):
        return False, "internal"
    if str(sender).startswith("noreply@"):
        return False, "noreply"

    try:
        intent_name = _infer_intent_from_text(subject, body[:4000])
    except Exception:
        intent_name = ""

    if is_scheduling_intent(intent_name):
        return True, intent_name or "scheduling_intent"

    combined = f"{subject}\n{body[:2000]}"
    if NOT_SCHEDULING_HINTS.search(combined):
        return False, "not_scheduling_noise"

    if subject.lower().startswith(("re:", "fw:", "fwd:")):
        if SCHEDULING_SUBJECT_HINTS.search(combined) or re.search(
            r"\b(?:times?|available|schedule|meet|coffee|call|intro)\b", combined, re.I
        ):
            return True, intent_name or "reply_thread"

    if SCHEDULING_SUBJECT_HINTS.search(combined) and re.search(
        r"\b(?:next week|this week|tomorrow|schedule|grab|times? that work)\b",
        combined,
        re.I,
    ):
        return True, intent_name or "keyword_match"

    return False, intent_name or "not_scheduling"


def _within_24h(received_at: str | None) -> bool:
    if not received_at:
        return True
    try:
        ts = datetime.fromisoformat(str(received_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts >= datetime.now(timezone.utc) - timedelta(hours=24)
    except (TypeError, ValueError):
        return True


def audit_message(msg: dict[str, Any], *, calendar_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not _within_24h(msg.get("received_at")):
        return None

    body = str(msg.get("preview") or "")
    message_id = msg.get("message_id")
    if message_id:
        try:
            full = get_thread_message(str(message_id))
            body = str(full.get("body") or body)
        except Exception as exc:
            body = body or ""
            fetch_error = str(exc)
        else:
            fetch_error = ""
    else:
        fetch_error = "no_message_id"

    is_sched, reason = _looks_scheduling(msg, body)
    if not is_sched:
        return None

    sender = str(msg.get("sender") or "")
    outcome = preview_scheduling_draft(
        subject=str(msg.get("subject") or ""),
        body=body,
        sender_email=str(msg.get("sender") or "") or None,
        intent=reason if reason not in {"keyword_match", "scheduling_intent"} else None,
        calendar_context=calendar_context,
    )

    sched = outcome.get("scheduling") or {}
    draft = str(outcome.get("drafted_reply") or "")
    ok = bool(outcome.get("ok"))
    has_slots = len(sched.get("slots") or outcome.get("slots") or []) >= 2
    has_tz = bool(sched.get("recipient_timezone")) or sched.get("timezone_uncertain")
    has_formatted = len(sched.get("formatted_slots") or outcome.get("formatted_slots") or []) >= 2
    draft_has_times = bool(re.search(r"\d{1,2}:\d{2}\s*[AP]M", draft, re.I)) if draft else False

    checks = {
        "slots_found": has_slots,
        "timezone_handled": has_tz,
        "formatted_slots": has_formatted,
        "draft_has_times": draft_has_times or not ok,
        "draft_nonempty": bool(draft) or not ok,
    }
    passed = all(checks.values()) if ok else (not ok and checks["draft_nonempty"])

    return {
        "subject": (msg.get("subject") or "")[:90],
        "sender": msg.get("sender"),
        "received_at": msg.get("received_at"),
        "scheduling_reason": reason,
        "ok": ok,
        "path": sched.get("path") or outcome.get("path"),
        "status": sched.get("status") or outcome.get("status"),
        "timezone": sched.get("recipient_timezone"),
        "timezone_uncertain": sched.get("timezone_uncertain"),
        "timezone_source": sched.get("recipient_timezone_source"),
        "formatted_slots": sched.get("formatted_slots") or outcome.get("formatted_slots"),
        "slot_count": len(sched.get("slots") or []),
        "checks": checks,
        "passed": passed,
        "error": outcome.get("error") or sched.get("failure_message"),
        "draft_preview": draft[:500] if draft else "",
        "fetch_error": fetch_error,
    }


def main() -> int:
    print("Inbox scheduling audit — past 24 hours (dry run, no sends)\n")
    rows: list[dict[str, Any]] = []
    try:
        messages, log_id = search_inbox(top=30)
        print(f"Fetched {len(messages)} recent messages (log={log_id})", flush=True)
    except Exception as exc:
        print(f"Inbox read failed: {exc}")
        return 1

    from app.scheduling.calendar_context import load_scheduling_calendar_context

    print("Loading calendar context (once)...", flush=True)
    shared_calendar = load_scheduling_calendar_context()
    print(f"  Calendar status: {shared_calendar.get('status')}", flush=True)

    for msg in messages:
        preview = str(msg.get("preview") or "")
        if not _within_24h(msg.get("received_at")):
            continue
        quick_sched, _ = _looks_scheduling(msg, preview)
        if not quick_sched:
            continue
        print(f"  Auditing: {(msg.get('subject') or '')[:60]}", flush=True)
        row = audit_message(msg, calendar_context=shared_calendar)
        if row:
            rows.append(row)

    passed = sum(1 for r in rows if r["passed"])
    ok_count = sum(1 for r in rows if r["ok"])
    print(f"\nScheduling emails (24h): {len(rows)}")
    print(f"Engine found slots: {ok_count}/{len(rows)}")
    print(f"Full checks passed: {passed}/{len(rows)}\n")

    for row in rows:
        flag = "PASS" if row["passed"] else ("PARTIAL" if row["ok"] else "FAIL")
        tz = row.get("timezone") or ("uncertain" if row.get("timezone_uncertain") else "?")
        print(
            f"  [{flag}] {str(row['sender'])[:38]:38} | {tz:22} | "
            f"slots={row['slot_count']} | {(row.get('subject') or '')[:50]}"
        )
        if not row["passed"] and row.get("error"):
            print(f"         → {row['error'][:120]}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": 24,
        "dry_run": True,
        "results": rows,
        "summary": {
            "total": len(rows),
            "engine_ok": ok_count,
            "checks_passed": passed,
        },
    }
    out = ROOT / "docs" / "INBOX_SCHEDULING_24H_AUDIT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nReport: {out}")
    return 0 if rows and passed == len(rows) else (0 if not rows else 1)


if __name__ == "__main__":
    raise SystemExit(main())

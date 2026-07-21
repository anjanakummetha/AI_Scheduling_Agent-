#!/usr/bin/env python3
"""Rung 0 — realistic scheduling scenarios (final-phase testing, DRY-RUN).

Runs the FULL agent pipeline (triage → scheduling → proposal → draft → approval
simulation) on the kinds of emails Kory actually receives. Everything is dry-run:
holds/sends are previewed, never executed; nothing changes in Outlook/Asana/HubSpot.
The resulting pending proposals persist to the test DB so the dashboard's Lexi
Assistant panel shows realistic data.

Run:  LEXI_ENV=testing .venv/bin/python scripts/rung0_realistic_scenarios.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LEXI_ENV", "testing")
os.environ["LEXI_DRY_RUN"] = "true"
os.environ["LEXI_KORY_SPACE_READ_ONLY"] = "true"
os.environ["LEXI_KORY_OUTBOUND_BLOCKED"] = "true"
os.environ["LEXI_WRITE_MODE"] = "sandbox"

from scripts.init_lexi_db import init_lexi_db

init_lexi_db()

# Realistic inbound scheduling emails (sanitized senders; real Kory rule surface).
SCENARIOS = [
    {
        "label": "Referral intro (30-min Teams)",
        "subject": "Intro: Steve Quinn (ICCI) <> Kory/Heidi",
        "sender": "steve.quinn@icci.example.com",
        "body": "Hi Kory — great connecting via Matt. Could we grab 30 minutes on Teams next week to explore how IFG might help? Flexible on timing.",
    },
    {
        "label": "Coffee in Cherry Creek",
        "subject": "Coffee next week?",
        "sender": "dana.reeves@example.com",
        "body": "Kory, would love to grab coffee in Cherry Creek soon. I'm flexible in the mornings. — Dana",
    },
    {
        "label": "New client (60-min)",
        "subject": "Exploring working with IFG",
        "sender": "founder@peakenv.example.com",
        "body": "We're raising and would love to explore working with Iconic Founders. Could we get an hour on your calendar in the next couple weeks?",
    },
    {
        "label": "East-Coast investor (early call)",
        "subject": "Quick call from NYC",
        "sender": "gp@investorfirm.example.com",
        "body": "I'm based in New York — could we do an early call? I'm free 6–7am Eastern most days this week. 30 minutes is plenty.",
    },
    {
        "label": "Happy hour",
        "subject": "Drinks to catch up?",
        "sender": "jared@example.com",
        "body": "Kory — want to grab drinks one evening this week and catch up? — Jared",
    },
    {
        "label": "Dinner (Cherry Creek)",
        "subject": "Dinner sometime?",
        "sender": "calae@example.com",
        "body": "Let's finally do that dinner in Cherry Creek. What evening works for you?",
    },
    {
        "label": "Reschedule request",
        "subject": "Re: Kory / Carruthers check in",
        "sender": "bryan.carruthers@example.com",
        "body": "Something came up on my end — can we move our check-in to later next week? Sorry for the shuffle.",
    },
    {
        "label": "Podcast recording (The Turn)",
        "subject": "The Turn podcast — record an episode?",
        "sender": "producer@theturn.example.com",
        "body": "We'd love to have you record a Turn podcast episode. It's about an hour. No rush on timing — whenever works.",
    },
    {
        "label": "Weekend ask (should defer to Kory)",
        "subject": "Free Saturday?",
        "sender": "weekend@example.com",
        "body": "Any chance you're free this Saturday for a quick call?",
    },
    {
        "label": "Lunch ask (exception-only → Kory)",
        "subject": "Lunch this week?",
        "sender": "lunchbuddy@example.com",
        "body": "Would you be up for lunch this week? I know you're busy — happy to come to Cherry Creek.",
    },
]

RESULTS = []


def run_scenario(s: dict) -> dict:
    from app.agents.triage_agent import process_new_email
    from app.agents.inbound_reply import begin_draft_reply
    from app.storage.lexi_store import get_proposal

    thread = f"rung0-{uuid.uuid4().hex[:8]}"
    email = {
        "thread_id": thread,
        "conversation_id": thread,
        "subject": s["subject"],
        "from": {"emailAddress": {"address": s["sender"], "name": s["sender"].split("@")[0]}},
        "to_recipients": ["kory.mitchell@iconicfounders.com"],
        "body": s["body"],
        "raw_body": s["body"],
        "receivedDateTime": "2026-07-20T15:00:00Z",
    }
    pid = process_new_email(email)
    if not pid:
        return {"label": s["label"], "status": "NO_PROPOSAL", "detail": "triage produced no proposal"}

    # Full scheduling → draft → pending_approval (all dry-run).
    draft = begin_draft_reply(pid)
    prop = get_proposal(pid) or {}
    slots = prop.get("proposed_slots") or []
    holds = prop.get("holds") or []
    status = prop.get("status")
    intent = prop.get("intent_classification")

    # A "real write" would be a non-dry-run hold event id; assert none.
    real_writes = [h for h in holds if h.get("event_id") and "dry-run" not in str(h.get("event_id")).lower()
                   and not str(h.get("event_id")).startswith("hold-pending-")]

    first = ""
    if slots:
        first = str(slots[0].get("start", ""))[:16]
    outcome = (
        "OFFERED" if slots else
        ("ASK_KORY" if status in ("needs_kory", "awaiting_reply_prompt") else "NO_SLOTS")
    )
    return {
        "label": s["label"],
        "status": "PASS" if not real_writes else "REAL_WRITE!",
        "pid": pid,
        "intent": intent,
        "outcome": outcome,
        "slots": len(slots),
        "first": first,
        "holds_previewed": len(holds),
        "draft_len": len(str(prop.get("drafted_reply") or "")),
    }


def main() -> int:
    print("\n=== Rung 0 — realistic scheduling scenarios (DRY-RUN, no real changes) ===\n")
    for s in SCENARIOS:
        try:
            RESULTS.append(run_scenario(s))
        except Exception as exc:  # noqa: BLE001
            RESULTS.append({"label": s["label"], "status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"[:160]})

    width = max(len(r["label"]) for r in RESULTS)
    real_writes = 0
    for r in RESULTS:
        mark = "✅" if r.get("status") == "PASS" else ("⚠️ " if r.get("status") in ("NO_PROPOSAL",) else "❌")
        if r.get("status") == "REAL_WRITE!":
            real_writes += 1
        detail = r.get("detail") or (
            f"pid={r.get('pid')} intent={r.get('intent')} → {r.get('outcome')} "
            f"({r.get('slots')} slots, first={r.get('first')}, {r.get('holds_previewed')} holds previewed, draft {r.get('draft_len')}ch)"
        )
        print(f"  {mark} {r['label'].ljust(width)}  {detail}")

    passed = sum(1 for r in RESULTS if r.get("status") == "PASS")
    print(f"\n=== {passed}/{len(RESULTS)} scenarios processed cleanly; real writes: {real_writes} (must be 0) ===")
    # These proposals now sit pending in the DB — visible in the dashboard's Lexi panel.
    print("Proposals persisted (pending) for dashboard review.\n")
    return 1 if real_writes else 0


if __name__ == "__main__":
    raise SystemExit(main())

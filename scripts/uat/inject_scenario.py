"""Inject a realistic scheduling scenario through the FULL production inbound path
(handle_inbound_stream: triage -> schedule -> Teams approval-card push), safely.

Usage: scripts/uat/inject_scenario.py <scenario_key>
All sends/holds are dry-run (or sandbox-loopback); Kory's real surfaces are never written.
"""
from __future__ import annotations

import sys
import uuid
import json

KORY_CONN = "ca_qORrE-NzPib2"  # NEVER write this one

SCENARIOS = {
    "intro": {
        "subject": "TEST — Intro: Steve Quinn (ICCI) <> Kory",
        "sender": "anjana.kummetha@iconicfounders.com",
        "sender_name": "Steve Quinn",
        "body": "Hi Kory — great connecting via Matt. Could we grab 30 minutes on "
                "Teams next week to explore how IFG might help? Flexible on timing, "
                "mornings are easiest for me. — Steve",
    },
    "coffee": {
        "subject": "TEST — Coffee in Cherry Creek?",
        "sender": "anjana.kummetha@iconicfounders.com",
        "sender_name": "Dana Reeves",
        "body": "Kory, would love to grab coffee in Cherry Creek soon. I'm pretty "
                "flexible on mornings this week or next. — Dana",
    },
    "accept": {
        # a counterpart proposing a specific time (acceptance path)
        "subject": "TEST — Re: Intro call",
        "sender": "anjana.kummetha@iconicfounders.com",
        "sender_name": "Steve Quinn",
        "body": "Thanks! Wednesday at 2pm works great for me if Kory's free. — Steve",
    },
    "lunch": {
        "subject": "TEST — Lunch this week?",
        "sender": "anjana.kummetha@iconicfounders.com",
        "sender_name": "Jordan",
        "body": "Would you be up for lunch this week? Happy to come to Cherry Creek. — Jordan",
    },
}


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else "intro"
    s = SCENARIOS[key]

    from app.config import settings
    from app.integrations.composio_client import resolve_connection

    # ---- HARD SAFETY GATE (dry-run OR sandbox-loopback; Kory never the write target) ----
    assert not settings.cc_kory_enabled, "ABORT: Kory CC is enabled"
    for role in ("write", "lexi"):
        conn_id, entity = resolve_connection(role)
        assert conn_id != KORY_CONN, f"ABORT: role={role} resolved to KORY connection {conn_id}"
        print(f"[safety] role={role} -> {conn_id} (entity={entity}) OK (not Kory)")
    if not settings.lexi_dry_run:
        # live writes require sandbox loopback so no external recipient is ever contacted
        assert settings.lexi_write_mode == "sandbox" and settings.sandbox_email_loopback, "ABORT: live writes without sandbox loopback"
        assert (settings.sandbox_mailbox_email or "").lower() == "lexi@iconicfounders.com", "ABORT: sandbox mailbox unexpected"
    print(f"[safety] dry_run={settings.lexi_dry_run} write_mode={settings.lexi_write_mode} loopback={settings.sandbox_email_loopback} cc_kory={settings.cc_kory_enabled}")
    print("[safety] GATE PASSED\n")

    from app.orchestrator import handle_inbound_stream

    thread = f"uat-{key}-{uuid.uuid4().hex[:8]}"
    email = {
        "thread_id": thread,
        "conversation_id": thread,
        "subject": s["subject"],
        "from": {"emailAddress": {"address": s["sender"], "name": s["sender_name"]}},
        "sender": s["sender"],
        "sender_email": s["sender"],
        "to_recipients": ["kory.mitchell@iconicfounders.com"],
        "cc_recipients": ["lexi@iconicfounders.com"],
        "body": s["body"],
        "raw_body": s["body"],
        "receivedDateTime": "2026-07-21T15:00:00Z",
    }
    print(f"[inject] scenario={key} subject={s['subject']!r} thread={thread}")
    result = handle_inbound_stream(email)

    def _get(o, *names):
        for n in names:
            if isinstance(o, dict) and n in o:
                return o[n]
            if hasattr(o, n):
                return getattr(o, n)
        return None

    pid = _get(result, "proposal_id")
    status = _get(result, "triage_status", "status")
    print(f"\n[result] proposal_id={pid} status={status}")
    if pid:
        from app.storage.lexi_store import get_proposal
        prop = get_proposal(pid) or {}
        print(f"[result] proposal.status={prop.get('status')} intent={prop.get('intent_classification')}")
        slots = prop.get("proposed_slots") or []
        print(f"[result] offered_slots={json.dumps(slots)[:400]}")
        holds = prop.get("holds") or []
        real = [h for h in holds if h.get("event_id") and "dry" not in str(h.get("event_id")).lower()
                and not str(h.get("event_id")).startswith("hold-pending-")]
        print(f"[result] holds={len(holds)} real_write_holds={len(real)} (MUST be 0 in dry-run)")
    try:
        print(f"[result] full={json.dumps(result if isinstance(result, dict) else _get(result,'__dict__'), default=str)[:600]}")
    except Exception:
        print(f"[result] repr={str(result)[:600]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

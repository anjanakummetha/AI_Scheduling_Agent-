"""In-process end-to-end: inject scheduling email -> approve/execute (the exact code the
Teams Send button triggers) -> real send (loopback to lexi@) + hold. Verifies Kory untouched.

Requires the sandbox live-write posture (LEXI_WRITE_MODE=sandbox, DRY_RUN=false,
SANDBOX_EMAIL_LOOPBACK=true) — run scripts/uat/preflight_livewrite.py first.
"""
from __future__ import annotations
import uuid, json, datetime

KORY_CONN = "ca_qORrE-NzPib2"
SANDBOX_CONN = "ca_4BTJ6d0O8sSZ"

from app.config import settings
from app.integrations.composio_client import resolve_connection

# ---- HARD SAFETY GATE ----
for role in ("write", "lexi"):
    cid, ent = resolve_connection(role)
    assert cid == SANDBOX_CONN, f"ABORT: role={role} -> {cid}, expected sandbox"
    assert cid != KORY_CONN, f"ABORT: role={role} is KORY"
assert settings.lexi_write_mode == "sandbox" and settings.sandbox_email_loopback, "ABORT: not sandbox loopback"
assert (settings.sandbox_mailbox_email or "").lower() == "lexi@iconicfounders.com"
assert not settings.cc_kory_enabled, "ABORT: cc kory on"
print(f"[safety] write/lexi -> {SANDBOX_CONN} (Lexi); loopback ON; mailbox=lexi@; dry_run={settings.lexi_dry_run}; db={settings.lexi_database_path}")
print("[safety] GATE PASSED\n")

from app.orchestrator import handle_inbound_stream
from app.storage.lexi_store import get_proposal
from app.agents.comms_agent import execute_lexi_approval

thread = f"e2e-{uuid.uuid4().hex[:8]}"
email = {
    "thread_id": thread, "conversation_id": thread,
    "subject": "TEST — Intro: Priya Nair (Everline) <> Kory",
    "from": {"emailAddress": {"address": "anjana.kummetha@iconicfounders.com", "name": "Priya Nair"}},
    "sender": "anjana.kummetha@iconicfounders.com", "sender_email": "anjana.kummetha@iconicfounders.com",
    "to_recipients": ["kory.mitchell@iconicfounders.com"],
    "cc_recipients": ["lexi@iconicfounders.com"],
    "body": "Hi Kory — great to connect. Could we find 30 minutes on Teams next week? Mornings are best for me. — Priya",
    "raw_body": "Hi Kory — great to connect. Could we find 30 minutes on Teams next week? Mornings are best for me. — Priya",
    "receivedDateTime": "2026-07-21T15:00:00Z",
}
print(f"[inject] thread={thread}")
res = handle_inbound_stream(email)
pid = res.get("proposal_id") if isinstance(res, dict) else getattr(res, "proposal_id", None)
prop = get_proposal(pid) or {}
print(f"[inject] proposal_id={pid} status={prop.get('status')} intent={prop.get('intent_classification')}")
print(f"[inject] offered_slots={json.dumps(prop.get('proposed_slots') or [])[:300]}\n")

print("[execute] calling execute_lexi_approval(approved, send_offer) — the Send-button code path...")
exec_res = execute_lexi_approval(int(pid), "approved", "", "uat-test-operator", decision_source="teams_card", execution_phase="send_offer")
d = exec_res.to_dict() if hasattr(exec_res, "to_dict") else vars(exec_res)
print(f"[execute] ok={d.get('ok')} status={d.get('status')}")
print(f"[execute] errors={d.get('errors')}")
print(f"[execute] warnings={str(d.get('warnings'))[:300]}")
print(f"[execute] full={json.dumps(d, default=str)[:700]}\n")

# ---- VERIFY: real send landed in lexi@ Sent Items; hold on Lexi calendar ----
from app.integrations.composio_client import execute_write_tool
try:
    r = execute_write_tool("OUTLOOK_LIST_SENT_ITEMS_MESSAGES", {"user_id": "me", "top": 4})
    data = r.get("data") or r
    items = (data.get("value") if isinstance(data, dict) else None) or []
    print(f"[verify] Lexi Sent Items (top 4):")
    for m in items[:4]:
        if isinstance(m, dict):
            to = ", ".join(x.get("emailAddress", {}).get("address", "") for x in (m.get("toRecipients") or []))
            print(f"  - {m.get('sentDateTime')} | to={to} | {str(m.get('subject'))[:60]}")
except Exception as e:
    print(f"[verify] sent-items read error: {e}")

prop2 = get_proposal(pid) or {}
print(f"\n[verify] proposal final status={prop2.get('status')}")
holds = prop2.get("holds") or []
print(f"[verify] holds={json.dumps(holds, default=str)[:400]}")
print(f"\n[cleanup] to delete these sandbox holds: scripts/uat/cleanup_holds.py {pid}")

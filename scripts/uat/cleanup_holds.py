"""Delete the sandbox calendar holds created by the e2e test (test hygiene).

Usage: scripts/uat/cleanup_holds.py <proposal_id>
"""
import sys
from app.integrations.composio_client import execute_write_tool, resolve_connection
from app.storage.lexi_store import get_proposal

KORY_CONN = "ca_qORrE-NzPib2"
cid, _ = resolve_connection("write")
assert cid != KORY_CONN and cid == "ca_4BTJ6d0O8sSZ", f"ABORT: write connection {cid}"

pid = int(sys.argv[1])
prop = get_proposal(pid) or {}
holds = prop.get("holds") or []
print(f"[cleanup] proposal {pid}: {len(holds)} holds on Lexi sandbox calendar (conn={cid})")
deleted = 0
for h in holds:
    eid = h.get("event_id")
    if not eid or str(eid).startswith("dry") or str(eid).startswith("hold-pending"):
        print(f"  - skip non-real event_id={eid}")
        continue
    try:
        execute_write_tool("OUTLOOK_DELETE_EVENT", {"user_id": "me", "event_id": eid})
        deleted += 1
        print(f"  - deleted {h.get('slot_start')} ({str(eid)[:24]}...)")
    except Exception as e:
        print(f"  - ERROR deleting {str(eid)[:24]}: {e}")
print(f"[cleanup] deleted {deleted}/{len(holds)} holds")

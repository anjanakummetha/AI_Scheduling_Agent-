"""Snapshot Lexi's sandbox mailbox Sent Items + recent calendar events (write connection)."""
import json
from app.config import settings
from app.integrations.composio_client import execute_write_tool, resolve_connection

cid, ent = resolve_connection("write")
assert cid == "ca_4BTJ6d0O8sSZ", f"write connection is {cid}, not Lexi sandbox"
print(f"[verify] write connection={cid} entity={ent}")

# Sent Items
try:
    res = execute_write_tool("OUTLOOK_LIST_SENT_ITEMS_MESSAGES", {"user_id": "me", "top": 6})
    data = res.get("data") or res
    items = (data.get("value") if isinstance(data, dict) else None) or (data.get("messages") if isinstance(data, dict) else None) or []
    print(f"[sent] count={len(items)}")
    for m in items[:6]:
        if isinstance(m, dict):
            to = ", ".join(r.get("emailAddress", {}).get("address", "") for r in (m.get("toRecipients") or []))
            print(f"  - {m.get('sentDateTime') or m.get('receivedDateTime')} | to={to} | {str(m.get('subject'))[:70]}")
except Exception as e:
    print(f"[sent] ERROR: {e}")

# Recent calendar events (holds land here in sandbox)
try:
    res = execute_write_tool("OUTLOOK_LIST_EVENTS", {"user_id": "me", "top": 8})
    data = res.get("data") or res
    evs = (data.get("value") if isinstance(data, dict) else None) or []
    print(f"[cal] recent events count={len(evs)}")
    for e in evs[:8]:
        if isinstance(e, dict):
            st = (e.get("start") or {}).get("dateTime") if isinstance(e.get("start"), dict) else e.get("start")
            print(f"  - {st} | {str(e.get('subject'))[:70]}")
except Exception as e:
    print(f"[cal] ERROR: {e}")

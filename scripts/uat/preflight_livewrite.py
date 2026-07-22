"""Hard pre-flight before enabling sandbox LIVE writes. Aborts unless Kory is provably safe.

Run standalone (no arguments) before starting the live-write gateway:
    .venv/bin/python scripts/uat/preflight_livewrite.py
Exit 0 = safe to start; exit 1 = one or more guards failed (do NOT start the gateway).
"""
from app.config import settings
from app.integrations.composio_client import resolve_connection

KORY_CONN = "ca_qORrE-NzPib2"
SANDBOX_CONN = "ca_4BTJ6d0O8sSZ"

fail = []

# 1. Every WRITE role must resolve to the Lexi sandbox connection, never Kory.
for role in ("write", "lexi"):
    cid, ent = resolve_connection(role)
    print(f"[chk] role={role} -> {cid} (entity={ent})")
    if cid == KORY_CONN:
        fail.append(f"role {role} resolved to KORY connection")
    if cid != SANDBOX_CONN:
        fail.append(f"role {role} resolved to {cid}, expected sandbox {SANDBOX_CONN}")

# 2. Sandbox loopback ON + mailbox = lexi@ (so no external recipient is ever contacted).
print(f"[chk] write_mode={settings.lexi_write_mode} loopback={settings.sandbox_email_loopback} mailbox={settings.sandbox_mailbox_email}")
if settings.lexi_write_mode != "sandbox":
    fail.append("write_mode is not sandbox")
if not settings.sandbox_email_loopback:
    fail.append("sandbox_email_loopback is OFF (external recipients could be contacted)")
if (settings.sandbox_mailbox_email or "").strip().lower() != "lexi@iconicfounders.com":
    fail.append(f"sandbox mailbox unexpected: {settings.sandbox_mailbox_email}")

# 3. Kory never CC'd.
print(f"[chk] cc_kory_enabled={settings.cc_kory_enabled}")
if settings.cc_kory_enabled:
    fail.append("cc_kory_enabled is ON")

# 4. Recipient allowlist present + only test addresses.
import os
allow = {a.strip().lower() for a in os.getenv("LEXI_ALLOWED_RECIPIENTS", "").split(",") if a.strip()}
print(f"[chk] allowlist={sorted(allow)}")
if not allow:
    fail.append("allowlist empty")
for a in allow:
    if a not in {"anjana.kummetha@iconicfounders.com", "anjanakummetha@gmail.com", "lexi@iconicfounders.com"}:
        fail.append(f"unexpected allowlist recipient: {a}")

# 5. Approval still required; no autonomous send/execute.
from app.safety.approval_gate import kory_approves_all, auto_execute_allowed, immediate_send_allowed
print(f"[chk] approves_all={kory_approves_all()} auto_execute={auto_execute_allowed()} immediate_send={immediate_send_allowed()}")
if not kory_approves_all():
    fail.append("kory approval not required")
if auto_execute_allowed() or immediate_send_allowed():
    fail.append("autonomous send/execute is enabled")

print(f"[chk] dry_run={settings.lexi_dry_run} (expected False for live send)")

if fail:
    print("\n=== PREFLIGHT FAILED ===")
    for f in fail:
        print("  x", f)
    raise SystemExit(1)
print("\n=== PREFLIGHT PASSED — sandbox live writes safe (Kory untouched, sends loop back to lexi@) ===")

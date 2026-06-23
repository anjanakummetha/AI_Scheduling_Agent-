#!/usr/bin/env python3
"""Verify sandbox email delivery and diagnose mailbox mismatches.

Usage:
    .venv/bin/python scripts/verify_sandbox_email.py
    .venv/bin/python scripts/verify_sandbox_email.py --send-test
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import settings
from app.integrations.composio_client import execute_write_tool
from app.integrations.outlook_email import sandbox_mailbox_mismatch, send_outbound_email
from app.integrations.outlook_profile import get_write_mailbox_profile


def _list_sent_lexi(top: int = 8) -> list[dict]:
    result = execute_write_tool(
        "OUTLOOK_LIST_SENT_ITEMS_MESSAGES",
        {"user_id": "me", "top": top},
    )
    data = result.get("data") or {}
    items = data.get("value") or data.get("messages") or []
    return [m for m in items if isinstance(m, dict) and "[Lexi pilot]" in (m.get("subject") or "")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-test", action="store_true", help="Send a verification email now")
    args = parser.parse_args()

    print("\n=== Lexi Sandbox Email Verification ===\n")
    print(f"LEXI_WRITE_MODE={settings.lexi_write_mode}")
    print(f"SANDBOX_MAILBOX_EMAIL (configured)={settings.sandbox_mailbox_email}")
    print(f"SANDBOX_EMAIL_LOOPBACK={settings.sandbox_email_loopback}")
    print(f"SANDBOX_COMPOSIO_CONNECTION_ID={settings.sandbox_composio_connection_id}")

    profile = get_write_mailbox_profile()
    print(f"\nComposio write connection profile:")
    print(f"  display_name: {profile.get('display_name')}")
    print(f"  mail:         {profile.get('mail')}")
    print(f"  upn:          {profile.get('user_principal_name')}")

    mismatch = sandbox_mailbox_mismatch()
    if mismatch.get("mismatch"):
        print(
            "\n⚠️  MISMATCH: .env says "
            f"{mismatch['configured']} but Composio is connected as {mismatch['connected']}."
        )
        print(
            "   Emails send successfully but land in the CONNECTED account (check its Sent folder),"
        )
        print(
            "   not necessarily the @outlook.com inbox you configured."
        )
        print(
            "   Fix: In https://dashboard.composio.dev reconnect Outlook as anjanakummetha@outlook.com"
        )
        print("   OR set SANDBOX_MAILBOX_EMAIL to the connected address above.")
    else:
        print("\n✓ Configured mailbox matches Composio write connection.")

    print("\n--- Recent [Lexi pilot] in Sent Items (connected account) ---")
    sent = _list_sent_lexi()
    if not sent:
        print("  (none found — run with --send-test)")
    for m in sent[:8]:
        tos = [
            t.get("emailAddress", {}).get("address")
            for t in (m.get("toRecipients") or [])
        ]
        print(f"  • {m.get('sentDateTime')} | {m.get('subject')} → {tos}")

    print("\n--- Where to look ---")
    print("  1. Outlook → Sent Items (always) for subjects starting with [Lexi pilot]")
    print("  2. Inbox only if recipient differs from sender (cross-address delivery)")
    print("  3. Junk/Other tab if sending to a separate @outlook.com login")

    if args.send_test:
        print("\n--- Sending test ---")
        msg_id, log_id = send_outbound_email(
            to_email=settings.sandbox_mailbox_email or profile.get("mail") or "",
            subject="Mailbox verification test",
            body=(
                "Lexi sandbox email is working. Check Sent Items on the Composio-connected "
                "account. If .env mailbox differs, this message also BCCs the configured address."
            ),
            approved_send=True,
        )
        print(f"  message_id={msg_id} log_id={log_id}")
        sent2 = _list_sent_lexi(top=3)
        print(f"  Sent Items now has {len(sent2)} recent [Lexi pilot] message(s).")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

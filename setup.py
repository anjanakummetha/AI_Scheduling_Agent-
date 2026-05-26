"""
One-time Setup Script
─────────────────────────────────────────────────────────────
Run this ONCE before starting the agent for the first time.
It registers the Outlook email trigger with Composio so the
agent gets notified whenever a new email arrives.

Usage:
    python setup.py
"""

import os
import sys
from dotenv import load_dotenv
from composio import Composio

load_dotenv()


def main():
    print("\n" + "═" * 60)
    print("  KORY'S AI SCHEDULING AGENT — ONE-TIME SETUP")
    print("═" * 60)

    # ── Validate environment ──────────────────────────────────
    api_key = os.getenv("COMPOSIO_API_KEY")
    user_id = os.getenv("COMPOSIO_USER_ID", "kory")

    if not api_key:
        print("\n  ERROR: COMPOSIO_API_KEY is missing from your .env file.")
        print("  1. Go to your Composio dashboard → Settings → API Keys")
        print("  2. Copy your API key")
        print("  3. Add it to the .env file: COMPOSIO_API_KEY=your_key_here")
        sys.exit(1)

    print(f"\n  Connecting to Composio for user: {user_id}")
    composio = Composio(api_key=api_key)

    # ── Step 1: Verify Microsoft 365 connection ───────────────
    print("\n  [1/3] Verifying Microsoft 365 connected account...")
    try:
        session = composio.create(user_id=user_id)
        print(f"  ✓ Composio session created successfully for '{user_id}'")
    except Exception as e:
        print(f"\n  ERROR: Could not create Composio session — {e}")
        print("  Make sure your Microsoft 365 account is connected in the Composio dashboard.")
        print("  Dashboard → Connected Accounts → Connect Microsoft 365")
        sys.exit(1)

    # ── Step 2: Inspect the trigger type ─────────────────────
    print("\n  [2/3] Inspecting OUTLOOK_MESSAGE_TRIGGER trigger type...")
    try:
        trigger_type = composio.triggers.get_type("OUTLOOK_MESSAGE_TRIGGER")
        print(f"  ✓ Trigger type found. Required config: {trigger_type.config}")
    except Exception as e:
        print(f"\n  WARNING: Could not inspect trigger type — {e}")
        print("  Proceeding with trigger creation using default config...")

    # ── Step 3: Create the trigger ────────────────────────────
    print(f"\n  [3/3] Creating OUTLOOK_MESSAGE_TRIGGER for user '{user_id}'...")
    try:
        trigger = composio.triggers.create(
            slug="OUTLOOK_MESSAGE_TRIGGER",
            user_id=user_id,
            trigger_config={},
        )
        print(f"\n  ✓ Trigger created successfully!")
        print(f"  Trigger ID: {trigger.trigger_id}")
        print(f"\n  Composio will now notify your agent whenever a new email")
        print(f"  arrives in Kory's Outlook inbox.")
    except Exception as e:
        print(f"\n  ERROR: Could not create trigger — {e}")
        print("\n  Possible causes:")
        print("  - Microsoft 365 account not connected in Composio dashboard")
        print("  - Trigger already exists (that's OK — check dashboard → Active Triggers)")
        print("  - API key doesn't have the right permissions")
        sys.exit(1)

    # ── Done ──────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  SETUP COMPLETE")
    print("═" * 60)
    print("\n  Next steps:")
    print("  1. Make sure Hermes is running (see README.md)")
    print("  2. Run the agent:  python agent.py")
    print("  3. Send a test email to Kory's Outlook inbox")
    print("  4. Watch the agent analyze it and propose an action")
    print("  5. Type 'y' to approve or 'n' to reject\n")


if __name__ == "__main__":
    main()

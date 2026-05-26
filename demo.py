"""
Kory's AI Scheduling Agent — DEMO MODE
────────────────────────────────────────────────────────────
Paste any email into the terminal and Hermes will analyze it
using all of Kory's scheduling rules and propose a response.

Run:  python demo.py
"""

import os
import ssl
import certifi
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

load_dotenv()

from prompts import build_system_prompt, build_email_context



def get_llm_client():
    return OpenAI(
        base_url=os.getenv("LLM_BASE_URL"),
        api_key=os.getenv("LLM_API_KEY"),
    )


def ask_hermes(llm, email_data):
    model = os.getenv("LLM_MODEL", "hermes3")
    print(f"\n  Sending to Hermes ({model})... please wait...\n")

    response = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": build_email_context(email_data)},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content


def get_email_input():
    """Prompt user to paste an email."""
    print("\n" + "═" * 60)
    print("  PASTE AN EMAIL")
    print("═" * 60)
    from_addr = input("  From (email address): ").strip()
    subject   = input("  Subject line:         ").strip()
    print("  Body: paste the full email body below.")
    print("  When done, type END on its own line and press Enter.")
    print("─" * 60)
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return {
        "from": from_addr or "unknown@example.com",
        "subject": subject or "(no subject)",
        "received_at": datetime.now().strftime("%a %b %d, %Y %I:%M %p"),
        "body": "\n".join(lines).strip(),
    }


def show_approval_gate(email_data, proposed_action):
    print("\n" + "═" * 60)
    print("  NEW EMAIL")
    print("═" * 60)
    print(f"  From:    {email_data['from']}")
    print(f"  Subject: {email_data['subject']}")
    print("─" * 60)
    print("  HERMES ANALYSIS & PROPOSED ACTION:")
    print("─" * 60)
    print(proposed_action)
    print("═" * 60)
    print("\n  What would you like to do?")
    print("  y = Approve & log    n = Reject    a = Try another email")
    print("─" * 60)

    while True:
        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "reject", None

        if choice in ("y", "yes", "approve"):
            return "approve", None
        elif choice in ("n", "no", "reject"):
            return "reject", None
        elif choice in ("a", "another"):
            return "another", None
        elif choice == "":
            print("  Type y, n, or a then press Enter.")
        else:
            print(f"  '{choice}' not recognized. Type y, n, or a.")


def log_decision(email_data, proposed_action, outcome):
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "from": email_data["from"],
        "subject": email_data["subject"],
        "proposed_action": proposed_action[:400],
        "outcome": outcome,
    }
    with open(os.path.join(log_dir, "decisions.log"), "a") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    print("\n" + "═" * 60)
    print("  KORY'S AI SCHEDULING AGENT — DEMO MODE")
    print("  Hermes + Composio | Phase 1: Kory approves all actions")
    print("═" * 60)

    # Verify connections
    print("\n  Checking connections...")
    try:
        llm = get_llm_client()
        test = llm.chat.completions.create(
            model=os.getenv("LLM_MODEL"),
            messages=[{"role": "user", "content": "Reply with: ready"}],
            max_tokens=5,
        )
        print("  ✓ Hermes (LLM) connected")
    except Exception as e:
        print(f"  ✗ Hermes connection failed: {e}")
        return

    try:
        from composio import Composio
        c = Composio(api_key=os.getenv("COMPOSIO_API_KEY"))
        accounts = c.connected_accounts.list()
        active = [a for a in accounts.items if getattr(a, "status", "") == "ACTIVE"]
        print(f"  ✓ Composio connected ({len(active)} active account(s))")
    except Exception as e:
        print(f"  ✗ Composio connection failed: {e}")

    print("\n  Everything ready. Let's run the demo.\n")

    while True:
        email_data = get_email_input()

        print("\n" + "─" * 60)
        print(f"  Processing email from {email_data['from']}...")

        proposed_action = ask_hermes(llm, email_data)
        outcome, override = show_approval_gate(email_data, proposed_action)

        if outcome == "approve":
            log_decision(email_data, proposed_action, "approved")
            print("\n  ✓ Logged as APPROVED.")
            print("  (In production, Composio would now send the email/book the calendar.)")
        elif outcome == "reject":
            log_decision(email_data, proposed_action, "rejected")
            print("\n  ✗ Logged as REJECTED. No action taken.")
        elif outcome == "another":
            continue

        again = input("\n  Run another email? [y/n]: ").strip().lower()
        if again not in ("y", "yes"):
            print("\n  Demo complete. Decisions saved to logs/decisions.log\n")
            break


if __name__ == "__main__":
    main()

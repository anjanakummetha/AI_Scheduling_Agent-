#!/usr/bin/env python3
"""Local Lexi console — test without Hermes or Teams.

Usage:
    .venv/bin/python scripts/lexi_console.py status
    .venv/bin/python scripts/lexi_console.py pending
    .venv/bin/python scripts/lexi_console.py calendar [--days 7]
    .venv/bin/python scripts/lexi_console.py approve <proposal_id>
    .venv/bin/python scripts/lexi_console.py reject <proposal_id>
    .venv/bin/python scripts/lexi_console.py inject --subject "..." --body "..."
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.agents.comms_agent import execute_lexi_approval
from app.assistant.actions import get_calendar_availability, get_lexi_system_status
from app.orchestrator import handle_inbound_stream
from app.storage.lexi_store import get_proposal, list_proposals


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(get_lexi_system_status(), indent=2))
    return 0


def cmd_pending(_: argparse.Namespace) -> int:
    rows = list_proposals("pending_approval")
    if not rows:
        print("No proposals pending approval.")
        return 0
    for row in rows:
        print(
            f"  #{row['id']}  {row.get('status')}  "
            f"{row.get('subject') or '(no subject)'}  thread={row.get('thread_id')}"
        )
    print(f"\nOpen dashboard: http://127.0.0.1:8000/decisions/<id>")
    return 0


def cmd_calendar(args: argparse.Namespace) -> int:
    data = get_calendar_availability(days=args.days)
    print(json.dumps(data, indent=2))
    return 0


def _default_slot(proposal: dict) -> str:
    holds = proposal.get("holds") or []
    if holds:
        return str(holds[0].get("slot_start") or "")
    slots = proposal.get("proposed_slots") or []
    if slots:
        return str(slots[0].get("start") or "")
    return ""


def cmd_approve(args: argparse.Namespace) -> int:
    proposal = get_proposal(args.proposal_id)
    if not proposal:
        print(f"Proposal {args.proposal_id} not found.", file=sys.stderr)
        return 1
    slot = args.slot or _default_slot(proposal)
    result = execute_lexi_approval(
        proposal_id=args.proposal_id,
        decision="approved",
        selected_slot=slot,
        authorized_by="lexi_console",
        decision_source="console",
    )
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0 if result.ok else 1


def cmd_reject(args: argparse.Namespace) -> int:
    if not get_proposal(args.proposal_id):
        print(f"Proposal {args.proposal_id} not found.", file=sys.stderr)
        return 1
    result = execute_lexi_approval(
        proposal_id=args.proposal_id,
        decision="rejected",
        selected_slot="",
        authorized_by="lexi_console",
        decision_source="console",
    )
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0 if result.ok else 1


def cmd_inject(args: argparse.Namespace) -> int:
    thread_id = args.thread_id or f"console-{args.subject[:24].replace(' ', '-')}"
    payload = {
        "thread_id": thread_id,
        "subject": args.subject,
        "sender": args.sender,
        "received_at": args.received_at,
        "raw_body": args.body,
        "outlook_message_id": args.message_id or f"console-msg-{thread_id}",
    }
    result = handle_inbound_stream(payload)
    print(json.dumps(result, indent=2, default=str))
    proposal_id = result.get("proposal_id")
    if proposal_id and result.get("final_status") == "pending_approval":
        print(f"\nApprove: python scripts/lexi_console.py approve {proposal_id}")
        print(f"Or open: http://127.0.0.1:8000/decisions/{proposal_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lexi local console (no Teams/Hermes)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show runtime flags and pending count").set_defaults(
        func=cmd_status
    )
    sub.add_parser("pending", help="List proposals awaiting approval").set_defaults(
        func=cmd_pending
    )
    cal = sub.add_parser("calendar", help="Read Kory calendar busy blocks")
    cal.add_argument("--days", type=int, default=14)
    cal.set_defaults(func=cmd_calendar)

    approve = sub.add_parser("approve", help="Approve a pending proposal")
    approve.add_argument("proposal_id", type=int)
    approve.add_argument("--slot", default="", help="ISO start time for selected slot")
    approve.set_defaults(func=cmd_approve)

    reject = sub.add_parser("reject", help="Reject a pending proposal")
    reject.add_argument("proposal_id", type=int)
    reject.set_defaults(func=cmd_reject)

    inj = sub.add_parser("inject", help="Run full inbound email pipeline locally")
    inj.add_argument("--subject", required=True)
    inj.add_argument("--body", required=True)
    inj.add_argument("--sender", default="client@example.com")
    inj.add_argument("--thread-id", dest="thread_id", default="")
    inj.add_argument("--message-id", dest="message_id", default="")
    inj.add_argument("--received-at", dest="received_at", default="2026-06-04 10:00:00")
    inj.set_defaults(func=cmd_inject)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run one live inbound email through triage → notify decision → draft (no send).

Usage:
    .venv/bin/python scripts/test_inbound_live.py --sender "Dan Phillips"
    .venv/bin/python scripts/test_inbound_live.py --message-id <outlook_id>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.inbound_filter import evaluate_inbound_notification
from app.agents.inbound_reply import AWAITING_REPLY_PROMPT, begin_draft_reply
from app.agents.triage_agent import process_new_email
from app.config import settings
from app.integrations.outlook_inbox import get_thread_message, search_inbox
from app.llm.kory_voice import rebuild_voice_profile
from app.orchestrator import handle_inbound_stream


def _mt_label(iso_ts: str) -> str:
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(settings.scheduling_timezone)).strftime(
            "%Y-%m-%d %I:%M %p %Z"
        )
    except (TypeError, ValueError):
        return iso_ts


def _pick_message(*, sender: str, subject_hint: str) -> dict:
    needle = sender.lower()
    messages, _ = search_inbox(query=sender.split()[0] if sender else "", top=25)
    candidates = [
        m
        for m in messages
        if needle in (m.get("sender_name") or "").lower()
        or needle in (m.get("sender") or "").lower()
    ]
    if subject_hint:
        sub = subject_hint.lower()
        narrowed = [m for m in candidates if sub in (m.get("subject") or "").lower()]
        if narrowed:
            candidates = narrowed
    if not candidates:
        raise SystemExit(f"No inbox message found for sender={sender!r}")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Live inbound email pipeline test")
    parser.add_argument("--sender", default="Dan Phillips")
    parser.add_argument("--subject-hint", default="W-2 Payroll")
    parser.add_argument("--message-id", default="")
    parser.add_argument("--skip-draft", action="store_true")
    args = parser.parse_args()

    print("Rebuilding Kory voice profile from sent mail…")
    voice = rebuild_voice_profile()
    print(f"  samples={voice.get('sample_count')} hints={voice.get('tone_hints')}")

    if args.message_id:
        payload = get_thread_message(args.message_id.strip())
        summary = {
            "message_id": payload.get("message_id"),
            "thread_id": payload.get("conversation_id") or payload.get("message_id"),
            "subject": payload.get("subject"),
            "sender": payload.get("sender"),
            "received_at": payload.get("received_at"),
        }
    else:
        summary = _pick_message(sender=args.sender, subject_hint=args.subject_hint)

    message_id = str(summary.get("message_id") or "")
    full = get_thread_message(message_id)
    raw_email = {
        "thread_id": full.get("conversation_id") or message_id,
        "message_id": message_id,
        "conversation_id": full.get("conversation_id") or "",
        "subject": full.get("subject") or "",
        "sender": full.get("sender") or "",
        "received_at": full.get("received_at") or "",
        "raw_body": full.get("body") or "",
    }

    print("\n=== INBOUND MESSAGE ===")
    print(f"From:      {raw_email['sender']}")
    print(f"Subject:   {raw_email['subject']}")
    print(f"Received:  {_mt_label(raw_email['received_at'])} (raw {raw_email['received_at']})")
    print(f"Thread:    {raw_email['thread_id']}")
    body_preview = (raw_email["raw_body"] or "")[:500]
    print(f"\nBody preview:\n{body_preview}\n…")

    print("=== ORCHESTRATOR (triage + notify decision) ===")
    orch = handle_inbound_stream(raw_email)
    print(json.dumps(orch, indent=2, default=str))

    proposal_id = orch.get("proposal_id")
    with __import__("app.storage.lexi_db", fromlist=["get_lexi_connection"]).get_lexi_connection() as conn:
        row = conn.execute(
            """
            SELECT intent_classification, priority_tier, justification, status
            FROM proposals WHERE id = ?
            """,
            (proposal_id,),
        ).fetchone()
    meta = dict(row) if row else {}
    notify = evaluate_inbound_notification(
        intent=str(meta.get("intent_classification") or ""),
        priority=str(meta.get("priority_tier") or ""),
        sender=raw_email["sender"],
        subject=raw_email["subject"],
        body=raw_email["raw_body"],
    )
    print("\n=== TEAMS NOTIFY? ===")
    print(f"  notify={notify.notify} reason={notify.reason} auto_skip={notify.auto_skip}")
    print(f"  status={meta.get('status')} intent={meta.get('intent_classification')} priority={meta.get('priority_tier')}")
    print(f"  justification: {meta.get('justification')}")

    if notify.auto_skip:
        print("\nWould NOT ping Teams (auto-skipped).")
        return

    if meta.get("status") != AWAITING_REPLY_PROMPT:
        print(f"\nProposal not awaiting reply prompt (status={meta.get('status')}).")
        if args.skip_draft:
            return

    if args.skip_draft:
        print("\n(Skipping draft step — use without --skip-draft to run begin_draft_reply)")
        return

    print("\n=== DRAFT (simulating Kory: draft yes) ===")
    draft_result = begin_draft_reply(int(proposal_id))
    print(json.dumps({k: draft_result[k] for k in draft_result if k != "traceback"}, indent=2, default=str))
    draft = draft_result.get("drafted_reply")
    if not draft:
        with __import__("app.storage.lexi_db", fromlist=["get_lexi_connection"]).get_lexi_connection() as conn:
            draft_row = conn.execute(
                "SELECT drafted_reply FROM proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        draft = draft_row["drafted_reply"] if draft_row else ""

    if draft:
        print("\n=== DRAFT REPLY ===")
        print("─" * 60)
        print(draft)
        print("─" * 60)


if __name__ == "__main__":
    main()

"""48-hour inbox review — Kory's real mail, topics, and what needs his attention."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.agents.inbound_filter import is_newsletter_or_bulk_mail, is_no_reply_needed_mail

_SCHEDULING_CUES = (
    "schedule",
    "meet",
    "coffee",
    "call",
    "connect",
    "intro",
    "time",
    "calendar",
    "available",
    "dinner",
    "lunch",
)
_ACTION_CUES = (
    "?",
    "let me know",
    "please",
    "can you",
    "could you",
    "need to",
    "waiting",
    "follow up",
    "when works",
)


def build_inbox_review(*, hours: int = 48) -> dict[str, Any]:
    """Summarize Kory's inbox activity — topics and human action items, not Lexi pipeline state."""
    from app.integrations.outlook_inbox import search_inbox

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        messages, log_id = search_inbox(top=50)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "kory_message": f"Couldn't read your inbox right now ({type(exc).__name__}). Try again in a minute.",
        }

    recent = _filter_recent(messages, cutoff)
    threads = _group_by_conversation(recent)
    lines: list[str] = [f"**Inbox review — last {hours} hours**\n"]
    action_items: list[dict[str, Any]] = []
    topic_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

    if not recent:
        lines.append("_No inbox messages in this window (or inbox read not configured)._")
        return {
            "ok": True,
            "hours": hours,
            "message_count": 0,
            "thread_count": 0,
            "action_items": [],
            "threads": [],
            "composio_log_id": log_id,
            "kory_message": "\n".join(lines),
        }

    for conv_id, thread_msgs in threads.items():
        latest = thread_msgs[0]
        subject = str(latest.get("subject") or "(no subject)")
        sender = str(latest.get("sender_name") or latest.get("sender") or "unknown")
        preview = str(latest.get("preview") or "")
        topic = _classify_topic(subject, preview)
        topic_buckets[topic].append(latest)

        if _needs_kory_attention(latest):
            reason = _attention_reason(latest)
            action_items.append(
                {
                    "subject": subject,
                    "sender": sender,
                    "received_at": latest.get("received_at"),
                    "reason": reason,
                    "preview": preview[:200],
                    "conversation_id": conv_id,
                }
            )

    lines.append(f"**Overview:** {len(recent)} messages across {len(threads)} threads\n")

    for topic, items in sorted(topic_buckets.items(), key=lambda x: -len(x[1])):
        lines.append(f"**{topic} ({len(items)})**")
        for msg in items[:6]:
            subj = str(msg.get("subject") or "(no subject)")
            who = str(msg.get("sender_name") or msg.get("sender") or "unknown")
            snippet = str(msg.get("preview") or "")[:100].replace("\n", " ")
            lines.append(f"- **{subj}** — {who}: _{snippet}_")
        if len(items) > 6:
            lines.append(f"  _…and {len(items) - 6} more._")
        lines.append("")

    lines.append("**Needs your attention**")
    if not action_items:
        lines.append("_Nothing urgent flagged — review threads above for anything I missed._")
    else:
        for item in action_items[:12]:
            lines.append(
                f"- **{item['subject']}** from {item['sender']} — {item['reason']}"
            )
            if item.get("preview"):
                lines.append(f"  _{item['preview'][:120]}_")

    summary = "\n".join(lines)
    return {
        "ok": True,
        "hours": hours,
        "message_count": len(recent),
        "thread_count": len(threads),
        "action_items": action_items,
        "threads": [
            {
                "subject": m.get("subject"),
                "sender": m.get("sender"),
                "sender_name": m.get("sender_name"),
                "received_at": m.get("received_at"),
                "preview": m.get("preview"),
                "topic": _classify_topic(str(m.get("subject") or ""), str(m.get("preview") or "")),
            }
            for m in recent[:30]
        ],
        "composio_log_id": log_id,
        "kory_message": summary,
        "hermes_note": (
            "Summarize kory_message in plain CEO language. Do not mention Lexi proposal status "
            "unless Kory asks about a specific thread."
        ),
    }


def _filter_recent(messages: list[dict[str, Any]], cutoff: datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        received = _parse_received(msg.get("received_at"))
        if received and received >= cutoff:
            out.append(msg)
    out.sort(key=lambda m: str(m.get("received_at") or ""), reverse=True)
    return out


def _parse_received(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _group_by_conversation(messages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for msg in messages:
        key = str(msg.get("thread_id") or msg.get("conversation_id") or msg.get("message_id") or "")
        buckets[key or f"msg-{id(msg)}"].append(msg)
    for key in buckets:
        buckets[key].sort(key=lambda m: str(m.get("received_at") or ""), reverse=True)
    return dict(buckets)


def _classify_topic(subject: str, preview: str) -> str:
    combined = f"{subject}\n{preview}".lower()
    if is_newsletter_or_bulk_mail(sender="", subject=subject, body=preview):
        return "Newsletters & automated"
    if any(c in combined for c in ("intro", "connect", "meet you", "good to meet")):
        return "Intros & new connections"
    if any(c in combined for c in ("reschedule", "move our meeting", "different time")):
        return "Reschedules"
    if any(c in combined for c in _SCHEDULING_CUES):
        return "Scheduling & meetings"
    if any(c in combined for c in ("diligence", "term sheet", "deal", "portfolio")):
        return "Deals & diligence"
    if any(c in combined for c in ("board", "360", "lp ")):
        return "Board & internal"
    return "General correspondence"


def _needs_kory_attention(msg: dict[str, Any]) -> bool:
    sender = str(msg.get("sender") or "")
    subject = str(msg.get("subject") or "")
    preview = str(msg.get("preview") or "")
    if is_no_reply_needed_mail(sender=sender, subject=subject, body=preview):
        return False
    combined = f"{subject}\n{preview}".lower()
    if any(cue in combined for cue in _ACTION_CUES):
        return True
    if any(cue in combined for cue in _SCHEDULING_CUES):
        return True
    return False


def _attention_reason(msg: dict[str, Any]) -> str:
    preview = str(msg.get("preview") or "").lower()
    subject = str(msg.get("subject") or "").lower()
    combined = f"{subject} {preview}"
    if "?" in preview or "let me know" in combined:
        return "may need a reply"
    if any(c in combined for c in ("intro", "connect", "meet")):
        return "intro / scheduling thread"
    if "reschedule" in combined or "different time" in combined:
        return "reschedule request"
    if any(c in combined for c in _SCHEDULING_CUES):
        return "scheduling-related"
    return "worth a look"

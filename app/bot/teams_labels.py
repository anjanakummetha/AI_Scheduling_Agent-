"""Human-readable Teams labels and command tokens (no proposal IDs in chat)."""

from __future__ import annotations

import re
from typing import Any

EM_DASH = " — "


def _display_sender(sender: str | None) -> str:
    from app.bot.teams_format import display_sender

    return display_sender(sender)


def _display_subject(subject: str | None) -> str:
    from app.bot.teams_format import display_subject

    return display_subject(subject)


def email_thread_label(*, subject: str | None, sender: str | None) -> str:
    """Short label for user-facing copy: 'Dan Smith — Project Paint'."""
    return f"{_display_sender(sender)}{EM_DASH}{_display_subject(subject)}"


def format_draft_yes_token(*, subject: str | None, sender: str | None) -> str:
    return f"Draft reply to {_display_sender(sender)}{EM_DASH}{_display_subject(subject)}"


def format_draft_no_token(*, subject: str | None, sender: str | None) -> str:
    return f"Skip reply to {_display_sender(sender)}{EM_DASH}{_display_subject(subject)}"


def format_send_token(*, subject: str | None, sender: str | None, option: int = 1) -> str:
    base = f"Send reply to {_display_sender(sender)}{EM_DASH}{_display_subject(subject)}"
    if option > 1:
        return f"{base} (option {option})"
    return base


def format_discard_token(*, subject: str | None, sender: str | None) -> str:
    return f"Discard draft for {_display_sender(sender)}{EM_DASH}{_display_subject(subject)}"


def format_show_draft_token(*, subject: str | None, sender: str | None) -> str:
    return f"Show draft for {_display_sender(sender)}{EM_DASH}{_display_subject(subject)}"


def _sender_keys(sender: str | None) -> set[str]:
    raw = (sender or "").strip().lower()
    keys: set[str] = set()
    if not raw:
        return keys
    keys.add(_display_sender(sender).lower())
    if "@" in raw:
        keys.add(raw)
        local = raw.split("@", 1)[0]
        keys.add(local)
        keys.add(re.sub(r"[._]+", " ", local).strip())
    return {k for k in keys if k}


def _subject_key(subject: str | None) -> str:
    return _display_subject(subject).lower()


def _items_match(*, item_subject: Any, item_sender: Any, subject: str, sender: str) -> bool:
    if _subject_key(str(item_subject or "")) != _subject_key(subject):
        return False
    target_keys = _sender_keys(sender)
    item_keys = _sender_keys(str(item_sender or ""))
    return bool(target_keys & item_keys)


def resolve_proposal_id(
    *,
    subject: str,
    sender: str,
    prefer_pending_approval: bool = False,
) -> int | None:
    """Map subject + sender to a proposal id (newest match wins)."""
    from app.agents.comms_agent import get_lexi_pending_queue
    from app.agents.inbound_reply import get_inbound_reply_queue

    pending = get_lexi_pending_queue() if prefer_pending_approval else []
    inbound = get_inbound_reply_queue()

    queues: list[tuple[str, list[Any]]] = []
    if prefer_pending_approval:
        queues.append(("pending", pending))
        queues.append(("inbound", inbound))
    else:
        queues.append(("inbound", inbound))
        queues.append(("pending", pending))

    for _name, items in queues:
        matches: list[int] = []
        for item in items:
            if isinstance(item, dict):
                pid = int(item.get("proposal_id") or item.get("id") or 0)
                subj = item.get("subject")
                snd = item.get("sender")
            else:
                pid = int(getattr(item, "proposal_id", 0) or 0)
                subj = getattr(item, "subject", None)
                snd = getattr(item, "sender", None)
            if pid and _items_match(item_subject=subj, item_sender=snd, subject=subject, sender=sender):
                matches.append(pid)
        if matches:
            return max(matches)
    return None


def parse_human_teams_command(text: str) -> dict[str, Any] | None:
    """Parse human-readable card/chat commands into action + subject/sender."""
    normalized = (text or "").strip()
    if not normalized:
        return None

    patterns: list[tuple[str, re.Pattern[str]]] = [
        ("draft_yes", re.compile(r"^Draft reply to (.+)$", re.IGNORECASE)),
        ("draft_no", re.compile(r"^Skip reply to (.+)$", re.IGNORECASE)),
        ("approve", re.compile(r"^Send reply to (.+)$", re.IGNORECASE)),
        ("reject", re.compile(r"^Discard draft for (.+)$", re.IGNORECASE)),
        ("show_draft", re.compile(r"^Show draft for (.+)$", re.IGNORECASE)),
    ]

    for action, pattern in patterns:
        match = pattern.match(normalized)
        if not match:
            continue
        payload = match.group(1).strip()
        option = 1
        if action == "approve":
            opt_match = re.search(r"\(option\s+(\d+)\)\s*$", payload, re.IGNORECASE)
            if opt_match:
                option = int(opt_match.group(1))
                payload = payload[: opt_match.start()].strip()
        if EM_DASH not in payload:
            continue
        sender_part, subject_part = payload.split(EM_DASH, 1)
        sender = sender_part.strip()
        subject = subject_part.strip()
        if not sender or not subject:
            continue
        prefer_pending = action in {"approve", "reject", "show_draft"}
        proposal_id = resolve_proposal_id(
            subject=subject,
            sender=sender,
            prefer_pending_approval=prefer_pending,
        )
        if proposal_id is None:
            return {
                "action": action,
                "subject": subject,
                "sender": sender,
                "option": option,
                "proposal_id": None,
                "unresolved": True,
            }
        result: dict[str, Any] = {
            "action": action,
            "subject": subject,
            "sender": sender,
            "proposal_id": proposal_id,
            "option": option,
        }
        return result
    return None


def unresolved_message(*, action: str, subject: str, sender: str) -> str:
    label = email_thread_label(subject=subject, sender=sender)
    if action in {"approve", "reject", "show_draft"}:
        return (
            f"I couldn't find a pending draft for **{label}**. "
            "Try `pending` to see what's ready."
        )
    return (
        f"I couldn't find that email (**{label}**) in your inbound queue. "
        "Try `inbound` to see what's waiting."
    )


def action_confirmation_message(
    *,
    action: str,
    subject: str | None,
    sender: str | None,
    success: bool = True,
    detail: str = "",
) -> str:
    label = email_thread_label(subject=subject, sender=sender)
    normalized = action.lower()
    if normalized in {"draft_no"} and success:
        return f"Skipped drafting a reply to **{label}**."
    if normalized in {"draft_yes"}:
        return f"Draft ready for **{label}**."
    if normalized in {"approve", "approved"} and success:
        suffix = f" {detail}".rstrip()
        return f"Sent reply for **{label}**.{suffix}"
    if normalized in {"reject", "rejected"} and success:
        return f"Discarded draft for **{label}**."
    if not success and detail:
        return f"**{label}** — {detail}"
    return label

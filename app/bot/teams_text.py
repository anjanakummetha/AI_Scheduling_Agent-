"""Teams text summaries and chat-based approve/reject commands."""

from __future__ import annotations

import re
from typing import Any

from app.agents.comms_agent import LexiQueueItem, get_lexi_pending_queue
from app.bot.teams_labels import (
    parse_human_teams_command,
    unresolved_message,
)

_APPROVE_RE = re.compile(
    r"^(?:approve|yes|send)\s+#?(\d+)(?:\s+option\s+(\d+))?$",
    re.IGNORECASE,
)
_REJECT_RE = re.compile(r"^(?:reject|no|discard)\s+#?(\d+)(?:\s*[—\-:]\s*(.+))?$", re.IGNORECASE)
_PENDING_RE = re.compile(r"^(?:pending|queue|status)$", re.IGNORECASE)
_DRAFT_YES_RE = re.compile(
    r"^(?:draft|reply)\s+#?(\d+)(?:\s+yes)?$",
    re.IGNORECASE,
)
_DRAFT_NO_RE = re.compile(
    r"^(?:draft|reply|skip)\s+#?(\d+)\s+(?:no|skip)$",
    re.IGNORECASE,
)
_INBOUND_RE = re.compile(r"^(?:inbound|new|emails)$", re.IGNORECASE)
_HELP_RE = re.compile(r"^(?:help|\?)$", re.IGNORECASE)
_SHOW_DRAFT_RE = re.compile(
    r"^(?:show|view|display)(?:\s+me)?(?:\s+the)?\s+draft(?:\s+(?:for|on))?\s+(?:email\s+)?#?(\d+)$",
    re.IGNORECASE,
)


def format_pending_list(items: list[LexiQueueItem]) -> str:
    if not items:
        return "No drafts waiting to send."
    from app.bot.teams_format import display_subject, display_sender

    lines = ["**Drafts ready**\n"]
    for item in items[:15]:
        lines.append(
            f"• **{display_subject(item.subject)}** — from {display_sender(item.sender)}"
        )
    if len(items) > 15:
        lines.append(f"_…and {len(items) - 15} more._")
    lines.append(
        "\nUse the card buttons, or say e.g. "
        "_Show draft for Dan Smith — Project Paint_."
    )
    return "\n".join(lines)


def format_approval_notification(item: LexiQueueItem) -> str:
    return _format_approval_text(item, include_draft=True)


def format_reply_prompt_notification(item: dict) -> str:
    """Notify Kory about a new inbound email — ask before drafting."""
    from app.bot.teams_format import format_reply_prompt_card_text

    return format_reply_prompt_card_text(item)


def format_inbound_reply_list(items: list[dict]) -> str:
    if not items:
        return "No emails waiting for a draft decision."
    from app.bot.teams_format import display_subject, display_sender

    lines = ["**New mail**\n"]
    for item in items[:15]:
        lines.append(
            f"• **{display_subject(item.get('subject'))}** — "
            f"from {display_sender(item.get('sender'))}"
        )
    lines.append("\nUse the card buttons or ask me to draft a reply in chat.")
    return "\n".join(lines)


def _format_approval_text(item: LexiQueueItem, *, include_draft: bool) -> str:
    from app.bot.teams_format import display_sender, display_subject, format_draft_ready_text

    if include_draft and (item.drafted_reply or "").strip():
        return format_draft_ready_text(
            subject=item.subject,
            sender=item.sender,
            draft=item.drafted_reply or "",
            slots=item.proposed_slots or None,
            voice_mode=str(item.voice_mode or "kory"),
        )
    return (
        f"**{display_subject(item.subject)}**\n"
        f"From {display_sender(item.sender)}\n\n"
        "_Draft in progress — ask me to show it when ready._"
    )


def parse_teams_command(text: str) -> dict[str, Any] | None:
    """Parse a Teams chat line into an approval command, or None."""
    normalized = (text or "").strip()
    if not normalized:
        return None

    human = parse_human_teams_command(normalized)
    if human:
        if human.get("unresolved"):
            return {
                "action": "unresolved",
                "original_action": human["action"],
                "subject": human["subject"],
                "sender": human["sender"],
                "message": unresolved_message(
                    action=human["action"],
                    subject=human["subject"],
                    sender=human["sender"],
                ),
            }
        return human

    if _HELP_RE.match(normalized):
        return {"action": "help"}

    if _PENDING_RE.match(normalized):
        return {"action": "pending"}

    if _INBOUND_RE.match(normalized):
        return {"action": "inbound"}

    draft_no = _DRAFT_NO_RE.match(normalized)
    if draft_no:
        return {
            "action": "draft_no",
            "proposal_id": int(draft_no.group(1)),
        }

    draft_yes = _DRAFT_YES_RE.match(normalized)
    if draft_yes:
        return {
            "action": "draft_yes",
            "proposal_id": int(draft_yes.group(1)),
        }

    show_draft = _SHOW_DRAFT_RE.match(normalized)
    if show_draft:
        return {
            "action": "show_draft",
            "proposal_id": int(show_draft.group(1)),
        }

    approve = _APPROVE_RE.match(normalized)
    if approve:
        return {
            "action": "approve",
            "proposal_id": int(approve.group(1)),
            "option": int(approve.group(2)) if approve.group(2) else 1,
        }

    reject = _REJECT_RE.match(normalized)
    if reject:
        return {
            "action": "reject",
            "proposal_id": int(reject.group(1)),
            "reason": (reject.group(2) or "").strip(),
        }

    return None


def resolve_slot_for_option(item: LexiQueueItem, option: int) -> str:
    """Map 1-based option number to ISO slot start."""
    index = max(1, option) - 1
    holds = item.holds or []
    if index < len(holds):
        return str(holds[index].get("slot_start") or "")
    slots = item.proposed_slots or []
    if index < len(slots):
        return str(slots[index].get("start") or "")
    if slots:
        return str(slots[0].get("start") or "")
    return ""


def find_pending_item(proposal_id: int) -> LexiQueueItem | None:
    for item in get_lexi_pending_queue():
        if item.proposal_id == proposal_id:
            return item
    return None


def find_pending_item_by_label(*, subject: str, sender: str) -> LexiQueueItem | None:
    from app.bot.teams_labels import resolve_proposal_id

    proposal_id = resolve_proposal_id(
        subject=subject,
        sender=sender,
        prefer_pending_approval=True,
    )
    if proposal_id is None:
        return None
    return find_pending_item(proposal_id)


TEAMS_HELP_TEXT = """**Lexi**
- Ask naturally: "draft a reply to Dan about payroll" or use card buttons
- `pending` — drafts ready to send
- `inbound` — mail waiting for your draft yes/no
- Card buttons use the email subject and sender (no numeric ids)
- Approval cards have an editable draft — edit in the card, Save draft, then Send
- Approve in chat only when you want it sent

Important mail only — calendar accepts and digests are skipped."""

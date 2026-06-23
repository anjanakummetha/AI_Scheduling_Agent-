"""Microsoft Teams Adaptive Card builders for Lexi approval workflows."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

ADAPTIVE_CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
ADAPTIVE_CARD_VERSION = "1.4"
CARD_ACTION_APPROVAL = "execute_lexi_approval"
CARD_ACTION_SAVE_DRAFT = "update_proposal_draft"
INPUT_DRAFT_ID = "drafted_reply"


def generate_approval_card(
    proposal_record: dict[str, Any],
    email_record: dict[str, Any],
    holds_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a minimal approval card: subject, from, draft, optional times."""
    from app.bot.teams_format import display_sender, display_subject

    sender = display_sender(str(email_record.get("sender") or "unknown"))
    subject = display_subject(str(email_record.get("subject") or "(no subject)"))
    draft_reply = str(proposal_record.get("drafted_reply") or "").strip()
    voice_mode = str(proposal_record.get("voice_mode") or "kory")

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": subject,
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": f"From {sender}",
            "isSubtle": True,
            "spacing": "None",
            "wrap": True,
        },
    ]

    slot_block = _holds_text_block(holds_list, proposal_record)
    if slot_block:
        body.append(slot_block)

    body.append(
        {
            "type": "Input.Text",
            "id": INPUT_DRAFT_ID,
            "label": "Email draft (edit before sending)",
            "isMultiline": True,
            "value": _draft_input_value(draft_reply, voice_mode=voice_mode),
            "spacing": "Medium",
        }
    )

    body.append(
        {
            "type": "TextBlock",
            "text": "Edit the draft above, then Save draft or Send.",
            "isSubtle": True,
            "spacing": "Small",
            "wrap": True,
        }
    )

    proposal_id = int(proposal_record["id"])
    selected_slot = _default_selected_slot(holds_list, proposal_record)

    return {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
        "actions": [
            _submit_action(
                title="Save draft",
                action=CARD_ACTION_SAVE_DRAFT,
                proposal_id=proposal_id,
            ),
            _submit_action(
                title="Send",
                action=CARD_ACTION_APPROVAL,
                proposal_id=proposal_id,
                decision="approved",
                selected_slot=selected_slot,
                style="positive",
            ),
            _submit_action(
                title="Discard",
                action=CARD_ACTION_APPROVAL,
                proposal_id=proposal_id,
                decision="rejected",
                selected_slot="",
                style="destructive",
            ),
        ],
        "msteams": {"width": "Full"},
    }


def _holds_text_block(
    holds_list: list[dict[str, Any]],
    proposal_record: dict[str, Any],
) -> dict[str, Any] | None:
    if holds_list:
        lines = ["**Times offered**"]
        for index, hold in enumerate(holds_list[:3], start=1):
            slot_start = str(hold.get("slot_start") or "")
            slot_end = str(hold.get("slot_end") or "")
            lines.append(f"{index}. {_format_slot_range(slot_start, slot_end)}")
        return {
            "type": "TextBlock",
            "text": "\n".join(lines),
            "wrap": True,
            "spacing": "Small",
        }

    proposed = proposal_record.get("proposed_slots")
    if isinstance(proposed, list) and proposed:
        lines = ["**Times offered**"]
        for index, slot in enumerate(proposed[:3], start=1):
            if isinstance(slot, dict):
                lines.append(
                    f"{index}. {_format_slot_range(str(slot.get('start', '')), str(slot.get('end', '')))}"
                )
        return {
            "type": "TextBlock",
            "text": "\n".join(lines),
            "wrap": True,
            "spacing": "Small",
        }
    return None


def _draft_input_value(draft_reply: str, *, voice_mode: str = "kory") -> str:
    from app.scheduling.email_format import normalize_draft_for_display

    if not draft_reply:
        return ""
    return normalize_draft_for_display(draft_reply, max_chars=None, voice_mode=voice_mode)


def _draft_preview(draft_reply: str) -> str:
    from app.scheduling.email_format import normalize_draft_for_display

    if not draft_reply:
        return "_No draft yet._"
    return normalize_draft_for_display(draft_reply, max_chars=None)


def _format_slot_range(slot_start: str, slot_end: str) -> str:
    if not slot_start:
        return "Unavailable"
    start_label = _format_iso_datetime(slot_start)
    if not slot_end:
        return start_label
    end_label = _format_iso_datetime(slot_end, time_only=True)
    return f"{start_label} – {end_label}"


def _format_iso_datetime(value: str, *, time_only: bool = False) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if time_only:
        return parsed.strftime("%-I:%M %p")
    return parsed.strftime("%a %b %-d · %-I:%M %p %Z").replace("  ", " ").strip()


def _default_selected_slot(
    holds_list: list[dict[str, Any]],
    proposal_record: dict[str, Any],
) -> str:
    if holds_list and holds_list[0].get("slot_start"):
        return str(holds_list[0]["slot_start"])
    proposed = proposal_record.get("proposed_slots")
    if isinstance(proposed, list) and proposed:
        first = proposed[0]
        if isinstance(first, dict) and first.get("start"):
            return str(first["start"])
    return ""


def generate_reply_prompt_card(
    proposal_record: dict[str, Any],
    email_record: dict[str, Any],
) -> dict[str, Any]:
    """Minimal card: subject, from, draft yes/no."""
    from app.bot.teams_format import display_sender, display_subject
    from app.bot.teams_labels import format_draft_no_token, format_draft_yes_token

    sender = display_sender(str(email_record.get("sender") or "unknown"))
    subject = display_subject(str(email_record.get("subject") or "(no subject)"))

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": subject,
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": f"From {sender}",
            "isSubtle": True,
            "spacing": "None",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": "Should I draft a reply?",
            "spacing": "Medium",
            "wrap": True,
        },
    ]

    return {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
        "actions": [
            _im_back_action(
                title="Draft reply",
                message=format_draft_yes_token(
                    subject=str(email_record.get("subject") or ""),
                    sender=str(email_record.get("sender") or ""),
                ),
            ),
            _im_back_action(
                title="Skip",
                message=format_draft_no_token(
                    subject=str(email_record.get("subject") or ""),
                    sender=str(email_record.get("sender") or ""),
                ),
                style="destructive",
            ),
        ],
        "msteams": {"width": "Full"},
    }


def _im_back_action(
    *,
    title: str,
    message: str,
    style: str | None = None,
) -> dict[str, Any]:
    """Teams-compatible submit action (ImBack via msteams payload)."""
    action: dict[str, Any] = {
        "type": "Action.Submit",
        "title": title,
        "data": {
            "msteams": {
                "type": "imBack",
                "value": message,
            }
        },
    }
    if style:
        action["style"] = style
    return action


def _submit_action(
    *,
    title: str,
    action: str,
    proposal_id: int,
    decision: str = "",
    selected_slot: str = "",
    style: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "action": action,
        "proposal_id": proposal_id,
    }
    if decision:
        data["decision"] = decision
    if selected_slot:
        data["selected_slot"] = selected_slot
    submit: dict[str, Any] = {
        "type": "Action.Submit",
        "title": title,
        "data": data,
    }
    if style:
        submit["style"] = style
    return submit

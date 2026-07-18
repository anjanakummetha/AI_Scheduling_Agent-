"""Microsoft Teams Adaptive Card builders for Lexi approval workflows."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

ADAPTIVE_CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
ADAPTIVE_CARD_VERSION = "1.4"
CARD_ACTION_APPROVAL = "execute_lexi_approval"
CARD_ACTION_INVITE = "execute_lexi_invite"
CARD_ACTION_REOFFER = "execute_lexi_reoffer"
CARD_ACTION_SAVE_DRAFT = "update_proposal_draft"
INPUT_DRAFT_ID = "drafted_reply"


def generate_approval_card(
    proposal_record: dict[str, Any],
    email_record: dict[str, Any],
    holds_list: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build a minimal approval card: subject, from, draft, optional times.

    Returns None when a scheduling offer cannot be prepared cleanly — caller must not notify.
    """
    from app.bot.teams_format import display_sender, display_subject
    from app.scheduling.offer_refresh import prepare_scheduling_offer_for_approval

    proposal_record, ready = prepare_scheduling_offer_for_approval(
        proposal_record,
        email_record,
        holds_list,
        persist=True,
    )
    if not ready or proposal_record is None:
        return None

    sender = display_sender(str(email_record.get("sender") or "unknown"))
    subject = display_subject(str(email_record.get("subject") or "(no subject)"))
    draft_reply = _ensure_complete_draft(proposal_record, email_record)
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
            "spacing": "Small",
            "wrap": True,
        },
    ]

    intent = str(proposal_record.get("intent_classification") or "").strip()
    from app.scheduling.meeting_type import resolve_meeting_type

    spec = resolve_meeting_type(
        intent=intent,
        subject=str(email_record.get("subject") or ""),
        body=str(email_record.get("raw_body") or ""),
    )
    meeting_type_label = str(proposal_record.get("meeting_type_label") or "").strip()
    type_label = spec.card_type_label()
    if type_label:
        body.append(
            {
                "type": "TextBlock",
                "text": f"Type: {type_label}",
                "isSubtle": True,
                "spacing": "Small",
                "wrap": True,
            }
        )

    rules_status = str(proposal_record.get("rules_status") or "").strip()
    scheduling_note = str(proposal_record.get("scheduling_note") or "").strip()
    if scheduling_note:
        body.append(
            {
                "type": "TextBlock",
                "text": scheduling_note,
                "wrap": True,
                "color": "Attention",
                "spacing": "Small",
            }
        )
    if rules_status:
        body.append(
            {
                "type": "TextBlock",
                "text": rules_status,
                "isSubtle": True,
                "spacing": "Small",
                "wrap": True,
                "color": "Good" if rules_status.lower().startswith("rules: pass") else "Attention",
            }
        )

    slot_block = _holds_text_block(holds_list, proposal_record, email_record)
    if slot_block:
        body.append(slot_block)

    body.append(
        {
            "type": "Input.Text",
            "id": INPUT_DRAFT_ID,
            "label": "Email draft (edit before sending or ask for changes)",
            "isMultiline": True,
            "value": _draft_input_value(draft_reply, voice_mode=voice_mode),
            "spacing": "Medium",
        }
    )

    body.append(
        {
            "type": "TextBlock",
            "text": "Holds are placed on Calendar after you send. Edit the draft or ask Lexi for changes, then Send.",
            "isSubtle": True,
            "spacing": "Small",
            "wrap": True,
        }
    )

    proposal_id = int(proposal_record["id"])

    writes_allowed = _teams_writes_allowed()
    if not writes_allowed:
        body.append(
            {
                "type": "TextBlock",
                "text": (
                    "**Sends are disabled right now** (UAT safety). "
                    "You can still edit + Save draft. When you're ready for real sends, enable live writes."
                ),
                "wrap": True,
                "spacing": "Small",
                "color": "Attention",
            }
        )

    actions: list[dict[str, Any]] = [
        _submit_action(
            title="Save draft",
            action=CARD_ACTION_SAVE_DRAFT,
            proposal_id=proposal_id,
        ),
    ]
    if writes_allowed:
        actions.append(
            _submit_action(
                title="Send",
                action=CARD_ACTION_APPROVAL,
                proposal_id=proposal_id,
                decision="approved",
                selected_slot="",
                style="positive",
            )
        )
    actions.append(
        _submit_action(
            title="Discard",
            action=CARD_ACTION_APPROVAL,
            proposal_id=proposal_id,
            decision="rejected",
            selected_slot="",
            style="destructive",
        )
    )

    return {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
        "actions": actions,
        "msteams": {"width": "Full"},
    }


def _ensure_complete_draft(
    proposal_record: dict[str, Any],
    email_record: dict[str, Any],
) -> str:
    """Repair stale or malformed drafts using deterministic compose."""
    from app.scheduling.offer_refresh import _draft_needs_repair, _normalize_slots
    from app.scheduling.reply_composer import compose_scheduling_reply

    draft = str(proposal_record.get("drafted_reply") or "").strip()
    slots = _normalize_slots(proposal_record.get("proposed_slots"))
    voice_mode = str(proposal_record.get("voice_mode") or "kory")

    needs_repair = not draft or _draft_needs_repair(draft, slots, voice_mode)

    if not needs_repair:
        return draft

    if not slots:
        return draft

    repaired, _ = compose_scheduling_reply(
        proposal_sender=str(email_record.get("sender") or "") or None,
        proposal_subject=str(email_record.get("subject") or ""),
        proposal_body=str(email_record.get("raw_body") or ""),
        thread_id=str(proposal_record.get("thread_id") or ""),
        slots=slots[:3],
        voice_mode=voice_mode,
        stored_recipient_timezone=str(proposal_record.get("recipient_timezone") or "") or None,
    )
    return repaired or draft


def _holds_text_block(
    holds_list: list[dict[str, Any]],
    proposal_record: dict[str, Any],
    email_record: dict[str, Any],
) -> dict[str, Any] | None:
    if holds_list:
        lines = ["**Times offered**"]
        for index, hold in enumerate(holds_list[:3], start=1):
            slot_start = str(hold.get("slot_start") or "")
            slot_end = str(hold.get("slot_end") or "")
            lines.append(
                f"{index}. {_format_slot_for_card(slot_start, slot_end, proposal_record, email_record)}"
            )
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
                    f"{index}. {_format_slot_for_card(str(slot.get('start', '')), str(slot.get('end', '')), proposal_record, email_record)}"
                )
        return {
            "type": "TextBlock",
            "text": "\n".join(lines),
            "wrap": True,
            "spacing": "Small",
        }
    return None


def _format_slot_for_card(
    slot_start: str,
    slot_end: str,
    proposal_record: dict[str, Any],
    email_record: dict[str, Any],
) -> str:
    from app.scheduling.email_format import format_slot_for_email, should_note_mt_only_timezone
    from app.scheduling.timezone_intel import lookup_recipient_timezone
    from app.config import settings
    from zoneinfo import ZoneInfo

    if not slot_start:
        return "Unavailable"
    mt = ZoneInfo(settings.scheduling_timezone)
    tz_result = lookup_recipient_timezone(
        sender_email=str(email_record.get("sender") or ""),
        body=str(email_record.get("raw_body") or ""),
        stored_timezone=str(proposal_record.get("recipient_timezone") or "") or None,
        for_scheduling=True,
    )
    from app.scheduling.timezone_intel import is_timezone_uncertain

    uncertain = is_timezone_uncertain(tz_result)
    mt_only = should_note_mt_only_timezone(
        sender_email=str(email_record.get("sender") or ""),
        uncertain=uncertain,
        tz_confidence=tz_result.confidence,
        tz_source=tz_result.source,
    )
    format_tz = mt if mt_only else (tz_result.timezone or mt)
    return format_slot_for_email(
        {"start": slot_start, "end": slot_end},
        recipient_tz=format_tz,
    )


def _draft_input_value(draft_reply: str, *, voice_mode: str = "kory") -> str:
    from app.scheduling.email_format import normalize_draft_for_display
    from app.scheduling.lexi_voice import LEXI_SIGNOFF_BLOCK, normalize_voice_mode

    if not draft_reply:
        return ""
    mode = normalize_voice_mode(voice_mode)
    stripped = draft_reply.strip()
    if mode == "lexi" and stripped.endswith(LEXI_SIGNOFF_BLOCK):
        return stripped
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


def generate_reoffer_prompt_card(
    proposal_record: dict[str, Any],
    email_record: dict[str, Any],
    *,
    reply_preview: str = "",
) -> dict[str, Any]:
    """Ask Kory whether Lexi should propose a new round of times."""
    from app.bot.teams_format import display_sender, display_subject

    sender = display_sender(str(email_record.get("sender") or "unknown"))
    subject = display_subject(str(email_record.get("subject") or "(no subject)"))
    proposal_id = int(proposal_record["id"])
    preview = (reply_preview or "").strip()
    if len(preview) > 280:
        preview = preview[:277] + "…"

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": "Send more times?",
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": subject,
            "weight": "Bolder",
            "wrap": True,
            "spacing": "Small",
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
            "text": "They said the offered times don't work. Previous holds were released.",
            "wrap": True,
            "spacing": "Medium",
        },
    ]
    if preview:
        body.append(
            {
                "type": "TextBlock",
                "text": f"_{preview}_",
                "isSubtle": True,
                "wrap": True,
                "spacing": "Small",
            }
        )

    writes_allowed = _teams_writes_allowed()
    actions: list[dict[str, Any]] = []
    if writes_allowed:
        actions.append(
            _submit_action(
                title="Find new times",
                action=CARD_ACTION_REOFFER,
                proposal_id=proposal_id,
                decision="approved",
                style="positive",
            )
        )
    actions.append(_im_back_action(title="Not now", message=f"skip reoffer {proposal_id}"))

    if not writes_allowed:
        body.append(
            {
                "type": "TextBlock",
                "text": "**Slot refresh is disabled right now** (UAT safety).",
                "wrap": True,
                "spacing": "Small",
                "color": "Attention",
            }
        )

    return {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
        "actions": actions,
        "msteams": {"width": "Full"},
    }


def generate_invite_prompt_card(
    proposal_record: dict[str, Any],
    email_record: dict[str, Any],
    holds_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Card asking Kory to send the Outlook invite after recipient picked a slot."""
    from app.bot.teams_format import display_sender, display_subject
    from app.scheduling.email_format import format_slot_for_email

    sender = display_sender(str(email_record.get("sender") or "unknown"))
    subject = display_subject(str(email_record.get("subject") or "(no subject)"))
    proposal_id = int(proposal_record["id"])

    selected_raw = proposal_record.get("recipient_selected_slot")
    selected_slot: dict[str, str] | None = None
    if isinstance(selected_raw, dict) and selected_raw.get("start"):
        selected_slot = selected_raw
    elif selected_raw:
        import json

        try:
            parsed = json.loads(str(selected_raw))
            if isinstance(parsed, dict) and parsed.get("start"):
                selected_slot = {"start": str(parsed["start"]), "end": str(parsed.get("end") or "")}
        except json.JSONDecodeError:
            selected_slot = None

    if not selected_slot and holds_list:
        hold = holds_list[0]
        selected_slot = {
            "start": str(hold.get("slot_start") or ""),
            "end": str(hold.get("slot_end") or ""),
        }

    slot_label = (
        format_slot_for_email(selected_slot)
        if selected_slot and selected_slot.get("start")
        else "Unknown time"
    )
    intent = str(proposal_record.get("intent_classification") or "unknown")
    from app.scheduling.invite_builder import default_location_for_intent, is_online_meeting

    location = default_location_for_intent(intent)
    meeting_note = (
        "Microsoft Teams link will be on the invite."
        if is_online_meeting(intent, location)
        else f"Location: {location} (no Teams/Zoom unless requested)."
    )

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": "Send calendar invite?",
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": subject,
            "weight": "Bolder",
            "wrap": True,
            "spacing": "Small",
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
            "text": f"**They picked:** {slot_label}",
            "wrap": True,
            "spacing": "Medium",
        },
        {
            "type": "TextBlock",
            "text": meeting_note,
            "isSubtle": True,
            "wrap": True,
            "spacing": "Small",
        },
    ]

    selected_slot_token = ""
    if selected_slot and selected_slot.get("start"):
        selected_slot_token = str(selected_slot["start"])

    writes_allowed = _teams_writes_allowed()
    actions: list[dict[str, Any]] = []
    if writes_allowed:
        actions.append(
            _submit_action(
                title="Send invite",
                action=CARD_ACTION_INVITE,
                proposal_id=proposal_id,
                decision="approved",
                selected_slot=selected_slot_token,
                style="positive",
            )
        )
    actions.append(_im_back_action(title="Not yet", message=f"skip invite {proposal_id}"))

    if not writes_allowed:
        body.append(
            {
                "type": "TextBlock",
                "text": "**Invite send is disabled right now** (UAT safety).",
                "wrap": True,
                "spacing": "Small",
                "color": "Attention",
            }
        )

    return {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
        "actions": actions,
        "msteams": {"width": "Full"},
    }


def _teams_writes_allowed() -> bool:
    """Whether Teams cards should show send/write buttons."""
    from app.config import settings

    if settings.lexi_dry_run:
        return False
    if settings.lexi_kory_space_read_only:
        return False
    if settings.lexi_kory_outbound_blocked:
        return False
    return True


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

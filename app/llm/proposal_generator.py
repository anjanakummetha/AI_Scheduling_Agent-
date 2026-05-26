"""Draft scheduling replies with Hermes; slots come from the policy engine."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
from typing import Any

from app.config import settings
from app.llm.hermes_client import get_hermes_client
from app.rules.policy_engine import build_scheduling_decision
from app.rules.rule_engine import is_priority_contact, rules_for_prompt


def generate_proposal(
    email: dict[str, Any],
    calendar_context: dict[str, Any] | None = None,
    change_request: str | None = None,
    existing_proposal: dict[str, Any] | None = None,
    scheduling_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if scheduling_decision is None:
        scheduling_decision = build_scheduling_decision(email, calendar_context)
    return draft_proposal_from_decision(
        email,
        scheduling_decision,
        change_request=change_request,
        existing_proposal=existing_proposal,
    )


def draft_proposal_from_decision(
    email: dict[str, Any],
    scheduling_decision: dict[str, Any],
    change_request: str | None = None,
    existing_proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not change_request:
        slots = scheduling_decision.get("proposed_slots") or []
        if slots:
            payload = {
                "draft_reply": _template_reply(email, scheduling_decision),
                "summary": "Deterministic reply from engine-selected coffee/meeting slots.",
            }
        else:
            payload = {
                "draft_reply": _no_slots_reply(email, scheduling_decision),
                "summary": "No legal slots found; Kory review required before offering times.",
            }
        return _merge_engine_proposal(email, scheduling_decision, payload)

    prompt = _build_draft_prompt(
        email,
        scheduling_decision,
        change_request=change_request,
        existing_proposal=existing_proposal,
    )
    try:
        client = get_hermes_client()
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You draft emails in Kory's voice, as if Kory is personally sending them. "
                        "Return only valid JSON with draft_reply and summary. Do not change proposed "
                        "times or add new slots. Do not send emails or book calendar events."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        llm_payload = _parse_json(content)
        return _merge_engine_proposal(email, scheduling_decision, llm_payload)
    except Exception as exc:
        return _merge_engine_proposal(
            email,
            scheduling_decision,
            {
                "draft_reply": _template_reply(email, scheduling_decision),
                "summary": f"Hermes unavailable; used template reply. ({exc})",
            },
        )


def _merge_engine_proposal(
    email: dict[str, Any],
    scheduling_decision: dict[str, Any],
    llm_payload: dict[str, Any],
) -> dict[str, Any]:
    proposal = {
        "intent": scheduling_decision.get("intent", "needs_review"),
        "meeting_type": scheduling_decision.get("meeting_type", "unknown"),
        "priority_contact": scheduling_decision.get("priority_contact", False),
        "summary": llm_payload.get("summary") or scheduling_decision.get("summary", ""),
        "reasoning": scheduling_decision.get("reasoning", []),
        "proposed_slots": scheduling_decision.get("proposed_slots", []),
        "draft_reply": llm_payload.get("draft_reply", ""),
        "calendar_action": scheduling_decision.get("calendar_action", {"type": "none"}),
        "needs_approval": True,
        "should_offer_times": scheduling_decision.get("should_offer_times", False),
    }
    return _normalize_proposal(proposal, email)


def _build_draft_prompt(
    email: dict[str, Any],
    scheduling_decision: dict[str, Any],
    change_request: str | None = None,
    existing_proposal: dict[str, Any] | None = None,
) -> str:
    sender_name = email.get("sender_name") or email["sender_email"]
    mailbox_name = email.get("mailbox_sender_name")
    identity_note = ""
    if mailbox_name and mailbox_name != sender_name:
        identity_note = (
            f"\nNote: Outlook display name is {mailbox_name}, but the email signature "
            f"indicates the sender is {sender_name}. Address the reply to {sender_name}."
        )

    revision_note = ""
    if change_request:
        revision_note = f"""
Revision request from dashboard reviewer:
{change_request}

Current proposal to revise:
{json.dumps(existing_proposal or {}, indent=2)}

Apply the requested changes to tone/wording only. Do not change the fixed slots below.
"""

    slots = scheduling_decision.get("proposed_slots") or []
    slots_note = json.dumps(slots, indent=2) if slots else "[] (do not invent times; ask for context or say you will follow up)"
    reasoning_note = "\n".join(f"- {line}" for line in scheduling_decision.get("reasoning", []))

    return f"""
Draft the email reply for a Phase 1 scheduling proposal. Times are already chosen by the
availability engine — you must use exactly these slots in draft_reply and must not add others.

Policy reasoning:
{reasoning_note}

Fixed proposed_slots (do not modify):
{slots_note}

Intent: {scheduling_decision.get('intent')}
Meeting type: {scheduling_decision.get('meeting_type')}
Should offer times: {scheduling_decision.get('should_offer_times')}
Calendar action type: {(scheduling_decision.get('calendar_action') or {}).get('type')}

Draft in first person as Kory. Never refer to Kory in third person.
Quote recipient timezone first with Mountain Time in parentheses when offering times.
End with exactly:
Let's Win,
Kory

Rules reference:
{rules_for_prompt()}

Incoming email:
From: {sender_name} <{email['sender_email']}>{identity_note}
Subject: {email['subject']}
Body:
{email['body']}

{revision_note}

Return JSON only:
{{
  "summary": "short explanation for reviewer",
  "draft_reply": "full email body"
}}
"""


def _template_reply(email: dict[str, Any], scheduling_decision: dict[str, Any]) -> str:
    first_name = (email.get("sender_name") or "there").split()[0]
    slots = scheduling_decision.get("proposed_slots") or []
    meeting_type = scheduling_decision.get("meeting_type", "meeting")
    intro = (
        "Appreciate you reaching out. I'd love to connect while you're in Denver."
        if "denver" in (email.get("body") or "").lower()
        else "Appreciate you reaching out."
    )
    if meeting_type == "coffee":
        location = slots[0].get("location") or "Olive & Finch in Cherry Creek"
        intro += f" Happy to grab coffee in Cherry Creek ({location}) — a few times that work on my end:"
        if "thursday" in (email.get("body") or "").lower() and slots:
            first_day = datetime.fromisoformat(slots[0]["start"]).strftime("%A")
            if first_day not in {"Thursday", "Friday"}:
                intro += (
                    " I couldn't find a clean 90-minute coffee window this Thursday or Friday "
                    "on my calendar, but here are the next openings that could work:"
                )
    else:
        intro += " A few options that work on my end:"

    lines = "\n".join(
        f"- {_format_slot_line(slot, scheduling_decision.get('recipient_timezone'))}" for slot in slots
    )
    option_note = ""
    if len(slots) >= 2:
        option_note = f"\n\nI'm offering {len(slots)} options so we can lock in what works best for you."
    return (
        f"Hi {first_name},\n\n"
        f"{intro}\n\n"
        f"{lines}{option_note}\n\n"
        "Let me know which works best and I can send a calendar invite.\n\n"
        "Let's Win,\n"
        "Kory"
    )


def _no_slots_reply(email: dict[str, Any], scheduling_decision: dict[str, Any]) -> str:
    first_name = (email.get("sender_name") or "there").split()[0]
    body = (email.get("body") or "").lower()
    day_hint = ""
    if "thursday" in body and "friday" in body:
        day_hint = " this Thursday and Friday"
    elif "thursday" in body:
        day_hint = " this Thursday"
    elif "friday" in body:
        day_hint = " this Friday"

    return (
        f"Hi {first_name},\n\n"
        "Appreciate you reaching out. I'd love to connect while you're in Denver.\n\n"
        f"My calendar is fully committed{day_hint} during the windows that usually work for coffee. "
        "I'm going to take a closer look at my schedule and follow up with you directly "
        "if I can move something to make it work.\n\n"
        "Let's Win,\n"
        "Kory"
    )


def _format_slot_line(slot: dict[str, str], recipient_tz: str | None) -> str:
    from zoneinfo import ZoneInfo

    start = datetime.fromisoformat(slot["start"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=ZoneInfo("America/Denver"))
    end = datetime.fromisoformat(slot["end"])
    if end.tzinfo is None:
        end = end.replace(tzinfo=ZoneInfo("America/Denver"))

    if recipient_tz:
        try:
            rtz = ZoneInfo(recipient_tz)
            r_start = start.astimezone(rtz)
            r_end = end.astimezone(rtz)
            tz_label = _timezone_label(recipient_tz)
            mt_start = start.strftime("%-I:%M %p")
            mt_end = end.strftime("%-I:%M %p")
            return (
                f"{r_start.strftime('%A, %B %-d at %-I:%M %p')} {tz_label} "
                f"({mt_start} to {mt_end} MT)"
            )
        except Exception:
            pass

    return (
        f"{start.strftime('%A, %B %-d at %-I:%M %p')} to "
        f"{end.strftime('%-I:%M %p')} Mountain Time"
    )


def _timezone_label(tz_name: str) -> str:
    labels = {
        "America/New_York": "Eastern",
        "America/Chicago": "Central",
        "America/Denver": "Mountain",
        "America/Los_Angeles": "Pacific",
    }
    return labels.get(tz_name, "local time")


def _parse_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_proposal(proposal: dict[str, Any], email: dict[str, Any]) -> dict[str, Any]:
    proposal["needs_approval"] = True
    proposal["priority_contact"] = is_priority_contact(email["sender_email"]) or bool(
        proposal.get("priority_contact")
    )
    proposal["draft_reply"] = _format_reply_spacing(_fix_greeting(
        _clean_reply(proposal.get("draft_reply", "")),
        email.get("sender_name") or email["sender_email"],
    ))

    if not proposal.get("draft_reply"):
        return _fallback_proposal(email, "Hermes returned an empty reply.")

    return proposal


def _clean_reply(reply: str) -> str:
    replacements = {
        "Thanks for reaching out.": "Appreciate you reaching out.",
        "Thanks,": "",
        "Thanks!": "",
        "Best,": "",
        "Best regards,": "",
        "Warmly,": "",
        "Regards,": "",
        "Sincerely,": "",
    }
    cleaned = reply
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = _fix_kory_voice(cleaned)
    if not re.search(r"\b(Eastern|Central|Pacific)\b.*\(.*MT.*\)", cleaned, flags=re.IGNORECASE):
        cleaned = _fix_time_range_wording(cleaned)

    required_signoff = "Let's Win,\nKory"
    if required_signoff not in cleaned:
        cleaned = cleaned.rstrip()
        cleaned = cleaned.removesuffix("Let's Win,").rstrip()
        cleaned = f"{cleaned}\n\n{required_signoff}"

    return cleaned.strip()


def _fix_kory_voice(reply: str) -> str:
    replacements = [
        (r"\bI have you scheduled for a call with Kory\b", "I can connect"),
        (r"\bI have scheduled you for a call with Kory\b", "I can connect"),
        (r"\byou scheduled for a call with Kory\b", "we can connect"),
        (r"\ba call with Kory\b", "a call with me"),
        (r"\bmeeting with Kory\b", "meeting with me"),
        (r"\bKory will send\b", "I'll send"),
        (r"\bKory can send\b", "I can send"),
        (r"\bKory is available\b", "I'm available"),
        (r"\bKory can connect\b", "I can connect"),
        (r"\bKory can meet\b", "I can meet"),
        (r"\bKory's calendar\b", "my calendar"),
        (r"\bKory's availability\b", "my availability"),
        (r"\bmy scheduling agent\b", "I"),
    ]
    cleaned = reply
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bI can connect today from ([^.]+)\.", r"I can do today from \1.", cleaned)
    return cleaned


def _fix_time_range_wording(reply: str) -> str:
    def replace_full_range(match: re.Match[str]) -> str:
        start = _format_time_text(match.group("start_hour"), match.group("start_minute"), match.group("start_period"))
        end = _format_time_text(match.group("end_hour"), match.group("end_minute"), match.group("end_period"))
        return f"{start} to {end} Mountain Time"

    cleaned = re.sub(
        r"\b(?P<start_hour>\d{1,2})(?::(?P<start_minute>\d{2}))?\s*(?P<start_period>AM|PM|am|pm)"
        r"\s*[-–]\s*"
        r"(?P<end_hour>\d{1,2})(?::(?P<end_minute>\d{2}))?\s*(?P<end_period>AM|PM|am|pm)\b"
        r"(?!\s*(?:Mountain Time|MT|MST|MDT|Eastern|Central|Pacific))",
        replace_full_range,
        reply,
    )

    def replace_short_range(match: re.Match[str]) -> str:
        start = _format_time_text(match.group("start_hour"), None, match.group("period"))
        end = _format_time_text(match.group("end_hour"), match.group("end_minute"), match.group("period"))
        return f"{start} to {end} Mountain Time"

    cleaned = re.sub(
        r"\b(?P<start_hour>\d{1,2})\s*[-–]\s*"
        r"(?P<end_hour>\d{1,2})(?::(?P<end_minute>\d{2}))?\s*(?P<period>AM|PM|am|pm)\b"
        r"(?!\s*(?:Mountain Time|MT|MST|MDT))",
        replace_short_range,
        cleaned,
    )

    def replace_single_time(match: re.Match[str]) -> str:
        time_text = _format_time_text(match.group("hour"), match.group("minute"), match.group("period"))
        return f"{match.group('prefix')}{time_text} Mountain Time"

    cleaned = re.sub(
        r"\b(?P<prefix>at |around |from |by |before |after )"
        r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<period>AM|PM|am|pm)\b"
        r"(?!\s*(?:Mountain Time|MT|MST|MDT|to\b))",
        replace_single_time,
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _format_time_text(hour: str, minute: str | None, period: str) -> str:
    return f"{int(hour)}:{minute or '00'} {period.upper()}"


def _fix_greeting(reply: str, sender_name: str) -> str:
    first_name = sender_name.split()[0] if sender_name else ""
    if not first_name or "@" in first_name:
        return reply

    lines = reply.splitlines()
    if not lines:
        return reply

    greeting_pattern = re.compile(r"^(hi|hey|hello|dear)?\s*[A-Za-z][A-Za-z .'-]{0,40},$", re.IGNORECASE)
    if greeting_pattern.match(lines[0].strip()):
        lines[0] = f"Hi {first_name},"
        return "\n".join(lines).strip()

    return f"Hi {first_name},\n\n{reply.strip()}"


def _format_reply_spacing(reply: str) -> str:
    normalized = reply.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = re.sub(r"^(Hi [A-Za-z][A-Za-z .'-]*,)\s+", r"\1\n\n", normalized)
    normalized = re.sub(r"\s+(Let's Win,\s*Kory)\s*$", r"\n\n\1", normalized)
    normalized = normalized.replace("Let's Win, Kory", "Let's Win,\nKory")
    normalized = re.sub(
        r"(\([A-Za-z ]+\))\s+(-\s+)",
        r"\1\n\2",
        normalized,
    )
    normalized = re.sub(
        r"(\([A-Za-z ]+\))\s+(Let me know|I'll|I will|If)",
        r"\1\n\n\2",
        normalized,
    )
    lines = [line.strip() for line in normalized.split("\n")]

    paragraphs: list[str] = []
    current: list[str] = []

    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue

        if line.startswith("- "):
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            paragraphs.append(line)
            continue

        if line in {"Let's Win,", "Kory"}:
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            paragraphs.append(line)
            continue

        current.append(line)

    if current:
        paragraphs.append(" ".join(current).strip())

    formatted: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        formatted.append(paragraph)
        next_paragraph = paragraphs[index + 1] if index + 1 < len(paragraphs) else None
        if paragraph == "Let's Win,":
            continue
        if next_paragraph == "Kory":
            continue
        if paragraph.startswith("- ") and next_paragraph and next_paragraph.startswith("- "):
            continue
        if next_paragraph is not None:
            formatted.append("")

    return "\n".join(formatted).strip()


def _fallback_proposal(email: dict[str, Any], reason: str) -> dict[str, Any]:
    start = _next_demo_slot()
    end = start + timedelta(minutes=30)
    priority = is_priority_contact(email["sender_email"])
    meeting_type = "priority_contact" if priority else "referral_or_intro"
    return {
        "intent": "schedule_meeting",
        "meeting_type": meeting_type,
        "priority_contact": priority,
        "summary": reason,
        "proposed_slots": [
            {
                "start": start.isoformat(timespec="seconds"),
                "end": end.isoformat(timespec="seconds"),
                "timezone": "America/Denver",
                "reason": "Demo fallback slot; verify against Outlook before approval.",
            }
        ],
        "draft_reply": (
            f"Hi {(email.get('sender_name') or 'there').split()[0]},\n\n"
            "Kory can connect for 30 minutes at the time below. "
            "Please confirm whether this works for you.\n\n"
            f"{start.strftime('%A at %-I:%M %p')} Mountain Time\n\n"
            "Let's Win,\n"
            "Kory"
        ),
        "calendar_action": {
            "type": "create_event",
            "title": f"Meeting with {email.get('sender_name') or email['sender_email']}",
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "timezone": "America/Denver",
            "attendees": [email["sender_email"]],
            "location": "Teams",
            "meeting_type": meeting_type,
        },
        "needs_approval": True,
    }


def _next_demo_slot() -> datetime:
    now = datetime.now().replace(second=0, microsecond=0)
    candidate = now + timedelta(days=1)
    return candidate.replace(hour=10, minute=0)

"""Programmatic safety checks for Hermes scheduling proposals."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from app.rules.availability_engine import slot_key
from app.rules.policy_engine import legal_slot_keys
from app.rules.rule_engine import load_rules


def validate_proposal(
    proposal: dict[str, Any],
    expected_recipient_name: str | None = None,
    scheduling_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = load_rules()["scheduling"]
    errors: list[str] = []
    warnings: list[str] = []

    if not proposal.get("draft_reply"):
        errors.append("Missing draft reply.")

    draft_reply = proposal.get("draft_reply", "")
    required_signoff = rules["email"]["sign_off"]
    if required_signoff not in draft_reply:
        errors.append("Draft reply is missing required sign-off.")

    closing_lines = _closing_lines(draft_reply)
    for closing in rules["email"].get("forbidden_closings", []):
        if closing.lower() in closing_lines:
            errors.append(f"Draft reply contains forbidden closing: {closing}.")

    for topic in rules["email"].get("forbidden_topics", []):
        if topic.lower() in draft_reply.lower():
            errors.append(f"Draft reply contains forbidden topic: {topic}.")

    errors.extend(_validate_kory_voice(draft_reply))
    errors.extend(_validate_time_labels(draft_reply))

    calendar_action = proposal.get("calendar_action") or {}
    if calendar_action.get("type") == "create_event":
        if not calendar_action.get("start") or not calendar_action.get("end"):
            errors.append("Calendar event proposal is missing start or end time.")
        else:
            errors.extend(_validate_calendar_times(calendar_action))
    else:
        warnings.append("No calendar event will be created for this proposal.")

    if proposal.get("needs_approval") is not True:
        errors.append("Proposal must explicitly require Phase 1 approval.")

    if expected_recipient_name:
        errors.extend(_validate_greeting(draft_reply, expected_recipient_name))

    if scheduling_decision:
        allowed = legal_slot_keys(scheduling_decision)
        proposed = proposal.get("proposed_slots") or []
        for slot in proposed:
            if allowed and slot_key(slot) not in allowed:
                errors.append(
                    f"Proposed slot {slot.get('start')} was not produced by the availability engine."
                )
        warnings.extend(
            line for line in scheduling_decision.get("reasoning", []) if line not in warnings
        )

        if proposed and scheduling_decision.get("should_offer_times"):
            min_options = int(
                load_rules()["scheduling"].get("offering", {}).get("min_slot_options", 2)
            )
            if len(proposed) < min_options:
                warnings.append(
                    f"Only {len(proposed)} slot(s) offered; policy prefers {min_options}-3 options."
                )
            lowered = draft_reply.lower()
            if any(
                phrase in lowered
                for phrase in (
                    "no availability",
                    "don't have any availability",
                    "do not have any availability",
                    "fully committed",
                    "my team",
                )
            ):
                errors.append(
                    "Draft declines or defers despite engine-provided slots, or uses forbidden phrasing."
                )
            if scheduling_decision.get("recipient_timezone") and proposed:
                if not re.search(r"\b(Eastern|Central|Pacific|ET|CT|PT)\b", draft_reply, re.I):
                    if not re.search(r"\(.*MT.*\)", draft_reply, re.I):
                        errors.append(
                            "Draft should quote recipient timezone first with MT in parentheses."
                        )
            if proposal.get("meeting_type") == "coffee" and proposed:
                if "cherry creek" not in lowered and "olive" not in lowered:
                    warnings.append("Coffee reply should mention Cherry Creek / coffee location.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "engine_reasoning": (scheduling_decision or {}).get("reasoning", []),
    }


def _validate_calendar_times(calendar_action: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        start = datetime.fromisoformat(calendar_action["start"])
        end = datetime.fromisoformat(calendar_action["end"])
    except ValueError:
        return ["Calendar start/end must be ISO datetime strings."]

    if end <= start:
        errors.append("Calendar event end time must be after start time.")

    if start.hour < 6:
        errors.append("Calendar event starts before the earliest possible demo window.")

    if end.hour > 18 and calendar_action.get("meeting_type") != "dinner":
        errors.append("Calendar event ends after 6 PM without dinner exception.")

    return errors


def _validate_kory_voice(reply: str) -> list[str]:
    forbidden_patterns = [
        r"\bKory will\b",
        r"\bKory can\b",
        r"\bKory is available\b",
        r"\bcall with Kory\b",
        r"\bmeeting with Kory\b",
        r"\bKory's calendar\b",
        r"\bKory's availability\b",
        r"\bI have you scheduled\b",
        r"\bmy scheduling agent\b",
        r"\bmy team will\b",
        r"\bmy team\b",
    ]
    lowered_reply = reply.lower()
    errors: list[str] = []
    for pattern in forbidden_patterns:
        if re.search(pattern, lowered_reply, flags=re.IGNORECASE):
            errors.append("Draft reply must be written as Kory speaking directly, not as an assistant.")
            break
    return errors


def _validate_time_labels(reply: str) -> list[str]:
    if not re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)\b", reply):
        return []

    if re.search(
        r"\(.*\bMT\b.*\)|\b(?:Mountain Time|MT|MST|MDT|Eastern|Central|Pacific)\b",
        reply,
        flags=re.IGNORECASE,
    ):
        return []

    return ["Draft reply mentions a time but does not specify timezone (recipient first, MT in parentheses)."]


def _closing_lines(reply: str) -> set[str]:
    lines = [line.strip().lower().rstrip(",.!") for line in reply.splitlines() if line.strip()]
    return set(lines[-4:])


def _validate_greeting(reply: str, expected_recipient_name: str) -> list[str]:
    first_name = expected_recipient_name.split()[0] if expected_recipient_name else ""
    if not first_name or "@" in first_name:
        return []

    first_line = next((line.strip() for line in reply.splitlines() if line.strip()), "")
    match = re.match(r"^(?:hi|hey|hello|dear)?\s*([A-Za-z][A-Za-z .'-]{0,40}),$", first_line, re.IGNORECASE)
    if not match:
        return [f"Draft reply is missing a greeting to {first_name}."]

    greeted_name = match.group(1).split()[0].lower()
    if greeted_name != first_name.lower():
        return [f"Draft reply greets {match.group(1)} but should greet {first_name}."]

    return []

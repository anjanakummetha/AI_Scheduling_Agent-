"""Rule-based email classification before availability search."""

from __future__ import annotations

import re
from typing import Any

from app.rules.rule_engine import load_rules
from app.rules.email_constraints import infer_recipient_timezone, is_east_coast_contact


def classify_email(email: dict[str, Any]) -> dict[str, Any]:
    subject = (email.get("subject") or "").lower()
    body = (email.get("body") or "").lower()
    text = f"{subject}\n{body}"

    intent = _detect_intent(text)
    meeting_type = _detect_meeting_type(text, intent)
    meeting_format = _detect_format(text, meeting_type)
    urgency = _detect_urgency(meeting_type, text)
    should_offer_times = _should_offer_times(intent, meeting_type, text)
    priority_contact = _is_priority_contact(email["sender_email"])
    east_coast = is_east_coast_contact(body)
    recipient_timezone = infer_recipient_timezone(body)

    if priority_contact and meeting_type == "unknown":
        meeting_type = "priority_contact"

    notes = _classification_notes(intent, meeting_type, should_offer_times)
    if east_coast:
        notes.append("East Coast contact detected — Tue/Thu early windows allowed when rules permit.")
    if urgency == "same_week":
        notes.append("Same-week urgency applied (prospect/new client/time-sensitive).")

    return {
        "intent": intent,
        "meeting_type": meeting_type,
        "meeting_format": meeting_format,
        "urgency": urgency,
        "should_offer_times": should_offer_times,
        "priority_contact": priority_contact,
        "east_coast_contact": east_coast,
        "recipient_timezone": recipient_timezone,
        "classification_notes": notes,
    }


def _is_priority_contact(email: str) -> bool:
    from app.rules.rule_engine import is_priority_contact

    return is_priority_contact(email)


def _detect_intent(text: str) -> str:
    if re.search(r"\b(cancel|cancellation)\b", text):
        return "cancellation"
    if re.search(r"\b(reschedul|rain check|move our|different time)\b", text):
        return "reschedule"
    if re.search(r"\b(newsletter|unsubscribe|no reply needed|fyi only)\b", text):
        return "non_scheduling"
    if re.search(
        r"\b(schedule|find time|meet|coffee|call|zoom|teams|calendar|availability|"
        r"when works|time slot|happy hour|dinner|podcast|interview|this week|next week|"
        r"\d+\s*minute|new client|prospective client|prospect|acquisition)\b",
        text,
    ):
        return "schedule_meeting"
    return "needs_review"


def _detect_meeting_type(text: str, intent: str) -> str:
    if intent == "reschedule":
        return "reschedule"
    if re.search(r"\b(podcast|the turn|recording session)\b", text):
        return "podcast"
    if _is_prospect_or_new_client(text):
        if re.search(r"\bcoffee\b", text):
            return "coffee"
        return "new_client"
    if re.search(r"\b(happy hour|drinks after work)\b", text):
        return "happy_hour"
    if re.search(r"\b(dinner)\b", text):
        return "dinner"
    if re.search(r"\bcoffee\b", text):
        return "coffee"
    if re.search(r"\b(referral)\b", text) or (
        re.search(r"\b(intro|introduction)\b", text)
        and not re.search(r"\bnew client\b", text)
    ):
        return "referral_or_intro"
    if intent == "schedule_meeting":
        return "referral_or_intro"
    return "unknown"


def _is_prospect_or_new_client(text: str) -> bool:
    return bool(
        re.search(
            r"\b(new client|prospect|prospective client|term sheet|first meeting with|"
            r"acquisition opportunit|evaluating a few acquisition|operators in|in town unexpectedly)\b",
            text,
        )
    )


def _detect_format(text: str, meeting_type: str) -> str:
    if meeting_type in {"coffee", "happy_hour", "dinner"}:
        return "in_person"
    if re.search(r"\b(in[- ]?person|meet at|come by|grab coffee|in town)\b", text):
        return "in_person"
    if re.search(r"\b(teams|zoom|virtual|phone call)\b", text):
        return "virtual"
    if re.search(r"\b(call|meet)\b", text) and meeting_type not in {"coffee", "happy_hour", "dinner"}:
        return "virtual"
    return "virtual"


def _detect_urgency(meeting_type: str, text: str) -> str:
    if _is_prospect_or_new_client(text) or meeting_type == "new_client":
        return "same_week"
    if re.search(r"\b(urgent|asap|this week|same week|in town unexpectedly)\b", text):
        return "same_week"
    if re.search(r"\b(unexpectedly|in town)\b", text) and re.search(
        r"\b(denver|thursday|friday)\b", text
    ):
        return "same_week"
    if meeting_type == "podcast":
        return "low"
    if meeting_type == "reschedule":
        return "high"
    return "normal"


def _should_offer_times(intent: str, meeting_type: str, text: str) -> bool:
    if intent in {"cancellation", "non_scheduling"}:
        return False
    if intent == "needs_review":
        return False

    rules = load_rules()["scheduling"]
    necessary = set(rules.get("offering", {}).get("necessary_meeting_types", []))
    if meeting_type in necessary:
        return True

    if intent == "schedule_meeting" and re.search(
        r"\b(\d{1,2}(:\d{2})?\s*(am|pm)|next week|this week|monday|tuesday|wednesday|thursday|friday)\b",
        text,
    ):
        return True

    if re.search(r"\b(let's connect|catch up sometime|would love to connect)\b", text):
        if not re.search(r"\b(when|time|schedule|available)\b", text):
            return False

    return intent == "schedule_meeting" and meeting_type in {"referral_or_intro", "podcast"}


def _classification_notes(intent: str, meeting_type: str, should_offer_times: bool) -> list[str]:
    notes = [f"Intent classified as {intent}."]
    notes.append(f"Meeting type classified as {meeting_type}.")
    if not should_offer_times:
        notes.append("Policy: not offering times until meeting appears necessary or timing is explicit.")
    return notes

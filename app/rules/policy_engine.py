"""Policy layer: classify, find legal slots, pick options, calendar action."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.integrations.outlook_calendar import has_conflict
from app.rules.availability_engine import find_legal_slots, slot_key
from app.rules.classifier import classify_email
from app.rules.email_constraints import infer_recipient_timezone, parse_requested_weekdays
from app.rules.rule_engine import load_rules

TZ = ZoneInfo("America/Denver")


def build_scheduling_decision(
    email: dict[str, Any],
    calendar_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = load_rules()
    scheduling = rules["scheduling"]
    classification = classify_email(email)
    busy_events = (calendar_context or {}).get("busy_events") or []

    reasoning: list[str] = list(classification.get("classification_notes", []))
    if calendar_context and calendar_context.get("status") != "available":
        reasoning.append("Outlook calendar context unavailable; slots may be incomplete.")

    meeting_type = classification["meeting_type"]
    should_offer = classification["should_offer_times"]
    duration = _requested_duration_minutes(email.get("body", ""))
    east_coast = classification.get("east_coast_contact", False)
    recipient_tz = classification.get("recipient_timezone") or infer_recipient_timezone(
        email.get("body", "")
    )

    legal_slots: list[dict[str, Any]] = []
    proposed_slots: list[dict[str, Any]] = []

    if should_offer and classification["intent"] in {"schedule_meeting", "reschedule"}:
        preferred_dates = parse_requested_weekdays(email.get("body", ""))
        if preferred_dates:
            reasoning.append(
                "Email mentioned specific days; searching those dates first: "
                + ", ".join(day.isoformat() for day in preferred_dates)
            )
        legal_slots = find_legal_slots(
            meeting_type=meeting_type,
            meeting_format=classification["meeting_format"],
            busy_events=busy_events,
            urgency=classification["urgency"],
            requested_duration_minutes=duration,
            preferred_dates=preferred_dates or None,
            east_coast_contact=east_coast,
        )
        min_needed = int(scheduling.get("offering", {}).get("min_slot_options", 2))
        if len(legal_slots) < min_needed:
            reasoning.append("Fewer than 2 slots on requested days; widening search.")
            extra = find_legal_slots(
                meeting_type=meeting_type,
                meeting_format=classification["meeting_format"],
                busy_events=busy_events,
                urgency=classification["urgency"],
                requested_duration_minutes=duration,
                east_coast_contact=east_coast,
            )
            legal_slots = _merge_slots(legal_slots, extra)

        if len(legal_slots) < min_needed and classification["urgency"] == "same_week":
            reasoning.append(
                "Same-week windows are full on the live calendar; searching further out."
            )
            extra = find_legal_slots(
                meeting_type=meeting_type,
                meeting_format=classification["meeting_format"],
                busy_events=busy_events,
                urgency="normal",
                requested_duration_minutes=duration,
                east_coast_contact=east_coast,
            )
            legal_slots = _merge_slots(legal_slots, extra)

        legal_slots = _drop_conflicting_slots(legal_slots)
        proposed_slots = _select_slots(legal_slots, scheduling, classification)
        reasoning.append(f"Availability engine found {len(legal_slots)} legal slot(s) open on live Outlook.")
        reasoning.append(f"Policy selected {len(proposed_slots)} option(s) for the reply.")
        if meeting_type == "coffee":
            reasoning.append(
                f"Coffee holds use {scheduling.get('buffers', {}).get('coffee_block_minutes', 90)} "
                f"minutes at {_coffee_location(scheduling)}."
            )
        if not proposed_slots:
            reasoning.append("No legal slots in search window; escalation recommended.")
    else:
        reasoning.append("Policy chose not to offer time options for this email.")

    calendar_action = _calendar_action(
        email,
        classification,
        proposed_slots,
        scheduling,
    )
    intent = classification["intent"]
    if not proposed_slots and should_offer:
        intent = "needs_review"

    return {
        "intent": intent,
        "meeting_type": meeting_type,
        "priority_contact": classification["priority_contact"],
        "should_offer_times": should_offer,
        "urgency": classification["urgency"],
        "meeting_format": classification["meeting_format"],
        "east_coast_contact": east_coast,
        "recipient_timezone": recipient_tz,
        "reasoning": reasoning,
        "legal_slots": legal_slots,
        "proposed_slots": proposed_slots,
        "calendar_action": calendar_action,
        "needs_approval": True,
        "summary": " | ".join(reasoning[:4]),
    }


def _select_slots(
    legal_slots: list[dict[str, Any]],
    scheduling: dict[str, Any],
    classification: dict[str, Any],
) -> list[dict[str, Any]]:
    offering = scheduling.get("offering", {})
    min_options = int(offering.get("min_slot_options", 2))
    max_options = int(offering.get("max_slot_options", 3))
    hold_types = set(offering.get("offer_holds_for_types", []))

    target_count = max_options if classification["meeting_type"] in hold_types else min_options
    if classification["meeting_type"] in {"coffee", "new_client"}:
        target_count = max_options

    if classification["urgency"] == "same_week":
        week_end = datetime.now(tz=TZ) + timedelta(days=7)
        same_week = [
            slot
            for slot in legal_slots
            if datetime.fromisoformat(slot["start"]).astimezone(TZ) <= week_end
        ]
        if len(same_week) >= min_options:
            legal_slots = same_week

    if not legal_slots:
        return []

    selected: list[dict[str, Any]] = []
    used_days: set[str] = set()
    for slot in legal_slots:
        if any(_slots_overlap(slot, chosen) for chosen in selected):
            continue
        day = datetime.fromisoformat(slot["start"]).date().isoformat()
        if day in used_days and len(selected) >= min_options:
            continue
        selected.append(slot)
        used_days.add(day)
        if len(selected) >= target_count:
            break

    if len(selected) < min_options:
        for slot in legal_slots:
            if slot in selected:
                continue
            if any(_slots_overlap(slot, chosen) for chosen in selected):
                continue
            selected.append(slot)
            if len(selected) >= min(len(legal_slots), target_count):
                break

    return selected[:target_count]


def _slots_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    start_a = datetime.fromisoformat(left["start"]).astimezone(TZ)
    end_a = datetime.fromisoformat(left["end"]).astimezone(TZ)
    start_b = datetime.fromisoformat(right["start"]).astimezone(TZ)
    end_b = datetime.fromisoformat(right["end"]).astimezone(TZ)
    return start_a < end_b and end_a > start_b


def _calendar_action(
    email: dict[str, Any],
    classification: dict[str, Any],
    proposed_slots: list[dict[str, Any]],
    scheduling: dict[str, Any],
) -> dict[str, Any]:
    if not proposed_slots:
        return {"type": "none"}

    holds_cfg = scheduling.get("holds", {})
    meeting_type = classification["meeting_type"]
    hold_types = set(scheduling.get("offering", {}).get("offer_holds_for_types", []))
    offer_holds = holds_cfg.get("enabled") and meeting_type in hold_types

    contact_name = _hold_contact_name(email)
    location = proposed_slots[0].get("location") or _default_location(classification, scheduling)

    if offer_holds and len(proposed_slots) >= 2:
        holds = []
        title_format = holds_cfg.get("title_format", "HOLD - {name} - Option {option}")
        for index, slot in enumerate(proposed_slots, start=1):
            holds.append(
                {
                    "title": title_format.format(name=contact_name, option=index),
                    "start": slot["start"],
                    "end": slot["end"],
                    "timezone": slot.get("timezone", "America/Denver"),
                    "attendees": [email["sender_email"]],
                    "location": slot.get("location") or location,
                    "meeting_type": meeting_type,
                }
            )
        return {
            "type": "create_holds",
            "holds": holds,
            "meeting_type": meeting_type,
        }

    first = proposed_slots[0]
    title = (
        f"Coffee with {contact_name}"
        if meeting_type == "coffee"
        else f"Meeting with {contact_name}"
    )
    return {
        "type": "create_event",
        "title": title,
        "start": first["start"],
        "end": first["end"],
        "timezone": first.get("timezone", "America/Denver"),
        "attendees": [email["sender_email"]],
        "location": first.get("location") or location,
        "meeting_type": meeting_type,
    }


def _hold_contact_name(email: dict[str, Any]) -> str:
    """First name from email signature — not the Outlook mailbox display name."""
    sender_name = (email.get("sender_name") or "").strip()
    if sender_name and "@" not in sender_name:
        return sender_name.split()[0]

    mailbox_name = (email.get("mailbox_sender_name") or "").strip()
    if mailbox_name and "@" not in mailbox_name and mailbox_name != sender_name:
        return mailbox_name.split()[0]

    local = email.get("sender_email", "").split("@")[0]
    if local:
        return local.replace(".", " ").replace("_", " ").split()[0].capitalize()
    return "Guest"


def _coffee_location(scheduling: dict[str, Any]) -> str:
    return scheduling.get("coffee", {}).get("default_location", "Olive & Finch, Cherry Creek")


def _default_location(classification: dict[str, Any], scheduling: dict[str, Any]) -> str:
    if classification["meeting_format"] == "in_person":
        if classification["meeting_type"] == "coffee":
            return _coffee_location(scheduling)
        if classification["meeting_type"] == "happy_hour":
            return "Cherry Creek Grill"
        return "Denver metro"
    return "Teams"


def _requested_duration_minutes(body: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\s*[- ]?\s*minute\b", body, flags=re.IGNORECASE)
    if not match:
        return None
    minutes = int(match.group(1))
    return minutes if 5 <= minutes <= 180 else None


def legal_slot_keys(decision: dict[str, Any]) -> set[str]:
    return {slot_key(slot) for slot in decision.get("legal_slots", [])}


def _drop_conflicting_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_slots: list[dict[str, Any]] = []
    for slot in slots:
        try:
            conflict, _events, _log = has_conflict(slot)
        except Exception:
            continue
        if not conflict:
            open_slots.append(slot)
    return open_slots


def _merge_slots(
    existing: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen = {slot_key(slot) for slot in existing}
    merged = list(existing)
    for slot in extra:
        key = slot_key(slot)
        if key not in seen:
            merged.append(slot)
            seen.add(key)
    return merged

"""Parse which offered slot a recipient selected in their reply."""

from __future__ import annotations

import re
from typing import Any

from app.scheduling.busy_intervals import parse_iso_datetime
from app.scheduling.email_format import format_slot_for_email


def _reply_text_for_matching(body: str) -> str:
    """Use only the recipient's new text — not quoted offer lines below."""
    text = (body or "").strip()
    if not text:
        return ""
    lower = text.lower()
    for marker in (
        "\nfrom:",
        "\n-----original message-----",
        "\n________________________________",
        "\n> ",
        "\non ",
        "[prior messages in this email chain]",
    ):
        idx = lower.find(marker)
        if idx > 0:
            text = text[:idx]
            lower = text.lower()
    return text.strip()


def match_recipient_slot_choice(
    body: str,
    proposed_slots: list[dict[str, str]],
    *,
    sender_email: str | None = None,
) -> dict[str, str] | None:
    """Return the matching slot dict if the reply picks one of the offered times."""
    if not body or not proposed_slots:
        return None
    text = _reply_text_for_matching(body).lower()
    if not text:
        return None

    for pattern, index in (
        (r"\boption\s*1\b", 0),
        (r"\boption\s*2\b", 1),
        (r"\boption\s*3\b", 2),
        (r"\bfirst (?:one|option|time|slot)\b", 0),
        (r"\bsecond (?:one|option|time|slot)\b", 1),
        (r"\bthird (?:one|option|time|slot)\b", 2),
        (r"\b1(?:st)?\s+(?:works|is fine|sounds good)\b", 0),
        (r"\b2(?:nd)?\s+(?:works|is fine|sounds good)\b", 1),
        (r"\b3(?:rd)?\s+(?:works|is fine|sounds good)\b", 2),
    ):
        if re.search(pattern, text) and index < len(proposed_slots):
            return proposed_slots[index]

    for slot in proposed_slots:
        start = parse_iso_datetime(str(slot.get("start") or ""))
        if not start:
            continue
        weekday = start.strftime("%A").lower()
        if weekday in text:
            hour_token = str(int(start.strftime("%I")))
            minute_token = start.strftime("%M")
            if re.search(
                rf"\b{re.escape(weekday)}\b[^\n]{{0,40}}\b{hour_token}(?::{minute_token})?\b",
                text,
            ):
                return slot

    for slot in proposed_slots:
        formatted = format_slot_for_email(slot, recipient_tz=None).lower()
        day_part = formatted.split(" at ", 1)[0] if " at " in formatted else ""
        if day_part and day_part in text:
            return slot
        start = parse_iso_datetime(str(slot.get("start") or ""))
        if not start:
            continue
        weekday = start.strftime("%A").lower()
        if re.search(rf"\b{re.escape(weekday)}\b", text) and len(proposed_slots) <= 3:
            for s in proposed_slots:
                s_start = parse_iso_datetime(str(s.get("start") or ""))
                if s_start and s_start.strftime("%A").lower() == weekday:
                    if s is slot:
                        return slot

    if re.search(r"\b(any|either|all)\b.*\bwork", text) and proposed_slots:
        return proposed_slots[0]

    for slot in proposed_slots:
        start = parse_iso_datetime(str(slot.get("start") or ""))
        if not start:
            continue
        from app.config import settings
        from zoneinfo import ZoneInfo

        local = start.astimezone(ZoneInfo(settings.scheduling_timezone))
        hour12 = int(local.strftime("%I"))
        minute = local.strftime("%M")
        hour_variants = {str(hour12), f"{hour12:02d}"}
        for hour_token in hour_variants:
            for pattern in (
                rf"\b{hour_token}:{minute}\b[^\n]{{0,30}}\b(?:works|is fine|sounds good|good for me)\b",
                rf"\b{hour_token}(?::{minute})?\s*(?:am|pm)\b[^\n]{{0,30}}\b(?:works|is fine|sounds good)\b",
            ):
                if re.search(pattern, text):
                    return slot

    return None


_REJECTION_PATTERNS = (
    r"\bnone of (?:the |those )?(?:times|options|slots)\b",
    r"\b(?:don't|do not|won't|will not|can't|cannot) work\b",
    r"\bnot (?:going to |gonna )?work\b",
    r"\bnone work\b",
    r"\bno (?:of the )?(?:times|options) work\b",
    r"\bneed (?:different|other|new) times\b",
    r"\b(?:different|other|new) times\b",
    r"\bnot available\b",
    r"\bwon't be available\b",
    r"\bcan't make (?:any|those|it)\b",
    r"\bunavailable (?:on|for|at)\b",
    r"\bwhat else (?:do you|have you) got\b",
    r"\bany other (?:times|options|availability)\b",
)


def recipient_times_rejected(body: str) -> bool:
    """True when the reply indicates offered slots don't work (not a slot pick)."""
    if not body.strip():
        return False
    text = body.lower()
    return any(re.search(p, text) for p in _REJECTION_PATTERNS)

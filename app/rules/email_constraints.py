"""Parse scheduling constraints mentioned in inbound email text."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.rules.rule_engine import load_rules

TZ = ZoneInfo("America/Denver")
WEEKDAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_requested_weekdays(body: str, anchor: datetime | None = None) -> list[date]:
    anchor = (anchor or datetime.now(tz=TZ)).astimezone(TZ)
    text = body.lower()
    found: list[date] = []

    for name, index in WEEKDAY_NAMES.items():
        if not re.search(rf"\b{re.escape(name)}\b", text):
            continue
        days_ahead = (index - anchor.weekday()) % 7
        if days_ahead == 0 and re.search(r"\bnext\s+" + re.escape(name) + r"\b", text):
            days_ahead = 7
        target = (anchor + timedelta(days=days_ahead)).date()
        if target not in found:
            found.append(target)

    return sorted(found)


def infer_recipient_timezone(body: str) -> str | None:
    rules = load_rules()["scheduling"]
    east_cfg = rules.get("east_coast", {})
    text = body.lower()
    for keyword in east_cfg.get("keywords", []):
        if keyword in text:
            return east_cfg.get("timezone", "America/New_York")
    if re.search(r"\b(boston|new york|nyc|eastern|east coast)\b", text):
        return "America/New_York"
    if re.search(r"\b(chicago|central time)\b", text):
        return "America/Chicago"
    if re.search(r"\b(los angeles|pacific|west coast)\b", text):
        return "America/Los_Angeles"
    if re.search(r"\b(denver|mountain)\b", text):
        return "America/Denver"
    return None


def is_east_coast_contact(body: str) -> bool:
    return infer_recipient_timezone(body) == "America/New_York"

"""US/Canada NANP area code → primary timezone (Heidi: check area code when email is silent)."""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo

# Area code → IANA (most common zone for that code; not perfect for edge cases).
_AREA_CODE_TZ: dict[str, str] = {
    # Eastern
    "201": "America/New_York",
    "202": "America/New_York",
    "203": "America/New_York",
    "212": "America/New_York",
    "213": "America/Los_Angeles",
    "214": "America/Chicago",
    "215": "America/New_York",
    "216": "America/New_York",
    "301": "America/New_York",
    "303": "America/Denver",
    "305": "America/New_York",
    "310": "America/Los_Angeles",
    "312": "America/Chicago",
    "313": "America/New_York",
    "314": "America/Chicago",
    "323": "America/Los_Angeles",
    "347": "America/New_York",
    "404": "America/New_York",
    "415": "America/Los_Angeles",
    "416": "America/New_York",
    "425": "America/Los_Angeles",
    "469": "America/Chicago",
    "480": "America/Phoenix",
    "503": "America/Los_Angeles",
    "512": "America/Chicago",
    "513": "America/New_York",
    "514": "America/New_York",
    "602": "America/Phoenix",
    "617": "America/New_York",
    "619": "America/Los_Angeles",
    "646": "America/New_York",
    "650": "America/Los_Angeles",
    "702": "America/Los_Angeles",
    "703": "America/New_York",
    "704": "America/New_York",
    "713": "America/Chicago",
    "718": "America/New_York",
    "720": "America/Denver",
    "732": "America/New_York",
    "773": "America/Chicago",
    "786": "America/New_York",
    "801": "America/Denver",
    "805": "America/Los_Angeles",
    "813": "America/New_York",
    "816": "America/Chicago",
    "818": "America/Los_Angeles",
    "832": "America/Chicago",
    "847": "America/Chicago",
    "858": "America/Los_Angeles",
    "901": "America/Chicago",
    "914": "America/New_York",
    "917": "America/New_York",
    "919": "America/New_York",
    "925": "America/Los_Angeles",
    "949": "America/Los_Angeles",
    "972": "America/Chicago",
    "973": "America/New_York",
}

_PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?(\d{3})\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)


def extract_area_codes(text: str) -> list[str]:
    if not text.strip():
        return []
    return [m.group(1) for m in _PHONE_RE.finditer(text)]


def timezone_from_area_codes(text: str) -> ZoneInfo | None:
    """Return timezone when all found area codes agree; else first mapped code."""
    codes = extract_area_codes(text)
    if not codes:
        return None
    zones: list[str] = []
    for code in codes:
        tz_name = _AREA_CODE_TZ.get(code)
        if tz_name:
            zones.append(tz_name)
    if not zones:
        return None
    if len(set(zones)) == 1:
        return ZoneInfo(zones[0])
    # Conflicting phones — use first mapped (Heidi would use judgment).
    return ZoneInfo(zones[0])

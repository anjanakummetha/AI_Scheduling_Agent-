"""Classify Outlook events, dedupe Master copies, and route calendar writes.

Reads Kory's work Calendar + Master rollup with intelligence so kid-only /
informational Master items do not block business scheduling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.config import settings

import rules as kory_rules

_COPY_SUFFIX_RE = re.compile(r"\s*\(copy\)\s*$", re.IGNORECASE)
_DO_NOT_MOVE_RE = re.compile(r"do\s*not\s*move", re.IGNORECASE)

# Kory-owned personal blocks on Master (always block).
_KORY_PERSONAL_BLOCK_PATTERNS = (
    r"\bkm\s+personal\s+training\b",
    r"\bkory\b.*\b(personal\s+)?training\b",
    r"\bkory\s+drop\s*off\b",
    r"\bkory\s+pick\s*up\b",
    r"\bdrop\s*off\b.*\bkory\b",
    r"\bpick\s*up\b.*\bkory\b",
    r"\bhrt\b",
    r"\bdr\.?\s*bruice\b",
    r"\bdo\s*not\s*move\b",
    r"\bbridget\b.*\b(do\s*not|non-negotiable)\b",
)

# Travel / out-of-office — block business scheduling across the span.
_TRAVEL_BLOCK_PATTERNS = (
    r"^stay at\b",
    r"\bflight to\b",
    r"\bflight from\b",
    r"\bin chicago\b",
    r"\bin travel\b",
    r"\bfamily safari\b",
    r"\bkory in [a-z]+\b",
    r"\bout of office\b",
    r"\booo\b",
)

# Kid / family activity on Master that does NOT mean Kory is busy.
_KID_ONLY_NON_BLOCKING_PATTERNS = (
    r"\bmaclain\b",
    r"\bgracie\b",
    r"\bbecky\b.*\bkids\b",
    r"\bsummer camp\b",
    r"\bmystery camp\b",
    r"\bisd summer\b",
    r"\bgeneva glen\b",
    r"\bmyths\s*&\s*magic\b",
    r"\bnatalia\b.*\bwedding\b",
    r"\bbridget\b.*\b(?!kory|drop|pick)",  # Bridget events without Kory logistics
)

# Work signals — block even on Master when not a duplicate copy of work cal.
_WORK_SIGNAL_PATTERNS = (
    r"\bhold\s*:",
    r"\bintro\b",
    r"\bifg\b",
    r"\bdiligence\b",
    r"\bpipeline\b",
    r"\bboard\b",
    r"\bypo\b",
    r"\bcapital demo\b",
    r"\bcapdemo\b",
    r"\bteams\b",
    r"\bzoom\b",
    r"\b@\s*kory",
    r"\bkory\s*\|",
    r"\bwith kory\b",
    r"\bjosh hood\b",
    r"\bheidi\b",
    r"\bdoug\b",
    r"\bpatrick\b",
    r"\bwob\b",
    r"\binbox review\b",
)

_BIRTHDAY_CALENDAR_NAMES = frozenset({"birthdays"})


class EventBlockingClass(str, Enum):
    WORK_BLOCKING = "work_blocking"
    PERSONAL_KORY_BLOCKING = "personal_kory_blocking"
    TRAVEL_BLOCKING = "travel_blocking"
    FAMILY_DO_NOT_MOVE = "family_do_not_move"
    DUPLICATE_COPY = "duplicate_copy"
    KID_ONLY_NON_BLOCKING = "kid_only_non_blocking"
    INFORMATIONAL = "informational"
    UNKNOWN_BLOCKING = "unknown_blocking"


@dataclass(frozen=True)
class ClassifiedEvent:
  raw: dict[str, Any]
  blocking_class: EventBlockingClass
  blocks_kory: bool
  calendar_name: str
  normalized_subject: str
  dedupe_key: str


def _normalize_subject(subject: str) -> str:
    text = _COPY_SUFFIX_RE.sub("", (subject or "").strip().lower())
    return re.sub(r"\s+", " ", text)


def _calendar_name(event: dict[str, Any]) -> str:
    return str(event.get("calendar_name") or event.get("source_calendar") or "").strip()


def _is_work_calendar(name: str) -> bool:
    norm = name.lower().replace("'", "'")
    return norm in {"calendar", "kory master calendar (all)"} and norm == "calendar"


def _is_master_calendar(name: str) -> bool:
    return "master calendar" in name.lower()


def _subject_matches(patterns: tuple[str, ...], subject: str) -> bool:
    return any(re.search(p, subject, re.IGNORECASE) for p in patterns)


def classify_event(event: dict[str, Any]) -> ClassifiedEvent:
    """Classify one Outlook event for Kory busy/free."""
    subject = str(event.get("subject") or "")
    norm_subject = _normalize_subject(subject)
    cal_name = _calendar_name(event)
    cal_lower = cal_name.lower()

    if cal_lower in _BIRTHDAY_CALENDAR_NAMES or subject.lower().startswith("birthday"):
        return ClassifiedEvent(
            raw=event,
            blocking_class=EventBlockingClass.INFORMATIONAL,
            blocks_kory=False,
            calendar_name=cal_name,
            normalized_subject=norm_subject,
            dedupe_key=_dedupe_key(event, norm_subject),
        )

    if _DO_NOT_MOVE_RE.search(subject):
        return ClassifiedEvent(
            raw=event,
            blocking_class=EventBlockingClass.FAMILY_DO_NOT_MOVE,
            blocks_kory=True,
            calendar_name=cal_name,
            normalized_subject=norm_subject,
            dedupe_key=_dedupe_key(event, norm_subject),
        )

    if _subject_matches(_TRAVEL_BLOCK_PATTERNS, norm_subject):
        return ClassifiedEvent(
            raw=event,
            blocking_class=EventBlockingClass.TRAVEL_BLOCKING,
            blocks_kory=True,
            calendar_name=cal_name,
            normalized_subject=norm_subject,
            dedupe_key=_dedupe_key(event, norm_subject),
        )

    if _subject_matches(_KORY_PERSONAL_BLOCK_PATTERNS, norm_subject):
        return ClassifiedEvent(
            raw=event,
            blocking_class=EventBlockingClass.PERSONAL_KORY_BLOCKING,
            blocks_kory=True,
            calendar_name=cal_name,
            normalized_subject=norm_subject,
            dedupe_key=_dedupe_key(event, norm_subject),
        )

    if _COPY_SUFFIX_RE.search(subject) and _is_master_calendar(cal_name):
        if _subject_matches(_WORK_SIGNAL_PATTERNS, norm_subject):
            return ClassifiedEvent(
                raw=event,
                blocking_class=EventBlockingClass.DUPLICATE_COPY,
                blocks_kory=False,
                calendar_name=cal_name,
                normalized_subject=norm_subject,
                dedupe_key=_dedupe_key(event, norm_subject),
            )
        if _subject_matches(_KID_ONLY_NON_BLOCKING_PATTERNS, norm_subject):
            return ClassifiedEvent(
                raw=event,
                blocking_class=EventBlockingClass.KID_ONLY_NON_BLOCKING,
                blocks_kory=False,
                calendar_name=cal_name,
                normalized_subject=norm_subject,
                dedupe_key=_dedupe_key(event, norm_subject),
            )

    if _is_master_calendar(cal_name) and _subject_matches(
        _KID_ONLY_NON_BLOCKING_PATTERNS, norm_subject
    ):
        if not _subject_matches(_WORK_SIGNAL_PATTERNS, norm_subject) and "kory" not in norm_subject:
            return ClassifiedEvent(
                raw=event,
                blocking_class=EventBlockingClass.KID_ONLY_NON_BLOCKING,
                blocks_kory=False,
                calendar_name=cal_name,
                normalized_subject=norm_subject,
                dedupe_key=_dedupe_key(event, norm_subject),
            )

    if _is_work_calendar(cal_name) or _subject_matches(_WORK_SIGNAL_PATTERNS, norm_subject):
        return ClassifiedEvent(
            raw=event,
            blocking_class=EventBlockingClass.WORK_BLOCKING,
            blocks_kory=True,
            calendar_name=cal_name,
            normalized_subject=norm_subject,
            dedupe_key=_dedupe_key(event, norm_subject),
        )

    if _is_master_calendar(cal_name):
        return ClassifiedEvent(
            raw=event,
            blocking_class=EventBlockingClass.UNKNOWN_BLOCKING,
            blocks_kory=True,
            calendar_name=cal_name,
            normalized_subject=norm_subject,
            dedupe_key=_dedupe_key(event, norm_subject),
        )

    return ClassifiedEvent(
        raw=event,
        blocking_class=EventBlockingClass.UNKNOWN_BLOCKING,
        blocks_kory=True,
        calendar_name=cal_name,
        normalized_subject=norm_subject,
        dedupe_key=_dedupe_key(event, norm_subject),
    )


def _dedupe_key(event: dict[str, Any], norm_subject: str) -> str:
    start = _event_start_iso(event)
    end = _event_end_iso(event)
    return f"{start}|{end}|{norm_subject}"


def _event_start_iso(event: dict[str, Any]) -> str:
    start = event.get("start")
    if isinstance(start, dict):
        return str(start.get("dateTime") or start.get("date") or "")
    return str(start or "")


def _event_end_iso(event: dict[str, Any]) -> str:
    end = event.get("end")
    if isinstance(end, dict):
        return str(end.get("dateTime") or end.get("date") or "")
    return str(end or "")


def dedupe_and_filter_blocking_events(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[ClassifiedEvent]]:
    """Dedupe cross-calendar copies; return Kory-blocking events with metadata."""
    classified = [classify_event(e) for e in events]
    seen_work_keys: set[str] = set()
    blocking: list[dict[str, Any]] = []
    audit: list[ClassifiedEvent] = []

    # Prefer work Calendar entries over Master (copy) for the same slot.
    work_first = sorted(
        classified,
        key=lambda c: (0 if _is_work_calendar(c.calendar_name) else 1, c.dedupe_key),
    )

    for item in work_first:
        if not item.blocks_kory:
            audit.append(item)
            continue
        if item.dedupe_key in seen_work_keys:
            audit.append(
                ClassifiedEvent(
                    raw=item.raw,
                    blocking_class=EventBlockingClass.DUPLICATE_COPY,
                    blocks_kory=False,
                    calendar_name=item.calendar_name,
                    normalized_subject=item.normalized_subject,
                    dedupe_key=item.dedupe_key,
                )
            )
            continue
        seen_work_keys.add(item.dedupe_key)
        enriched = dict(item.raw)
        enriched["blocking_class"] = item.blocking_class.value
        enriched["blocks_kory"] = True
        blocking.append(enriched)
        audit.append(item)

    return blocking, audit


def resolve_calendar_horizon_days(
    *,
    subject: str = "",
    body: str = "",
    explicit_days: int | None = None,
) -> int:
    """How many days ahead to load — default from settings, extend for far-future asks."""
    base = explicit_days or settings.lexi_calendar_search_days
    base = max(7, min(base, settings.lexi_calendar_search_days_max))
    combined = f"{subject}\n{body}".lower()

  # Month names / relative far-future cues
    month_hints = (
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "next month", "following month", "in a month", "few weeks",
        "couple of weeks", "later this summer", "this fall", "this winter",
    )
    if any(h in combined for h in month_hints):
        return settings.lexi_calendar_search_days_max

    if re.search(r"\b(in|during)\s+\d+\s+weeks?\b", combined):
        return settings.lexi_calendar_search_days_max

    return base


def resolve_write_calendar_name(
    *,
    intent: str | None = None,
    explicit: str | None = None,
) -> str:
    """Route holds/invites: work → Calendar, personal → Master."""
    from app.integrations.named_calendars import resolve_write_calendar_for_intent

    if explicit and explicit.strip():
        return explicit.strip()
    return resolve_write_calendar_for_intent(intent)


def summarize_blocking_events(events: list[dict[str, Any]], *, limit: int = 80) -> dict[str, Any]:
    """Summary for Hermes / debugging."""
    counts: dict[str, int] = {}
    for event in events:
        key = str(event.get("blocking_class") or "unclassified")
        counts[key] = counts.get(key, 0) + 1
    return {
        "blocking_count": len(events),
        "by_class": counts,
        "events": events[:limit],
    }


def infer_meeting_duration_minutes(intent: str | None) -> int:
    """Default duration from rules.py meeting types."""
    intent_key = (intent or "unknown").lower().replace(" ", "_")
    mapping = {
        "coffee": 60,
        "lunch_request": 60,
        "lunch": 60,
        "dinner_request": 90,
        "dinner": 90,
        "happy_hour": 90,
        "pitch": 60,
        "new_client": 60,
        "board_meeting": 60,
        "internal_sync": 30,
        "delegation": 30,
        "reschedule": 30,
    }
    if intent_key in mapping:
        return mapping[intent_key]
    if intent_key in kory_rules.MEETING_TYPES:
        mt = kory_rules.MEETING_TYPES[intent_key]
        return int(mt.get("duration_minutes") or mt.get("calendar_block_minutes") or 30)
    return 30


def calendar_block_minutes_for_intent(intent: str | None) -> int:
    """Calendar block size including buffers (e.g. coffee = 90)."""
    intent_key = (intent or "unknown").lower().replace(" ", "_")
    if intent_key == "coffee":
        return int(kory_rules.MEETING_TYPES["coffee"].get("calendar_block_minutes") or 90)
    return infer_meeting_duration_minutes(intent)

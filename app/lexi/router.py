"""
Lexi router — classifies intent and dispatches to the right subagent(s).

Intent classes:
  calendar      → add/block/check calendar events (direct, no holds)
  email         → find/read/draft/send emails
  scheduling    → find slots + place holds + draft options to external party
  task          → create Asana reservation or follow-up task
  confirm_hold  → confirm one of the offered holds, remove others
  general       → anything that doesn't fit a specialist bucket
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CALENDAR_PATTERNS = re.compile(
    r"\b(add|schedule|create|put|block|book|cancel|delete|remove|move|reschedule|what.s on|check my calendar|"
    r"calendar today|calendar this|am i free|do i have|clear|open slot|free|busy)\b",
    re.IGNORECASE,
)

_EMAIL_PATTERNS = re.compile(
    r"\b(draft|email|reply|write|send|compose|message|inbox|read|find the email|check email|"
    r"from .+about|re:|subject)\b",
    re.IGNORECASE,
)

_SCHEDULING_PATTERNS = re.compile(
    r"\b(suggest times|find times|send.*times|times to offer|options for|hold.*option|"
    r"i emailed.+about a meeting|find.*slot|available times|2.?3 options)\b",
    re.IGNORECASE,
)

_CONFIRM_PATTERNS = re.compile(
    r"\b(confirm option|go with option|option [123]|confirm that time|use that slot|"
    r"book option|that works|go with that|confirm.*hold)\b",
    re.IGNORECASE,
)

_TASK_PATTERNS = re.compile(
    r"\b(asana|task|reservation|reserve|book.*table|follow.?up task|remind me|add task)\b",
    re.IGNORECASE,
)

_RESERVATION_TYPES = re.compile(
    r"\b(coffee|happy hour|dinner|lunch)\b",
    re.IGNORECASE,
)


@dataclass
class RoutingDecision:
    primary: str                 # main agent to run
    secondary: list[str]         # additional agents to run after (in order)
    needs_task: bool = False     # whether to also create an Asana task


def classify(message: str) -> RoutingDecision:
    """
    Classify a user message into a routing decision.
    Uses fast regex matching — no LLM call needed for routing.
    """
    msg = message.lower()

    # Confirm hold takes precedence
    if _CONFIRM_PATTERNS.search(message):
        return RoutingDecision(primary="confirm_hold", secondary=[], needs_task=False)

    # Explicit scheduling request (find+send options to external party)
    if _SCHEDULING_PATTERNS.search(message):
        needs_task = bool(_RESERVATION_TYPES.search(message))
        return RoutingDecision(primary="scheduling", secondary=[], needs_task=needs_task)

    has_calendar = bool(_CALENDAR_PATTERNS.search(message))
    has_email = bool(_EMAIL_PATTERNS.search(message))
    has_task = bool(_TASK_PATTERNS.search(message))

    # Both calendar and email requested
    if has_calendar and has_email:
        needs_task = bool(_RESERVATION_TYPES.search(message))
        return RoutingDecision(primary="calendar", secondary=["email"], needs_task=needs_task)

    # Email only
    if has_email and not has_calendar:
        return RoutingDecision(primary="email", secondary=[], needs_task=False)

    # Calendar only
    if has_calendar:
        needs_task = bool(_RESERVATION_TYPES.search(message))
        return RoutingDecision(primary="calendar", secondary=[], needs_task=needs_task)

    # Task only
    if has_task:
        return RoutingDecision(primary="task", secondary=[], needs_task=False)

    # Fallback: general
    return RoutingDecision(primary="general", secondary=[], needs_task=False)

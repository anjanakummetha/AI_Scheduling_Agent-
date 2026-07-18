"""Filter inbound email notifications — important mail only, no newsletter noise."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

NEWSLETTER_SENDER_PATTERNS = (
    r"noreply@",
    r"no-reply@",
    r"donotreply@",
    r"notifications?@",
    r"mailer-daemon@",
    r"newsletter@",
    r"digest@",
    r"marketplace@",
)

NEWSLETTER_SUBJECT_PATTERNS = (
    r"daily digest",
    r"weekly digest",
    r"newsletter",
    r"marketplace",
    r"unsubscribe",
    r"no longer wish to receive",
    r"view in browser",
    r"linkedin.*digest",
    r"undeliverable",
    r"delivery status notification",
)

CALENDAR_RESPONSE_SUBJECT_PATTERNS = (
    r"^accepted:",
    r"^declined:",
    r"^tentative:",
    r"^canceled:",
    r"^cancelled:",
    r"invitation from google calendar",
    r"updated invitation:",
)

CALENDAR_RESPONSE_BODY_PATTERNS = (
    r"has accepted this invitation",
    r"has declined this invitation",
    r"has tentatively accepted",
    r"this event has been (?:cancelled|canceled)",
    r"invitation from google calendar",
)

SCHEDULING_INTENTS = frozenset(
    {
        "board_meeting",
        "dinner_request",
        "lunch_request",
        "pitch",
        "internal_sync",
        "coffee",
        "happy_hour",
        "reschedule",
        "cancellation",
        "delegation",
    }
)


@dataclass(frozen=True)
class InboundNotificationDecision:
    notify: bool
    reason: str
    auto_skip: bool = False


def notify_important_only_enabled() -> bool:
    return os.getenv("LEXI_NOTIFY_IMPORTANT_ONLY", "true").lower() in {"1", "true", "yes"}


def is_newsletter_or_bulk_mail(*, sender: str, subject: str, body: str) -> bool:
    sender_l = (sender or "").lower()
    combined = f"{subject}\n{body}".lower()
    if any(re.search(p, sender_l) for p in NEWSLETTER_SENDER_PATTERNS):
        return True
    if any(re.search(p, combined) for p in NEWSLETTER_SUBJECT_PATTERNS):
        return True
    return False


def is_calendar_invite_response(*, sender: str, subject: str, body: str) -> bool:
    """Calendar accept/decline/update — no draft needed."""
    subject_l = (subject or "").strip().lower()
    body_l = (body or "").lower()
    sender_l = (sender or "").lower()

    if any(re.search(p, subject_l) for p in CALENDAR_RESPONSE_SUBJECT_PATTERNS):
        return True
    if any(re.search(p, body_l) for p in CALENDAR_RESPONSE_BODY_PATTERNS):
        return True
    if "calendar-notification@google.com" in sender_l:
        return True
    if subject_l.startswith("accepted:") or subject_l.startswith("declined:"):
        return True
    return False


def is_no_reply_needed_mail(*, sender: str, subject: str, body: str) -> bool:
    """Mail that should never ping Kory for a draft."""
    if is_newsletter_or_bulk_mail(sender=sender, subject=subject, body=body):
        return True
    if is_calendar_invite_response(sender=sender, subject=subject, body=body):
        return True
    return False


def normalize_subject_key(subject: str) -> str:
    text = (subject or "").strip().lower()
    text = re.sub(r"^(re|fw|fwd):\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text


def evaluate_inbound_notification(
    *,
    intent: str,
    priority: str,
    sender: str,
    subject: str,
    body: str,
    is_delegation: bool = False,
) -> InboundNotificationDecision:
    """Decide whether Kory should get a Teams prompt for this inbound email."""
    from app.config import settings

    if is_delegation:
        return InboundNotificationDecision(
            notify=True,
            reason="delegation_to_lexi",
            auto_skip=False,
        )

    intent_l = (intent or "unknown").strip().lower()
    priority_l = (priority or "medium").strip().lower()

    if settings.lexi_teams_inbound_notify_mode == "delegation_only":
        return InboundNotificationDecision(
            notify=False,
            reason="delegation_only_mode",
            auto_skip=True,
        )

    if settings.lexi_teams_inbound_notify_mode == "delegation_and_followups":
        return InboundNotificationDecision(
            notify=False,
            reason="delegation_and_followups_cold_inbound",
            auto_skip=True,
        )

    if is_no_reply_needed_mail(sender=sender, subject=subject, body=body):
        reason = "calendar_invite_response"
        if is_newsletter_or_bulk_mail(sender=sender, subject=subject, body=body):
            reason = "newsletter_or_digest"
        return InboundNotificationDecision(
            notify=False,
            reason=reason,
            auto_skip=True,
        )

    if intent_l == "non_scheduling" and priority_l == "low":
        return InboundNotificationDecision(
            notify=False,
            reason="non_scheduling_low_priority",
            auto_skip=True,
        )

    if not notify_important_only_enabled():
        return InboundNotificationDecision(notify=True, reason="all_mail_mode")

    if intent_l in SCHEDULING_INTENTS and intent_l not in {"reschedule", "cancellation"}:
        return InboundNotificationDecision(notify=True, reason=f"scheduling_intent:{intent_l}")

    if intent_l in {"reschedule", "cancellation"}:
        if _looks_like_real_reschedule_request(subject=subject, body=body):
            return InboundNotificationDecision(
                notify=True,
                reason=f"scheduling_intent:{intent_l}",
            )
        return InboundNotificationDecision(
            notify=False,
            reason="calendar_status_only",
            auto_skip=True,
        )

    if priority_l == "high" and _needs_ceo_attention(subject=subject, body=body):
        return InboundNotificationDecision(notify=True, reason="high_priority_actionable")

    if priority_l == "medium" and intent_l not in {"unknown", "non_scheduling"}:
        return InboundNotificationDecision(notify=True, reason="medium_actionable")

    return InboundNotificationDecision(
        notify=False,
        reason="not_important_enough",
        auto_skip=True,
    )


def _looks_like_real_reschedule_request(*, subject: str, body: str) -> bool:
    """True when someone is asking to move a meeting — not an auto calendar receipt."""
    combined = f"{subject}\n{body}".lower()
    cues = (
        "can we reschedule",
        "move our meeting",
        "different time",
        "doesn't work",
        "won't work",
        "unable to make",
        "push to",
        "another day",
        "reschedule",
    )
    return any(cue in combined for cue in cues)


def _needs_ceo_attention(*, subject: str, body: str) -> bool:
    """High priority alone is not enough — skip FYI / status-only threads."""
    combined = f"{subject}\n{body}".lower()
    fyi_only = (
        "no action required",
        "for your information",
        "fyi only",
        "automated notification",
        "this is a courtesy copy",
    )
    if any(phrase in combined for phrase in fyi_only):
        return False
    action_cues = (
        "?",
        "please",
        "can you",
        "could you",
        "need to",
        "let me know",
        "schedule",
        "meet",
        "call",
        "dinner",
        "lunch",
        "coffee",
        "term sheet",
        "diligence",
        "board",
        "approve",
        "confirm",
        "urgent",
    )
    return any(cue in combined for cue in action_cues)


def triage_adjustments_for_sender_subject(
    *,
    sender: str,
    subject: str,
    body: str,
    intent: str,
    priority: str,
) -> tuple[str, str]:
    """Downgrade noise before persisting proposal metadata."""
    if is_no_reply_needed_mail(sender=sender, subject=subject, body=body):
        return "non_scheduling", "low"
    return intent, priority

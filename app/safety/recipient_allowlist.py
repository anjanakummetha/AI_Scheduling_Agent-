"""Recipient allowlist — a structural guard independent of the kill-switch flags.

Plan Phase 1: outside a production run (LEXI_ENV != "production"), any real
Outlook send / draft / calendar-invite whose recipients or attendees are not on
the allowlist is refused at the single choke point (composio_client.execute_tool),
regardless of dry-run / write-mode. This means three independent mechanisms must
all fail at once for a test or script to email a real, non-sandbox person.

The allowlist is:  LEXI_ALLOWED_RECIPIENTS (comma list)  ∪  the sandbox mailbox.
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.config import resolve_lexi_env, settings

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Argument keys whose values carry recipients/attendees (across the tool shapes in use).
_RECIPIENT_KEYS = {
    "torecipients",
    "ccrecipients",
    "bccrecipients",
    "to_recipients",
    "cc_recipients",
    "bcc_recipients",
    "to",
    "cc",
    "bcc",
    "to_email",
    "recipient",
    "recipients",
    "attendees",
    "required_attendees",
    "optional_attendees",
}


def _is_outbound_recipient_tool(tool_slug: str) -> bool:
    slug = tool_slug.upper()
    if not (slug.startswith("OUTLOOK_") or slug.startswith("MICROSOFT_OUTLOOK_")):
        return False
    return any(
        tok in slug
        for tok in ("SEND", "CREATE_DRAFT", "REPLY", "FORWARD", "CREATE_ME_EVENT",
                    "CREATE_CALENDAR_EVENT", "CREATE_EVENT")
    )


def _emails_from_value(value: Any) -> set[str]:
    found: set[str] = set()
    if value is None:
        return found
    if isinstance(value, str):
        found.update(m.group(0).lower() for m in _EMAIL_RE.finditer(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _emails_from_value(v)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            found |= _emails_from_value(item)
    return found


def extract_recipients(arguments: dict[str, Any]) -> set[str]:
    """All recipient/attendee emails found under recipient-type keys in the arguments."""
    recipients: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                if str(key).lower() in _RECIPIENT_KEYS:
                    recipients.update(_emails_from_value(val))
                else:
                    walk(val)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                walk(item)

    walk(arguments)
    return recipients


def allowed_recipients() -> set[str]:
    allowed = {
        e.strip().lower()
        for e in os.getenv("LEXI_ALLOWED_RECIPIENTS", "").split(",")
        if e.strip()
    }
    if settings.sandbox_mailbox_email:
        allowed.add(settings.sandbox_mailbox_email.strip().lower())
    return allowed


def assert_recipients_allowed(tool_slug: str, arguments: dict[str, Any]) -> None:
    """Raise if a non-production outbound tool targets any recipient off the allowlist."""
    if resolve_lexi_env() == "production":
        return
    if not _is_outbound_recipient_tool(tool_slug):
        return
    recipients = extract_recipients(arguments)
    if not recipients:
        return
    allowed = allowed_recipients()
    disallowed = sorted(r for r in recipients if r not in allowed)
    if disallowed:
        raise PermissionError(
            f"Recipient allowlist (LEXI_ENV={resolve_lexi_env()}): {tool_slug} would reach "
            f"{disallowed}, which are not on LEXI_ALLOWED_RECIPIENTS "
            f"(allowed: {sorted(allowed) or 'none configured'}). "
            "Add them to LEXI_ALLOWED_RECIPIENTS, use the sandbox mailbox, or run in production."
        )

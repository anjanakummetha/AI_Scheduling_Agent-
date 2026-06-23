"""Hard blocks on any modification to Kory's Outlook/calendar space."""

from __future__ import annotations

from app.config import settings


_WRITE_PREFIXES = (
    "OUTLOOK_CREATE",
    "OUTLOOK_SEND",
    "OUTLOOK_DELETE",
    "OUTLOOK_UPDATE",
    "OUTLOOK_CANCEL",
    "OUTLOOK_ACCEPT",
    "OUTLOOK_DECLINE",
    "OUTLOOK_MOVE",
    "OUTLOOK_COPY",
    "OUTLOOK_FORWARD",
    "OUTLOOK_REPLY",
    "OUTLOOK_PERMANENT",
    "OUTLOOK_BATCH",
    "OUTLOOK_PIN",
    "OUTLOOK_SNOOZE",
    "OUTLOOK_DISMISS",
    "MICROSOFT_OUTLOOK_SEND",
    "MICROSOFT_OUTLOOK_CREATE",
    "MICROSOFT_OUTLOOK_DELETE",
    "MICROSOFT_OUTLOOK_UPDATE",
)


def is_outlook_write_slug(tool_slug: str) -> bool:
    slug = (tool_slug or "").upper()
    return any(slug.startswith(prefix) for prefix in _WRITE_PREFIXES)


def kory_space_read_only_enabled() -> bool:
    return settings.lexi_kory_space_read_only


def assert_kory_space_write_allowed(*, tool_slug: str, connection_id: str | None) -> None:
    """Raise if this Composio call would modify Kory's mailbox/calendar."""
    if not kory_space_read_only_enabled():
        return
    if not is_outlook_write_slug(tool_slug):
        return
    kory_id = (settings.kory_composio_connection_id or "").strip()
    if not kory_id or not connection_id:
        return
    if connection_id.strip() == kory_id:
        raise PermissionError(
            "Kory space is READ-ONLY (LEXI_KORY_SPACE_READ_ONLY=true). "
            f"Blocked write: {tool_slug}. Re-enable only after explicit UAT approval."
        )


def read_only_safety_snapshot() -> dict[str, bool]:
    return {
        "lexi_dry_run": settings.lexi_dry_run,
        "lexi_kory_outbound_blocked": settings.lexi_kory_outbound_blocked,
        "lexi_kory_space_read_only": settings.lexi_kory_space_read_only,
        "lexi_delegation_auto_draft": settings.lexi_delegation_auto_draft,
    }

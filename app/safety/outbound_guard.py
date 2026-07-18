"""Gate outbound Teams, email, and calendar writes during UAT / dry-run."""

from __future__ import annotations

import os

from app.config import settings


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes"}


def outbound_writes_allowed() -> bool:
    """False when LEXI_DRY_RUN — no Composio mail/calendar writes."""
    return not settings.lexi_dry_run


def teams_push_allowed() -> bool:
    """False during dry-run or when Teams push is explicitly suppressed."""
    if settings.lexi_dry_run:
        return False
    if not settings.lexi_teams_enabled:
        return False
    if _truthy("LEXI_SUPPRESS_TEAMS_PUSH"):
        return False
    if getattr(settings, "lexi_suppress_teams_push", False):
        return False
    return True


def heidi_email_allowed() -> bool:
    """Heidi escalations respect dry-run (stage only)."""
    return outbound_writes_allowed()


def staging_mode_label() -> str:
    if settings.lexi_dry_run:
        return "dry_run"
    if not teams_push_allowed():
        return "teams_suppressed"
    return "live"

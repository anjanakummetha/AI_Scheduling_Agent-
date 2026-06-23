"""Teams bot security helpers (allowed-user firewall)."""

from __future__ import annotations

import os
from functools import lru_cache

from botbuilder.core import TurnContext


def _resolve_sender_identity(turn_context: TurnContext) -> str:
    sender = turn_context.activity.from_property
    if sender is None:
        return ""

    aad_id = getattr(sender, "aad_object_id", None) or getattr(sender, "aadObjectId", None)
    if aad_id:
        return str(aad_id).strip().lower()

    user_id = getattr(sender, "id", None)
    if user_id:
        return str(user_id).strip().lower()

    name = getattr(sender, "name", None)
    if name:
        return str(name).strip().lower()

    return ""


@lru_cache
def load_teams_allowed_users() -> frozenset[str]:
    """Parse TEAMS_ALLOWED_USERS (comma-separated AAD object IDs or user ids)."""
    raw = os.getenv("TEAMS_ALLOWED_USERS", "")
    allowed = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return frozenset(allowed)


def is_teams_sender_allowed(turn_context: TurnContext) -> bool:
    """Return True when the activity sender is on the TEAMS_ALLOWED_USERS allowlist."""
    allowed = load_teams_allowed_users()
    if not allowed:
        return False

    sender_identity = _resolve_sender_identity(turn_context)
    if not sender_identity:
        return False

    return sender_identity in allowed

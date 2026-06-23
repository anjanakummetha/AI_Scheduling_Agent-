"""Resolve the actual Microsoft mailbox tied to the Composio write connection."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.integrations.composio_client import execute_write_tool


@lru_cache(maxsize=1)
def get_write_mailbox_profile() -> dict[str, str]:
    """Return display_name, mail, user_principal_name for the sandbox write connection."""
    try:
        result = execute_write_tool("OUTLOOK_GET_PROFILE", {"user_id": "me"})
        data = result.get("data") or {}
        if hasattr(data, "model_dump"):
            data = data.model_dump()
        if not isinstance(data, dict):
            return {}
        return {
            "display_name": str(data.get("displayName") or ""),
            "mail": str(data.get("mail") or "").strip().lower(),
            "user_principal_name": str(data.get("userPrincipalName") or "").strip().lower(),
        }
    except Exception:
        return {}


def get_write_mailbox_email() -> str | None:
    """Primary SMTP address for the connected write mailbox."""
    profile = get_write_mailbox_profile()
    return profile.get("mail") or profile.get("user_principal_name") or None

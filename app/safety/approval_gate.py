"""Phase 1 safety: no sends or bookings without Kory approval."""

from __future__ import annotations

import os

import rules as kory_rules


def kory_approves_all() -> bool:
    """True when rules.py requires human approval for every action."""
    return bool(kory_rules.APPROVAL_RULES.get("kory_approves_all", True))


def require_kory_approval_env() -> bool:
    return os.getenv("LEXI_REQUIRE_KORY_APPROVAL", "true").lower() in {"1", "true", "yes"}


def auto_execute_allowed() -> bool:
    if kory_approves_all() and require_kory_approval_env():
        return False
    return os.getenv("LEXI_AUTO_EXECUTE_ENABLED", "false").lower() in {"1", "true", "yes"}


def immediate_send_allowed() -> bool:
    """Outbound send without pending_approval — disabled in Phase 1."""
    if kory_approves_all() and require_kory_approval_env():
        return os.getenv("LEXI_ALLOW_IMMEDIATE_SEND", "false").lower() in {"1", "true", "yes"}
    return True


def kory_outbound_email_blocked() -> bool:
    from app.config import settings

    return settings.lexi_kory_outbound_blocked


def assert_outbound_send_authorized(
    *,
    approved_send: bool,
    send_channel: str = "kory",
) -> None:
    """Raise if a direct Composio send is attempted without an approval flow."""
    channel = (send_channel or "kory").strip().lower()
    if channel == "lexi":
        if settings_lexi_dry_run():
            return
        if approved_send:
            return
        if require_kory_approval_env() and kory_approves_all():
            raise PermissionError(
                "Outbound email blocked: Kory approval required. "
                "Approve in Teams (Send on card or execute_lexi_approval) before Lexi sends."
            )
        return

    if kory_outbound_email_blocked():
        raise PermissionError(
            "Kory outbound email is DISABLED (LEXI_KORY_OUTBOUND_BLOCKED=true). "
            "Re-enable only when Kory explicitly approves live sends."
        )
    if settings_lexi_dry_run():
        return
    if approved_send:
        return
    if require_kory_approval_env() and kory_approves_all():
        raise PermissionError(
            "Outbound email blocked: Kory approval required. "
            "Use approve_decision / execute_lexi_approval_tool after Kory says send, "
            "or lexi_send_outbound_email with confirm_send=true."
        )


def settings_lexi_dry_run() -> bool:
    from app.config import settings

    return settings.lexi_dry_run


def assert_kory_approved_write(*, approved: bool, action: str) -> None:
    """Raise unless Kory explicitly approved this write in Teams (or dry-run)."""
    if settings_lexi_dry_run():
        return
    if approved:
        return
    if require_kory_approval_env() and kory_approves_all():
        raise PermissionError(
            f"{action} blocked: Kory approval required in Teams before Lexi makes changes."
        )

"""Lexi-channel send authorization (Kory outbound stays blocked)."""

from unittest.mock import patch

from app.safety.approval_gate import assert_outbound_send_authorized


def test_lexi_channel_requires_approval_when_not_dry_run() -> None:
    with (
        patch("app.safety.approval_gate.settings_lexi_dry_run", return_value=False),
        patch("app.safety.approval_gate.kory_outbound_email_blocked", return_value=True),
        patch("app.safety.approval_gate.require_kory_approval_env", return_value=True),
        patch("app.safety.approval_gate.kory_approves_all", return_value=True),
    ):
        try:
            assert_outbound_send_authorized(approved_send=False, send_channel="lexi")
            raise AssertionError("expected PermissionError")
        except PermissionError as exc:
            assert "Kory approval required" in str(exc)


def test_lexi_channel_allows_approved_even_when_kory_blocked() -> None:
    with (
        patch("app.safety.approval_gate.settings_lexi_dry_run", return_value=False),
        patch("app.safety.approval_gate.kory_outbound_email_blocked", return_value=True),
    ):
        assert_outbound_send_authorized(approved_send=True, send_channel="lexi")


def test_kory_channel_still_blocked_when_kory_outbound_disabled() -> None:
    with (
        patch("app.safety.approval_gate.settings_lexi_dry_run", return_value=False),
        patch("app.safety.approval_gate.kory_outbound_email_blocked", return_value=True),
    ):
        try:
            assert_outbound_send_authorized(approved_send=True, send_channel="kory")
            raise AssertionError("expected PermissionError")
        except PermissionError as exc:
            assert "Kory outbound email is DISABLED" in str(exc)


def test_kory_channel_allows_approved_when_outbound_enabled() -> None:
    with (
        patch("app.safety.approval_gate.settings_lexi_dry_run", return_value=False),
        patch("app.safety.approval_gate.kory_outbound_email_blocked", return_value=False),
    ):
        assert_outbound_send_authorized(approved_send=True, send_channel="kory")

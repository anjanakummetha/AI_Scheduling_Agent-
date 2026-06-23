"""Tests for Kory read-only safety gates."""

from app.integrations.outlook_actions import execute_outlook_action
from app.safety.kory_read_only import (
    assert_kory_space_write_allowed,
    is_outlook_write_slug,
    kory_space_read_only_enabled,
)


def test_write_slug_detection():
    assert is_outlook_write_slug("OUTLOOK_SEND_EMAIL")
    assert is_outlook_write_slug("OUTLOOK_ACCEPT_EVENT")
    assert not is_outlook_write_slug("OUTLOOK_LIST_MESSAGES")
    assert not is_outlook_write_slug("OUTLOOK_FIND_MEETING_TIMES")


def test_kory_space_write_blocked_when_read_only(monkeypatch=None):
    """When read-only is on and connection is Kory, writes raise."""
    if not kory_space_read_only_enabled():
        return
    kory_id = __import__("app.config", fromlist=["settings"]).settings.kory_composio_connection_id
    if not kory_id:
        kory_id = "ca_kory_test"
    try:
        assert_kory_space_write_allowed(
            tool_slug="OUTLOOK_UPDATE_CALENDAR_EVENT",
            connection_id=kory_id,
        )
        raise AssertionError("Expected PermissionError for Kory write")
    except PermissionError as exc:
        assert "READ-ONLY" in str(exc)


def test_execute_outlook_write_requires_confirm():
    try:
        execute_outlook_action(
            "OUTLOOK_SEND_EMAIL",
            {"to": "a@b.com"},
            confirm=False,
        )
        raise AssertionError("Expected PermissionError for missing confirm")
    except PermissionError as exc:
        assert "confirm=true" in str(exc)


def test_execute_outlook_deny_permanent_delete():
    try:
        execute_outlook_action(
            "OUTLOOK_DELETE_EVENT_PERMANENTLY",
            {"event_id": "x"},
            confirm=True,
            allow_unlisted=True,
        )
        raise AssertionError("Expected PermissionError for permanent delete")
    except PermissionError as exc:
        assert "Permanently blocked" in str(exc)

"""Brief Kory-facing status line."""

from app.assistant.actions import format_kory_status_brief


def test_status_brief_uses_mt_not_outlook_et() -> None:
    text = format_kory_status_brief(
        {
            "lexi_dry_run": False,
            "worker_running": True,
            "pending_approval_count": 2,
            "teams_cards_ready": True,
            "scheduling_timezone": "America/Denver",
            "outlook_timezone": "America/New_York",
        }
    )
    assert "Mountain Time" in text
    assert "Eastern" not in text
    assert "2 drafts" in text
    assert "travel" in text.lower()
    assert "Composio" not in text


def test_status_brief_no_pending() -> None:
    text = format_kory_status_brief(
        {
            "lexi_dry_run": True,
            "worker_running": False,
            "pending_approval_count": 0,
            "teams_cards_ready": True,
        }
    )
    assert "test mode" in text
    assert "No drafts waiting" in text

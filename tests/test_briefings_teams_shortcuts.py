"""Teams shortcuts and briefing builders."""

from __future__ import annotations

from unittest.mock import patch

from app.bot.teams_text import parse_teams_command
from app.scheduling.introducer import extract_introducer_from_email, format_introducer_line
from app.teams.commands import handle_teams_command


def test_parse_teams_shortcuts():
    assert parse_teams_command("unanswered") == {"action": "unanswered"}
    assert parse_teams_command("today") == {"action": "today"}
    assert parse_teams_command("prebrief") == {"action": "prebrief"}
    assert parse_teams_command("brief") == {"action": "daily_briefing"}


@patch("app.assistant.briefings.build_unanswered_brief")
def test_handle_unanswered_command(mock_brief):
    mock_brief.return_value = {"kory_message": "Unanswered list"}
    out = handle_teams_command("unanswered")
    assert out["handled"] is True
    assert "Unanswered" in out["message"]


@patch("app.assistant.briefings.build_today_calendar_brief")
def test_handle_today_command(mock_cal):
    mock_cal.return_value = {"kory_message": "Calendar today"}
    out = handle_teams_command("today")
    assert out["ok"] is True
    assert "Calendar" in out["message"]


def test_introducer_from_intro_email():
    info = extract_introducer_from_email(
        subject="Intro — Jane and Kory",
        body="Wanted to introduce you to Jane for a quick chat.",
        sender="connector@vc.com",
        to_recipients=["kory@iconicfounders.com", "jane@startup.io"],
        cc_recipients=["lexi@iconicfounders.com"],
    )
    assert info is not None
    assert "connector" in (info.email or "")
    line = format_introducer_line(info)
    assert "Introduced by" in line


@patch("app.integrations.asana_manager.list_asana_tasks")
def test_daily_briefing_includes_asana(mock_tasks):
    mock_tasks.return_value = {"tasks": [], "ok": True}
    from app.assistant.briefings import build_daily_ceo_briefing

    with patch("app.assistant.briefings.build_today_calendar_brief") as mock_today, patch(
        "app.assistant.briefings.build_unanswered_brief"
    ) as mock_unanswered:
        mock_today.return_value = {"kory_message": "Today cal"}
        mock_unanswered.return_value = {"kory_message": "Unanswered"}
        brief = build_daily_ceo_briefing()
    assert "CEO briefing" in brief["kory_message"]
    assert "Today cal" in brief["kory_message"]

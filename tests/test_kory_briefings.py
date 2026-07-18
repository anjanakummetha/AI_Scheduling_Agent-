"""24h reminders and daily briefing scheduling."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.jobs.kory_briefings import process_daily_ceo_briefing_if_due


@patch("app.jobs.kory_briefings._notify_daily_briefing")
@patch("app.jobs.kory_briefings._daily_briefing_already_sent", return_value=False)
@patch("app.assistant.briefings.build_daily_ceo_briefing")
def test_daily_briefing_fires_in_window(mock_build, _sent, mock_notify):
    mock_build.return_value = {"kory_message": "Morning package"}
    mt = ZoneInfo("America/Denver")
    now = datetime(2026, 7, 16, 4, 50, tzinfo=mt)
    result = process_daily_ceo_briefing_if_due(now=now)
    assert result["sent"] is True
    mock_notify.assert_called_once()


def test_daily_briefing_outside_window():
    mt = ZoneInfo("America/Denver")
    now = datetime(2026, 7, 16, 12, 0, tzinfo=mt)
    result = process_daily_ceo_briefing_if_due(now=now)
    assert result["sent"] is False

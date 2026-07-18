"""Microsoft Teams Bot Framework integration for Lexi."""

from __future__ import annotations

from typing import Any

__all__ = [
    "LexiTeamsBot",
    "push_approval_card_for_proposal_id",
    "push_approval_card_to_teams",
    "schedule_teams_approval_push",
]


def __getattr__(name: str) -> Any:
    if name == "LexiTeamsBot":
        from app.bot.teams_handler import LexiTeamsBot

        return LexiTeamsBot
    if name in {
        "push_approval_card_for_proposal_id",
        "push_approval_card_to_teams",
        "schedule_teams_approval_push",
    }:
        from app.bot import teams_publisher

        return getattr(teams_publisher, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

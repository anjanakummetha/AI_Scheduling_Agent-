"""Unified scheduling entry points for email, Hermes MCP, and orchestrator."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "propose_schedule":
        from app.scheduling.propose import propose_schedule

        return propose_schedule
    if name == "schedule_from_context":
        from app.scheduling.schedule_from_context import schedule_from_context

        return schedule_from_context
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["propose_schedule", "schedule_from_context"]

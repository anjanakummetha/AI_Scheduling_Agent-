"""Unified scheduling entry points for email, Hermes MCP, and orchestrator."""

from app.scheduling.propose import propose_schedule

__all__ = ["propose_schedule"]

"""Composio session and tool execution helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from composio import Composio

from app.config import settings


class ComposioNotConfiguredError(RuntimeError):
    """Raised when Composio credentials are missing."""


def _require_api_key() -> str:
    if not settings.composio_api_key:
        raise ComposioNotConfiguredError("COMPOSIO_API_KEY is missing.")
    return settings.composio_api_key


@lru_cache
def get_composio() -> Composio:
    return Composio(api_key=_require_api_key())


def execute_tool(tool_slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = get_composio().tools.execute(
        tool_slug,
        arguments=arguments,
        user_id=settings.composio_user_id,
        dangerously_skip_version_check=True,
    )
    if isinstance(response, dict):
        data = response.get("data")
        error = response.get("error")
        log_id = response.get("log_id")
    else:
        data = getattr(response, "data", None)
        error = getattr(response, "error", None)
        log_id = getattr(response, "log_id", None)

    if error:
        raise RuntimeError(f"{tool_slug} failed: {error}")

    return {
        "data": data,
        "log_id": log_id,
    }

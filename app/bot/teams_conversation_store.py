"""Persist Teams conversation reference for proactive Adaptive Card delivery."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from botbuilder.core import TurnContext

from app.config import settings

logger = logging.getLogger(__name__)

STORE_PATH = settings.lexi_database_path.parent / "teams_conversation.json"
_HERMES_ENV_PATH = Path.home() / ".hermes" / ".env"

WRITE_TOOL_PREFIXES = (
    "OUTLOOK_CREATE",
    "OUTLOOK_SEND",
    "OUTLOOK_DELETE",
    "OUTLOOK_UPDATE",
)


def save_conversation_reference(
    conversation_id: str,
    *,
    service_url: str = "",
    tenant_id: str = "",
    channel_id: str = "msteams",
    bot_id: str = "",
) -> dict[str, str]:
    """Persist Teams conversation for proactive Lexi cards (Hermes-only path)."""
    record = {
        "conversation_id": conversation_id.strip(),
        "service_url": (
            service_url.strip()
            or _tenant_teams_service_url_from_env()
        ),
        "tenant_id": tenant_id.strip(),
        "channel_id": channel_id.strip() or "msteams",
        "bot_id": bot_id.strip(),
    }
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info(
        "Saved Teams conversation reference conversation_id=%s service_url=%s",
        record["conversation_id"],
        record["service_url"],
    )
    return record


def capture_conversation_reference(turn_context: TurnContext) -> dict[str, str] | None:
    """Save conversation id + service URL from an inbound Teams activity."""
    activity = turn_context.activity
    conversation = activity.conversation
    if conversation is None or not conversation.id:
        return None

    service_url = (activity.service_url or "").strip()
    if not service_url:
        service_url = _tenant_teams_service_url_from_env()

    record = {
        "conversation_id": str(conversation.id),
        "service_url": service_url,
        "tenant_id": str(conversation.tenant_id or ""),
        "channel_id": str(activity.channel_id or "msteams"),
        "bot_id": str(activity.recipient.id if activity.recipient else ""),
    }
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info(
        "Saved Teams conversation reference conversation_id=%s service_url=%s",
        record["conversation_id"],
        record["service_url"],
    )
    return record


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _hermes_home_channel_reference() -> dict[str, str] | None:
    """Hermes /sethome stores Kory's live DM — prefer it when project store is stale."""
    hermes_env = _read_env_file(_HERMES_ENV_PATH)
    conversation_id = hermes_env.get("TEAMS_HOME_CHANNEL", "").strip()
    if not conversation_id:
        return None
    service_url = (
        hermes_env.get("TEAMS_SERVICE_URL", "").strip()
        or os.getenv("TEAMS_SERVICE_URL", "").strip()
    )
    if not service_url:
        tenant_id = hermes_env.get("TEAMS_TENANT_ID", "").strip() or os.getenv(
            "TEAMS_TENANT_ID", ""
        ).strip()
        if tenant_id:
            service_url = f"https://smba.trafficmanager.net/amer/{tenant_id}/"
        else:
            service_url = "https://smba.trafficmanager.net/amer/"
    if not service_url.endswith("/"):
        service_url += "/"
    tenant_id = hermes_env.get("TEAMS_TENANT_ID", "").strip()
    return {
        "conversation_id": conversation_id,
        "service_url": service_url,
        "tenant_id": tenant_id,
        "channel_id": "msteams",
        "bot_id": hermes_env.get("TEAMS_CLIENT_ID", "").strip(),
    }


def load_conversation_reference() -> dict[str, str] | None:
    env_conversation = os.getenv("TEAMS_CONVERSATION_ID", "").strip()
    env_service = os.getenv("TEAMS_SERVICE_URL", "").strip()

    if env_conversation:
        return {
            "conversation_id": env_conversation,
            "service_url": env_service or _tenant_teams_service_url_from_env(),
        }

    if STORE_PATH.exists():
        try:
            data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("conversation_id"):
                return {
                    "conversation_id": str(data["conversation_id"]),
                    "service_url": str(
                        data.get("service_url") or _tenant_teams_service_url_from_env()
                    ),
                }
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read Teams conversation store: %s", exc)

    hermes_ref = _hermes_home_channel_reference()
    if hermes_ref:
        return hermes_ref

    return None


def _tenant_teams_service_url_from_env() -> str:
    explicit = os.getenv("TEAMS_SERVICE_URL", "").strip()
    if explicit:
        return explicit if explicit.endswith("/") else f"{explicit}/"
    tenant_id = os.getenv("TEAMS_TENANT_ID", "").strip()
    if tenant_id:
        return f"https://smba.trafficmanager.net/amer/{tenant_id}/"
    return "https://smba.trafficmanager.net/amer/"


def teams_delivery_ready() -> bool:
    return bool(
        os.getenv("TEAMS_CLIENT_ID", "").strip()
        and os.getenv("TEAMS_CLIENT_SECRET", "").strip()
        and load_conversation_reference()
    )

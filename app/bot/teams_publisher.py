"""Proactive delivery of Lexi approval Adaptive Cards to Microsoft Teams."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from botbuilder.core import CardFactory
from botbuilder.schema import Activity, ActivityTypes
from botframework.connector.aio import ConnectorClient
from botframework.connector.auth import MicrosoftAppCredentials

from app.agents.comms_agent import get_lexi_pending_queue
from app.bot.teams_conversation_store import load_conversation_reference, teams_delivery_ready
from app.agents.inbound_reply import get_inbound_reply_queue
from app.bot.teams_text import format_approval_notification, format_reply_prompt_notification
from app.config import settings
from app.storage.lexi_db import get_lexi_connection
from app.utils.teams_cards import generate_approval_card, generate_reply_prompt_card

logger = logging.getLogger(__name__)

DEFAULT_TEAMS_SERVICE_URL = "https://smba.trafficmanager.net/amer/"


def _tenant_teams_service_url() -> str:
    explicit = os.getenv("TEAMS_SERVICE_URL", "").strip()
    if explicit:
        return explicit if explicit.endswith("/") else f"{explicit}/"
    tenant_id = os.getenv("TEAMS_TENANT_ID", "").strip()
    if tenant_id:
        return f"https://smba.trafficmanager.net/amer/{tenant_id}/"
    return DEFAULT_TEAMS_SERVICE_URL
PENDING_APPROVAL = "pending_approval"
_TEAMS_PUSH_COOLDOWN_SECONDS = 300
_recent_teams_pushes: dict[int, float] = {}


def _teams_push_on_cooldown(proposal_id: int) -> bool:
    import time

    last = _recent_teams_pushes.get(proposal_id)
    if last is None:
        return False
    return (time.time() - last) < _TEAMS_PUSH_COOLDOWN_SECONDS


def _mark_teams_push_sent(proposal_id: int) -> None:
    import time

    _recent_teams_pushes[proposal_id] = time.time()


def _teams_credentials_configured() -> bool:
    return teams_delivery_ready()


def _build_app_credentials() -> MicrosoftAppCredentials:
    app_id = os.getenv("TEAMS_CLIENT_ID", "").strip()
    app_password = os.getenv("TEAMS_CLIENT_SECRET", "").strip()
    tenant_id = os.getenv("TEAMS_TENANT_ID", "").strip() or None
    return MicrosoftAppCredentials(
        app_id,
        app_password,
        channel_auth_tenant=tenant_id,
    )


def _sandbox_log_card(proposal_id: int | str, card_json: dict[str, Any], reason: str) -> None:
    print(json.dumps(card_json, indent=2, default=str))
    logger.info(
        "Teams sandbox fallback for proposal %s (%s); printed approval card JSON to terminal.",
        proposal_id,
        reason,
    )


def _parse_json_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _fetch_holds(conn: Any, proposal_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, event_id, slot_start, slot_end, created_at
        FROM holds
        WHERE proposal_id = ?
        ORDER BY id ASC
        """,
        (proposal_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def load_proposal_approval_payload(
    proposal_id: int,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Load proposal, email thread, holds, and generated approval card for Teams delivery."""
    with get_lexi_connection() as conn:
        row = conn.execute(
            """
            SELECT
                p.id AS proposal_id,
                p.thread_id,
                p.status,
                p.intent_classification,
                p.priority_tier,
                p.proposed_slots,
                p.drafted_reply,
                p.confidence_score,
                p.justification,
                p.voice_mode,
                e.subject,
                e.sender,
                e.raw_body
            FROM proposals AS p
            INNER JOIN email_threads AS e ON e.thread_id = p.thread_id
            WHERE p.id = ?
            """,
            (proposal_id,),
        ).fetchone()

        if row is None:
            return None

        if row["status"] != PENDING_APPROVAL:
            logger.debug(
                "Skipping Teams card for proposal %s; status=%s",
                proposal_id,
                row["status"],
            )
            return None

        holds = _fetch_holds(conn, proposal_id)
        proposal_record = {
            "id": int(row["proposal_id"]),
            "thread_id": row["thread_id"],
            "intent_classification": row["intent_classification"],
            "priority_tier": row["priority_tier"],
            "drafted_reply": row["drafted_reply"],
            "justification": row["justification"],
            "confidence_score": row["confidence_score"],
            "voice_mode": row["voice_mode"],
            "proposed_slots": _parse_json_list(row["proposed_slots"]),
        }
        email_record = {
            "subject": row["subject"],
            "sender": row["sender"],
            "raw_body": row["raw_body"],
        }
        card_json = generate_approval_card(proposal_record, email_record, holds)
        return proposal_record, card_json


async def push_approval_text_to_teams(text: str, *, proposal_id: int | str = "") -> None:
    """Proactively post a text approval summary to the configured Teams conversation."""
    if not _teams_credentials_configured():
        logger.info(
            "Teams text notify skipped for proposal %s — message Lexi bot once or set TEAMS_CONVERSATION_ID.",
            proposal_id,
        )
        print(f"\n[Lexi Teams text — proposal {proposal_id}]\n{text}\n", flush=True)
        return

    ref = load_conversation_reference()
    if ref is None:
        return

    activity = Activity(
        type=ActivityTypes.message,
        text=text,
        summary=f"Lexi approval required — proposal {proposal_id}",
    )
    conversation_id = ref["conversation_id"]
    service_url = ref.get("service_url") or _tenant_teams_service_url()
    try:
        credentials = _build_app_credentials()
        async with ConnectorClient(credentials, service_url) as client:
            await client.conversations.send_to_conversation(conversation_id, activity)
        logger.info("Posted Lexi approval text to Teams for proposal %s", proposal_id)
        if isinstance(proposal_id, int):
            _mark_teams_push_sent(proposal_id)
    except Exception as exc:
        logger.exception(
            "Failed to push approval text to Teams for proposal %s: %s",
            proposal_id,
            exc,
        )


async def push_approval_card_to_teams(
    proposal_record: dict[str, Any],
    card_json: dict[str, Any],
) -> bool:
    """Proactively post an approval Adaptive Card to the configured Teams conversation."""
    proposal_id = proposal_record.get("id", "unknown")

    if not _teams_credentials_configured():
        _sandbox_log_card(
            proposal_id,
            card_json,
            "no_conversation_id_message_bot_first_or_set_TEAMS_CONVERSATION_ID",
        )
        return False

    ref = load_conversation_reference()
    if ref is None:
        _sandbox_log_card(proposal_id, card_json, "conversation_reference_missing")
        return False

    conversation_id = ref["conversation_id"]
    service_url = ref.get("service_url") or _tenant_teams_service_url()

    activity = Activity(
        type=ActivityTypes.message,
        attachments=[CardFactory.adaptive_card(card_json)],
        summary=f"Lexi approval required — proposal {proposal_id}",
    )

    try:
        credentials = _build_app_credentials()
        async with ConnectorClient(credentials, service_url) as client:
            await client.conversations.send_to_conversation(conversation_id, activity)
        logger.info("Posted Lexi approval card to Teams for proposal %s", proposal_id)
        if isinstance(proposal_id, int):
            _mark_teams_push_sent(proposal_id)
        return True
    except Exception as exc:
        logger.exception(
            "Failed to push approval card to Teams for proposal %s: %s",
            proposal_id,
            exc,
        )
        _sandbox_log_card(proposal_id, card_json, "teams_api_error")
        return False


async def push_approval_card_for_proposal_id(proposal_id: int) -> None:
    """Load a pending proposal and notify Teams (text and/or Adaptive Card)."""
    if _teams_push_on_cooldown(proposal_id):
        logger.info(
            "Skipping duplicate Teams approval push for proposal %s (cooldown).",
            proposal_id,
        )
        return

    queue = get_lexi_pending_queue()
    item = next((entry for entry in queue if entry.proposal_id == proposal_id), None)
    if item is not None:
        await push_approval_text_to_teams(
            format_approval_notification(item),
            proposal_id=proposal_id,
        )
        if settings.lexi_teams_text_only:
            _mark_teams_push_sent(proposal_id)
            return
        await push_approval_card_to_teams(
            {
                "id": item.proposal_id,
                "thread_id": item.thread_id,
                "drafted_reply": item.drafted_reply,
                "voice_mode": item.voice_mode,
                "proposed_slots": item.proposed_slots,
            },
            item.approval_card,
        )
        _mark_teams_push_sent(proposal_id)
        return

    payload = load_proposal_approval_payload(proposal_id)
    if payload is None:
        logger.info(
            "No pending_approval payload available for Teams push (proposal_id=%s).",
            proposal_id,
        )
        return

    proposal_record, card_json = payload
    await push_approval_card_to_teams(proposal_record, card_json)
    _mark_teams_push_sent(proposal_id)


async def push_all_pending_cards_to_teams() -> int:
    """Notify Teams for every pending_approval proposal (text and/or cards)."""
    queue = get_lexi_pending_queue()
    if not queue:
        return 0

    pushed = 0
    for item in queue:
        await push_approval_text_to_teams(
            format_approval_notification(item),
            proposal_id=item.proposal_id,
        )
        if not settings.lexi_teams_text_only:
            await push_approval_card_to_teams(
                {
                    "id": item.proposal_id,
                    "thread_id": item.thread_id,
                },
                item.approval_card,
            )
        pushed += 1
    return pushed


def schedule_push_all_pending_cards() -> None:
    """Fire-and-forget push of all pending approval cards."""
    try:
        coro = push_all_pending_cards_to_teams()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
        loop.create_task(coro)
    except Exception as exc:
        logger.exception("Failed to schedule pending Teams card push: %s", exc)


def _load_reply_prompt_item(proposal_id: int) -> dict[str, Any] | None:
    for item in get_inbound_reply_queue():
        if int(item.get("proposal_id", 0)) == proposal_id:
            return item
    return None


async def push_reply_prompt_for_proposal_id(proposal_id: int) -> None:
    """Ask Kory whether to draft a reply for a new inbound email."""
    item = _load_reply_prompt_item(proposal_id)
    if item is None:
        logger.info(
            "No awaiting_reply_prompt payload for Teams push (proposal_id=%s).",
            proposal_id,
        )
        return

    if settings.lexi_teams_text_only:
        await push_approval_text_to_teams(
            format_reply_prompt_notification(item),
            proposal_id=proposal_id,
        )
        return

    if not _teams_credentials_configured():
        await push_approval_text_to_teams(
            format_reply_prompt_notification(item),
            proposal_id=proposal_id,
        )
        return

    ref = load_conversation_reference()
    if ref is None:
        await push_approval_text_to_teams(
            format_reply_prompt_notification(item),
            proposal_id=proposal_id,
        )
        return

    proposal_record = {
        "id": proposal_id,
        "intent_classification": item.get("intent_classification"),
        "priority_tier": item.get("priority_tier"),
    }
    email_record = {
        "sender": item.get("sender"),
        "subject": item.get("subject"),
        "received_at": item.get("received_at"),
        "raw_body": item.get("raw_body"),
    }
    prompt_text = format_reply_prompt_notification(item)
    await push_approval_text_to_teams(prompt_text, proposal_id=proposal_id)

    card_json = generate_reply_prompt_card(proposal_record, email_record)

    conversation_id = ref["conversation_id"]
    service_url = ref.get("service_url") or _tenant_teams_service_url()
    activity = Activity(
        type=ActivityTypes.message,
        attachments=[CardFactory.adaptive_card(card_json)],
        summary=f"Lexi — {email_record.get('subject', 'new email')}",
    )
    try:
        credentials = _build_app_credentials()
        async with ConnectorClient(credentials, service_url) as client:
            await client.conversations.send_to_conversation(conversation_id, activity)
        logger.info("Posted Lexi reply-prompt card to Teams for proposal %s", proposal_id)
    except Exception as exc:
        logger.exception(
            "Failed to push reply-prompt card for proposal %s: %s",
            proposal_id,
            exc,
        )


def schedule_teams_reply_prompt_push(proposal_id: int) -> None:
    """Fire-and-forget Teams notification: should I draft a reply?"""
    try:
        coro = push_reply_prompt_for_proposal_id(proposal_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
        loop.create_task(coro)
    except Exception as exc:
        logger.exception(
            "Failed to schedule Teams reply prompt for proposal %s: %s",
            proposal_id,
            exc,
        )


def schedule_teams_approval_push(proposal_id: int) -> None:
    """Fire-and-forget Teams card delivery so orchestration never blocks on Bot Framework."""
    try:
        coro = push_approval_card_for_proposal_id(proposal_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return

        loop.create_task(coro)
    except Exception as exc:
        logger.exception(
            "Failed to schedule Teams approval push for proposal %s: %s",
            proposal_id,
            exc,
        )

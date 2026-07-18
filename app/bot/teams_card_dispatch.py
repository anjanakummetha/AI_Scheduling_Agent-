"""Deterministic Teams Adaptive Card Action.Submit → Lexi approval (no LLM)."""

from __future__ import annotations

import logging
from typing import Any

from app.utils.teams_cards import (
    CARD_ACTION_APPROVAL,
    CARD_ACTION_INVITE,
    CARD_ACTION_REOFFER,
    CARD_ACTION_SAVE_DRAFT,
    INPUT_DRAFT_ID,
)

logger = logging.getLogger(__name__)

_LEXI_CARD_ACTIONS = frozenset(
    {
        CARD_ACTION_APPROVAL,
        CARD_ACTION_SAVE_DRAFT,
        CARD_ACTION_INVITE,
        CARD_ACTION_REOFFER,
    }
)


def is_lexi_card_submit(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    action = str(payload.get("action") or "").strip()
    return action in _LEXI_CARD_ACTIONS


async def handle_teams_card_submit_activity(
    ctx: Any,
    payload: dict[str, Any],
    *,
    send_fn: Any = None,
    conv_id: str = "",
) -> None:
    """Process Action.Submit from Lexi approval cards; reply in Teams without Hermes LLM."""
    from app.teams.commands import handle_teams_card_submit

    from_account = ctx.activity.from_
    user_id = getattr(from_account, "aad_object_id", None) or getattr(from_account, "id", "")
    authorized_by = str(user_id or "kory")

    # Teams merges Input.Text values into submit data under the input id.
    if INPUT_DRAFT_ID not in payload and payload.get("drafted_reply"):
        payload = {**payload, INPUT_DRAFT_ID: payload["drafted_reply"]}

    result = handle_teams_card_submit(payload, authorized_by=authorized_by)
    message = str(result.get("message") or "Done.")
    if not result.get("ok"):
        message = f"⚠️ {message}"

    sent = False
    if send_fn:
        await send_fn(message)
        sent = True
    else:
        app = getattr(ctx, "app", None)
        cid = conv_id or getattr(getattr(ctx.activity, "conversation", None), "id", None)
        if cid and app:
            await app.send(str(cid), message)
            sent = True
    if not sent:
        logger.warning("Lexi card submit handled but could not reply in Teams: %s", message)

    logger.info(
        "Lexi card submit handled action=%s proposal=%s ok=%s",
        payload.get("action"),
        payload.get("proposal_id"),
        result.get("ok"),
    )

"""Scheduling reply composition — Hermes intelligence with template fallback."""

from __future__ import annotations

from typing import Any

from app.scheduling.scheduling_plan import SchedulingPlan
from app.scheduling.timezone_intel import extract_internet_headers


def compose_scheduling_reply(
    *,
    proposal_sender: str | None,
    proposal_subject: str,
    proposal_body: str,
    thread_id: str,
    slots: list[dict[str, str]],
    voice_mode: str = "lexi",
    stored_recipient_timezone: str | None = None,
    plan: SchedulingPlan | None = None,
    intent: str | None = None,
) -> tuple[str, str]:
    """Return (draft_body, source) where source is hermes or template_fallback."""
    from app.scheduling.hermes_compose import compose_offer_email_with_hermes

    resolved_intent = intent or (plan.raw.get("intent") if plan and plan.raw else None)
    return compose_offer_email_with_hermes(
        proposal_sender=proposal_sender,
        proposal_subject=proposal_subject,
        proposal_body=proposal_body,
        thread_id=thread_id,
        slots=slots,
        voice_mode=voice_mode,
        stored_recipient_timezone=stored_recipient_timezone,
        intent=resolved_intent,
    )


def _fetch_headers(thread_id: str) -> list[dict[str, Any]] | None:
    try:
        from app.integrations.outlook_email import get_message

        full_message, _ = get_message(thread_id)
        return extract_internet_headers(full_message)
    except Exception:
        return None

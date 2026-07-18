"""Sync Hermes scheduling_session from proposal state."""

from __future__ import annotations

from typing import Any

from app.scheduling.hermes_compose import build_scheduling_context_packet
from app.storage.scheduling_sessions import upsert_thread_session


def sync_scheduling_session_for_proposal(proposal_id: int) -> dict[str, Any]:
    """Create or update scheduling_session so Hermes has whole-task context."""
    packet = build_scheduling_context_packet(proposal_id)
    if not packet.get("ok"):
        return {"ok": False, "error": packet.get("error")}

    thread_id = str(packet.get("thread_id") or proposal_id)
    context = {
        "proposal_id": proposal_id,
        "thread_id": thread_id,
        "subject": packet.get("subject"),
        "sender": packet.get("sender"),
        "intent": packet.get("intent_classification"),
        "meeting_type_label": packet.get("meeting_type_label"),
        "voice_mode": packet.get("voice_mode"),
        "status": packet.get("status"),
        "offered_slots": packet.get("offered_slots"),
        "is_delegation": packet.get("is_delegation"),
        "recipient_timezone": packet.get("recipient_timezone"),
        "scheduling_rules_summary": packet.get("scheduling_rules_summary"),
        "latest_inbound_body": (packet.get("latest_inbound_body") or "")[:1500],
    }
    session_id = upsert_thread_session(thread_id, context, channel="inbound")
    return {"ok": True, "session_id": session_id, "context": context}

"""Deterministic scheduling actions for Hermes (Option A conversational Lexi)."""

from __future__ import annotations

import json
import traceback
from typing import Any

from app.config import settings
from app.integrations.calendar_holds import place_tentative_hold
from app.integrations.named_calendars import list_all_calendars, resolve_calendar_name
from app.integrations.outlook_calendar import has_conflict
from app.scheduling.email_format import build_scheduling_reply, example_draft_preview, sender_first_name
from app.integrations.outlook_email import send_outbound_email
from app.storage.lexi_db import get_lexi_connection


def _ingress_status() -> dict[str, Any]:
    import os

    from app.orchestrator import describe_ingress_mode
    from app.worker.runner import is_worker_running

    interval = int(os.getenv("LEXI_ORCHESTRATOR_INTERVAL", "30"))
    status = describe_ingress_mode(interval_seconds=interval)
    status["worker_running"] = is_worker_running()
    return status


def get_lexi_system_status() -> dict[str, Any]:
    """Runtime flags for Hermes to explain dry-run vs live Outlook."""
    pending_count = 0
    try:
        with get_lexi_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM proposals WHERE status = 'pending_approval'",
            ).fetchone()
            pending_count = int(row["c"]) if row else 0
    except Exception:
        pending_count = -1

    from app.bot.teams_conversation_store import load_conversation_reference, teams_delivery_ready
    from app.safety.kory_read_only import read_only_safety_snapshot
    from app.storage.learning_log import recent_feedback_summary

    safety = read_only_safety_snapshot()
    teams_ref = load_conversation_reference()
    return {
        "lexi_dry_run": settings.lexi_dry_run,
        "lexi_write_mode": settings.lexi_write_mode,
        "demo_mode": settings.demo_mode,
        "read_connection": settings.kory_composio_connection_id,
        "lexi_connection": settings.lexi_composio_connection_id,
        "lexi_mailbox_email": settings.lexi_mailbox_email,
        "write_connection": settings.sandbox_composio_connection_id
        if settings.lexi_write_mode == "sandbox"
        else settings.kory_composio_connection_id,
        "sandbox_mailbox_email": settings.sandbox_mailbox_email,
        "sandbox_email_loopback": settings.sandbox_email_loopback,
        "asana_enabled": settings.asana_enabled,
        "asana_connection": settings.asana_composio_connection_id,
        "asana_project_gid_set": bool(settings.asana_project_gid),
        "lexi_teams_enabled": settings.lexi_teams_enabled,
        "lexi_teams_text_only": settings.lexi_teams_text_only,
        "teams_cards_ready": teams_delivery_ready(),
        "teams_conversation_registered": bool(teams_ref),
        "teams_conversation_id_prefix": (teams_ref or {}).get("conversation_id", "")[:24] or None,
        "lexi_teams_inbound_notify_mode": settings.lexi_teams_inbound_notify_mode,
        "lexi_delegation_auto_draft": settings.lexi_delegation_auto_draft,
        "lexi_composio_search_enabled": settings.lexi_composio_search_enabled,
        "composio_configured": bool(settings.composio_api_key and settings.kory_composio_connection_id),
        "pending_approval_count": pending_count,
        "scheduling_timezone": settings.scheduling_timezone,
        "outlook_timezone": settings.outlook_timezone,
        "llm_model": settings.llm_model,
        "learning_summary": recent_feedback_summary(limit=5) or None,
        "safety": safety,
        "ingress": _ingress_status(),
        "note": (
            "Production: lexi@ + kory@ifg.vc sends and calendar writes enabled; "
            "all external impact needs Teams approval. "
            f"Composio Search: {'on' if settings.lexi_composio_search_enabled else 'off'}. "
            "Teams inbound notify: "
            f"{settings.lexi_teams_inbound_notify_mode}. "
            "Delegation auto-draft when Kory CCs Lexi."
        ),
    }


def get_calendar_availability(*, days: int = 0) -> dict[str, Any]:
    """Return Kory-blocking events across Outlook calendars (intelligence-filtered)."""
    from app.integrations.family_google_calendar import family_calendar_status
    from app.scheduling.calendar_context import load_scheduling_calendar_context

    window_days = days if days > 0 else settings.lexi_calendar_search_days
    window_days = max(7, min(window_days, settings.lexi_calendar_search_days_max))
    context = load_scheduling_calendar_context(horizon_days=window_days)
    busy = context.get("busy_events") or []
    consulted = context.get("calendars_consulted") or []
    resolved_names = [c["name"] for c in consulted if c.get("resolved")]
    family = family_calendar_status()
    family_count = sum(1 for e in busy if e.get("source") == "family_calendar")
    if family["configured"] and family_count == 0:
        family_note = "Family calendar connected; no Do Not Move blocks in this window."
    elif not family["configured"]:
        family_note = family["hint"]
    else:
        family_note = f"Family Do Not Move blocks in window: {family_count}"
    unavailable = context.get("calendars_unavailable") or []
    return {
        "window_days": context.get("horizon_days", window_days),
        "calendar_status": context.get("status"),
        "calendars_consulted": consulted,
        "calendars_resolved": resolved_names,
        "calendars_unavailable": unavailable,
        "busy_summary": context.get("busy_summary"),
        "family_calendar": family,
        "family_blocks_in_window": family_count,
        "busy_event_count": len(busy),
        "busy_events": busy[:120],
        "range_start": context.get("range_start"),
        "range_end": context.get("range_end"),
        "scheduling_timezone": settings.scheduling_timezone,
        "hint": (
            "Busy/free merges work Calendar + Master (kid-only / duplicate copies filtered), "
            "plus family Do Not Move when configured. "
            "Writes: business → Calendar, personal Kory → Master. "
            f"{family_note}"
        ),
    }


def check_time_slot(*, start_iso: str, end_iso: str) -> dict[str, Any]:
    """Check whether a proposed interval conflicts with Kory's calendar."""
    action = {"start": start_iso.strip(), "end": end_iso.strip()}
    conflict, events, log_id = has_conflict(action)
    return {
        "start": action["start"],
        "end": action["end"],
        "has_conflict": conflict,
        "conflicting_events": events[:10],
        "composio_log_id": log_id,
    }


def list_calendars(*, role: str = "read") -> dict[str, Any]:
    """List named Outlook calendars (read=Kory, write=sandbox/kory)."""
    conn_role = "write" if role.strip().lower() == "write" else "read"
    calendars = list_all_calendars(role=conn_role)  # type: ignore[arg-type]
    return {"ok": True, "role": conn_role, "count": len(calendars), "calendars": calendars}


def add_conflict_calendar(calendar_name: str) -> dict[str, Any]:
    """Add an Outlook calendar to Lexi's conflict-read list (persists config/calendars.yaml)."""
    from app.integrations.named_calendars import add_conflict_calendar as _add

    return _add(calendar_name)


def preview_scheduling_email_example() -> dict[str, Any]:
    """Return a formatted example scheduling reply for Kory's rules."""
    return {"ok": True, **example_draft_preview()}


def place_calendar_hold(
    *,
    title: str,
    start_iso: str,
    end_iso: str,
    attendee_email: str = "",
    location: str = "TBD",
    notes: str = "",
    calendar_name: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Place a tentative hold on a named Outlook calendar (default: Kory Master)."""
    from app.safety.approval_gate import assert_kory_approved_write

    assert_kory_approved_write(approved=confirm, action="Calendar hold")
    subject = (title or "Meeting").strip()
    if not subject.lower().startswith("hold"):
        subject = f"Hold - {subject}"

    attendees = []
    email = attendee_email.strip().lower()
    if email and "@" in email:
        attendees.append(email)

    body_note = (notes or "").strip() or "Tentative hold created by Lexi via Hermes."
    action = {
        "title": subject,
        "start": start_iso.strip(),
        "end": end_iso.strip(),
        "attendees": attendees,
        "location": location.strip() or "TBD",
        "body": body_note,
    }

    conflict, conflicts, _ = has_conflict(action)
    if conflict:
        return {
            "ok": False,
            "error": "Requested slot conflicts with existing calendar blocks.",
            "conflicting_events": conflicts[:5],
            "action": action,
        }

    cal = (calendar_name or "").strip()
    if cal:
        resolved = resolve_calendar_name(cal, role="write")
        if not resolved:
            return {
                "ok": False,
                "error": f"Calendar not found: {cal}. Call lexi_list_calendars first.",
            }

    try:
        hold = place_tentative_hold(
            title=subject,
            start_iso=action["start"],
            end_iso=action["end"],
            notes=body_note,
            calendar_name=cal or None,
        )
        if not hold.get("ok"):
            return hold
        event_id = hold.get("event_id")
        log_id = hold.get("composio_log_id")
        _audit(
            "hermes_place_hold",
            reference_id=event_id or "unknown",
            message=f"Calendar hold placed: {subject}",
            payload={
                "action": action,
                "event_id": event_id,
                "log_id": log_id,
                "calendar_name": cal or "default",
            },
        )
        return {
            "ok": bool(event_id),
            "event_id": event_id,
            "composio_log_id": log_id,
            "dry_run": settings.lexi_dry_run,
            "calendar_name": cal or "default",
            "action": action,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "action": action,
        }


def draft_outbound_email_preview(
    *,
    to_email: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """Return an outbound email preview without sending (Hermes drafts the body in chat)."""
    recipient = to_email.strip().lower()
    if not recipient or "@" not in recipient:
        return {"ok": False, "error": "to_email must be a valid email address."}

    return {
        "ok": True,
        "preview_only": True,
        "to": recipient,
        "subject": subject.strip() or "(no subject)",
        "body": body.strip(),
        "dry_run": settings.lexi_dry_run,
        "next_step": (
            "Show this preview to Kory. After explicit approval, call "
            "lexi_send_outbound_email with confirm_send=true."
        ),
    }


def send_outbound_email_confirmed(
    *,
    to_email: str,
    subject: str,
    body: str,
    confirm_send: bool,
    authorized_by: str = "hermes_user",
    send_channel: str | None = None,
) -> dict[str, Any]:
    """Send outbound email only when confirm_send is true (lexi@ by default)."""
    if not confirm_send:
        return {
            "ok": False,
            "error": (
                "confirm_send must be true. Get Kory's explicit approval first "
                "(e.g. 'yes send it')."
            ),
        }

    recipient = to_email.strip().lower()
    if not recipient or "@" not in recipient:
        return {"ok": False, "error": "to_email must be a valid email address."}

    try:
        channel = (send_channel or settings.lexi_default_send_channel or "lexi").strip().lower()
        if channel not in {"kory", "lexi"}:
            channel = "lexi"
        message_id, log_id = send_outbound_email(
            to_email=recipient,
            subject=subject.strip(),
            body=body.strip(),
            approved_send=True,
            send_channel=channel,  # type: ignore[arg-type]
        )
        _audit(
            "hermes_send_email",
            reference_id=message_id or recipient,
            message=f"Outbound email dispatched to {recipient}",
            payload={
                "to": recipient,
                "subject": subject,
                "message_id": message_id,
                "authorized_by": authorized_by,
                "dry_run": settings.lexi_dry_run,
            },
        )
        return {
            "ok": bool(message_id),
            "message_id": message_id,
            "composio_log_id": log_id,
            "dry_run": settings.lexi_dry_run,
            "to": recipient,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def search_inbox(query: str = "", top: int = 10) -> dict[str, Any]:
    """Search Kory's Outlook inbox (read-only)."""
    from app.integrations.outlook_inbox import search_inbox as _search

    try:
        messages, log_id = _search(query=query, top=top)
        return {
            "ok": True,
            "count": len(messages),
            "messages": messages,
            "composio_log_id": log_id,
            "query": query,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def get_email_thread(message_id: str) -> dict[str, Any]:
    """Fetch one inbox message from Kory's mailbox by message id."""
    from app.integrations.outlook_inbox import get_thread_message

    try:
        payload = get_thread_message(message_id.strip())
        return {"ok": True, **payload}
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def run_propose_schedule(
    *,
    subject: str = "",
    body: str = "",
    sender: str = "unknown@example.com",
    thread_id: str = "",
) -> dict[str, Any]:
    """Unified propose_schedule via inbound email dict (Hermes / console)."""
    from app.scheduling.propose import propose_schedule
    import uuid

    tid = thread_id.strip() or f"hermes-{uuid.uuid4().hex[:10]}"
    raw_email = {
        "thread_id": tid,
        "subject": subject.strip(),
        "sender": sender.strip(),
        "received_at": "",
        "raw_body": body.strip(),
    }
    try:
        result = propose_schedule(raw_email=raw_email)
        return {"ok": True, **result}
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def get_scheduling_session(session_id: str) -> dict[str, Any]:
    from app.storage.scheduling_sessions import get_session

    session = get_session(session_id.strip())
    if not session:
        return {"ok": False, "error": "session_not_found"}
    return {"ok": True, "session": session}


def upsert_scheduling_session(
    *,
    session_id: str = "",
    channel: str = "hermes",
    context: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    from app.storage.scheduling_sessions import create_session, get_session, update_session

    if session_id.strip():
        updated = update_session(session_id.strip(), context=context, status=status)
        if not updated:
            return {"ok": False, "error": "session_not_found"}
        session = get_session(session_id.strip())
        return {"ok": True, "session": session}

    new_id = create_session(channel=channel, context=context or {})
    session = get_session(new_id)
    return {"ok": True, "session": session}


def validate_slots_preview(
    slots: list[dict[str, str]],
    intent: str = "",
) -> dict[str, Any]:
    from app.rules.validators import validate_proposal_slots

    result = validate_proposal_slots(slots, intent=intent or None)
    return {"ok": result.valid, **result.to_dict()}


def get_inbound_reply_queue_action() -> dict[str, Any]:
    from app.agents.inbound_reply import get_inbound_reply_queue

    items = get_inbound_reply_queue()
    return {"ok": True, "count": len(items), "queue": items}


def begin_draft_reply_action(*, proposal_id: int, voice_mode: str = "") -> dict[str, Any]:
    from app.agents.inbound_reply import begin_draft_reply

    return begin_draft_reply(proposal_id, voice_mode=voice_mode)


def decline_inbound_reply_action(*, proposal_id: int, reason: str = "") -> dict[str, Any]:
    from app.agents.inbound_reply import decline_reply

    return decline_reply(proposal_id, reason=reason)


def update_proposal_draft_action(*, proposal_id: int, drafted_reply: str) -> dict[str, Any]:
    from app.agents.inbound_reply import update_proposal_draft

    return update_proposal_draft(proposal_id, drafted_reply)


def start_outbound_scheduling(
    *,
    recipient_email: str,
    subject: str,
    meeting_intent: str,
    duration_minutes: int,
    authorized_by: str,
    require_ceo_signoff: bool = True,
) -> dict[str, Any]:
    """Start full outbound proposal flow (slots + draft + optional pending_approval)."""
    from app.agents.outbound_agent import initiate_outbound_scheduling

    try:
        result = initiate_outbound_scheduling(
            recipient_email=recipient_email,
            subject=subject,
            meeting_intent=meeting_intent,
            duration_minutes=duration_minutes,
            authorized_by=authorized_by,
            require_ceo_signoff=require_ceo_signoff,
        )
        result["dry_run"] = settings.lexi_dry_run
        return result
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _audit(
    step_name: str,
    *,
    reference_id: str,
    message: str,
    payload: dict[str, Any],
) -> None:
    try:
        with get_lexi_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (step_name, reference_id, log_level, message, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    step_name,
                    reference_id,
                    "INFO",
                    message,
                    json.dumps(payload, default=str),
                ),
            )
            conn.commit()
    except Exception:
        pass


def execute_outlook_action_action(
    *,
    slug: str,
    arguments_json: str = "{}",
    confirm: bool = False,
    send_channel: str = "kory",
    allow_unlisted: bool = False,
) -> dict[str, Any]:
    from app.integrations.outlook_actions import execute_outlook_action

    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"arguments_json invalid: {exc}"}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "arguments_json must be a JSON object."}
    channel = send_channel.strip().lower()
    if channel not in {"kory", "lexi"}:
        channel = "kory"
    try:
        result = execute_outlook_action(
            slug,
            arguments,
            confirm=confirm,
            send_channel=channel,  # type: ignore[arg-type]
            allow_unlisted=allow_unlisted,
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def accept_calendar_invite_action(event_id: str) -> dict[str, Any]:
    from app.integrations.outlook_actions import accept_calendar_invite

    try:
        return {"ok": True, "result": accept_calendar_invite(event_id)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def decline_calendar_invite_action(event_id: str, comment: str = "") -> dict[str, Any]:
    from app.integrations.outlook_actions import decline_calendar_invite

    try:
        return {"ok": True, "result": decline_calendar_invite(event_id, comment=comment)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def find_meeting_times_action(payload_json: str) -> dict[str, Any]:
    from app.integrations.outlook_actions import find_meeting_times

    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"payload_json invalid: {exc}"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload_json must be a JSON object."}
    try:
        return {"ok": True, "result": find_meeting_times(payload)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def get_thread_context_action(conversation_id: str, exclude_message_id: str = "") -> dict[str, Any]:
    from app.integrations.outlook_thread import fetch_conversation_context

    context = fetch_conversation_context(
        conversation_id,
        exclude_message_id=exclude_message_id or None,
    )
    return {"ok": True, "conversation_id": conversation_id, "context": context}


def remember_kory_fact_action(fact_key: str, fact_value: str) -> dict[str, Any]:
    from app.storage.kory_memory import upsert_fact

    return upsert_fact(fact_key=fact_key, fact_value=fact_value, source="hermes")


def list_kory_memory_action() -> dict[str, Any]:
    from app.storage.kory_memory import list_facts

    facts = list_facts(limit=50)
    return {"ok": True, "count": len(facts), "facts": facts}


# ── Composio Search (web, travel, maps — read-only) ──────────────────────────


def web_search_action(query: str) -> dict[str, Any]:
    from app.integrations.composio_search import web_search

    try:
        return {"ok": True, "result": web_search(query)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def search_flights_action(query: str = "", payload_json: str = "{}") -> dict[str, Any]:
    from app.integrations.composio_search import parse_arguments_json, search_flights

    try:
        args = parse_arguments_json(payload_json)
        if query.strip():
            args.setdefault("query", query.strip())
        if not args.get("query") and not args.get("departure_id"):
            return {"ok": False, "error": "Provide query or departure_id/arrival_id/outbound_date."}
        return {"ok": True, "result": search_flights(args)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def search_hotels_action(payload_json: str) -> dict[str, Any]:
    from app.integrations.composio_search import parse_arguments_json, search_hotels

    try:
        return {"ok": True, "result": search_hotels(parse_arguments_json(payload_json))}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def search_maps_action(query: str) -> dict[str, Any]:
    from app.integrations.composio_search import search_maps

    try:
        return {"ok": True, "result": search_maps(query)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def search_news_action(query: str) -> dict[str, Any]:
    from app.integrations.composio_search import search_news

    try:
        return {"ok": True, "result": search_news(query)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def fetch_url_content_action(url: str, max_characters: int = 8000) -> dict[str, Any]:
    from app.integrations.composio_search import fetch_url_content

    try:
        return {"ok": True, "result": fetch_url_content(url, max_characters=max_characters)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def execute_search_action_action(
    slug: str,
    arguments_json: str = "{}",
    allow_unlisted: bool = False,
) -> dict[str, Any]:
    from app.integrations.composio_search import execute_search_action, parse_arguments_json

    try:
        result = execute_search_action(
            slug,
            parse_arguments_json(arguments_json),
            allow_unlisted=allow_unlisted,
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def get_family_calendar_status_action() -> dict[str, Any]:
    from app.integrations.family_google_calendar import family_calendar_status

    return {"ok": True, **family_calendar_status()}


def research_person_action(
    name: str,
    company: str = "",
    email: str = "",
    include_inbox: bool = True,
) -> dict[str, Any]:
    from app.integrations.person_research import research_person

    try:
        result = research_person(
            name,
            company=company,
            email=email,
            include_inbox=include_inbox,
        )
        return {"ok": True, "research": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


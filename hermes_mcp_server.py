"""MCP bridge: Lexi scheduling assistant tools for Hermes (Hermes-only Teams).

Hermes (Claude OAuth) is the sole Teams front door. This server exposes
calendar, email, hold, queue, and approval actions against Kory's Outlook via Composio.
A background Lexi worker (orchestrator) starts automatically for inbound email.

Run with:
    python hermes_mcp_server.py
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.comms_agent import execute_lexi_approval, get_lexi_pending_queue
from app.assistant import actions as lexi
from scripts.init_lexi_db import init_lexi_db


mcp = FastMCP("ai-scheduling-backend")

_WORKER_BOOTSTRAPPED = False


def _bootstrap_lexi_worker() -> None:
    """Start headless Lexi orchestrator when Hermes loads this MCP server."""
    global _WORKER_BOOTSTRAPPED
    if _WORKER_BOOTSTRAPPED:
        return
    if os.getenv("LEXI_EMBED_WORKER", "true").lower() not in {"1", "true", "yes"}:
        return
    from app.worker.runner import start_lexi_worker

    start_lexi_worker()
    _WORKER_BOOTSTRAPPED = True


class ExecuteLexiApprovalInput(BaseModel):
    model_config = ConfigDict(strict=True)
    proposal_id: int = Field(..., ge=1, description="Lexi proposal id from the pending queue.")
    decision: str = Field(
        ...,
        description="One of: approved, modified, rejected.",
    )
    selected_slot: str = Field(
        default="",
        description=(
            "ISO start time, JSON slot object, or empty string when rejecting. "
            'Example: {"start":"2026-06-03T10:00:00-06:00","end":"2026-06-03T10:30:00-06:00"}'
        ),
    )
    authorized_by: str = Field(
        ...,
        min_length=1,
        description="Azure AD object id or UPN of the approving user.",
    )
    modification_notes: str = Field(
        default="",
        max_length=500,
        description="Optional notes when decision is modified.",
    )


def _ok(data: dict[str, Any]) -> str:
    return json.dumps({"ok": True, **data}, default=str)


def _error(message: str, *, code: str = "tool_error") -> str:
    return json.dumps({"ok": False, "error_code": code, "message": message})


def _wrap(action: str, fn, **kwargs: Any) -> str:
    try:
        result = fn(**kwargs)
        if isinstance(result, dict) and result.get("ok") is False and "error_code" not in result:
            return json.dumps({"ok": False, "error_code": "action_failed", **result}, default=str)
        return _ok({"action": action, "result": result})
    except Exception as exc:
        return _error(f"{action} failed: {type(exc).__name__}: {exc}", code="exception")


# ── Conversational assistant (Hermes drives dialogue; tools execute) ─────────


@mcp.tool()
def lexi_get_inbound_reply_queue() -> str:
    """New inbound emails awaiting Kory's yes/no on whether to draft a reply."""
    return _wrap("lexi_get_inbound_reply_queue", lexi.get_inbound_reply_queue_action)


@mcp.tool()
def lexi_begin_draft_reply(proposal_id: str, voice_mode: str = "kory") -> str:
    """After Kory says yes (or chat draft): draft reply. voice_mode: kory | lexi."""
    try:
        pid = int(proposal_id)
    except ValueError:
        return _error("proposal_id must be an integer string.", code="validation_error")
    return _wrap(
        "lexi_begin_draft_reply",
        lexi.begin_draft_reply_action,
        proposal_id=pid,
        voice_mode=voice_mode.strip() or "kory",
    )


@mcp.tool()
def lexi_decline_inbound_reply(proposal_id: str, reason: str = "") -> str:
    """Kory declined to draft a reply for this inbound email."""
    try:
        pid = int(proposal_id)
    except ValueError:
        return _error("proposal_id must be an integer string.", code="validation_error")
    return _wrap(
        "lexi_decline_inbound_reply",
        lexi.decline_inbound_reply_action,
        proposal_id=pid,
        reason=reason,
    )


@mcp.tool()
def lexi_update_proposal_draft(proposal_id: str, drafted_reply: str) -> str:
    """Apply Kory's edits to a staged draft before send."""
    try:
        pid = int(proposal_id)
    except ValueError:
        return _error("proposal_id must be an integer string.", code="validation_error")
    return _wrap(
        "lexi_update_proposal_draft",
        lexi.update_proposal_draft_action,
        proposal_id=pid,
        drafted_reply=drafted_reply,
    )


@mcp.tool()
def lexi_list_calendars(role: str = "read") -> str:
    """List Outlook calendars by name (read=Kory, write=pilot/production mailbox).

    Use aliases from config/calendars.yaml: team, ifg, master, deals, heidi, etc.
    """
    return _wrap("lexi_list_calendars", lexi.list_calendars, role=role)


@mcp.tool()
def lexi_add_conflict_calendar(calendar_name: str) -> str:
    """Add an Outlook calendar to Lexi's busy/free conflict list (updates config/calendars.yaml).

    Use when Kory says e.g. "I added a new calendar — include it for scheduling."
    Calls lexi_list_calendars first if the exact name is unknown.
    """
    return _wrap(
        "lexi_add_conflict_calendar",
        lexi.add_conflict_calendar,
        calendar_name=calendar_name,
    )


@mcp.tool()
def lexi_preview_scheduling_email() -> str:
    """Show an example scheduling reply with correct Kory formatting (TZ + sign-off)."""
    return _wrap("lexi_preview_scheduling_email", lexi.preview_scheduling_email_example)


@mcp.tool()
def lexi_get_system_status() -> str:
    """Lexi runtime status: dry_run, Composio, pending approval count, worker mode."""
    from app.worker.runner import is_worker_running

    def _status() -> dict[str, Any]:
        base = lexi.get_lexi_system_status()
        base["worker_running"] = is_worker_running()
        base["teams_mode"] = "hermes_only"
        from app.bot.teams_conversation_store import teams_delivery_ready

        base["teams_cards_ready"] = teams_delivery_ready()
        return base

    return _wrap("lexi_get_system_status", _status)


@mcp.tool()
def lexi_register_teams_conversation(
    conversation_id: str,
    service_url: str = "",
) -> str:
    """Save Teams conversation id for proactive approval cards (call after Kory DMs the bot).

    Hermes: call on first message in a session, or when Kory runs /sethome.
    Requires TEAMS_CLIENT_ID + TEAMS_CLIENT_SECRET in project .env for card delivery.
    """
    from app.bot.teams_conversation_store import save_conversation_reference, teams_delivery_ready

    if not conversation_id.strip():
        return _error("conversation_id is required.", code="validation_error")
    record = save_conversation_reference(conversation_id, service_url=service_url)
    return _ok(
        {
            "action": "lexi_register_teams_conversation",
            "saved": record,
            "teams_cards_ready": teams_delivery_ready(),
        }
    )


@mcp.tool()
def lexi_handle_teams_command(text: str, authorized_by: str = "kory") -> str:
    """Execute Lexi Teams commands from Hermes chat (approve, reject, draft, pending).

    Call when Kory sends card button text or short commands, e.g.
    'Send reply to Dan Smith — Project Paint', 'Draft reply to …', 'pending', 'inbound'.
    """
    from app.teams.commands import handle_teams_command

    result = handle_teams_command(text, authorized_by=authorized_by.strip() or "kory")
    return json.dumps({"ok": result.get("ok", False), **result}, default=str)


@mcp.tool()
def lexi_handle_teams_card_submit(payload_json: str, authorized_by: str = "kory") -> str:
    """Process an editable approval Adaptive Card submit (draft edits + Send/Discard/Save).

    payload_json is the card Action.Submit data object (includes drafted_reply input).
    """
    from app.teams.commands import handle_teams_card_submit

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        return _error(f"payload_json invalid: {exc}", code="validation_error")
    if not isinstance(payload, dict):
        return _error("payload_json must be a JSON object.", code="validation_error")
    result = handle_teams_card_submit(payload, authorized_by=authorized_by.strip() or "kory")
    return json.dumps({"ok": result.get("ok", False), **result}, default=str)


@mcp.tool()
def lexi_get_calendar_availability(days: str = "14") -> str:
    """Read Kory's busy blocks across multiple Outlook calendars (default 14 days).

    Merges primary + named calendars from config/calendars.yaml (IFG Team, Master, etc.).
    Call lexi_list_calendars to see which calendars are on the account.
    """
    try:
        window = int(days)
    except ValueError:
        return _error("days must be an integer string, e.g. '14'.", code="validation_error")
    return _wrap("lexi_get_calendar_availability", lexi.get_calendar_availability, days=window)


@mcp.tool()
def lexi_check_time_slot(start_iso: str, end_iso: str) -> str:
    """Check if a start/end ISO interval conflicts with Kory's calendar."""
    return _wrap(
        "lexi_check_time_slot",
        lexi.check_time_slot,
        start_iso=start_iso,
        end_iso=end_iso,
    )


@mcp.tool()
def lexi_place_calendar_hold(
    title: str,
    start_iso: str,
    end_iso: str,
    attendee_email: str = "",
    location: str = "TBD",
    notes: str = "",
    calendar_name: str = "",
    confirm: str = "false",
) -> str:
    """Place a tentative calendar hold (e.g. 'IFG Team', 'Kory Master Calendar (ALL)').

    calendar_name: optional alias — team, ifg, master, deals, heidi, ceo_daily.
    confirm must be 'true' after Kory explicitly approves in Teams chat.
    """
    confirmed = confirm.strip().lower() in {"true", "yes", "1"}
    return _wrap(
        "lexi_place_calendar_hold",
        lexi.place_calendar_hold,
        title=title,
        start_iso=start_iso,
        end_iso=end_iso,
        attendee_email=attendee_email,
        location=location,
        notes=notes,
        calendar_name=calendar_name,
        confirm=confirmed,
    )


@mcp.tool()
def lexi_draft_outbound_email(to_email: str, subject: str, body: str) -> str:
    """Preview an outbound email from Kory's mailbox without sending.

    You (Hermes) should write the body in Kory's voice ('Let's Win,\\nKory').
    After Kory approves the text, call lexi_send_outbound_email with confirm_send=true.
    """
    return _wrap(
        "lexi_draft_outbound_email",
        lexi.draft_outbound_email_preview,
        to_email=to_email,
        subject=subject,
        body=body,
    )


@mcp.tool()
def lexi_send_outbound_email(
    to_email: str,
    subject: str,
    body: str,
    confirm_send: str,
    authorized_by: str = "kory",
    send_channel: str = "lexi",
) -> str:
    """Send outbound email only after Kory explicitly approves (default: lexi@).

    confirm_send must be 'true' or 'yes' (case insensitive).
    """
    confirmed = confirm_send.strip().lower() in {"true", "yes", "1"}
    return _wrap(
        "lexi_send_outbound_email",
        lexi.send_outbound_email_confirmed,
        to_email=to_email,
        subject=subject,
        body=body,
        confirm_send=confirmed,
        authorized_by=authorized_by,
        send_channel=send_channel,
    )


@mcp.tool()
def lexi_create_reservation_reminder(
    meeting_subject: str,
    time_slot: str = "",
    notes: str = "",
    meal: str = "",
    confirm: str = "false",
) -> str:
    """Create a reservation reminder on Kory NON-IFG → Reservation Reminders (Asana).

    Use when Kory asks to book lunch/dinner. confirm must be 'true' after Kory approves in chat.
    """
    from app.integrations.asana_manager import create_booking_reminder_task

    confirmed = confirm.strip().lower() in {"true", "yes", "1"}
    meal_kind = (meal or "dinner").strip().lower()
    if meal_kind not in {"lunch", "dinner"}:
        meal_kind = "dinner"
    body = notes.strip()
    if time_slot.strip():
        body = f"Time slot: {time_slot.strip()}\n{body}".strip()
    return _wrap(
        "lexi_create_reservation_reminder",
        create_booking_reminder_task,
        meal=meal_kind,
        meeting_subject=meeting_subject,
        thread_id="hermes-manual",
        sender="kory",
        body_excerpt=body,
        approved=confirmed,
    )


@mcp.tool()
def lexi_search_inbox(query: str = "", top: str = "10") -> str:
    """Search Kory's Outlook inbox (read-only). Use before drafting replies."""
    try:
        limit = int(top)
    except ValueError:
        return _error("top must be an integer string.", code="validation_error")
    return _wrap("lexi_search_inbox", lexi.search_inbox, query=query, top=limit)


@mcp.tool()
def lexi_get_thread(message_id: str) -> str:
    """Fetch a single Kory inbox message by Outlook message id."""
    return _wrap("lexi_get_thread", lexi.get_email_thread, message_id=message_id)


@mcp.tool()
def lexi_propose_schedule(
    subject: str,
    body: str,
    sender: str = "unknown@example.com",
    thread_id: str = "",
) -> str:
    """Run full inbound triage + scheduler for a scheduling email (unified propose_schedule)."""
    return _wrap(
        "lexi_propose_schedule",
        lexi.run_propose_schedule,
        subject=subject,
        body=body,
        sender=sender,
        thread_id=thread_id,
    )


@mcp.tool()
def lexi_validate_slots(slots_json: str, intent: str = "") -> str:
    """Validate ISO slots against Kory rules (6pm cutoff, weekends, lunch warnings)."""
    try:
        slots = json.loads(slots_json)
    except json.JSONDecodeError as exc:
        return _error(f"slots_json must be a JSON array: {exc}", code="validation_error")
    if not isinstance(slots, list):
        return _error("slots_json must be a JSON array.", code="validation_error")
    return _wrap(
        "lexi_validate_slots",
        lexi.validate_slots_preview,
        slots=slots,
        intent=intent,
    )


@mcp.tool()
def lexi_get_scheduling_session(session_id: str) -> str:
    """Load a multi-turn Hermes scheduling session."""
    return _wrap("lexi_get_scheduling_session", lexi.get_scheduling_session, session_id=session_id)


@mcp.tool()
def lexi_upsert_scheduling_session(
    session_id: str = "",
    channel: str = "hermes",
    context_json: str = "{}",
    status: str = "",
) -> str:
    """Create or update a scheduling session for interrupted Hermes flows."""
    try:
        context = json.loads(context_json or "{}")
    except json.JSONDecodeError as exc:
        return _error(f"context_json invalid: {exc}", code="validation_error")
    if not isinstance(context, dict):
        return _error("context_json must be a JSON object.", code="validation_error")
    kwargs: dict[str, Any] = {
        "session_id": session_id,
        "channel": channel,
        "context": context,
    }
    if status.strip():
        kwargs["status"] = status.strip()
    return _wrap("lexi_upsert_scheduling_session", lexi.upsert_scheduling_session, **kwargs)


@mcp.tool()
def lexi_start_scheduling(
    recipient_email: str,
    subject: str,
    meeting_intent: str,
    duration_minutes: str,
    authorized_by: str = "kory",
    require_ceo_signoff: str = "true",
) -> str:
    """Start outbound scheduling: LLM slots + draft + holds + pending_approval.

    meeting_intent examples: lunch, dinner, coffee, meeting, internal_sync.
    duration_minutes: e.g. '60' for lunch. Set require_ceo_signoff=false only if Kory
    asked to send immediately without sign-off.
    """
    try:
        duration = int(duration_minutes)
    except ValueError:
        return _error("duration_minutes must be an integer string.", code="validation_error")
    from app.safety.approval_gate import immediate_send_allowed, kory_approves_all

    signoff = require_ceo_signoff.strip().lower() in {"true", "yes", "1"}
    if kory_approves_all() and not immediate_send_allowed():
        signoff = True
    return _wrap(
        "lexi_start_scheduling",
        lexi.start_outbound_scheduling,
        recipient_email=recipient_email,
        subject=subject,
        meeting_intent=meeting_intent,
        duration_minutes=duration,
        authorized_by=authorized_by,
        require_ceo_signoff=signoff,
    )


# ── Outlook scheduling actions (Composio SDK behind Lexi — not Composio MCP) ──


@mcp.tool()
def lexi_execute_outlook_action(
    slug: str,
    arguments_json: str = "{}",
    confirm: str = "false",
    send_channel: str = "kory",
) -> str:
    """Run one Outlook Composio slug (allowlisted). confirm=true for writes. Blocked in read-only UAT."""
    confirmed = confirm.strip().lower() in {"true", "yes", "1"}
    return _wrap(
        "lexi_execute_outlook_action",
        lexi.execute_outlook_action_action,
        slug=slug,
        arguments_json=arguments_json,
        confirm=confirmed,
        send_channel=send_channel,
    )


@mcp.tool()
def lexi_accept_calendar_invite(event_id: str) -> str:
    """Accept a calendar invite on Kory's calendar (read-only UAT: dry-run blocked)."""
    return _wrap("lexi_accept_calendar_invite", lexi.accept_calendar_invite_action, event_id=event_id)


@mcp.tool()
def lexi_decline_calendar_invite(event_id: str, comment: str = "") -> str:
    """Decline a calendar invite (blocked in read-only UAT)."""
    return _wrap(
        "lexi_decline_calendar_invite",
        lexi.decline_calendar_invite_action,
        event_id=event_id,
        comment=comment,
    )


@mcp.tool()
def lexi_find_meeting_times(payload_json: str) -> str:
    """Find meeting times via Outlook (read-only). Pass JSON for OUTLOOK_FIND_MEETING_TIMES."""
    return _wrap("lexi_find_meeting_times", lexi.find_meeting_times_action, payload_json=payload_json)


@mcp.tool()
def lexi_get_thread_context(conversation_id: str, exclude_message_id: str = "") -> str:
    """Load prior messages in an Outlook conversation for accurate replies."""
    return _wrap(
        "lexi_get_thread_context",
        lexi.get_thread_context_action,
        conversation_id=conversation_id,
        exclude_message_id=exclude_message_id,
    )


@mcp.tool()
def lexi_remember_kory_fact(fact_key: str, fact_value: str) -> str:
    """Save an explicit long-term preference Kory stated (not chat thread memory)."""
    return _wrap(
        "lexi_remember_kory_fact",
        lexi.remember_kory_fact_action,
        fact_key=fact_key,
        fact_value=fact_value,
    )


@mcp.tool()
def lexi_list_kory_memory() -> str:
    """List saved Kory facts (long-term memory)."""
    return _wrap("lexi_list_kory_memory", lexi.list_kory_memory_action)


# ── Composio Search (web, travel, maps — read-only; uses COMPOSIO_API_KEY) ───


@mcp.tool()
def lexi_web_search(query: str) -> str:
    """Search the web for venues, restaurants, travel info, research. Read-only."""
    return _wrap("lexi_web_search", lexi.web_search_action, query=query)


@mcp.tool()
def lexi_search_flights(query: str = "", payload_json: str = "{}") -> str:
    """Search flights. Use query='Denver to NYC March 15' or JSON with departure_id/arrival_id/outbound_date."""
    return _wrap(
        "lexi_search_flights",
        lexi.search_flights_action,
        query=query,
        payload_json=payload_json,
    )


@mcp.tool()
def lexi_search_hotels(payload_json: str) -> str:
    """Search hotels. JSON: q, check_in_date, check_out_date, adults (required: q)."""
    return _wrap("lexi_search_hotels", lexi.search_hotels_action, payload_json=payload_json)


@mcp.tool()
def lexi_search_maps(query: str) -> str:
    """Google Maps search for venues, restaurants, addresses near a location."""
    return _wrap("lexi_search_maps", lexi.search_maps_action, query=query)


@mcp.tool()
def lexi_search_news(query: str) -> str:
    """News search for context on meetings, companies, events."""
    return _wrap("lexi_search_news", lexi.search_news_action, query=query)


@mcp.tool()
def lexi_fetch_url_content(url: str, max_characters: int = 8000) -> str:
    """Fetch readable text from a public URL (docs, venue pages, articles)."""
    return _wrap(
        "lexi_fetch_url_content",
        lexi.fetch_url_content_action,
        url=url,
        max_characters=max_characters,
    )


@mcp.tool()
def lexi_execute_search_action(slug: str, arguments_json: str = "{}") -> str:
    """Run any allowlisted COMPOSIO_SEARCH_* slug (events, TripAdvisor, shopping, etc.)."""
    return _wrap(
        "lexi_execute_search_action",
        lexi.execute_search_action_action,
        slug=slug,
        arguments_json=arguments_json,
    )


@mcp.tool()
def lexi_get_family_calendar_status() -> str:
    """Check if family Google calendar (Do Not Move blocks) is configured for weekend scheduling."""
    return _wrap("lexi_get_family_calendar_status", lexi.get_family_calendar_status_action)


@mcp.tool()
def lexi_research_person(
    name: str,
    company: str = "",
    email: str = "",
    include_inbox: str = "true",
) -> str:
    """Pre-meeting research: web + news + prior Kory inbox threads about this person."""
    use_inbox = include_inbox.strip().lower() in {"true", "yes", "1"}
    return _wrap(
        "lexi_research_person",
        lexi.research_person_action,
        name=name,
        company=company,
        email=email,
        include_inbox=use_inbox,
    )


# ── Inbound email approval queue (existing Teams / dashboard flow) ────────────


@mcp.tool()
def get_lexi_pending_queue_tool() -> str:
    """Return Lexi proposals awaiting CEO approval (pending_approval) from inbound email."""
    try:
        items = get_lexi_pending_queue()
        payload = [item.to_dict() for item in items]
        return _ok(
            {
                "count": len(payload),
                "queue": payload,
                "formatted_list": [item.teams_summary_line() for item in items],
            }
        )
    except Exception as exc:
        return _error(
            f"Failed to load Lexi pending queue: {type(exc).__name__}: {exc}",
            code="queue_load_failed",
        )


@mcp.tool()
def get_pending_decisions() -> str:
    """Alias for get_lexi_pending_queue_tool."""
    return get_lexi_pending_queue_tool()


@mcp.tool()
def execute_lexi_approval_tool(
    proposal_id: str,
    decision: str,
    selected_slot: str,
    authorized_by: str,
    modification_notes: str = "",
) -> str:
    """Approve, modify-approve, or reject an inbound-email Lexi proposal."""
    try:
        parsed = ExecuteLexiApprovalInput(
            proposal_id=int(proposal_id),
            decision=decision.strip().lower(),
            selected_slot=selected_slot,
            authorized_by=authorized_by.strip(),
            modification_notes=modification_notes,
        )
        if parsed.decision == "rejected":
            slot_value = ""
        else:
            slot_value = parsed.selected_slot.strip()
            pending = next(
                (item for item in get_lexi_pending_queue() if item.proposal_id == parsed.proposal_id),
                None,
            )
            needs_slot = bool(
                pending and (pending.proposed_slots or pending.holds)
            )
            if needs_slot and not slot_value:
                return _error(
                    "selected_slot is required for approved/modified scheduling proposals.",
                    code="validation_error",
                )

        result = execute_lexi_approval(
            proposal_id=parsed.proposal_id,
            decision=parsed.decision,
            selected_slot=slot_value,
            authorized_by=parsed.authorized_by,
            modification_notes=parsed.modification_notes.strip() or None,
            decision_source="hermes_mcp",
        )
        body = result.to_dict()
        body["ok"] = result.ok
        return json.dumps(body, default=str)
    except ValidationError as exc:
        return _error(f"Invalid tool input: {exc}", code="validation_error")
    except ValueError as exc:
        return _error(str(exc), code="value_error")
    except Exception as exc:
        return _error(
            f"Lexi execution failed: {type(exc).__name__}: {exc}",
            code="execution_failed",
        )


@mcp.tool()
def approve_decision(
    decision_id: str,
    selected_slot: str = "",
    authorized_by: str = "kory",
) -> str:
    """Approve a pending inbound proposal (auto-picks first slot if omitted)."""
    slot_value = selected_slot.strip()
    if not slot_value:
        for item in get_lexi_pending_queue():
            if item.proposal_id == int(decision_id):
                if item.proposed_slots:
                    slot_value = json.dumps(item.proposed_slots[0])
                elif not (item.holds or []):
                    slot_value = ""
                break
        if slot_value == "" and any(
            item.proposal_id == int(decision_id) and (item.proposed_slots or item.holds)
            for item in get_lexi_pending_queue()
        ):
            return _error(
                "selected_slot is required when the proposal has scheduling slots.",
                code="validation_error",
            )
    return execute_lexi_approval_tool(
        proposal_id=decision_id,
        decision="approved",
        selected_slot=slot_value,
        authorized_by=authorized_by,
    )


@mcp.tool()
def modify_and_approve_decision(
    decision_id: str,
    new_time: str,
    notes: str,
    authorized_by: str,
) -> str:
    """Modify and approve using new_time as selected slot start."""
    slot_payload = json.dumps({"start": new_time.strip(), "end": new_time.strip()})
    return execute_lexi_approval_tool(
        proposal_id=decision_id,
        decision="modified",
        selected_slot=slot_payload,
        authorized_by=authorized_by,
        modification_notes=notes,
    )


@mcp.tool()
def reject_decision(decision_id: str, reason: str, authorized_by: str = "kory") -> str:
    """Reject a pending inbound proposal."""
    return execute_lexi_approval_tool(
        proposal_id=decision_id,
        decision="rejected",
        selected_slot="",
        authorized_by=authorized_by.strip() or "kory",
        modification_notes=reason,
    )


if __name__ == "__main__":
    init_lexi_db()
    _bootstrap_lexi_worker()
    mcp.run(transport="stdio")

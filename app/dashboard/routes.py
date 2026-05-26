"""Simple web dashboard for reviewing scheduling proposals."""

from __future__ import annotations

from datetime import datetime
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.storage.decision_store import get_decision, list_decisions
from app.workflows.approval import approve_all, approve_calendar, approve_email, reject_decision
from app.workflows.revision import request_proposal_changes, save_manual_reply
from app.workflows.webhooks import process_composio_webhook

from app.lexi import agent as lexi_agent
from app.dashboard.approval_hooks import on_approve, on_reject
from app.lexi.sessions import (
    create_session_id,
    get_recent_messages_for_display,
    list_sessions,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/dashboard/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "pending": list_decisions("pending"),
            "history": list_decisions(),
        },
    )


@router.get("/decisions/{decision_id}", response_class=HTMLResponse)
def decision_detail(request: Request, decision_id: int):
    decision = get_decision(decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    validation = json.loads(decision["validation_result_json"])
    return templates.TemplateResponse(
        request,
        "decision_detail.html",
        {
            "decision": decision,
            "slots": _friendly_slots(json.loads(decision["proposed_slots_json"])),
            "calendar_action": _friendly_calendar_action(
                json.loads(decision["proposed_calendar_action_json"])
            ),
            "engine_reasoning": validation.get("engine_reasoning") or [],
            "activity_log": _friendly_activity_log(decision.get("audit_events", [])),
        },
    )


@router.post("/decisions/{decision_id}/approve")
def approve(decision_id: int):
    if not get_decision(decision_id):
        raise HTTPException(status_code=404, detail="Decision not found")
    d = get_decision(decision_id)
    approve_all(decision_id)
    on_approve(dict(d) if d else {})
    return RedirectResponse(f"/decisions/{decision_id}", status_code=303)


@router.post("/decisions/{decision_id}/approve-email")
def approve_email_route(decision_id: int):
    if not get_decision(decision_id):
        raise HTTPException(status_code=404, detail="Decision not found")
    approve_email(decision_id)
    return RedirectResponse(f"/decisions/{decision_id}", status_code=303)


@router.post("/decisions/{decision_id}/approve-calendar")
def approve_calendar_route(decision_id: int):
    if not get_decision(decision_id):
        raise HTTPException(status_code=404, detail="Decision not found")
    approve_calendar(decision_id)
    return RedirectResponse(f"/decisions/{decision_id}", status_code=303)


@router.post("/decisions/{decision_id}/reject")
def reject(decision_id: int):
    if not get_decision(decision_id):
        raise HTTPException(status_code=404, detail="Decision not found")
    d = get_decision(decision_id)
    reject_decision(decision_id)
    on_reject(dict(d) if d else {})
    return RedirectResponse(f"/decisions/{decision_id}", status_code=303)


@router.post("/decisions/{decision_id}/save-reply")
async def save_reply_route(request: Request, decision_id: int):
    if not get_decision(decision_id):
        raise HTTPException(status_code=404, detail="Decision not found")
    proposed_reply = (await _form_value(request, "proposed_reply")).strip()
    if not proposed_reply:
        raise HTTPException(status_code=400, detail="Proposed reply cannot be empty")
    save_manual_reply(decision_id, proposed_reply)
    return RedirectResponse(f"/decisions/{decision_id}", status_code=303)


@router.post("/decisions/{decision_id}/request-changes")
async def request_changes_route(request: Request, decision_id: int):
    if not get_decision(decision_id):
        raise HTTPException(status_code=404, detail="Decision not found")
    change_request = (await _form_value(request, "change_request")).strip()
    if not change_request:
        raise HTTPException(status_code=400, detail="Change request cannot be empty")
    request_proposal_changes(decision_id, change_request)
    return RedirectResponse(f"/decisions/{decision_id}", status_code=303)


@router.post("/webhooks/composio")
async def composio_webhook(request: Request):
    payload = await request.json()
    decision_id = process_composio_webhook(payload)
    return JSONResponse({"ok": True, "decision_id": decision_id})


# ── Lexi Chat ─────────────────────────────────────────────────────────────────

@router.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request, session: str | None = None):
    if not session:
        session = create_session_id()
        return RedirectResponse(f"/chat?session={session}", status_code=302)
    messages = get_recent_messages_for_display(session)
    sessions = list_sessions(channel="web", limit=10)
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"session_id": session, "messages": messages, "sessions": sessions},
    )


@router.post("/chat/message")
async def chat_message(request: Request):
    body = await request.json()
    user_input = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "").strip()
    if not user_input or not session_id:
        raise HTTPException(status_code=400, detail="message and session_id are required")
    reply = lexi_agent.chat(user_input, session_id, channel="web")
    return JSONResponse({"reply": reply})


@router.post("/webhooks/imessage")
async def imessage_webhook(request: Request):
    """
    Receive inbound iMessages forwarded by the OpenClaw gateway.

    Expected payload shape (OpenClaw JSON-RPC style):
    {
        "from": "+15551234567",         # sender handle
        "text": "message body",
        "chat_id": "...",               # optional iMessage chat GUID
        "session_id": "..."             # optional; we derive one from `from` if absent
    }
    """
    payload = await request.json()
    sender = payload.get("from") or payload.get("sender") or "unknown"
    text = (payload.get("text") or payload.get("body") or "").strip()
    if not text:
        return JSONResponse({"ok": True, "skipped": "empty message"})

    # Use a stable session per sender so conversation history carries over
    session_id = payload.get("session_id") or f"imsg-{sender.replace('+', '').replace(' ', '')}"
    reply = lexi_agent.chat(text, session_id, channel="imessage")
    return JSONResponse({"ok": True, "reply": reply, "session_id": session_id})


async def _form_value(request: Request, key: str) -> str:
    body = (await request.body()).decode()
    values = parse_qs(body)
    return values.get(key, [""])[0]


def _friendly_calendar_action(action: dict) -> dict[str, str]:
    action_type = action.get("type")
    if action_type == "create_holds":
        holds = action.get("holds") or []
        hold_lines = [
            f"{hold.get('title')}: {_friendly_time_range(hold.get('start'), hold.get('end'))}"
            for hold in holds
        ]
        return {
            "summary": (
                f"After approval, the agent will place {len(holds)} calendar hold(s) "
                "so offered times are not double-booked."
            ),
            "title": "Calendar holds",
            "time": "\n".join(hold_lines) if hold_lines else "No holds listed",
            "attendees": ", ".join(
                sorted({email for hold in holds for email in hold.get("attendees") or []})
            )
            or "None",
            "location": holds[0].get("location") if holds else "None",
        }

    if action_type != "create_event":
        return {
            "summary": "No calendar event is currently proposed.",
            "title": "None",
            "time": "Not scheduled",
            "attendees": "None",
            "location": "None",
        }

    return {
        "summary": "The agent is proposing to add this event to Outlook after approval.",
        "title": action.get("title") or "Meeting with Kory",
        "time": _friendly_time_range(action.get("start"), action.get("end")),
        "attendees": ", ".join(action.get("attendees") or []) or "No attendees listed",
        "location": action.get("location") or "Teams",
    }


def _friendly_slots(slots: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "time": _friendly_time_range(slot.get("start"), slot.get("end")),
            "reason": slot.get("reason") or "Suggested by the agent.",
        }
        for slot in slots
    ]


def _friendly_activity_log(events: list[dict]) -> list[dict[str, str]]:
    return [_friendly_audit_event(event) for event in events]


def _friendly_audit_event(event: dict) -> dict[str, str]:
    event_type = event.get("event_type") or ""
    title_map = {
        "workflow.proposal_created": "Rules engine prepared a proposal",
        "execution.calendar_hold_created": "Calendar hold created",
        "execution.calendar_holds_completed": "All calendar holds created",
        "workflow.duplicate_skipped": "Duplicate email skipped",
        "proposal.safety_corrected": "Calendar-safe times updated",
        "proposal.reply_edited": "Reply edited",
        "proposal.revised": "Agent revised the proposal",
        "approval.approved": "Approval recorded",
        "approval.rejected": "Request rejected",
        "execution.calendar_conflict_check": "Calendar checked for conflicts",
        "execution.calendar_created": "Calendar event created",
        "execution.calendar_completed": "Calendar action completed",
        "execution.calendar_failed": "Calendar action blocked",
        "execution.email_draft_created": "Email draft created",
        "execution.email_sent": "Email sent",
        "execution.email_completed": "Email action completed",
        "execution.email_failed": "Email action blocked",
    }
    return {
        "title": title_map.get(event_type, "Activity recorded"),
        "time": event.get("created_at") or "",
        "message": _friendly_audit_message(event),
    }


def _friendly_audit_message(event: dict) -> str:
    message = event.get("message") or "The agent recorded an update."
    metadata = _metadata(event)
    event_type = event.get("event_type") or ""

    if event_type == "execution.calendar_conflict_check":
        conflict = metadata.get("conflict")
        if conflict:
            return "The agent found a calendar conflict, so it did not book the meeting."
        return "The agent checked Outlook and did not find a conflict."

    if event_type == "execution.calendar_created":
        return "The approved meeting was added to Outlook."

    if event_type == "execution.email_sent":
        return "The approved reply was sent through Outlook."

    if event_type == "proposal.revised":
        change_request = metadata.get("change_request")
        if change_request:
            return f"The agent updated the proposal based on your request: {change_request}"

    return message


def _metadata(event: dict) -> dict:
    try:
        return json.loads(event.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        return {}


def _friendly_time_range(start: str | None, end: str | None) -> str:
    if not start or not end:
        return "Time not selected"
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return f"{start} to {end}"

    same_day = start_dt.date() == end_dt.date()
    start_text = start_dt.strftime("%A, %B %-d at %-I:%M %p")
    end_text = end_dt.strftime("%-I:%M %p") if same_day else end_dt.strftime("%A, %B %-d at %-I:%M %p")
    return f"{start_text} to {end_text} Mountain Time"

@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    from app.config import settings as _s
    from app.integrations.composio_client import get_composio, ComposioNotConfiguredError

    outlook_connected = False
    outlook_connect_url = None
    composio_error = None

    try:
        composio = get_composio()
        accounts = composio.connected_accounts.list(limit=20)
        items = getattr(accounts, "items", accounts) or []
        outlook_connected = any(
            (getattr(a, "toolkit_slug", "") or "").upper() == "OUTLOOK"
            for a in items
        )
        if not outlook_connected and _s.composio_outlook_auth_config_id:
            try:
                conn_req = composio.connected_accounts.link(
                    user_id=_s.composio_user_id,
                    auth_config_id=_s.composio_outlook_auth_config_id,
                )
                outlook_connect_url = conn_req.redirect_url
            except Exception:
                pass
    except ComposioNotConfiguredError as exc:
        composio_error = str(exc)
    except Exception as exc:
        composio_error = str(exc)

    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "outlook_connected": outlook_connected,
            "outlook_connect_url": outlook_connect_url,
            "composio_error": composio_error,
            "llm_model": _s.llm_model,
            "llm_base_url": _s.llm_base_url,
        },
    )

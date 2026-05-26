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
    approve_all(decision_id)
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
    reject_decision(decision_id)
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

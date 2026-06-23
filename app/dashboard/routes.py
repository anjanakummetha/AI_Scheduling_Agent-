"""Lexi dashboard routes backed by data/lexi.db."""

from __future__ import annotations

from datetime import datetime
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.agents.comms_agent import execute_lexi_approval
from app.storage.lexi_store import (
    get_proposal,
    list_audit_log_for_proposal,
    list_proposals,
    update_drafted_reply,
)
router = APIRouter()
templates = Jinja2Templates(directory="app/dashboard/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "pending": list_proposals("pending_approval"),
            "history": list_proposals(),
        },
    )


@router.get("/decisions/{proposal_id}", response_class=HTMLResponse)
def proposal_detail(request: Request, proposal_id: int):
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    audit_rows = list_audit_log_for_proposal(proposal_id)
    return templates.TemplateResponse(
        request,
        "decision_detail.html",
        {
            "decision": proposal,
            "slots": _friendly_slots(proposal.get("proposed_slots") or []),
            "holds": proposal.get("holds") or [],
            "engine_reasoning": _rule_reasoning_lines(proposal.get("rule_reasoning")),
            "activity_log": _friendly_activity_log(audit_rows),
        },
    )


@router.post("/decisions/{proposal_id}/approve")
def approve(proposal_id: int):
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    selected_slot = _default_slot(proposal)
    execute_lexi_approval(
        proposal_id=proposal_id,
        decision="approved",
        selected_slot=selected_slot,
        authorized_by="dashboard_user",
        decision_source="dashboard",
    )
    return RedirectResponse(f"/decisions/{proposal_id}", status_code=303)


@router.post("/decisions/{proposal_id}/reject")
def reject(proposal_id: int):
    if not get_proposal(proposal_id):
        raise HTTPException(status_code=404, detail="Proposal not found")
    execute_lexi_approval(
        proposal_id=proposal_id,
        decision="rejected",
        selected_slot="",
        authorized_by="dashboard_user",
        decision_source="dashboard",
    )
    return RedirectResponse(f"/decisions/{proposal_id}", status_code=303)


@router.post("/decisions/{proposal_id}/save-reply")
async def save_reply_route(request: Request, proposal_id: int):
    if not get_proposal(proposal_id):
        raise HTTPException(status_code=404, detail="Proposal not found")
    drafted_reply = (await _form_value(request, "proposed_reply")).strip()
    if not drafted_reply:
        raise HTTPException(status_code=400, detail="Drafted reply cannot be empty")
    update_drafted_reply(proposal_id, drafted_reply)
    return RedirectResponse(f"/decisions/{proposal_id}", status_code=303)


async def _form_value(request: Request, key: str) -> str:
    body = (await request.body()).decode()
    values = parse_qs(body)
    return values.get(key, [""])[0]


def _default_slot(proposal: dict) -> str:
    holds = proposal.get("holds") or []
    if holds:
        return str(holds[0].get("slot_start") or "")
    slots = proposal.get("proposed_slots") or []
    if slots:
        return str(slots[0].get("start") or "")
    return ""


def _rule_reasoning_lines(rule_reasoning: dict | None) -> list[str]:
    if not rule_reasoning:
        return []
    lines: list[str] = []
    for rule in rule_reasoning.get("rules_applied") or []:
        if isinstance(rule, dict):
            lines.append(
                f"{rule.get('rule', 'rule')}: {rule.get('match', '')} → {rule.get('effect', '')}"
            )
    llm = rule_reasoning.get("llm")
    if isinstance(llm, dict) and llm.get("justification"):
        lines.append(str(llm["justification"]))
    return lines


def _friendly_slots(slots: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "time": _friendly_time_range(slot.get("start"), slot.get("end")),
            "reason": slot.get("reason") or "Suggested by Lexi.",
        }
        for slot in slots
    ]


def _friendly_activity_log(events: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "title": event.get("step_name") or "Activity",
            "time": event.get("timestamp") or "",
            "message": event.get("message") or "",
            "level": event.get("log_level") or "INFO",
        }
        for event in events
    ]


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

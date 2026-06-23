"""Lexi Phase 4: Teams-facing approval queue and Composio execution dispatch."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import sqlite3
import traceback
from typing import Any, Literal

from app.integrations.outlook_calendar import create_calendar_event, delete_calendar_event
from app.integrations.outlook_email import (
    create_draft_reply,
    send_draft,
    send_pilot_reply_for_proposal,
)
from app.config import settings
from app.storage.lexi_db import get_lexi_connection
from app.utils.teams_cards import generate_approval_card

PENDING_APPROVAL = "pending_approval"
STATUS_EXECUTED = "executed"
STATUS_REJECTED = "rejected"

DecisionType = Literal["approved", "modified", "rejected"]
MOCK_HOLD_PREFIX = "hold-pending-"


@dataclass(frozen=True)
class LexiQueueItem:
    proposal_id: int
    thread_id: str
    subject: str | None
    sender: str | None
    raw_body: str | None
    intent_classification: str | None
    priority_tier: str | None
    proposed_slots: list[dict[str, Any]]
    drafted_reply: str | None
    confidence_score: float | None
    justification: str | None
    voice_mode: str | None
    holds: list[dict[str, Any]]
    approval_card: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def teams_summary_line(self) -> str:
        slot_preview = ""
        if self.proposed_slots:
            first = self.proposed_slots[0]
            slot_preview = f" | first slot {first.get('start', '?')}"
        return (
            f"[{self.proposal_id}] {self.subject or '(no subject)'} | "
            f"from {self.sender or 'unknown'} | {self.intent_classification or 'unknown'} | "
            f"priority={self.priority_tier or 'medium'}{slot_preview}"
        )


@dataclass
class ExecutionResult:
    ok: bool
    proposal_id: int
    status: str
    decision: str
    calendar_event_id: str | None = None
    email_sent: bool = False
    holds_released: int = 0
    holds_confirmed: int = 0
    errors: list[str] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_lexi_pending_queue() -> list[LexiQueueItem]:
    """Return pending_approval proposals joined with source email thread metadata."""
    with get_lexi_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id AS proposal_id,
                p.thread_id,
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
            WHERE p.status = ?
            ORDER BY
                CASE p.priority_tier
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                p.id ASC
            """,
            (PENDING_APPROVAL,),
        ).fetchall()

        items: list[LexiQueueItem] = []
        for row in rows:
            proposal_id = int(row["proposal_id"])
            holds = _fetch_holds(conn, proposal_id)
            proposal_record = {
                "id": proposal_id,
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
            approval_card = generate_approval_card(proposal_record, email_record, holds)
            items.append(
                LexiQueueItem(
                    proposal_id=proposal_id,
                    thread_id=str(row["thread_id"]),
                    subject=row["subject"],
                    sender=row["sender"],
                    raw_body=row["raw_body"],
                    intent_classification=row["intent_classification"],
                    priority_tier=row["priority_tier"],
                    proposed_slots=proposal_record["proposed_slots"],
                    drafted_reply=row["drafted_reply"],
                    confidence_score=row["confidence_score"],
                    justification=row["justification"],
                    voice_mode=row["voice_mode"],
                    holds=holds,
                    approval_card=approval_card,
                )
            )
        return items


def execute_lexi_approval(
    proposal_id: int,
    decision: str,
    selected_slot: str,
    authorized_by: str,
    *,
    decision_source: str = "teams_card",
    modification_notes: str | None = None,
) -> ExecutionResult:
    """Record approval decision and dispatch calendar/email execution via Composio."""
    normalized_decision = decision.strip().lower()
    if normalized_decision not in {"approved", "modified", "rejected"}:
        raise ValueError("decision must be one of: approved, modified, rejected")

    result = ExecutionResult(
        ok=False,
        proposal_id=proposal_id,
        status=PENDING_APPROVAL,
        decision=normalized_decision,
        errors=[],
        warnings=[],
    )

    with get_lexi_connection() as conn:
        conn.execute("SAVEPOINT lexi_execution")
        try:
            proposal = _fetch_proposal_bundle(conn, proposal_id)
            if not proposal:
                raise ValueError(f"Proposal {proposal_id} was not found.")
            if proposal["status"] != PENDING_APPROVAL:
                raise ValueError(
                    f"Proposal {proposal_id} is not pending approval (status={proposal['status']})."
                )

            _insert_approval(
                conn,
                proposal_id=proposal_id,
                decision=normalized_decision,
                decision_source=decision_source,
                authorized_by=authorized_by,
                modification_notes=modification_notes,
            )

            if normalized_decision == "rejected":
                released = _release_all_holds(conn, proposal_id, result)
                _set_proposal_status(conn, proposal_id, STATUS_REJECTED)
                result.holds_released = released
                result.status = STATUS_REJECTED
                result.ok = True
            else:
                slots = proposal.get("proposed_slots") or []
                holds = proposal.get("holds") or []
                confirmed_id: str | None = None
                selected: dict[str, str] = {}

                if slots or holds:
                    selected = _resolve_selected_slot(proposal, selected_slot)
                    confirmed_id, hold_errors = _confirm_selected_hold(
                        conn,
                        proposal_id=proposal_id,
                        proposal=proposal,
                        selected_slot=selected,
                        result=result,
                    )
                    result.errors.extend(hold_errors)
                    result.calendar_event_id = confirmed_id
                    result.holds_confirmed = 1 if confirmed_id else 0

                    released = _release_unused_holds(
                        conn,
                        proposal_id,
                        keep_event_id=confirmed_id,
                        result=result,
                    )
                    result.holds_released = released

                else:
                    released = _release_unused_holds(
                        conn,
                        proposal_id,
                        keep_event_id=None,
                        result=result,
                    )
                    result.holds_released = released

                email_ok, email_error = _send_drafted_reply(proposal, result)
                result.email_sent = email_ok
                if email_error:
                    result.errors.append(email_error)

                if email_ok:
                    time_slot = ""
                    if selected:
                        time_slot = f"{selected.get('start', '')} → {selected.get('end', '')}"
                    _dispatch_asana_reservation_reminder_if_needed(
                        conn,
                        proposal_id=proposal_id,
                        proposal=proposal,
                        time_slot=time_slot,
                        result=result,
                    )

                _set_proposal_status(conn, proposal_id, STATUS_EXECUTED)
                result.status = STATUS_EXECUTED
                result.ok = result.holds_confirmed > 0 or bool(confirmed_id)
                if email_ok:
                    result.ok = True
                if result.errors and not result.ok:
                    result.warnings = list(result.errors)
                    result.ok = result.holds_confirmed > 0

            _insert_audit_log(
                conn,
                step_name="execution_dispatch",
                reference_id=str(proposal_id),
                log_level="INFO" if result.ok else "ERROR",
                message=(
                    f"Execution dispatch completed for proposal {proposal_id} "
                    f"with decision={normalized_decision}."
                ),
                payload={
                    "proposal_id": proposal_id,
                    "decision": normalized_decision,
                    "decision_source": decision_source,
                    "authorized_by": authorized_by,
                    "selected_slot": selected_slot,
                    "execution": result.to_dict(),
                },
            )
            conn.execute("RELEASE SAVEPOINT lexi_execution")
            conn.commit()
            if result.ok or normalized_decision == "rejected":
                from app.storage.learning_log import record_approval_outcome

                record_approval_outcome(
                    proposal_id=proposal_id,
                    decision=normalized_decision,
                    intent=proposal.get("intent_classification"),
                    voice_mode=proposal.get("voice_mode"),
                    send_channel=proposal.get("send_channel"),
                    drafted_reply=str(proposal.get("drafted_reply") or ""),
                    selected_slot=selected_slot,
                    modification_notes=modification_notes,
                )
            return result
        except Exception as exc:
            conn.execute("ROLLBACK TO SAVEPOINT lexi_execution")
            conn.execute("RELEASE SAVEPOINT lexi_execution")
            tb = traceback.format_exc()
            _insert_audit_log(
                conn,
                step_name="execution_dispatch",
                reference_id=str(proposal_id),
                log_level="ERROR",
                message=f"Execution dispatch failed for proposal {proposal_id}.",
                payload={
                    "proposal_id": proposal_id,
                    "decision": normalized_decision,
                    "authorized_by": authorized_by,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": tb,
                },
            )
            conn.commit()
            result.errors = (result.errors or []) + [f"{type(exc).__name__}: {exc}"]
            result.ok = False
            return result


def _fetch_holds(conn: sqlite3.Connection, proposal_id: int) -> list[dict[str, Any]]:
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


def _fetch_proposal_bundle(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            p.id,
            p.thread_id,
            p.status,
            p.intent_classification,
            p.priority_tier,
            p.proposed_slots,
            p.drafted_reply,
            p.confidence_score,
            p.justification,
            p.voice_mode,
            p.send_channel,
            p.is_delegation,
            e.subject,
            e.sender,
            e.raw_body
        FROM proposals AS p
        INNER JOIN email_threads AS e ON e.thread_id = p.thread_id
        WHERE p.id = ?
        """,
        (proposal_id,),
    ).fetchone()
    if not row:
        return None
    bundle = dict(row)
    bundle["proposed_slots"] = _parse_json_list(bundle.get("proposed_slots"))
    bundle["holds"] = _fetch_holds(conn, proposal_id)
    return bundle


def _insert_approval(
    conn: sqlite3.Connection,
    *,
    proposal_id: int,
    decision: str,
    decision_source: str,
    authorized_by: str,
    modification_notes: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO approvals (
            proposal_id, decision, decision_source, authorized_by, modification_notes
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            proposal_id,
            decision,
            decision_source,
            authorized_by,
            modification_notes,
        ),
    )


def _set_proposal_status(conn: sqlite3.Connection, proposal_id: int, status: str) -> None:
    conn.execute(
        """
        UPDATE proposals
        SET status = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, proposal_id),
    )


def _resolve_selected_slot(proposal: dict[str, Any], selected_slot: str) -> dict[str, str]:
    selected_slot = (selected_slot or "").strip()
    if not selected_slot:
        raise ValueError("selected_slot is required for approved/modified decisions.")

    try:
        parsed = json.loads(selected_slot)
        if isinstance(parsed, dict) and parsed.get("start"):
            start_norm = _normalize_slot_token(str(parsed["start"]))
            for slot in proposal.get("proposed_slots") or []:
                if _normalize_slot_token(str(slot.get("start", ""))) == start_norm:
                    return {"start": str(slot["start"]), "end": str(slot["end"])}
            for hold in proposal.get("holds") or []:
                if _normalize_slot_token(str(hold.get("slot_start", ""))) == start_norm:
                    return {
                        "start": str(hold["slot_start"]),
                        "end": str(hold["slot_end"]),
                    }
            if parsed.get("end"):
                return {"start": str(parsed["start"]), "end": str(parsed["end"])}
    except json.JSONDecodeError:
        pass

    normalized = _normalize_slot_token(selected_slot)
    for slot in proposal.get("proposed_slots") or []:
        if _normalize_slot_token(slot.get("start", "")) == normalized:
            return {"start": str(slot["start"]), "end": str(slot["end"])}

    for hold in proposal.get("holds") or []:
        if _normalize_slot_token(str(hold.get("slot_start", ""))) == normalized:
            return {
                "start": str(hold["slot_start"]),
                "end": str(hold["slot_end"]),
            }

    if "start" in selected_slot and "end" in selected_slot:
        match = re.search(
            r'"start"\s*:\s*"([^"]+)".*?"end"\s*:\s*"([^"]+)"',
            selected_slot,
            flags=re.DOTALL,
        )
        if match:
            return {"start": match.group(1), "end": match.group(2)}

    raise ValueError(f"Could not resolve selected_slot against proposal {proposal['id']}.")


def _normalize_slot_token(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _confirm_selected_hold(
    conn: sqlite3.Connection,
    *,
    proposal_id: int,
    proposal: dict[str, Any],
    selected_slot: dict[str, str],
    result: ExecutionResult,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    matched_hold = _match_hold_for_slot(proposal.get("holds") or [], selected_slot)
    attendee = _extract_email(proposal.get("sender"))

    if matched_hold:
        event_id = _confirm_hold_event(
            hold=matched_hold,
            subject=proposal.get("subject"),
            sender_display=proposal.get("sender"),
            attendee_email=attendee,
            result=result,
        )
        if event_id and _is_mock_event_id(str(matched_hold.get("event_id", ""))):
            conn.execute(
                "UPDATE holds SET event_id = ? WHERE id = ?",
                (event_id, matched_hold["id"]),
            )
        return event_id, errors

    action = {
        "start": selected_slot["start"],
        "end": selected_slot["end"],
        "title": _confirmed_event_title(proposal.get("subject"), proposal.get("sender")),
        "location": "Teams",
        "attendees": [attendee] if attendee else [],
    }
    try:
        event_id, _log_id = create_calendar_event(action)
        if not event_id:
            errors.append("Composio did not return a confirmed calendar event id.")
            result.warnings = (result.warnings or []) + [
                "Calendar confirmation returned no event id; marked locally only."
            ]
        return event_id, errors
    except Exception as exc:
        errors.append(f"Calendar confirmation failed: {type(exc).__name__}: {exc}")
        _insert_audit_log(
            conn,
            step_name="execution_dispatch",
            reference_id=str(proposal_id),
            log_level="WARNING",
            message="Calendar confirmation failed; continuing with email dispatch.",
            payload={"proposal_id": proposal_id, "error": str(exc)},
        )
        return None, errors


def _confirm_hold_event(
    *,
    hold: dict[str, Any],
    subject: str | None,
    sender_display: str | None,
    attendee_email: str | None,
    result: ExecutionResult,
) -> str | None:
    event_id = str(hold.get("event_id") or "")
    slot_start = str(hold.get("slot_start") or "")
    slot_end = str(hold.get("slot_end") or "")

    if _is_mock_event_id(event_id):
        action = {
            "start": slot_start,
            "end": slot_end,
            "title": _confirmed_event_title(subject, sender_display),
            "location": "Teams",
            "attendees": [attendee_email] if attendee_email else [],
        }
        try:
            confirmed_id, _ = create_calendar_event(action)
            return confirmed_id
        except Exception as exc:
            result.warnings = (result.warnings or []) + [
                f"Mock hold could not be promoted to Outlook event: {exc}"
            ]
            return None

    try:
        delete_calendar_event(event_id)
    except Exception as exc:
        result.warnings = (result.warnings or []) + [
            f"Could not delete tentative hold {event_id}: {exc}"
        ]

    action = {
        "start": slot_start,
        "end": slot_end,
        "title": _confirmed_event_title(subject, sender_display),
        "location": "Teams",
        "attendees": [attendee_email] if attendee_email else [],
    }
    try:
        confirmed_id, _ = create_calendar_event(action)
        return confirmed_id or event_id
    except Exception as exc:
        result.warnings = (result.warnings or []) + [
            f"Hold conversion failed; retaining reference {event_id}: {exc}"
        ]
        return event_id


def _release_all_holds(
    conn: sqlite3.Connection,
    proposal_id: int,
    result: ExecutionResult,
) -> int:
    holds = _fetch_holds(conn, proposal_id)
    released = 0
    for hold in holds:
        if _release_hold(conn, hold, result):
            released += 1
    return released


def _release_unused_holds(
    conn: sqlite3.Connection,
    proposal_id: int,
    *,
    keep_event_id: str | None,
    result: ExecutionResult,
) -> int:
    holds = _fetch_holds(conn, proposal_id)
    released = 0
    for hold in holds:
        event_id = str(hold.get("event_id") or "")
        if keep_event_id and event_id == keep_event_id:
            continue
        if _release_hold(conn, hold, result):
            released += 1
    return released


def _release_hold(
    conn: sqlite3.Connection,
    hold: dict[str, Any],
    result: ExecutionResult,
) -> bool:
    event_id = str(hold.get("event_id") or "")
    if event_id and not _is_mock_event_id(event_id):
        try:
            delete_calendar_event(event_id)
        except Exception as exc:
            result.warnings = (result.warnings or []) + [
                f"Failed to delete Outlook hold {event_id}: {exc}"
            ]
    conn.execute("DELETE FROM holds WHERE id = ?", (hold["id"],))
    return True


def _asana_booking_reminder_exists(conn: sqlite3.Connection, thread_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM audit_log
        WHERE step_name = 'asana_booking_reminder' AND reference_id = ?
        LIMIT 1
        """,
        (thread_id,),
    ).fetchone()
    return row is not None


def _dispatch_asana_reservation_reminder_if_needed(
    conn: sqlite3.Connection,
    *,
    proposal_id: int,
    proposal: dict[str, Any],
    time_slot: str,
    result: ExecutionResult,
) -> None:
    """After a sent email: task on Kory NON-IFG → Reservation Reminders when booking needed."""
    from app.config import settings

    if not settings.asana_enabled:
        return

    intent = str(proposal.get("intent_classification") or "").lower()
    thread_id = str(proposal.get("thread_id") or "")
    if thread_id and _asana_booking_reminder_exists(conn, thread_id):
        return

    meeting_subject = str(proposal.get("subject") or "Meeting")
    participants = str(proposal.get("sender") or "unknown")
    drafted_reply = str(proposal.get("drafted_reply") or "")
    raw_body = str(proposal.get("raw_body") or "")

    try:
        from app.integrations.asana_manager import dispatch_reservation_reminder_for_proposal

        asana_result = dispatch_reservation_reminder_for_proposal(
            intent=intent,
            meeting_subject=meeting_subject,
            thread_id=thread_id or str(proposal_id),
            sender=participants,
            drafted_reply=drafted_reply,
            raw_body=raw_body,
            time_slot=time_slot,
            approved=True,
        )
        if not asana_result:
            return

        log_level = "INFO" if asana_result.get("ok") else "ERROR"
        _insert_audit_log(
            conn,
            step_name="asana_task_dispatch",
            reference_id=str(proposal_id),
            log_level=log_level,
            message=(
                f"Asana reservation reminder {'created' if asana_result.get('ok') else 'failed'} "
                f"after send (intent={intent})."
            ),
            payload={
                "proposal_id": proposal_id,
                "intent_classification": intent,
                "asana_result": asana_result,
                "calendar_event_id": result.calendar_event_id,
            },
        )
        if thread_id:
            _insert_audit_log(
                conn,
                step_name="asana_booking_reminder",
                reference_id=thread_id,
                log_level=log_level,
                message="Asana reservation reminder linked to thread.",
                payload={"proposal_id": proposal_id, "asana_result": asana_result},
            )
        if not asana_result.get("ok"):
            result.warnings = (result.warnings or []) + [
                f"Asana task not created: {asana_result.get('error') or 'unknown error'}"
            ]
    except Exception as exc:
        _insert_audit_log(
            conn,
            step_name="asana_task_dispatch",
            reference_id=str(proposal_id),
            log_level="ERROR",
            message="Asana reservation dispatch raised an exception.",
            payload={
                "proposal_id": proposal_id,
                "intent_classification": intent,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "calendar_event_id": result.calendar_event_id,
            },
        )
        result.warnings = (result.warnings or []) + [
            f"Asana dispatch failed (email send preserved): {type(exc).__name__}: {exc}"
        ]


def _send_drafted_reply(
    proposal: dict[str, Any],
    result: ExecutionResult,
) -> tuple[bool, str | None]:
    body = (proposal.get("drafted_reply") or "").strip()
    if not body:
        return False, "No drafted_reply available on proposal."

    thread_id = str(proposal.get("thread_id") or "").strip()
    if not thread_id or thread_id.startswith("demo-"):
        result.warnings = (result.warnings or []) + [
            "Email dispatch skipped: thread_id is missing or demo-only."
        ]
        return False, None

    try:
        intended = _extract_email(proposal.get("sender"))
        send_channel = str(proposal.get("send_channel") or "kory").strip().lower()
        if send_channel not in {"kory", "lexi"}:
            send_channel = "kory"
        if settings.sandbox_email_loopback and settings.lexi_write_mode == "sandbox":
            message_id, _log = send_pilot_reply_for_proposal(
                original_subject=proposal.get("subject"),
                body=body,
                intended_recipient=intended,
                send_channel=send_channel,  # type: ignore[arg-type]
            )
            return bool(message_id), None

        if intended and not settings.sandbox_email_loopback:
            message_id, _log = send_pilot_reply_for_proposal(
                original_subject=proposal.get("subject"),
                body=body,
                intended_recipient=intended,
                send_channel=send_channel,  # type: ignore[arg-type]
            )
            return bool(message_id), None

        if send_channel == "lexi":
            message_id, _log = send_pilot_reply_for_proposal(
                original_subject=proposal.get("subject"),
                body=body,
                intended_recipient=intended,
                send_channel="lexi",
            )
            return bool(message_id), None

        draft_id, _draft_log = create_draft_reply(thread_id, body)
        if not draft_id:
            return False, "Composio created no draft message id for reply."
        send_draft(draft_id)
        return True, None
    except Exception as exc:
        return False, f"Email dispatch failed: {type(exc).__name__}: {exc}"


def _match_hold_for_slot(
    holds: list[dict[str, Any]],
    selected_slot: dict[str, str],
) -> dict[str, Any] | None:
    target_start = _normalize_slot_token(selected_slot["start"])
    target_end = _normalize_slot_token(selected_slot["end"])
    for hold in holds:
        if (
            _normalize_slot_token(str(hold.get("slot_start", ""))) == target_start
            and _normalize_slot_token(str(hold.get("slot_end", ""))) == target_end
        ):
            return hold
    return None


def _is_mock_event_id(event_id: str) -> bool:
    return event_id.startswith(MOCK_HOLD_PREFIX)


def _confirmed_event_title(subject: str | None, sender: str | None) -> str:
    if subject:
        return f"Confirmed: {subject}"
    if sender:
        return f"Meeting with {_sender_display(sender)}"
    return "Confirmed meeting"


def _sender_display(sender: str | None) -> str:
    if not sender:
        return "Guest"
    if "@" in sender:
        local = sender.split("@", 1)[0]
        return local.replace(".", " ").replace("_", " ").title()
    return sender


def _extract_email(sender: str | None) -> str | None:
    if not sender:
        return None
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", sender)
    return match.group(0).lower() if match else (sender if "@" in sender else None)


def _parse_json_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _insert_audit_log(
    conn: sqlite3.Connection,
    *,
    step_name: str,
    reference_id: str,
    log_level: str,
    message: str,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (step_name, reference_id, log_level, message, payload)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            step_name,
            reference_id,
            log_level,
            message,
            json.dumps(payload, default=str),
        ),
    )


# ---------------------------------------------------------------------------
# Hermes MCP server bridge (apply these tools in hermes_mcp_server.py)
# ---------------------------------------------------------------------------
#
# from app.agents.comms_agent import execute_lexi_approval, get_lexi_pending_queue
#
# @mcp.tool()
# def get_lexi_pending_queue_tool() -> str:
#     items = get_lexi_pending_queue()
#     payload = [item.to_dict() for item in items]
#     return json.dumps({
#         "ok": True,
#         "count": len(payload),
#         "queue": payload,
#         "formatted_list": [item.teams_summary_line() for item in items],
#     })
#
# @mcp.tool()
# def execute_lexi_approval_tool(
#     proposal_id: str,
#     decision: str,
#     selected_slot: str,
#     authorized_by: str,
#     modification_notes: str = "",
# ) -> str:
#     result = execute_lexi_approval(
#         proposal_id=int(proposal_id),
#         decision=decision,
#         selected_slot=selected_slot,
#         authorized_by=authorized_by,
#         modification_notes=modification_notes or None,
#     )
#     return json.dumps({"ok": result.ok, **result.to_dict()}, default=str)

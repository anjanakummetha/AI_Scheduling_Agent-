"""Asana task creation for Lexi venue / meal booking reminders."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, Literal

from app.config import ASANA_BOARD_NAME, ASANA_PARENT_PROJECT_NAME, settings
from app.integrations.composio_client import ComposioNotConfiguredError, execute_asana_tool

ASANA_CREATE_TOOL = "ASANA_CREATE_A_TASK"
BOOKING_TASK_PREFIX = "Lexi Booking:"
VENUE_TASK_PREFIX = "Needs Reservation:"

MealKind = Literal["lunch", "dinner"]

VENUE_RESERVATION_INTENTS = frozenset({"lunch_request", "dinner_request", "happy_hour"})
INTENT_TO_MEAL: dict[str, MealKind] = {
    "lunch_request": "lunch",
    "dinner_request": "dinner",
}

_KORY_SIGNATURE_RE = re.compile(r"let['']s win,?\s*\n\s*kory\b", re.IGNORECASE)
_MEAL_PATTERNS: dict[MealKind, re.Pattern[str]] = {
    "dinner": re.compile(r"\bdinner\b", re.IGNORECASE),
    "lunch": re.compile(r"\blunch\b", re.IGNORECASE),
}
_RESERVATION_DRAFT_RE = re.compile(
    r"\b("
    r"reservation|reserve a table|book a table|book (?:us |me )?a table|"
    r"make a reservation|hold a table|restaurant|venue"
    r")\b",
    re.IGNORECASE,
)


def detect_kory_meal_mention(
    *,
    subject: str,
    body: str,
    sender: str,
) -> MealKind | None:
    """Return lunch/dinner when Kory authored or signed the email and mentions that meal."""
    text = f"{subject}\n{body}"
    meal: MealKind | None = None
    if _MEAL_PATTERNS["dinner"].search(text):
        meal = "dinner"
    elif _MEAL_PATTERNS["lunch"].search(text):
        meal = "lunch"
    if not meal or not is_kory_author(sender, body):
        return None
    return meal


def is_kory_author(sender: str, body: str) -> bool:
    if _KORY_SIGNATURE_RE.search(body):
        return True
    sender_lower = sender.lower()
    for email in settings.kory_sender_emails:
        if email in sender_lower:
            return True
    local = sender_lower.split("@", 1)[0]
    if "kory" in local:
        return True
    return False


def create_booking_reminder_task(
    *,
    meal: MealKind,
    meeting_subject: str,
    thread_id: str,
    sender: str,
    body_excerpt: str = "",
    approved: bool = False,
) -> dict[str, Any]:
    """Create a task on the Lexi Booking reminders Asana board."""
    from app.safety.approval_gate import assert_kory_approved_write

    assert_kory_approved_write(approved=approved, action="Asana reservation reminder")
    subject = (meeting_subject or "Email thread").strip()
    title = f"{BOOKING_TASK_PREFIX} {meal.title()} — {subject}"
    notes = (
        f"Lexi booking reminder — {ASANA_BOARD_NAME} ({ASANA_PARENT_PROJECT_NAME})\n"
        "----------------------------------------\n"
        f"Meal: {meal}\n"
        f"Thread: {thread_id}\n"
        f"Counterparty / sender: {sender.strip()}\n"
    )
    if body_excerpt.strip():
        notes += f"\nExcerpt:\n{body_excerpt.strip()[:1200]}\n"
    return _create_asana_task(title=title, notes=notes)


def meal_from_intent(intent: str | None) -> MealKind | None:
    return INTENT_TO_MEAL.get((intent or "").strip().lower())  # type: ignore[return-value]


def reservation_needed_for_proposal(
    *,
    intent: str | None,
    drafted_reply: str = "",
    subject: str = "",
    body: str = "",
    sender: str = "",
) -> bool:
    """True when Kory likely needs to book a venue (meal, happy hour, or explicit reservation)."""
    intent_key = (intent or "").strip().lower()
    if intent_key in VENUE_RESERVATION_INTENTS:
        return True
    if detect_kory_meal_mention(subject=subject, body=body, sender=sender):
        return True
    draft = (drafted_reply or "").strip()
    if draft and _RESERVATION_DRAFT_RE.search(draft):
        return True
    if draft and meal_from_draft_text(draft):
        return True
    return False


def meal_from_draft_text(text: str) -> MealKind | None:
    if _MEAL_PATTERNS["lunch"].search(text):
        return "lunch"
    if _MEAL_PATTERNS["dinner"].search(text):
        return "dinner"
    return None


def dispatch_reservation_reminder_for_proposal(
    *,
    intent: str | None,
    meeting_subject: str,
    thread_id: str,
    sender: str,
    drafted_reply: str = "",
    raw_body: str = "",
    time_slot: str = "",
    approved: bool = False,
) -> dict[str, Any] | None:
    """Create the right Asana task on Reservation Reminders, or None if not needed."""
    intent_key = (intent or "").strip().lower()
    if not reservation_needed_for_proposal(
        intent=intent_key,
        drafted_reply=drafted_reply,
        subject=meeting_subject,
        body=raw_body,
        sender=sender,
    ):
        return None

    meal = (
        meal_from_intent(intent_key)
        or detect_kory_meal_mention(subject=meeting_subject, body=raw_body, sender=sender)
        or meal_from_draft_text(drafted_reply)
        or meal_from_draft_text(raw_body)
    )

    if meal:
        excerpt = drafted_reply.strip() or raw_body.strip()
        if time_slot.strip():
            excerpt = f"Confirmed slot: {time_slot.strip()}\n\n{excerpt}".strip()
        return create_booking_reminder_task(
            meal=meal,
            meeting_subject=meeting_subject,
            thread_id=thread_id,
            sender=sender,
            body_excerpt=excerpt,
            approved=approved,
        )

    if intent_key == "happy_hour" or _RESERVATION_DRAFT_RE.search(drafted_reply or ""):
        return create_venue_reservation_task(
            meeting_subject=meeting_subject,
            time_slot=time_slot or "See approved email / calendar",
            participants=sender,
            approved=approved,
        )

    return None


def create_venue_reservation_task(
    meeting_subject: str,
    time_slot: str,
    participants: str,
    *,
    approved: bool = False,
) -> dict[str, Any]:
    """Create an Asana action task after a confirmed calendar slot (venue logistics)."""
    from app.safety.approval_gate import assert_kory_approved_write

    assert_kory_approved_write(approved=approved, action="Asana venue reservation task")
    subject = (meeting_subject or "Meeting").strip()
    title = f"{VENUE_TASK_PREFIX} {subject}"
    notes = (
        "Lexi venue reservation request\n"
        "------------------------------\n"
        f"Board: {ASANA_BOARD_NAME}\n"
        f"Selected time slot: {time_slot.strip()}\n"
        f"Target participant(s): {participants.strip()}\n"
    )
    return _create_asana_task(title=title, notes=notes)


def _create_asana_task(*, title: str, notes: str) -> dict[str, Any]:
    if _should_simulate_asana():
        task_id = f"asana-sim-{uuid.uuid4().hex[:12]}"
        return {
            "ok": True,
            "task_id": task_id,
            "title": title,
            "notes": notes,
            "board": ASANA_BOARD_NAME,
            "simulated": True,
            "composio_log_id": None,
            "error": None,
        }

    if not settings.asana_project_gid:
        return {
            "ok": False,
            "task_id": None,
            "title": title,
            "notes": notes,
            "board": ASANA_BOARD_NAME,
            "simulated": False,
            "composio_log_id": None,
            "error": (
                f"ASANA_PROJECT_GID is not set — add the GID for board '{ASANA_BOARD_NAME}' in .env"
            ),
        }

    try:
        task_id, log_id = _create_task_via_composio(title=title, notes=notes)
        return {
            "ok": bool(task_id),
            "task_id": task_id,
            "title": title,
            "notes": notes,
            "board": ASANA_BOARD_NAME,
            "simulated": False,
            "composio_log_id": log_id,
            "error": None if task_id else "Composio returned no task id.",
        }
    except ComposioNotConfiguredError as exc:
        return {
            "ok": False,
            "task_id": None,
            "title": title,
            "notes": notes,
            "board": ASANA_BOARD_NAME,
            "simulated": False,
            "composio_log_id": None,
            "error": str(exc),
        }
    except Exception as exc:
        friendly = _friendly_asana_error(exc)
        if friendly:
            return {
                "ok": False,
                "task_id": None,
                "title": title,
                "notes": notes,
                "board": ASANA_BOARD_NAME,
                "simulated": False,
                "composio_log_id": None,
                "error": friendly,
            }
        if settings.demo_mode:
            task_id = f"asana-sim-{uuid.uuid4().hex[:12]}"
            return {
                "ok": True,
                "task_id": task_id,
                "title": title,
                "notes": notes,
                "board": ASANA_BOARD_NAME,
                "simulated": True,
                "composio_log_id": None,
                "error": f"composio_failed_simulated: {exc}",
            }
        return {
            "ok": False,
            "task_id": None,
            "title": title,
            "notes": notes,
            "board": ASANA_BOARD_NAME,
            "simulated": False,
            "composio_log_id": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _friendly_asana_error(exc: Exception) -> str | None:
    """Human-readable message when Asana board/section is missing — never crash the agent."""
    msg = str(exc).lower()
    if any(token in msg for token in ("404", "not found", "does not exist", "no longer accessible")):
        return (
            f"Asana board '{ASANA_BOARD_NAME}' was not found (it may have been deleted or renamed). "
            "Scheduling and email are unaffected. Update ASANA_PROJECT_GID in .env or recreate the board."
        )
    if "403" in msg or "forbidden" in msg:
        return (
            f"Asana access denied for board '{ASANA_BOARD_NAME}'. "
            "Reconnect Asana in Composio or check project permissions."
        )
    return None


def _should_simulate_asana() -> bool:
    if not settings.asana_enabled:
        return True
    if os.getenv("ASANA_SIMULATE", "").lower() in {"1", "true", "yes"}:
        return True
    if settings.demo_mode and not settings.composio_api_key:
        return True
    if not settings.asana_project_gid:
        return True
    return False


def _create_task_via_composio(*, title: str, notes: str) -> tuple[str | None, str | None]:
    project_gid = settings.asana_project_gid
    if not project_gid:
        raise RuntimeError("ASANA_PROJECT_GID is not configured.")

    arguments: dict[str, Any] = {
        "data": {
            "name": title,
            "notes": notes,
            "projects": [project_gid],
        }
    }
    result = execute_asana_tool(ASANA_CREATE_TOOL, arguments)
    if result.get("dry_run"):
        return f"asana-dry-run-{uuid.uuid4().hex[:12]}", result.get("log_id")
    task_id = _extract_task_id(result.get("data"))
    if not task_id:
        raise RuntimeError("Composio Asana create returned no task id.")
    _add_task_to_section_if_configured(task_id)
    return task_id, result.get("log_id")


def _add_task_to_section_if_configured(task_gid: str) -> None:
    section_gid = settings.asana_section_gid
    if not section_gid:
        return
    try:
        execute_asana_tool(
            "ASANA_ADD_TASK_TO_SECTION",
            {
                "task_gid": task_gid,
                "section_gid": section_gid,
            },
        )
    except Exception:
        pass


def _extract_task_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("gid", "id", "task_id", "task_gid"):
            value = data.get(key)
            if value:
                return str(value)
        task = data.get("task") or data.get("data")
        if isinstance(task, dict):
            return _extract_task_id(task)
    return None

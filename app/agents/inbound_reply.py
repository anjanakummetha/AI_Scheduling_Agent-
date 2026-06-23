"""Inbound email reply workflow: ask Kory before drafting, then draft → revise → send."""

from __future__ import annotations

import json
import re
import time
import traceback
from typing import Any

from app.agents.scheduler_agent import process_proposal_schedule
from app.agents.triage_agent import NON_SCHEDULING_INTENTS, VALID_INTENTS
from app.config import settings
from app.llm.hermes_client import get_hermes_client
from app.storage.lexi_db import get_lexi_connection
from app.storage.lexi_store import update_drafted_reply

AWAITING_REPLY_PROMPT = "awaiting_reply_prompt"
NO_REPLY_NEEDED = "no_reply_needed"
PENDING_APPROVAL = "pending_approval"

SCHEDULING_INTENTS = frozenset(VALID_INTENTS) - NON_SCHEDULING_INTENTS


def is_scheduling_intent(intent: str | None) -> bool:
    """True when begin_draft_reply should run the scheduler (slots + holds)."""
    return (intent or "unknown").strip().lower() in SCHEDULING_INTENTS

def _general_reply_system_prompt(
    *,
    recipient_email: str | None = None,
    voice_mode: str = "kory",
) -> str:
    from app.llm.kory_voice import voice_prompt_block
    from app.scheduling.lexi_voice import normalize_voice_mode, voice_instruction_for_mode
    from app.storage.kory_memory import facts_prompt_block

    mode = normalize_voice_mode(voice_mode)
    if mode == "lexi":
        voice = voice_instruction_for_mode(mode)
    else:
        voice = voice_prompt_block(recipient_email=recipient_email)
    memory = facts_prompt_block(limit=15)
    memory_block = f"\n\n{memory}" if memory else ""
    return f"""You are Lexi, Kory's executive assistant drafting an email reply.

Given the inbound email and triage metadata, write a concise reply.

{voice}
{memory_block}

Return ONLY a valid JSON object with exactly one key:
- drafted_reply: string (the full plain-text email body to send)

Rules:
- Use proper paragraph spacing (blank line between paragraphs).
- Do not invent calendar times unless the email is clearly about scheduling.
- If unsure about intent, meeting type, or recipient timezone → ask a clarifying question; never assume timezone.
- Do not include markdown fences or text outside the JSON object."""


def get_inbound_reply_queue() -> list[dict[str, Any]]:
    """Proposals waiting for Kory to say whether Lexi should draft a reply."""
    with get_lexi_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id AS proposal_id,
                p.thread_id,
                p.intent_classification,
                p.priority_tier,
                p.justification,
                e.subject,
                e.sender,
                e.received_at,
                e.raw_body
            FROM proposals AS p
            INNER JOIN email_threads AS e ON e.thread_id = p.thread_id
            WHERE p.status = ?
            ORDER BY p.id ASC
            """,
            (AWAITING_REPLY_PROMPT,),
        ).fetchall()
    return [dict(row) for row in rows]


def decline_reply(proposal_id: int, *, reason: str = "") -> dict[str, Any]:
    """Kory declined to draft a reply for this inbound email."""
    with get_lexi_connection() as conn:
        row = conn.execute(
            "SELECT status FROM proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"Proposal {proposal_id} not found."}
        if row["status"] != AWAITING_REPLY_PROMPT:
            return {
                "ok": False,
                "error": f"Proposal {proposal_id} is not awaiting reply prompt (status={row['status']}).",
            }
        conn.execute(
            "UPDATE proposals SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (NO_REPLY_NEEDED, proposal_id),
        )
        _audit(
            conn,
            proposal_id,
            "inbound_reply_declined",
            reason or "Kory declined to draft a reply.",
        )
        conn.commit()
    return {"ok": True, "proposal_id": proposal_id, "status": NO_REPLY_NEEDED}


def set_proposal_delegation_metadata(
    proposal_id: int,
    *,
    voice_mode: str,
    send_channel: str,
    is_delegation: bool,
) -> None:
    with get_lexi_connection() as conn:
        conn.execute(
            """
            UPDATE proposals
            SET voice_mode = ?, send_channel = ?, is_delegation = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                voice_mode,
                send_channel,
                1 if is_delegation else 0,
                proposal_id,
            ),
        )
        conn.commit()


def begin_delegation_draft(proposal_id: int) -> dict[str, Any]:
    """Auto-draft after Kory CCs Lexi / delegates (skips awaiting_reply_prompt gate)."""
    bundle = _fetch_proposal_bundle(proposal_id)
    if not bundle:
        return {"ok": False, "error": f"Proposal {proposal_id} not found."}
    status = bundle.get("status")
    if status not in {AWAITING_REPLY_PROMPT, PENDING_APPROVAL}:
        return {
            "ok": False,
            "error": f"Proposal {proposal_id} cannot auto-draft (status={status}).",
        }

    intent = (bundle.get("intent_classification") or "unknown").lower()
    voice_mode = (bundle.get("voice_mode") or "lexi").lower()
    if intent in SCHEDULING_INTENTS:
        scheduled = process_proposal_schedule(proposal_id)
        if scheduled:
            result = {
                "ok": True,
                "proposal_id": proposal_id,
                "status": PENDING_APPROVAL,
                "path": "delegation_scheduling",
                "voice_mode": voice_mode,
                "send_channel": bundle.get("send_channel") or "lexi",
                "message": "Delegation scheduling draft staged for Teams approval.",
            }
            _maybe_push_teams_approval(proposal_id)
            return _attach_draft_verification(result, proposal_id)

    general = _draft_general_reply(bundle, voice_mode=voice_mode)
    if not general.get("ok"):
        return general
    _set_pending_approval(
        proposal_id,
        general["drafted_reply"],
        general.get("confidence_score", 0.5),
        voice_mode=voice_mode,
    )
    _maybe_push_teams_approval(proposal_id)
    result = {
        "ok": True,
        "proposal_id": proposal_id,
        "status": PENDING_APPROVAL,
        "path": "delegation_general",
        "voice_mode": voice_mode,
        "drafted_reply": general["drafted_reply"],
        "message": "Lexi delegation draft ready for Teams approval.",
    }
    return _attach_draft_verification(result, proposal_id)


def begin_draft_reply(proposal_id: int, *, voice_mode: str = "") -> dict[str, Any]:
    """After Kory says yes: draft reply (scheduling path with holds, or general reply)."""
    bundle = _fetch_proposal_bundle(proposal_id)
    if not bundle:
        return {"ok": False, "error": f"Proposal {proposal_id} not found."}
    if bundle["status"] != AWAITING_REPLY_PROMPT:
        return {
            "ok": False,
            "error": (
                f"Proposal {proposal_id} is not awaiting reply prompt "
                f"(status={bundle['status']})."
            ),
        }

    if voice_mode.strip():
        set_proposal_delegation_metadata(
            proposal_id,
            voice_mode=voice_mode.strip().lower(),
            send_channel="lexi" if voice_mode.strip().lower() == "lexi" else "kory",
            is_delegation=False,
        )
        bundle = _fetch_proposal_bundle(proposal_id) or bundle

    intent = (bundle.get("intent_classification") or "unknown").lower()
    result: dict[str, Any] | None = None
    if intent in SCHEDULING_INTENTS:
        scheduled = process_proposal_schedule(proposal_id)
        if scheduled:
            result = {
                "ok": True,
                "proposal_id": proposal_id,
                "status": PENDING_APPROVAL,
                "path": "scheduling",
                "message": (
                    "Drafted scheduling reply with time options and calendar holds. "
                    "Show Kory the full draft; ask for changes before sending."
                ),
            }
        else:
            general = _draft_general_reply(
                bundle,
                voice_mode=str(bundle.get("voice_mode") or voice_mode or "kory"),
            )
            if not general.get("ok"):
                return general
            _set_pending_approval(
                proposal_id,
                general["drafted_reply"],
                general.get("confidence_score", 0.5),
                voice_mode=str(bundle.get("voice_mode") or voice_mode or "kory"),
            )
            result = {
                "ok": True,
                "proposal_id": proposal_id,
                "status": PENDING_APPROVAL,
                "path": "general_fallback",
                "drafted_reply": general["drafted_reply"],
                "message": (
                    "Scheduling slots could not be placed; drafted a general reply instead. "
                    "Show Kory the draft and ask for changes before sending."
                ),
            }
    else:
        general = _draft_general_reply(
            bundle,
            voice_mode=str(bundle.get("voice_mode") or voice_mode or "kory"),
        )
        if not general.get("ok"):
            return general
        _set_pending_approval(
            proposal_id,
            general["drafted_reply"],
            general.get("confidence_score", 0.5),
            voice_mode=str(bundle.get("voice_mode") or voice_mode or "kory"),
        )
        result = {
            "ok": True,
            "proposal_id": proposal_id,
            "status": PENDING_APPROVAL,
            "path": "general",
            "drafted_reply": general["drafted_reply"],
            "message": "Draft ready. Show Kory the full text; ask for changes before sending.",
        }

    if result and result.get("status") == PENDING_APPROVAL:
        _maybe_push_teams_approval(proposal_id)
    if result:
        result = _attach_draft_verification(result, proposal_id)
    return result or {"ok": False, "error": "Draft failed."}


def update_proposal_draft(proposal_id: int, drafted_reply: str) -> dict[str, Any]:
    """Apply Kory's edits to a draft before send."""
    body = (drafted_reply or "").strip()
    if not body:
        return {"ok": False, "error": "drafted_reply cannot be empty."}
    with get_lexi_connection() as conn:
        row = conn.execute(
            "SELECT status FROM proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"Proposal {proposal_id} not found."}
        if row["status"] != PENDING_APPROVAL:
            return {
                "ok": False,
                "error": f"Proposal {proposal_id} is not pending approval (status={row['status']}).",
            }
    update_drafted_reply(proposal_id, body)
    return {"ok": True, "proposal_id": proposal_id, "drafted_reply": body}


def _maybe_push_teams_approval(proposal_id: int) -> None:
    from app.config import settings

    if settings.lexi_teams_enabled:
        from app.bot.teams_publisher import schedule_teams_approval_push

        schedule_teams_approval_push(proposal_id)


def _set_pending_approval(
    proposal_id: int,
    drafted_reply: str,
    confidence_score: float,
    *,
    voice_mode: str = "kory",
) -> None:
    from app.scheduling.email_format import normalize_draft_for_display

    body = normalize_draft_for_display(drafted_reply, max_chars=None, voice_mode=voice_mode)
    with get_lexi_connection() as conn:
        conn.execute(
            """
            UPDATE proposals
            SET status = ?,
                drafted_reply = ?,
                confidence_score = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (PENDING_APPROVAL, body, confidence_score, proposal_id),
        )
        _audit(conn, proposal_id, "inbound_reply_drafted", "General reply draft staged.")
        conn.commit()


def _draft_general_reply(bundle: dict[str, Any], *, voice_mode: str = "kory") -> dict[str, Any]:
    started = time.perf_counter()
    subject = bundle.get("subject") or ""
    sender = bundle.get("sender") or ""
    body = bundle.get("raw_body") or ""
    intent = bundle.get("intent_classification") or "unknown"
    priority = bundle.get("priority_tier") or "medium"

    user_content = json.dumps(
        {
            "subject": subject,
            "sender": sender,
            "body": body,
            "intent": intent,
            "priority": priority,
            "justification": bundle.get("justification") or "",
        },
        ensure_ascii=False,
    )

    try:
        client = get_hermes_client()
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": _general_reply_system_prompt(
                        recipient_email=sender,
                        voice_mode=voice_mode or str(bundle.get("voice_mode") or "kory"),
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
        )
        content = response.choices[0].message.content or ""
        payload = _parse_json_object(content)
        drafted = _finalize_draft(
            str(payload.get("drafted_reply", "")),
            voice_mode=voice_mode or str(bundle.get("voice_mode") or "kory"),
        )
        if not drafted:
            raise ValueError("LLM returned empty drafted_reply")
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "ok": True,
            "drafted_reply": drafted,
            "confidence_score": 0.75,
            "duration_ms": duration_ms,
            "source": "llm",
        }
    except Exception as exc:
        fallback = _template_general_reply(
            subject,
            sender,
            body,
            voice_mode=voice_mode or str(bundle.get("voice_mode") or "kory"),
        )
        return {
            "ok": True,
            "drafted_reply": fallback,
            "confidence_score": 0.4,
            "source": "template_fallback",
            "warning": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _finalize_draft(draft: str, *, voice_mode: str = "kory") -> str:
    from app.scheduling.email_format import finalize_lexi_email_body, finalize_outbound_email_body
    from app.scheduling.lexi_voice import normalize_voice_mode
    from app.safety.operation_verify import verify_draft_reply

    mode = normalize_voice_mode(voice_mode)
    if mode == "lexi":
        normalized = finalize_lexi_email_body(draft.strip())
    else:
        normalized = finalize_outbound_email_body(draft.strip())
    check = verify_draft_reply(normalized, voice_mode=mode)
    if not check.ok:
        raise ValueError("; ".join(check.errors) or "Draft failed verification.")
    return normalized


def _attach_draft_verification(result: dict[str, Any], proposal_id: int) -> dict[str, Any]:
    from app.safety.operation_verify import merge_verify, verify_draft_reply

    bundle = _fetch_proposal_bundle(proposal_id)
    draft = result.get("drafted_reply") or (bundle or {}).get("drafted_reply") or ""
    if not draft:
        return result
    voice_mode = str((bundle or {}).get("voice_mode") or "kory")
    verify = verify_draft_reply(str(draft), voice_mode=voice_mode)
    return merge_verify(result, verify)


def _template_general_reply(
    subject: str,
    sender: str,
    body: str,
    *,
    voice_mode: str = "kory",
) -> str:
    from app.scheduling.lexi_voice import normalize_voice_mode

    excerpt = (body or "").strip()
    if len(excerpt) > 200:
        excerpt = excerpt[:200] + "…"
    mode = normalize_voice_mode(voice_mode)
    if mode == "lexi":
        from app.scheduling.email_format import finalize_lexi_email_body

        return finalize_lexi_email_body(
            f"Hi — I'm Lexi, Kory's assistant.\n\n"
            f"Thanks for your note regarding \"{subject or 'your message'}\". "
            "I'll follow up shortly on next steps."
        )
    return (
        f"Thanks for your note regarding \"{subject or 'your message'}\".\n\n"
        f"I received your message and will follow up shortly.\n\n"
        f"Let's Win,\n"
        f"Kory"
    )


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise ValueError("LLM response did not contain valid JSON") from None
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON root must be an object")
    return parsed


def _fetch_proposal_bundle(proposal_id: int) -> dict[str, Any] | None:
    with get_lexi_connection() as conn:
        row = conn.execute(
            """
            SELECT
                p.id AS proposal_id,
                p.thread_id,
                p.status,
                p.intent_classification,
                p.priority_tier,
                p.justification,
                p.voice_mode,
                p.send_channel,
                p.is_delegation,
                p.drafted_reply,
                e.subject,
                e.sender,
                e.raw_body
            FROM proposals AS p
            INNER JOIN email_threads AS e ON e.thread_id = p.thread_id
            WHERE p.id = ?
            """,
            (proposal_id,),
        ).fetchone()
    return dict(row) if row else None


def _audit(
    conn,
    proposal_id: int,
    step_name: str,
    message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (step_name, reference_id, log_level, message, payload)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            step_name,
            str(proposal_id),
            "INFO",
            message,
            json.dumps({"proposal_id": proposal_id}, default=str),
        ),
    )

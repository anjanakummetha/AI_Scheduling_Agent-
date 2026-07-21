"""HubSpot CRM — read/stage proposals; live writes blocked until explicit env flag."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.integrations.composio_client import ComposioNotConfiguredError, execute_hubspot_tool
from app.safety.approval_gate import assert_kory_approved_write

HUBSPOT_SEARCH_CONTACTS = "HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA"
HUBSPOT_LIST_CONTACTS = "HUBSPOT_LIST_CONTACTS"
HUBSPOT_UPDATE_CONTACT = "HUBSPOT_UPDATE_CONTACT"
HUBSPOT_MERGE_CONTACTS = "HUBSPOT_MERGE_CONTACTS"
HUBSPOT_CREATE_NOTE = "HUBSPOT_CREATE_NOTE"
HUBSPOT_LIST_DEALS = "HUBSPOT_LIST_DEALS"
HUBSPOT_SEARCH_DEALS = "HUBSPOT_SEARCH_DEALS"


def hubspot_configured() -> bool:
    return bool(settings.hubspot_composio_connection_id and settings.composio_api_key)


def hubspot_writes_blocked() -> bool:
    return settings.lexi_dry_run or not settings.hubspot_live_writes_enabled


def hubspot_status_brief() -> dict[str, Any]:
    if not hubspot_configured():
        return {
            "ok": False,
            "kory_message": (
                "**HubSpot:** not connected in Lexi yet. "
                "Set `HUBSPOT_COMPOSIO_CONNECTION_ID=ca_jdY18Wb0L46M` "
                "(reads ok; writes stay blocked until you enable live HubSpot writes)."
            ),
        }
    try:
        sample = search_contacts(limit=5)
        count = sample.get("count", 0)
        write_note = (
            "Live writes **blocked**."
            if hubspot_writes_blocked()
            else "Live writes enabled."
        )
        return {
            "ok": True,
            "kory_message": (
                f"**HubSpot:** connected. Sampled {count} contact(s). {write_note} "
                "Cleanup / outreach / merges stage locally until you approve."
            ),
            "sample": sample.get("contacts", [])[:5],
            "writes_blocked": hubspot_writes_blocked(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "kory_message": f"**HubSpot:** read failed ({type(exc).__name__}).",
            "error": str(exc),
        }


def search_contacts(*, limit: int = 25, query: str = "") -> dict[str, Any]:
    if not hubspot_configured():
        raise ComposioNotConfiguredError("HUBSPOT_COMPOSIO_CONNECTION_ID is missing.")

    arguments: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if query.strip():
        arguments["query"] = query.strip()
        tool = HUBSPOT_SEARCH_CONTACTS
    else:
        tool = HUBSPOT_LIST_CONTACTS

    try:
        result = execute_hubspot_tool(tool, arguments)
    except Exception:
        result = execute_hubspot_tool(HUBSPOT_LIST_CONTACTS, {"limit": arguments["limit"]})

    contacts = _normalize_contacts(result.get("data"))
    return {
        "ok": True,
        "count": len(contacts),
        "contacts": contacts,
        "composio_log_id": result.get("log_id"),
        "dry_run": result.get("dry_run", False),
    }


def propose_inactive_cleanup(*, inactive_days: int = 180, limit: int = 50) -> dict[str, Any]:
    """Stage cleanup using last-activity age (no HubSpot writes)."""
    raw = search_contacts(limit=limit)
    contacts = raw.get("contacts") or []
    proposals: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(30, inactive_days))

    for contact in contacts:
        last = contact.get("lastmodifieddate") or contact.get("last_activity") or ""
        action = _suggest_cleanup_action(
            contact,
            inactive_days=inactive_days,
            cutoff=cutoff,
        )
        if action:
            proposals.append(
                {
                    "contact_id": contact.get("id"),
                    "email": contact.get("email"),
                    "name": contact.get("name"),
                    "suggested_action": action,
                    "last_activity": last,
                    "days_inactive": _days_since(last),
                }
            )

    batch_id = _stage_hubspot_batch(
        batch_type="cleanup",
        payload={"inactive_days": inactive_days, "proposals": proposals},
    )
    lines = [f"**HubSpot cleanup proposals** ({len(proposals)} contact(s))\n"]
    for row in proposals[:15]:
        age = row.get("days_inactive")
        age_s = f" · {age}d idle" if age is not None else ""
        lines.append(
            f"• {row.get('name') or row.get('email')} — **{row['suggested_action']}**{age_s}"
        )
    if not proposals:
        lines.append("_No inactive contacts in this sample._")
    lines.append("\n_Nothing changed in HubSpot — approve a batch to apply (still blocked until live writes)._")
    return {
        "ok": True,
        "batch_id": batch_id,
        "proposal_count": len(proposals),
        "proposals": proposals,
        "writes_blocked": hubspot_writes_blocked(),
        "kory_message": "\n".join(lines),
    }


def propose_duplicate_merges(*, limit: int = 50) -> dict[str, Any]:
    """Find likely duplicate contacts by email/name — stage merge proposals only."""
    raw = search_contacts(limit=limit)
    contacts = raw.get("contacts") or []
    by_email: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for contact in contacts:
        email = (contact.get("email") or "").strip().lower()
        name = re.sub(r"\s+", " ", (contact.get("name") or "").strip().lower())
        if email:
            by_email.setdefault(email, []).append(contact)
        if name and " " in name:
            by_name.setdefault(name, []).append(contact)

    pairs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for email, group in by_email.items():
        if len(group) < 2:
            continue
        primary, *dupes = group
        for dupe in dupes:
            key = f"{primary.get('id')}:{dupe.get('id')}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            pairs.append(
                {
                    "reason": "same_email",
                    "email": email,
                    "primary_id": primary.get("id"),
                    "primary_name": primary.get("name"),
                    "duplicate_id": dupe.get("id"),
                    "duplicate_name": dupe.get("name"),
                    "suggested_action": "merge",
                }
            )
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        emails = {(c.get("email") or "").lower() for c in group if c.get("email")}
        if len(emails) <= 1:
            continue
        primary, *dupes = group
        for dupe in dupes:
            key = f"{primary.get('id')}:{dupe.get('id')}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            pairs.append(
                {
                    "reason": "same_name_different_email",
                    "name": name,
                    "primary_id": primary.get("id"),
                    "primary_email": primary.get("email"),
                    "duplicate_id": dupe.get("id"),
                    "duplicate_email": dupe.get("email"),
                    "suggested_action": "review_or_merge",
                }
            )

    batch_id = _stage_hubspot_batch(
        batch_type="duplicate_merge",
        payload={"pairs": pairs},
    )
    lines = [f"**HubSpot duplicate proposals** ({len(pairs)})\n"]
    for row in pairs[:12]:
        lines.append(
            f"• {row.get('primary_name') or row.get('primary_email')} "
            f"↔ {row.get('duplicate_name') or row.get('duplicate_email')} "
            f"— **{row['suggested_action']}** ({row['reason']})"
        )
    if not pairs:
        lines.append("_No obvious duplicates in this sample._")
    lines.append("\n_Merges are staged only — no HubSpot changes until live writes + approval._")
    return {
        "ok": True,
        "batch_id": batch_id,
        "pair_count": len(pairs),
        "pairs": pairs,
        "writes_blocked": hubspot_writes_blocked(),
        "kory_message": "\n".join(lines),
    }


def propose_lead_source_fills(*, limit: int = 25) -> dict[str, Any]:
    """Propose lead source / lifecycle fills from Outlook history — stage only."""
    raw = search_contacts(limit=limit)
    contacts = raw.get("contacts") or []
    proposals: list[dict[str, Any]] = []

    for contact in contacts:
        email = (contact.get("email") or "").strip()
        if not email:
            continue
        missing_source = not (contact.get("hs_analytics_source") or contact.get("lead_source"))
        missing_stage = not (contact.get("lifecyclestage") or "").strip()
        if not missing_source and not missing_stage:
            continue
        inferred = _infer_lead_fields_from_inbox(email)
        if not inferred:
            continue
        proposals.append(
            {
                "contact_id": contact.get("id"),
                "email": email,
                "name": contact.get("name"),
                "proposed_fields": inferred,
                "suggested_action": "fill_from_email_history",
            }
        )

    batch_id = _stage_hubspot_batch(
        batch_type="lead_source_fill",
        payload={"proposals": proposals},
    )
    lines = [f"**HubSpot field-fill proposals** ({len(proposals)})\n"]
    for row in proposals[:12]:
        fields = ", ".join(f"{k}={v}" for k, v in (row.get("proposed_fields") or {}).items())
        lines.append(f"• {row.get('name') or row['email']} — {fields}")
    if not proposals:
        lines.append("_No missing lead fields matched to inbox history in this sample._")
    lines.append("\n_Staged only — HubSpot not updated._")
    return {
        "ok": True,
        "batch_id": batch_id,
        "proposal_count": len(proposals),
        "proposals": proposals,
        "writes_blocked": hubspot_writes_blocked(),
        "kory_message": "\n".join(lines),
    }


def enrich_prebrief_from_hubspot(*, email: str = "", name: str = "") -> dict[str, Any]:
    """Read-only HubSpot context for prebrief / who-introduced."""
    if not hubspot_configured():
        return {
            "ok": False,
            "kory_message": "HubSpot not connected — prebrief enrichment skipped.",
        }
    query = email.strip() or name.strip()
    if not query:
        return {"ok": False, "error": "email or name required"}
    try:
        found = search_contacts(limit=10, query=query)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    contacts = found.get("contacts") or []
    match = None
    email_l = email.strip().lower()
    for contact in contacts:
        if email_l and (contact.get("email") or "").lower() == email_l:
            match = contact
            break
    if match is None and contacts:
        match = contacts[0]
    if not match:
        return {
            "ok": True,
            "found": False,
            "kory_message": f"No HubSpot contact for {query}.",
        }

    lines = [
        f"**HubSpot:** {match.get('name') or match.get('email')}",
        f"Lifecycle: {match.get('lifecyclestage') or 'unknown'}",
        f"Lead status: {match.get('hs_lead_status') or 'unknown'}",
    ]
    if match.get("company"):
        lines.append(f"Company: {match['company']}")
    if match.get("hs_analytics_source") or match.get("lead_source"):
        lines.append(
            f"Source: {match.get('hs_analytics_source') or match.get('lead_source')}"
        )
    return {
        "ok": True,
        "found": True,
        "contact": match,
        "kory_message": "\n".join(lines),
    }


def stage_meeting_note(
    *,
    email: str,
    note: str,
    meeting_subject: str = "",
    approved: bool = False,
) -> dict[str, Any]:
    """Stage a HubSpot note after a meeting — no live write while blocked."""
    assert_kory_approved_write(approved=approved, action="HubSpot meeting note")
    text = note.strip()
    if not text:
        return {"ok": False, "error": "note is required"}
    body = text
    if meeting_subject.strip():
        body = f"Meeting: {meeting_subject.strip()}\n\n{text}"

    contact_id = None
    try:
        found = search_contacts(limit=5, query=email)
        for contact in found.get("contacts") or []:
            if (contact.get("email") or "").lower() == email.lower():
                contact_id = contact.get("id")
                break
        if not contact_id and found.get("contacts"):
            contact_id = found["contacts"][0].get("id")
    except Exception:
        contact_id = None

    batch_id = _stage_hubspot_batch(
        batch_type="meeting_note",
        payload={
            "email": email,
            "contact_id": contact_id,
            "note": body,
            "meeting_subject": meeting_subject,
        },
    )
    if hubspot_writes_blocked() or not approved:
        return {
            "ok": True,
            "batch_id": batch_id,
            "dry_run": True,
            "writes_blocked": True,
            "kory_message": (
                f"Staged HubSpot note for {email} (batch `{batch_id}`). "
                "Not written — live HubSpot writes are blocked."
            ),
        }

    result = execute_hubspot_tool(
        HUBSPOT_CREATE_NOTE,
        {"contactId": contact_id, "body": body},
    )
    return {
        "ok": True,
        "batch_id": batch_id,
        "dry_run": bool(result.get("dry_run")),
        "composio_log_id": result.get("log_id"),
    }


def find_contacts_for_outreach(
    *,
    goal: str = "",
    lifecycle: str = "",
    query: str = "",
    limit: int = 15,
) -> dict[str, Any]:
    """Filter contacts for outreach batches (read-only)."""
    raw = search_contacts(limit=max(limit, 40), query=query)
    contacts = raw.get("contacts") or []
    lifecycle_l = lifecycle.strip().lower()
    goal_l = goal.strip().lower()
    filtered: list[dict[str, Any]] = []
    for contact in contacts:
        stage = str(contact.get("lifecyclestage") or "").lower()
        status = str(contact.get("hs_lead_status") or "").lower()
        if lifecycle_l and lifecycle_l not in stage and lifecycle_l not in status:
            continue
        if goal_l and "investor" in goal_l and "investor" not in f"{stage} {status}":
            # Soft preference only — still include if no better signal
            pass
        filtered.append(contact)
        if len(filtered) >= limit:
            break
    if not filtered:
        filtered = contacts[:limit]
    lines = [f"**Outreach candidates** ({len(filtered)})\n"]
    for contact in filtered[:12]:
        lines.append(
            f"• {contact.get('name') or contact.get('email')} "
            f"— {contact.get('lifecyclestage') or contact.get('hs_lead_status') or 'unknown'}"
        )
    return {
        "ok": True,
        "contacts": filtered,
        "count": len(filtered),
        "kory_message": "\n".join(lines),
    }


def deals_snapshot_for_brief(*, limit: int = 8) -> dict[str, Any]:
    """Read-only open deals for CEO briefing."""
    if not hubspot_configured():
        return {
            "ok": False,
            "kory_message": "**Deals:** HubSpot not connected.",
        }
    try:
        result = execute_hubspot_tool(HUBSPOT_LIST_DEALS, {"limit": max(1, min(limit, 25))})
    except Exception:
        try:
            result = execute_hubspot_tool(HUBSPOT_SEARCH_DEALS, {"limit": max(1, min(limit, 25))})
        except Exception as exc:
            return {
                "ok": False,
                "kory_message": f"**Deals:** unavailable ({type(exc).__name__}).",
                "error": str(exc),
            }

    deals = _normalize_deals(result.get("data"))
    open_deals = [
        d
        for d in deals
        if str(d.get("dealstage") or "").lower() not in {"closedwon", "closedlost", "closed"}
    ]
    lines = [f"**Open deals** ({len(open_deals)})\n"]
    if not open_deals:
        lines.append("_No open deals in sample._")
    for deal in open_deals[:limit]:
        amount = deal.get("amount")
        amt = f" · ${amount}" if amount not in (None, "") else ""
        lines.append(
            f"• {deal.get('dealname') or 'Untitled'} — {deal.get('dealstage') or '?'}{amt}"
        )
    return {
        "ok": True,
        "deals": open_deals[:limit],
        "kory_message": "\n".join(lines),
    }


def propose_outreach_batch(
    *,
    goal: str = "",
    contact_ids: list[str] | None = None,
    limit: int = 10,
    lifecycle: str = "",
) -> dict[str, Any]:
    """Draft outreach emails for approval — no send."""
    if contact_ids:
        contacts = [{"id": cid} for cid in contact_ids[:limit]]
    else:
        found = find_contacts_for_outreach(goal=goal, lifecycle=lifecycle, limit=limit)
        contacts = found.get("contacts") or []

    drafts: list[dict[str, Any]] = []
    for contact in contacts[:limit]:
        name = contact.get("name") or (contact.get("email") or "there").split("@")[0]
        draft = _draft_outreach_email(name=name, goal=goal)
        drafts.append(
            {
                "contact_id": contact.get("id"),
                "email": contact.get("email"),
                "name": name,
                "subject": draft["subject"],
                "body": draft["body"],
            }
        )

    batch_id = _stage_hubspot_batch(
        batch_type="outreach",
        payload={"goal": goal, "drafts": drafts},
    )
    lines = [f"**HubSpot outreach drafts** ({len(drafts)})\n"]
    for d in drafts[:5]:
        lines.append(f"• **{d['subject']}** → {d['email']}")
    lines.append("\n_Approve in Teams before any email sends. HubSpot writes stay blocked for now._")
    return {
        "ok": True,
        "batch_id": batch_id,
        "draft_count": len(drafts),
        "drafts": drafts,
        "writes_blocked": hubspot_writes_blocked(),
        "kory_message": "\n".join(lines),
    }


def execute_hubspot_batch(*, batch_id: str, approved: bool = False) -> dict[str, Any]:
    """Apply staged batch only after approval; still blocked when live writes disabled."""
    assert_kory_approved_write(approved=approved, action="HubSpot batch update")
    batch = _load_hubspot_batch(batch_id)
    if not batch:
        return {"ok": False, "error": f"Unknown batch {batch_id}"}

    if hubspot_writes_blocked():
        return {
            "ok": True,
            "dry_run": True,
            "batch_id": batch_id,
            "writes_blocked": True,
            "message": (
                "Blocked — HubSpot live writes disabled "
                "(LEXI_DRY_RUN or LEXI_HUBSPOT_LIVE_WRITES_ENABLED=false)."
            ),
            "batch": batch,
        }

    applied = 0
    errors: list[str] = []
    batch_type = batch.get("batch_type")
    payload = batch.get("payload") or {}

    if batch_type == "cleanup":
        for row in payload.get("proposals", []):
            try:
                _apply_cleanup_row(row)
                applied += 1
            except Exception as exc:
                errors.append(str(exc))
    elif batch_type == "duplicate_merge":
        for row in payload.get("pairs", []):
            try:
                _apply_merge_row(row)
                applied += 1
            except Exception as exc:
                errors.append(str(exc))
    elif batch_type == "lead_source_fill":
        for row in payload.get("proposals", []):
            try:
                _apply_field_fill(row)
                applied += 1
            except Exception as exc:
                errors.append(str(exc))
    elif batch_type == "meeting_note":
        try:
            execute_hubspot_tool(
                HUBSPOT_CREATE_NOTE,
                {
                    "contactId": payload.get("contact_id"),
                    "body": payload.get("note"),
                },
            )
            applied = 1
        except Exception as exc:
            errors.append(str(exc))

    return {
        "ok": not errors,
        "applied": applied,
        "errors": errors,
        "batch_id": batch_id,
    }


def _apply_cleanup_row(row: dict[str, Any]) -> None:
    contact_id = row.get("contact_id")
    if not contact_id:
        return
    action = row.get("suggested_action")
    props: dict[str, Any] = {}
    if action == "archive":
        props["hs_lead_status"] = "UNQUALIFIED"
    elif action == "re_engage":
        props["hs_lead_status"] = "OPEN"
    if props:
        execute_hubspot_tool(
            HUBSPOT_UPDATE_CONTACT,
            {"contactId": contact_id, "properties": props},
        )


def _apply_merge_row(row: dict[str, Any]) -> None:
    primary = row.get("primary_id")
    duplicate = row.get("duplicate_id")
    if not primary or not duplicate:
        return
    execute_hubspot_tool(
        HUBSPOT_MERGE_CONTACTS,
        {"primaryObjectId": primary, "objectIdToMerge": duplicate},
    )


def _apply_field_fill(row: dict[str, Any]) -> None:
    contact_id = row.get("contact_id")
    props = row.get("proposed_fields") or {}
    if not contact_id or not props:
        return
    execute_hubspot_tool(
        HUBSPOT_UPDATE_CONTACT,
        {"contactId": contact_id, "properties": props},
    )


def _draft_outreach_email(*, name: str, goal: str) -> dict[str, str]:
    goal_line = goal.strip() or "catch up and explore whether there is a fit"
    first = name.split()[0] if name else "there"
    subject = f"Quick note — {first}"
    body = (
        f"Hi {first},\n\n"
        f"I wanted to reach out — {goal_line}.\n\n"
        "Would a brief call next week work?\n\n"
        "Best,\nKory"
    )
    return {"subject": subject, "body": body}


def _infer_lead_fields_from_inbox(email: str) -> dict[str, str]:
    """Best-effort lead source from prior Lexi threads / inbox search (read-only)."""
    fields: dict[str, str] = {}
    try:
        from app.storage.recipient_profiles import get_recipient_profile, list_prior_email_threads

        profile = get_recipient_profile(email)
        if profile and profile.get("introducer_name"):
            fields["hs_analytics_source"] = "OFFLINE"
            fields["hs_analytics_source_data_1"] = (
                f"Introduced by {profile.get('introducer_name')}"
            )
        threads = list_prior_email_threads(email, limit=5)
        if threads and "lifecyclestage" not in fields:
            fields.setdefault("lifecyclestage", "lead")
        if threads and "hs_analytics_source" not in fields:
            fields["hs_analytics_source"] = "EMAIL_MARKETING"
    except Exception:
        pass

    if not fields:
        try:
            from app.integrations.outlook_inbox import search_inbox

            messages, _ = search_inbox(query=email, top=5)
            if messages:
                fields["lifecyclestage"] = "lead"
                subjects = " ".join(str(m.get("subject") or "").lower() for m in messages)
                if "intro" in subjects:
                    fields["hs_analytics_source"] = "OFFLINE"
                    fields["hs_analytics_source_data_1"] = "Email intro thread"
                else:
                    fields["hs_analytics_source"] = "EMAIL_MARKETING"
        except Exception:
            return {}
    return fields


def _days_since(raw: str) -> int | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days)
    except ValueError:
        return None


def _suggest_cleanup_action(
    contact: dict[str, Any],
    *,
    inactive_days: int,
    cutoff: datetime,
) -> str | None:
    email = contact.get("email")
    if not email:
        return "review_missing_email"
    last = contact.get("lastmodifieddate") or contact.get("last_activity") or ""
    days = _days_since(str(last)) if last else None
    status = str(contact.get("hs_lead_status") or contact.get("lifecyclestage") or "").lower()

    if days is not None and days >= inactive_days:
        if status in {"customer", "opportunity", "salesqualifiedlead"}:
            return "keep"
        if status in {"subscriber", "lead", "marketingqualifiedlead", "open"}:
            return "re_engage"
        return "archive"

    if days is None and status in {"other", "unqualified", ""}:
        return "archive"
    if days is None and status in {"subscriber", "lead"}:
        return "re_engage"
    return None


def _normalize_contacts(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and data.get("dry_run"):
        return []
    rows: list[Any] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("results", "contacts", "data", "value"):
            nested = data.get(key)
            if isinstance(nested, list):
                rows = nested
                break
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        props = row.get("properties") if isinstance(row.get("properties"), dict) else row
        email = props.get("email") or row.get("email")
        first = props.get("firstname") or ""
        last = props.get("lastname") or ""
        name = f"{first} {last}".strip() or props.get("name") or ""
        out.append(
            {
                "id": row.get("id") or props.get("hs_object_id"),
                "email": email,
                "name": name,
                "company": props.get("company") or props.get("associatedcompanyid"),
                "hs_lead_status": props.get("hs_lead_status"),
                "lifecyclestage": props.get("lifecyclestage"),
                "hs_analytics_source": props.get("hs_analytics_source"),
                "lead_source": props.get("hs_analytics_source") or props.get("lead_source"),
                "lastmodifieddate": props.get("lastmodifieddate") or props.get("notes_last_updated"),
                "last_activity": props.get("notes_last_contacted") or props.get("lastmodifieddate"),
            }
        )
    return out


def _normalize_deals(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and data.get("dry_run"):
        return []
    rows: list[Any] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("results", "deals", "data", "value"):
            nested = data.get(key)
            if isinstance(nested, list):
                rows = nested
                break
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        props = row.get("properties") if isinstance(row.get("properties"), dict) else row
        out.append(
            {
                "id": row.get("id"),
                "dealname": props.get("dealname") or props.get("name"),
                "dealstage": props.get("dealstage") or props.get("stage"),
                "amount": props.get("amount"),
                "closedate": props.get("closedate"),
            }
        )
    return out


def _stage_hubspot_batch(*, batch_type: str, payload: dict[str, Any]) -> str:
    from app.storage.lexi_db import get_lexi_connection

    batch_id = f"hs-{uuid.uuid4().hex[:12]}"
    with get_lexi_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hubspot_batches (
                batch_id TEXT PRIMARY KEY,
                batch_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO hubspot_batches (batch_id, batch_type, payload)
            VALUES (?, ?, ?)
            """,
            (batch_id, batch_type, json.dumps(payload, default=str)),
        )
        conn.commit()
    return batch_id


def _load_hubspot_batch(batch_id: str) -> dict[str, Any] | None:
    from app.storage.lexi_db import get_lexi_connection

    with get_lexi_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hubspot_batches (
                batch_id TEXT PRIMARY KEY,
                batch_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        row = conn.execute(
            "SELECT batch_id, batch_type, payload FROM hubspot_batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload"])
    return {
        "batch_id": row["batch_id"],
        "batch_type": row["batch_type"],
        "payload": payload,
    }

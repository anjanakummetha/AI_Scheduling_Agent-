"""Kory email reply formatting — recipient TZ first, MT in parentheses."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings

import rules as kory_rules

MT = ZoneInfo(settings.scheduling_timezone)

# Rough recipient TZ hints from email domain / TLD patterns.
DOMAIN_TIMEZONE_HINTS: dict[str, str] = {
    "iconicfounders.com": "America/Denver",
    "ifg.vc": "America/Denver",
    "newportadvisors.co": "America/New_York",
    "solamerecapital.com": "America/New_York",
    "daybreakadvisory.com": "America/Los_Angeles",
    "price.co": "America/Los_Angeles",
}

TZ_ABBREV = {
    "America/New_York": "Eastern",
    "America/Chicago": "Central",
    "America/Denver": "Mountain",
    "America/Los_Angeles": "Pacific",
    "Europe/London": "UK",
}


def recipient_timezone_confidence(sender_email: str | None) -> tuple[ZoneInfo | None, str]:
    """Return (timezone, confidence) where confidence is known | inferred | unknown.

    Hermes must ask Kory when confidence is unknown before putting times in a draft.
    """
    if not sender_email or "@" not in sender_email:
        return None, "unknown"
    domain = sender_email.split("@", 1)[1].lower()
    for pattern, tz_name in DOMAIN_TIMEZONE_HINTS.items():
        if domain == pattern or domain.endswith("." + pattern):
            return ZoneInfo(tz_name), "known"
    if domain.endswith(".co.uk") or domain.endswith(".uk"):
        return ZoneInfo("Europe/London"), "inferred"
    return None, "unknown"


def infer_recipient_timezone(sender_email: str | None) -> ZoneInfo:
    """Legacy helper — prefer recipient_timezone_confidence; MT fallback only for formatting."""
    tz, confidence = recipient_timezone_confidence(sender_email)
    if tz is not None:
        return tz
    return MT


def format_slot_for_email(
    slot: dict[str, str],
    *,
    recipient_tz: ZoneInfo | None = None,
) -> str:
    """Format one offered slot: recipient local time first, MT in parentheses."""
    recipient_tz = recipient_tz or MT
    start_raw = slot.get("start", "")
    end_raw = slot.get("end", "")
    try:
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return f"{start_raw} – {end_raw}"

    start_local = start.astimezone(recipient_tz)
    end_local = end.astimezone(recipient_tz)
    start_mt = start.astimezone(MT)
    end_mt = end.astimezone(MT)

    recipient_label = TZ_ABBREV.get(str(recipient_tz), "local")
    day = start_local.strftime("%A, %B %-d")
    start_t = start_local.strftime("%-I:%M %p").lstrip("0")
    end_t = end_local.strftime("%-I:%M %p").lstrip("0")
    start_mt_t = start_mt.strftime("%-I:%M %p").lstrip("0")
    end_mt_t = end_mt.strftime("%-I:%M %p").lstrip("0")

    if str(recipient_tz) == str(MT):
        return f"{day} at {start_mt_t}–{end_mt_t} MT"

    return (
        f"{day} at {start_t}–{end_t} {recipient_label} "
        f"({start_mt_t}–{end_mt_t} MT)"
    )


def build_scheduling_reply(
    *,
    recipient_first_name: str,
    slots: list[dict[str, str]],
    sender_email: str | None = None,
    meeting_context: str = "",
    voice_mode: str = "kory",
) -> str:
    """Build a scheduling reply matching Kory's rules (plain text email body)."""
    from app.scheduling.lexi_voice import normalize_voice_mode

    mode = normalize_voice_mode(voice_mode)
    sign_off = kory_rules.EMAIL_RULES.get("sign_off", "Let's Win")
    if mode == "lexi":
        from app.scheduling.lexi_voice import LEXI_SIGNOFF_BLOCK

        closing = LEXI_SIGNOFF_BLOCK
    else:
        closing = f"{sign_off},\nKory"
    intro = (
        "Hi — I'm Lexi, Kory's assistant. A few times that work for scheduling:\n\n"
        if mode == "lexi"
        else ""
    )
    name = recipient_first_name.strip() or "there"
    recipient_tz, tz_confidence = recipient_timezone_confidence(sender_email)
    needs_tz_confirm = bool(slots) and tz_confidence == "unknown"
    format_tz = recipient_tz or MT

    if not slots:
        greeting = f"Hi {name}," if mode == "kory" else "Hi,"
        return (
            f"{greeting}\n\n"
            f"{intro}"
            "Appreciate you reaching out. I'm going to review the calendar and follow up "
            "with times that work.\n\n"
            f"{closing}"
        )

    context_line = ""
    if meeting_context.strip():
        context_line = f"{meeting_context.strip()}\n\n"

    lines = "\n".join(
        f"• {format_slot_for_email(slot, recipient_tz=format_tz)}"
        for slot in slots[:3]
    )
    tz_note = ""
    if needs_tz_confirm:
        tz_note = (
            "[Ask Kory: what timezone should we use for this recipient before sending? "
            "Times below are Mountain Time only until confirmed.]\n\n"
        )
    return normalize_draft_for_display(
        f"{tz_note}"
        f"{'Hi,' if mode == 'lexi' else f'Hi {name},'}\n\n"
        f"{intro}"
        f"{context_line}"
        "Thanks for reaching out — a few options that work on my end:\n\n"
        f"{lines}\n\n"
        "Let me know which works best and I can send a calendar invite.\n\n"
        f"{closing}",
        max_chars=None,
        voice_mode=mode,
    )


def normalize_draft_for_display(body: str, *, max_chars: int | None = 2000, voice_mode: str = "kory") -> str:
    """Normalize line breaks and sign-off for Teams previews and send."""
    from app.scheduling.lexi_voice import normalize_voice_mode

    if normalize_voice_mode(voice_mode) == "lexi":
        return finalize_lexi_email_body(body, max_chars=max_chars)
    return finalize_outbound_email_body(body, max_chars=max_chars)


def _strip_trailing_outlook_signature_block(text: str) -> str:
    """Remove Kory's rich Outlook signature if already present (avoid double sign-off)."""
    if not text.strip():
        return text
    lowered = text.lower()
    markers = (
        "see amazing founders",
        "kory mitchell - ceo",
        "kory mitchell – ceo",
        "kory mitchell — ceo",
        "iconic founders group",
        "denver, colorado",
        "preserving legacy",
        "m: 720",
        "p: 720",
    )
    cut_at = len(text)
    for marker in markers:
        idx = lowered.find(marker)
        if idx >= 0:
            cut_at = min(cut_at, idx)
    if cut_at < len(text):
        text = text[:cut_at].rstrip()
    patterns = [
        r"\n*See amazing founders.*$",
        r"\n*Kory Mitchell\s*[-–—]\s*CEO.*$",
        r"\n*Iconic Founders Group.*$",
        r"\n*Denver, Colorado.*$",
        r"\n*M:\s*720[-.\s]?561[-.\s]?0611.*$",
        r"\n*PRESERVING LEGACY.*$",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL).rstrip()
    return cleaned


def _dedupe_lexi_signoff(text: str) -> str:
    from app.scheduling.lexi_voice import LEXI_SIGNOFF_BLOCK

    block = LEXI_SIGNOFF_BLOCK
    while text.count(block) > 1:
        first = text.find(block)
        second = text.find(block, first + len(block))
        if second < 0:
            break
        text = (text[:second] + text[second + len(block) :]).strip()
    return text


def _dedupe_kory_signoff(text: str) -> str:
    sign_off = kory_rules.EMAIL_RULES.get("sign_off", "Let's Win")
    closing = f"{sign_off},\nKory"
    while text.lower().count(closing.lower()) > 1:
        idx = text.lower().rfind(closing.lower())
        if idx <= 0:
            break
        text = text[:idx].rstrip()
        if not text.lower().endswith(closing.lower()):
            text = f"{text}\n\n{closing}"
    return text


def _strip_all_lexi_closings(text: str) -> str:
    """Remove every Lexi sign-off block (LLM duplicates, pasted closings)."""
    from app.scheduling.lexi_voice import LEXI_SIGNOFF_BLOCK

    cleaned = text
    while LEXI_SIGNOFF_BLOCK in cleaned:
        cleaned = cleaned.replace(LEXI_SIGNOFF_BLOCK, "").strip()
    cleaned = _strip_lexi_closing(cleaned)
    return cleaned.rstrip()


def finalize_lexi_email_body(body: str, *, max_chars: int | None = None) -> str:
    """Lexi assistant email: paragraph spacing + standard Thank you / Lexi sign-off."""
    from app.scheduling.lexi_voice import LEXI_SIGNOFF_BLOCK

    text = (body or "").strip().replace("\r\n", "\n")
    if not text:
        return LEXI_SIGNOFF_BLOCK

    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _strip_trailing_outlook_signature_block(text)
    text = _strip_all_lexi_closings(text)
    text = _strip_kory_closing(text)

    main = _ensure_paragraph_spacing(text.rstrip())
    closing = LEXI_SIGNOFF_BLOCK
    text = f"{main}\n\n{closing}" if main else closing
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = _dedupe_lexi_signoff(text)

    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _strip_lexi_closing(text: str) -> str:
    from app.scheduling.lexi_voice import LEXI_SIGNOFF_BLOCK

    lowered = text.lower()
    block_lower = LEXI_SIGNOFF_BLOCK.lower()
    if lowered.endswith(block_lower):
        return text[: -len(LEXI_SIGNOFF_BLOCK)].rstrip()
    patterns = [
        r"(?:Best|Thank you),?\s*\n\s*Lexi(?:\s*\n.*)?$",
        r"Lexi\s*\n\s*Assistant to Kory Mitchell.*$",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL).rstrip()
    return text


def _strip_kory_closing(text: str) -> str:
    sign_off = kory_rules.EMAIL_RULES.get("sign_off", "Let's Win")
    return re.sub(
        rf"{re.escape(sign_off)},?\s*\n?\s*Kory\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).rstrip()


def finalize_outbound_email_body(body: str, *, max_chars: int | None = None) -> str:
    """Production email body: paragraph spacing + Let's Win, / Kory on separate lines."""
    text = (body or "").strip().replace("\r\n", "\n")
    if not text:
        return ""

    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _strip_trailing_outlook_signature_block(text)

    sign_off = kory_rules.EMAIL_RULES.get("sign_off", "Let's Win")
    closing_pattern = re.compile(
        rf"({re.escape(sign_off)}),?\s*\n?\s*Kory\s*$",
        flags=re.IGNORECASE,
    )
    match = closing_pattern.search(text)
    if match:
        main = text[: match.start()].rstrip()
        closing = f"{sign_off},\nKory"
    else:
        main = _strip_lexi_closing(text).rstrip()
        closing = f"{sign_off},\nKory"

    main = _ensure_paragraph_spacing(main)
    text = f"{main}\n\n{closing}" if main else closing

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = _dedupe_kory_signoff(text)
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _ensure_paragraph_spacing(text: str) -> str:
    """Blank line between paragraphs; preserve intentional single lines (bullets, short lines)."""
    if not text.strip():
        return ""

    blocks = re.split(r"\n\n+", text.strip())
    spaced: list[str] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("•") or block.startswith("-") or block.startswith("*"):
            spaced.append(block)
            continue
        if block.count("\n") == 0:
            spaced.append(block)
            continue
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if len(lines) <= 1:
            spaced.append(block)
            continue
        merged: list[str] = []
        for line in lines:
            if merged and len(line) < 60 and not line.endswith((".", "!", "?")):
                merged[-1] = f"{merged[-1]} {line}"
            else:
                merged.append(line)
        spaced.append("\n\n".join(merged))
    return "\n\n".join(spaced)


def sender_first_name(sender: str | None) -> str:
    if not sender:
        return "there"
    local = sender.split("@", 1)[0]
    local = re.sub(r"[._+-]+", " ", local).strip()
    return local.split()[0].title() if local else "there"


def example_draft_preview() -> dict[str, Any]:
    """Static example for docs / demos (diligence coffee-style thread)."""
    slots = [
        {
            "start": "2026-06-17T14:00:00-06:00",
            "end": "2026-06-17T14:30:00-06:00",
        },
        {
            "start": "2026-06-18T15:00:00-06:00",
            "end": "2026-06-18T15:30:00-06:00",
        },
        {
            "start": "2026-06-19T13:00:00-06:00",
            "end": "2026-06-19T13:30:00-06:00",
        },
    ]
    body = build_scheduling_reply(
        recipient_first_name="Bill",
        slots=slots,
        sender_email="bill.heermann@newportadvisors.co",
        meeting_context="Happy to connect on Project Paint diligence.",
    )
    return {
        "inbound_subject": "RE: diligence call and organization for Project Paint",
        "inbound_from": "bill.heermann@newportadvisors.co",
        "draft_body": body,
        "format_rules": [
            "Recipient timezone first (Eastern for newportadvisors.co), MT in parentheses",
            f"Sign-off: {kory_rules.EMAIL_RULES.get('sign_off')}, then Kory on its own line",
            "Bullet options (2–3 slots)",
            "Never mention YPO in outgoing drafts",
        ],
    }

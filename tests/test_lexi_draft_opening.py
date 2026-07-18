"""Lexi scheduling draft — single opening, recipient name, TZ formatting."""

from app.scheduling.email_format import build_scheduling_reply, recipient_display_name
from app.utils.teams_cards import generate_approval_card


def test_lexi_voice_single_opening_with_recipient_name():
    body = build_scheduling_reply(
        recipient_first_name="Anjana",
        slots=[
            {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T11:00:00-06:00"},
        ],
        sender_email="anjana.kummetha@iconicfounders.com",
        recipient_body="Hi Kory,\nHope you're doing well.\nThanks,Anju",
        internet_headers=[
            {"name": "Date", "value": "Mon, 23 Jun 2026 14:30:00 -0400"},
        ],
        voice_mode="lexi",
        intent="referral_or_intro",
        subject="TEST — intro call",
    )
    assert body.startswith("Hi Anju,")
    assert "I'm Lexi, Kory's assistant." in body
    assert "I have a few times for a 30-minute virtual intro call on Teams:" in body
    assert "Hi — I'm Lexi" not in body
    assert "Hi,\n\nHi" not in body


def test_lexi_draft_includes_meeting_type_phrase():
    body = build_scheduling_reply(
        recipient_first_name="Anju",
        slots=[
            {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T10:30:00-06:00"},
            {"start": "2026-06-30T14:00:00-06:00", "end": "2026-06-30T14:30:00-06:00"},
        ],
        sender_email="anjana.kummetha@iconicfounders.com",
        recipient_body="30-minute intro on Teams",
        voice_mode="lexi",
        intent="referral_or_intro",
        subject="TEST — intro",
    )
    assert "I have a few times for a 30-minute virtual intro call on Teams:" in body


def test_recipient_name_from_thanks_same_line():
    name = recipient_display_name(
        "anjana.kummetha@iconicfounders.com",
        "Hi Kory,\n\nWould love to connect.\nThanks,Anju",
    )
    assert name == "Anju"


def test_teams_card_shows_meeting_type_and_rules():
    card = generate_approval_card(
        {
            "id": 9,
            "drafted_reply": "Hi Anju,\n\nDraft.",
            "voice_mode": "lexi",
            "proposed_slots": [
                {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T10:30:00-06:00"},
            ],
            "meeting_type_label": "Intro call (30 min)",
            "rules_status": "Rules: pass",
        },
        {
            "subject": "TEST — intro",
            "sender": "anjana.kummetha@iconicfounders.com",
            "raw_body": "Thanks,Anju",
        },
        [],
    )
    meta_texts = [block.get("text", "") for block in card["body"] if block.get("type") == "TextBlock"]
    combined = " | ".join(meta_texts)
    assert "Type: Intro call (30 min)" in combined
    assert "Rules: pass" in combined


def test_teams_card_slot_uses_mt_not_utc_label():
    card = generate_approval_card(
        {
            "id": 2,
            "drafted_reply": "Hi Anju,\n\nTimes below.",
            "voice_mode": "lexi",
            "proposed_slots": [
                {"start": "2026-06-29T10:00:00-06:00", "end": "2026-06-29T11:00:00-06:00"},
            ],
            "recipient_timezone": "America/Denver",
        },
        {
            "subject": "TEST — intro",
            "sender": "anjana.kummetha@iconicfounders.com",
            "raw_body": "Thanks,Anju",
        },
        [],
    )
    times_block = next(
        block for block in card["body"] if block.get("text", "").startswith("**Times offered**")
    )
    assert "UTC" not in times_block["text"]
    assert "MT" in times_block["text"]

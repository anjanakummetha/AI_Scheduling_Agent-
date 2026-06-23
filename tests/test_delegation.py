"""Tests for delegation detection."""

import os

from app.agents.delegation import detect_delegation


def _with_lexi_mailbox(email: str):
    key = "LEXI_MAILBOX_EMAIL"
    prev = os.environ.get(key)
    os.environ[key] = email
    from importlib import reload

    import app.agents.delegation as delegation_mod
    import app.config as config_mod

    reload(config_mod)
    reload(delegation_mod)
    return prev


def _restore_lexi_mailbox(prev: str | None) -> None:
    key = "LEXI_MAILBOX_EMAIL"
    if prev is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = prev
    from importlib import reload

    import app.agents.delegation as delegation_mod
    import app.config as config_mod

    reload(config_mod)
    reload(delegation_mod)


def test_delegation_phrase_from_kory():
    decision = detect_delegation(
        subject="Intro call",
        body="Looping in my assistant Lexi — she will help coordinate times.",
        sender="kory@iconicfounders.com",
    )
    assert decision.is_delegation
    assert decision.phrase_match


def test_delegation_lexi_cc():
    prev = _with_lexi_mailbox("lexi@ifg.vc")
    try:
        from app.agents.delegation import detect_delegation

        decision = detect_delegation(
            subject="Scheduling",
            body="Please find time next week.",
            sender="kory@iconicfounders.com",
            raw_email={
                "cc_recipients": [{"emailAddress": {"address": "lexi@ifg.vc"}}],
            },
        )
        assert decision.lexi_cc
    finally:
        _restore_lexi_mailbox(prev)


def test_not_delegation_random_mail():
    decision = detect_delegation(
        subject="Dinner?",
        body="Can we meet Thursday?",
        sender="investor@fund.com",
    )
    assert not decision.is_delegation


def test_delegation_cc_and_phrase():
    prev = _with_lexi_mailbox("lexi@ifg.vc")
    try:
        from app.agents.delegation import detect_delegation

        decision = detect_delegation(
            subject="Intro",
            body="My assistant Lexi will follow up on scheduling.",
            sender="kory@iconicfounders.com",
            raw_email={
                "cc_recipients": [{"emailAddress": {"address": "lexi@ifg.vc"}}],
            },
        )
        assert decision.is_delegation
        assert decision.lexi_cc
        assert decision.phrase_match
    finally:
        _restore_lexi_mailbox(prev)

"""Tests for inbound notification filtering."""

import os

from app.agents.inbound_filter import (
    evaluate_inbound_notification,
    is_calendar_invite_response,
    is_newsletter_or_bulk_mail,
    normalize_subject_key,
)


def _with_notify_mode(mode: str):
    """Context manager via save/restore env for notify mode tests."""
    key = "LEXI_TEAMS_INBOUND_NOTIFY_MODE"
    prev = os.environ.get(key)
    os.environ[key] = mode
    from importlib import reload

    import app.config as config_mod

    reload(config_mod)
    return prev


def _restore_notify_mode(prev: str | None) -> None:
    key = "LEXI_TEAMS_INBOUND_NOTIFY_MODE"
    if prev is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = prev
    from importlib import reload

    import app.config as config_mod

    reload(config_mod)


def test_ypo_digest_is_newsletter():
    assert is_newsletter_or_bulk_mail(
        sender="noreply@ypo.org",
        subject="Business Marketplace - Daily Digest 12/June/2026",
        body="4 new posts unsubscribe",
    )


def test_ypo_digest_not_notified():
    decision = evaluate_inbound_notification(
        intent="non_scheduling",
        priority="high",
        sender="noreply@ypo.org",
        subject="Business Marketplace - Daily Digest",
        body="digest content",
    )
    assert not decision.notify
    assert decision.auto_skip


def test_calendar_accept_not_notified():
    assert is_calendar_invite_response(
        sender="travis.rue@gmail.com",
        subject="Accepted: T. Rue | Kory @ Wed Jul 1, 2026 10am - 12pm (MDT)",
        body="Travis Rue has accepted this invitation.",
    )
    decision = evaluate_inbound_notification(
        intent="reschedule",
        priority="low",
        sender="travis.rue@gmail.com",
        subject="Accepted: T. Rue | Kory @ Wed Jul 1, 2026 10am - 12pm (MDT)",
        body="Travis Rue has accepted this invitation.",
    )
    assert not decision.notify
    assert decision.auto_skip


def test_scheduling_investor_not_notified_in_delegation_only_mode():
    prev = _with_notify_mode("delegation_only")
    try:
        decision = evaluate_inbound_notification(
            intent="pitch",
            priority="high",
            sender="investor@fund.com",
            subject="Diligence call next week",
            body="Can we schedule time?",
        )
        assert not decision.notify
        assert decision.reason == "delegation_only_mode"
    finally:
        _restore_notify_mode(prev)


def test_delegation_always_notifies():
    prev = _with_notify_mode("delegation_only")
    try:
        decision = evaluate_inbound_notification(
            intent="delegation",
            priority="high",
            sender="kory@iconicfounders.com",
            subject="Intro",
            body="Lexi will help",
            is_delegation=True,
        )
        assert decision.notify
        assert decision.reason == "delegation_to_lexi"
    finally:
        _restore_notify_mode(prev)


def test_scheduling_investor_notified_when_important_mode():
    prev = _with_notify_mode("important")
    try:
        decision = evaluate_inbound_notification(
            intent="pitch",
            priority="high",
            sender="investor@fund.com",
            subject="Diligence call next week",
            body="Can we schedule time?",
        )
        assert decision.notify
    finally:
        _restore_notify_mode(prev)


def test_subject_dedupe_key_strips_re():
    assert normalize_subject_key("Re: Hello") == normalize_subject_key("hello")

"""Composio retry/backoff at the choke point (plan Phase 4)."""

from __future__ import annotations

import pytest

from app.integrations.composio_client import _execute_with_retry, _is_retryable_error


def test_retryable_classification():
    assert _is_retryable_error(RuntimeError("HTTP 503 overloaded"))
    assert _is_retryable_error(RuntimeError("connection reset"))
    assert _is_retryable_error(RuntimeError("429 rate limit exceeded"))
    assert not _is_retryable_error(RuntimeError("400 invalid request"))
    assert not _is_retryable_error(RuntimeError("404 not found"))
    assert not _is_retryable_error(RuntimeError("something unspecific"))


def test_read_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.integrations.composio_client.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("503 overloaded")
        return "ok"

    assert _execute_with_retry(flaky, is_write=False, tool_slug="OUTLOOK_LIST_MESSAGES") == "ok"
    assert calls["n"] == 3


def test_write_never_retries(monkeypatch):
    monkeypatch.setattr("app.integrations.composio_client.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky_write():
        calls["n"] += 1
        raise RuntimeError("503 overloaded")

    with pytest.raises(RuntimeError):
        _execute_with_retry(flaky_write, is_write=True, tool_slug="OUTLOOK_SEND_EMAIL")
    assert calls["n"] == 1  # a write is attempted exactly once


def test_non_retryable_read_not_retried(monkeypatch):
    monkeypatch.setattr("app.integrations.composio_client.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise RuntimeError("400 invalid request")

    with pytest.raises(RuntimeError):
        _execute_with_retry(bad, is_write=False, tool_slug="OUTLOOK_LIST_MESSAGES")
    assert calls["n"] == 1

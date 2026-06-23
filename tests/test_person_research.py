"""Tests for person research helpers (no live API)."""

from app.integrations.composio_search import SEARCH_ALLOW_SLUGS


def test_scholar_slug_on_allowlist():
    assert "COMPOSIO_SEARCH_SCHOLAR" in SEARCH_ALLOW_SLUGS


def test_search_allowlist_count():
    assert len(SEARCH_ALLOW_SLUGS) >= 20

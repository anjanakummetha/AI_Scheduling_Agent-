"""HubSpot staging — no live writes in tests."""

from __future__ import annotations

from unittest.mock import patch

from app.integrations.hubspot_manager import (
    hubspot_status_brief,
    propose_inactive_cleanup,
    propose_outreach_batch,
)


def test_hubspot_not_configured():
    with patch("app.integrations.hubspot_manager.hubspot_configured", return_value=False):
        brief = hubspot_status_brief()
    assert "not connected" in brief["kory_message"].lower()


@patch("app.integrations.hubspot_manager.search_contacts")
def test_cleanup_proposals_staged_locally(mock_search, tmp_path, monkeypatch):
    monkeypatch.setenv("LEXI_DATABASE_PATH", str(tmp_path / "lexi.db"))
    import importlib
    import app.config

    importlib.reload(app.config)
    from scripts.init_lexi_db import init_lexi_db

    init_lexi_db(tmp_path / "lexi.db")

    mock_search.return_value = {
        "contacts": [
            {"id": "1", "email": "a@x.com", "name": "A", "hs_lead_status": "subscriber"},
            {"id": "2", "email": "b@x.com", "name": "B", "hs_lead_status": "unqualified"},
        ]
    }
    result = propose_inactive_cleanup(limit=10)
    assert result["ok"] is True
    assert result["batch_id"].startswith("hs-")


@patch("app.integrations.hubspot_manager.search_contacts")
def test_outreach_batch_drafts(mock_search):
    mock_search.return_value = {
        "contacts": [{"id": "1", "email": "founder@co.com", "name": "Founder"}]
    }
    result = propose_outreach_batch(goal="reconnect", limit=1)
    assert result["draft_count"] == 1
    assert "approve" in result["kory_message"].lower()

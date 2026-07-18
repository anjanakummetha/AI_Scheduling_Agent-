"""HubSpot expansion — staging only, writes blocked."""

from __future__ import annotations

from unittest.mock import patch

from app.integrations.hubspot_manager import (
    deals_snapshot_for_brief,
    enrich_prebrief_from_hubspot,
    execute_hubspot_batch,
    find_contacts_for_outreach,
    propose_duplicate_merges,
    propose_inactive_cleanup,
    propose_lead_source_fills,
    stage_meeting_note,
)


@patch("app.integrations.hubspot_manager.search_contacts")
def test_inactive_cleanup_uses_activity_age(mock_search, tmp_path, monkeypatch):
    monkeypatch.setenv("LEXI_DATABASE_PATH", str(tmp_path / "lexi.db"))
    import importlib
    import app.config
    import app.storage.lexi_db as lexi_db

    importlib.reload(app.config)
    importlib.reload(lexi_db)
    from scripts.init_lexi_db import init_lexi_db

    init_lexi_db(tmp_path / "lexi.db")
    mock_search.return_value = {
        "contacts": [
            {
                "id": "1",
                "email": "old@x.com",
                "name": "Old",
                "hs_lead_status": "subscriber",
                "lastmodifieddate": "2025-01-01T00:00:00+00:00",
            }
        ]
    }
    out = propose_inactive_cleanup(inactive_days=90, limit=10)
    assert out["ok"]
    assert out["writes_blocked"] is True
    assert out["proposal_count"] >= 1


@patch("app.integrations.hubspot_manager.search_contacts")
def test_duplicate_merges_staged(mock_search, tmp_path, monkeypatch):
    monkeypatch.setenv("LEXI_DATABASE_PATH", str(tmp_path / "lexi.db"))
    import importlib
    import app.config
    import app.storage.lexi_db as lexi_db

    importlib.reload(app.config)
    importlib.reload(lexi_db)
    from scripts.init_lexi_db import init_lexi_db

    init_lexi_db(tmp_path / "lexi.db")
    mock_search.return_value = {
        "contacts": [
            {"id": "1", "email": "a@x.com", "name": "Ann"},
            {"id": "2", "email": "a@x.com", "name": "Ann Duplicate"},
        ]
    }
    out = propose_duplicate_merges(limit=10)
    assert out["pair_count"] == 1
    assert out["writes_blocked"] is True


@patch("app.integrations.hubspot_manager._infer_lead_fields_from_inbox")
@patch("app.integrations.hubspot_manager.search_contacts")
def test_lead_source_fills(mock_search, mock_infer, tmp_path, monkeypatch):
    monkeypatch.setenv("LEXI_DATABASE_PATH", str(tmp_path / "lexi.db"))
    import importlib
    import app.config
    import app.storage.lexi_db as lexi_db

    importlib.reload(app.config)
    importlib.reload(lexi_db)
    from scripts.init_lexi_db import init_lexi_db

    init_lexi_db(tmp_path / "lexi.db")
    mock_search.return_value = {
        "contacts": [{"id": "1", "email": "b@x.com", "name": "Bob", "lifecyclestage": ""}]
    }
    mock_infer.return_value = {"lifecyclestage": "lead", "hs_analytics_source": "OFFLINE"}
    out = propose_lead_source_fills(limit=5)
    assert out["proposal_count"] == 1


@patch("app.integrations.hubspot_manager.hubspot_configured", return_value=True)
@patch("app.integrations.hubspot_manager.search_contacts")
def test_prebrief_enrich(mock_search, _cfg):
    mock_search.return_value = {
        "contacts": [
            {
                "id": "1",
                "email": "c@co.com",
                "name": "Casey",
                "company": "Co",
                "lifecyclestage": "opportunity",
            }
        ]
    }
    out = enrich_prebrief_from_hubspot(email="c@co.com")
    assert out["found"] is True
    assert "HubSpot" in out["kory_message"]


@patch("app.integrations.hubspot_manager.hubspot_writes_blocked", return_value=True)
@patch("app.integrations.hubspot_manager.search_contacts")
def test_meeting_note_staged_not_written(mock_search, _blocked, tmp_path, monkeypatch):
    monkeypatch.setenv("LEXI_DATABASE_PATH", str(tmp_path / "lexi.db"))
    import importlib
    import app.config
    import app.storage.lexi_db as lexi_db

    importlib.reload(app.config)
    importlib.reload(lexi_db)
    from scripts.init_lexi_db import init_lexi_db

    init_lexi_db(tmp_path / "lexi.db")
    mock_search.return_value = {"contacts": [{"id": "1", "email": "d@x.com", "name": "Dan"}]}
    out = stage_meeting_note(email="d@x.com", note="Great intro call", approved=True)
    assert out["dry_run"] is True
    assert out["writes_blocked"] is True


@patch("app.integrations.hubspot_manager.search_contacts")
def test_outreach_candidates(mock_search):
    mock_search.return_value = {
        "contacts": [
            {"id": "1", "email": "e@x.com", "name": "Eve", "lifecyclestage": "lead"},
            {"id": "2", "email": "f@x.com", "name": "Frank", "lifecyclestage": "customer"},
        ]
    }
    out = find_contacts_for_outreach(lifecycle="lead", limit=10)
    assert out["count"] >= 1


@patch("app.integrations.hubspot_manager.hubspot_configured", return_value=True)
@patch("app.integrations.hubspot_manager.execute_hubspot_tool")
def test_deals_snapshot(mock_tool, _cfg):
    mock_tool.return_value = {
        "data": {
            "results": [
                {
                    "id": "d1",
                    "properties": {
                        "dealname": "Series A",
                        "dealstage": "negotiations",
                        "amount": "1000000",
                    },
                }
            ]
        }
    }
    out = deals_snapshot_for_brief(limit=5)
    assert "Series A" in out["kory_message"]


@patch("app.integrations.hubspot_manager.hubspot_writes_blocked", return_value=True)
def test_execute_batch_blocked(mock_blocked, tmp_path, monkeypatch):
    monkeypatch.setenv("LEXI_DATABASE_PATH", str(tmp_path / "lexi.db"))
    import importlib
    import app.config
    import app.storage.lexi_db as lexi_db

    importlib.reload(app.config)
    importlib.reload(lexi_db)
    from scripts.init_lexi_db import init_lexi_db
    from app.integrations.hubspot_manager import _stage_hubspot_batch

    init_lexi_db(tmp_path / "lexi.db")
    batch_id = _stage_hubspot_batch(batch_type="cleanup", payload={"proposals": []})
    out = execute_hubspot_batch(batch_id=batch_id, approved=True)
    assert out["dry_run"] is True
    assert out["writes_blocked"] is True

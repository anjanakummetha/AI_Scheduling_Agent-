"""Read-only /api/v1 dashboard API (token auth + shape)."""

from __future__ import annotations

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from app.storage.lexi_db import get_lexi_connection


TOKEN = "test-token-123"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LEXI_API_ENABLED", "true")
    monkeypatch.setenv("LEXI_API_TOKEN", TOKEN)
    monkeypatch.setenv("LEXI_DASHBOARD_ENABLED", "false")
    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture
def seed_proposal():
    import uuid

    thread = f"apiv1-thread-{uuid.uuid4().hex[:8]}"
    with get_lexi_connection() as conn:
        conn.execute(
            "INSERT INTO email_threads(thread_id, subject, sender) VALUES (?,?,?)",
            (thread, "TEST — intro", "prospect@example.com"),
        )
        cur = conn.execute(
            "INSERT INTO proposals(thread_id, status, intent_classification, proposed_slots) "
            "VALUES (?,?,?,?)",
            (thread, "pending_approval", "referral_or_intro",
             '[{"start":"2026-07-28T09:00:00-06:00","end":"2026-07-28T09:30:00-06:00"}]'),
        )
        pid = cur.lastrowid
        conn.execute(
            "INSERT INTO holds(proposal_id, event_id, slot_start, slot_end, expires_at) "
            "VALUES (?,?,?,?,?)",
            (pid, "evt-1", "2026-07-28T09:00:00-06:00", "2026-07-28T09:30:00-06:00",
             "2026-07-31T00:00:00Z"),
        )
        conn.commit()
    yield pid


def test_health_is_public(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert "db_ok" in r.json()


def test_pending_requires_token(client):
    assert client.get("/api/v1/pending-approvals").status_code == 401
    assert client.get(
        "/api/v1/pending-approvals", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_pending_approvals_with_token(client, seed_proposal):
    r = client.get("/api/v1/pending-approvals", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1
    item = next(i for i in data["items"] if i["id"] == seed_proposal)
    assert item["subject"] == "TEST — intro"
    assert item["requester"] == "prospect@example.com"
    assert isinstance(item["proposed_slots"], list) and item["proposed_slots"]


def test_holds_with_token(client, seed_proposal):
    r = client.get("/api/v1/holds", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_costs_and_audit_shape(client):
    h = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/v1/costs", headers=h).status_code == 200
    assert "items" in client.get("/api/v1/audit?limit=5", headers=h).json()


def test_api_disabled_without_env(monkeypatch):
    monkeypatch.delenv("LEXI_API_ENABLED", raising=False)
    monkeypatch.setenv("LEXI_DASHBOARD_ENABLED", "false")
    from app.main import create_app

    c = TestClient(create_app())
    # Router not mounted → 404, never an unauthenticated data leak.
    assert c.get("/api/v1/pending-approvals").status_code == 404

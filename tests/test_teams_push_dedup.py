"""Teams approval notifications send at most once per proposal."""

import importlib
from unittest.mock import patch


def test_teams_approval_notification_claim_is_idempotent(tmp_path, monkeypatch):
    db = tmp_path / "lexi.db"
    monkeypatch.setenv("LEXI_DATABASE_PATH", str(db))
    import app.config

    importlib.reload(app.config)
    import app.storage.lexi_db as lexi_db

    importlib.reload(lexi_db)
    from scripts.init_lexi_db import init_lexi_db
    from app.storage.lexi_db import get_lexi_connection
    from app.bot import teams_publisher

    importlib.reload(teams_publisher)

    init_lexi_db(db)
    monkeypatch.setattr(teams_publisher, "teams_push_allowed", lambda: True)
    with get_lexi_connection() as conn:
        conn.execute(
            """
            INSERT INTO email_threads (thread_id, subject, sender, received_at, raw_body)
            VALUES ('t-dedup-1', 'TEST', 'a@b.com', '2026-01-01', 'body')
            """
        )
        conn.execute(
            """
            INSERT INTO proposals (thread_id, status, intent_classification, priority_tier)
            VALUES ('t-dedup-1', 'pending_approval', 'pitch', 'high')
            """
        )
        conn.commit()
        proposal_id = int(conn.execute("SELECT id FROM proposals").fetchone()[0])

    assert not teams_publisher._teams_approval_already_notified(proposal_id)
    assert teams_publisher._claim_teams_approval_notification(proposal_id) is True
    assert teams_publisher._teams_approval_already_notified(proposal_id)
    assert teams_publisher._claim_teams_approval_notification(proposal_id) is False

def test_schedule_teams_approval_push_dedupes_concurrent_calls(tmp_path, monkeypatch):
    db = tmp_path / "lexi.db"
    monkeypatch.setenv("LEXI_DATABASE_PATH", str(db))
    import app.config

    importlib.reload(app.config)
    import app.storage.lexi_db as lexi_db

    importlib.reload(lexi_db)
    from scripts.init_lexi_db import init_lexi_db
    from app.storage.lexi_db import get_lexi_connection
    from app.bot import teams_publisher

    importlib.reload(teams_publisher)

    init_lexi_db(db)
    monkeypatch.setattr(teams_publisher, "teams_push_allowed", lambda: True)
    with get_lexi_connection() as conn:
        conn.execute(
            """
            INSERT INTO email_threads (thread_id, subject, sender, received_at, raw_body)
            VALUES ('t-dedup-2', 'TEST', 'a@b.com', '2026-01-01', 'body')
            """
        )
        conn.execute(
            """
            INSERT INTO proposals (thread_id, status, intent_classification, priority_tier)
            VALUES ('t-dedup-2', 'pending_approval', 'pitch', 'high')
            """
        )
        conn.commit()
        proposal_id = int(conn.execute("SELECT id FROM proposals").fetchone()[0])

    with patch("app.bot.teams_publisher.asyncio.get_running_loop", side_effect=RuntimeError), patch(
        "app.bot.teams_publisher.asyncio.run", lambda _coro: None
    ):
        teams_publisher.schedule_teams_approval_push(proposal_id)
        teams_publisher.schedule_teams_approval_push(proposal_id)
        assert proposal_id in teams_publisher._inflight_scheduled_pushes
    teams_publisher._inflight_scheduled_pushes.discard(proposal_id)

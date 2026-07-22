"""Worker heartbeat (plan Phase 4) — freshness signal for the health check.

The orchestrator touches the heartbeat each cycle; /api/health reports its age
so a watchdog can detect a hung/stalled daemon even while the process is alive.
"""

from __future__ import annotations

import time
from typing import Any

from app.storage.lexi_db import get_lexi_connection


def _ensure_table(conn: Any) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS worker_heartbeat (id INTEGER PRIMARY KEY CHECK (id = 1), ts REAL)"
    )


def touch_heartbeat() -> None:
    try:
        with get_lexi_connection() as conn:
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO worker_heartbeat(id, ts) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET ts = excluded.ts",
                (time.time(),),
            )
            conn.commit()
    except Exception:
        pass


def heartbeat_age_seconds() -> float | None:
    """Seconds since the last orchestrator cycle, or None if never recorded."""
    try:
        with get_lexi_connection() as conn:
            _ensure_table(conn)
            row = conn.execute("SELECT ts FROM worker_heartbeat WHERE id = 1").fetchone()
        if not row or row["ts"] is None:
            return None
        return max(0.0, time.time() - float(row["ts"]))
    except Exception:
        return None

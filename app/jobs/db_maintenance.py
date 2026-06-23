"""SQLite retention, session TTL, and vacuum for multi-year Lexi operation."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.storage.lexi_db import get_lexi_connection

logger = logging.getLogger(__name__)

AUDIT_RETENTION_DAYS = int(os.getenv("LEXI_AUDIT_RETENTION_DAYS", "180"))
SESSION_IDLE_DAYS = int(os.getenv("LEXI_SESSION_TTL_DAYS", "7"))
SESSION_CLOSED_RETENTION_DAYS = int(os.getenv("LEXI_SESSION_CLOSED_RETENTION_DAYS", "90"))
RAW_BODY_RETENTION_DAYS = int(os.getenv("LEXI_RAW_BODY_RETENTION_DAYS", "120"))
VACUUM_MIN_FREED_MB = float(os.getenv("LEXI_DB_VACUUM_MIN_FREED_MB", "5"))


def run_db_maintenance_cycle() -> dict[str, Any]:
    """Prune old rows and optionally VACUUM. Safe to run from orchestrator daemon."""
    result: dict[str, Any] = {
        "audit_deleted": 0,
        "sessions_closed": 0,
        "sessions_deleted": 0,
        "raw_bodies_trimmed": 0,
        "feedback_pruned": 0,
        "vacuumed": False,
    }
    try:
        result["audit_deleted"] = _prune_audit_log()
        result["sessions_closed"] = _expire_idle_sessions()
        result["sessions_deleted"] = _delete_old_closed_sessions()
        result["raw_bodies_trimmed"] = _trim_old_email_bodies()
        result["feedback_pruned"] = _prune_approval_feedback()
        result["vacuumed"] = _maybe_vacuum(result)
    except sqlite3.Error as exc:
        logger.warning("DB maintenance failed: %s", exc)
        result["error"] = str(exc)
    if any(result.get(k) for k in ("audit_deleted", "sessions_closed", "sessions_deleted", "raw_bodies_trimmed")):
        logger.info("DB maintenance: %s", {k: v for k, v in result.items() if v})
    return result


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _prune_audit_log() -> int:
    cutoff = _cutoff_iso(AUDIT_RETENTION_DAYS)
    with get_lexi_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM audit_log WHERE timestamp < ?",
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount


def _expire_idle_sessions() -> int:
    cutoff = _cutoff_iso(SESSION_IDLE_DAYS)
    with get_lexi_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE scheduling_sessions
            SET status = 'closed', updated_at = datetime('now')
            WHERE status = 'active'
              AND COALESCE(updated_at, created_at) < ?
            """,
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount


def _delete_old_closed_sessions() -> int:
    cutoff = _cutoff_iso(SESSION_CLOSED_RETENTION_DAYS)
    with get_lexi_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM scheduling_sessions
            WHERE status = 'closed'
              AND COALESCE(updated_at, created_at) < ?
            """,
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount


def _trim_old_email_bodies() -> int:
    """Drop large raw_body blobs for old executed/rejected threads."""
    cutoff = _cutoff_iso(RAW_BODY_RETENTION_DAYS)
    with get_lexi_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE email_threads
            SET raw_body = substr(raw_body, 1, 500)
            WHERE thread_id IN (
                SELECT DISTINCT p.thread_id
                FROM proposals AS p
                WHERE p.status IN ('executed', 'rejected', 'no_reply_needed')
                  AND COALESCE(p.updated_at, p.created_at) < ?
            )
              AND raw_body IS NOT NULL
              AND length(raw_body) > 600
            """,
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount


def _prune_approval_feedback() -> int:
    from app.storage.learning_log import prune_old_feedback

    return prune_old_feedback(days=365)


def _maybe_vacuum(maintenance_result: dict[str, Any]) -> bool:
    pruned = sum(
        int(maintenance_result.get(k) or 0)
        for k in ("audit_deleted", "sessions_deleted", "raw_bodies_trimmed", "feedback_pruned")
    )
    if pruned < 100:
        return False
    db_path = settings.lexi_database_path
    if not db_path.exists():
        return False
    size_before = db_path.stat().st_size
    try:
        with get_lexi_connection() as conn:
            conn.execute("VACUUM")
            conn.commit()
    except sqlite3.Error as exc:
        logger.debug("VACUUM skipped: %s", exc)
        return False
    freed_mb = (size_before - db_path.stat().st_size) / (1024 * 1024)
    return freed_mb >= VACUUM_MIN_FREED_MB


def db_health_snapshot() -> dict[str, Any]:
    """Row counts and size warnings for status endpoints."""
    db_path = settings.lexi_database_path
    if not db_path.exists():
        return {"ok": False, "error": "database missing"}

    size_mb = round(db_path.stat().st_size / (1024 * 1024), 3)
    warnings: list[str] = []
    counts: dict[str, int] = {}
    with get_lexi_connection() as conn:
        table_names = _table_names(conn)
        for table in (
            "audit_log",
            "proposals",
            "scheduling_sessions",
            "kory_memory",
            "approval_feedback",
        ):
            if table not in table_names:
                continue
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            except sqlite3.Error:
                counts[table] = -1
    if counts.get("audit_log", 0) > 50_000:
        warnings.append("audit_log >50k — maintenance will prune on schedule")
    if counts.get("scheduling_sessions", 0) > 5_000:
        warnings.append("scheduling_sessions >5k — check TTL")
    if size_mb > 500:
        warnings.append(f"DB {size_mb}MB — plan archival")
    return {
        "ok": True,
        "path": str(db_path),
        "size_mb": size_mb,
        "table_counts": counts,
        "retention_days": {
            "audit": AUDIT_RETENTION_DAYS,
            "session_idle": SESSION_IDLE_DAYS,
            "session_closed": SESSION_CLOSED_RETENTION_DAYS,
            "raw_body": RAW_BODY_RETENTION_DAYS,
        },
        "warnings": warnings,
    }


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

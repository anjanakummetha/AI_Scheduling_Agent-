"""SQLite connection helpers for the unified Lexi database."""

from __future__ import annotations

import sqlite3

from app.config import settings


def get_lexi_connection() -> sqlite3.Connection:
    """Open a connection to data/lexi.db with foreign keys enabled."""
    settings.lexi_database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.lexi_database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

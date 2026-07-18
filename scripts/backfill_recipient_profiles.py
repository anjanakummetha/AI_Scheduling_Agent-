#!/usr/bin/env python3
"""Backfill recipient_profiles + sender_email from ingested email_threads."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.config import settings
    from app.scheduling.timezone_intel import resolve_recipient_timezone_at_ingest
    from app.storage.lexi_db import get_lexi_connection
    from app.storage.recipient_profiles import normalize_sender_email, upsert_recipient_timezone
    from scripts.init_lexi_db import init_lexi_db

    init_lexi_db(settings.lexi_database_path)
    updated_profiles = 0
    updated_threads = 0

    with get_lexi_connection() as conn:
        rows = conn.execute(
            """
            SELECT thread_id, sender, raw_body, internet_headers_json, recipient_timezone
            FROM email_threads
            ORDER BY received_at DESC
            """
        ).fetchall()

    for row in rows:
        sender = str(row["sender"] or "")
        sender_email = normalize_sender_email(sender)
        if sender_email:
            with get_lexi_connection() as conn:
                conn.execute(
                    "UPDATE email_threads SET sender_email = ? WHERE thread_id = ? AND (sender_email IS NULL OR sender_email = '')",
                    (sender_email, row["thread_id"]),
                )
                conn.commit()
            updated_threads += 1

        headers: list = []
        raw_headers = row["internet_headers_json"]
        if raw_headers:
            try:
                parsed = json.loads(raw_headers)
                if isinstance(parsed, list):
                    headers = parsed
            except (TypeError, json.JSONDecodeError):
                pass

        result = resolve_recipient_timezone_at_ingest(
            sender_email=sender_email or sender,
            body=str(row["raw_body"] or ""),
            internet_headers=headers,
            exclude_thread_id=str(row["thread_id"]),
        )
        if result.source in {"internal_default", "none", "stored"}:
            continue
        if result.tz_name():
            upsert_recipient_timezone(
                email=sender_email or sender,
                timezone=result.tz_name() or "",
                source=result.source,
            )
            updated_profiles += 1

    print(
        f"[backfill] sender_email rows touched: {updated_threads}; "
        f"profiles upserted: {updated_profiles}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

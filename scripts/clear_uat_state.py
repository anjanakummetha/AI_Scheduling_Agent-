#!/usr/bin/env python3
"""Clear UAT logs and TEST proposals from local Lexi databases."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG_FILES = (
    "hermes_gateway.log",
    "listen_outlook.log",
    "ngrok.log",
)
PID_FILES = (
    "hermes_gateway.pid",
    "listen_outlook.pid",
    "ngrok.pid",
)


def _clear_test_rows(db_path: Path) -> dict[str, int]:
    if not db_path.is_file():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        thread_ids = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT thread_id FROM email_threads
                WHERE subject LIKE 'TEST%' OR subject LIKE '%TEST —%'
                """
            ).fetchall()
        ]
        dry_run_ids = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT thread_id FROM email_threads
                WHERE thread_id LIKE 'dry-run-%'
                   OR thread_id LIKE 'debug-%'
                   OR thread_id LIKE 'dbg-%'
                """
            ).fetchall()
        ]
        all_threads = sorted(set(thread_ids + dry_run_ids))
        if not all_threads:
            return {"proposals": 0, "threads": 0}

        proposal_ids = [
            int(r[0])
            for r in conn.execute(
                f"""
                SELECT id FROM proposals
                WHERE thread_id IN ({",".join("?" * len(all_threads))})
                """,
                all_threads,
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        if proposal_ids:
            ph = ",".join("?" * len(proposal_ids))
            for table, col in (
                ("holds", "proposal_id"),
                ("approvals", "proposal_id"),
                ("approval_feedback", "proposal_id"),
            ):
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE {col} IN ({ph})",
                    proposal_ids,
                )
                counts[table] = cur.rowcount
            cur = conn.execute(
                f"DELETE FROM audit_log WHERE reference_id IN ({ph})",
                [str(pid) for pid in proposal_ids],
            )
            counts["audit_log"] = cur.rowcount
            cur = conn.execute(f"DELETE FROM proposals WHERE id IN ({ph})", proposal_ids)
            counts["proposals"] = cur.rowcount

        ph_t = ",".join("?" * len(all_threads))
        cur = conn.execute(
            f"DELETE FROM email_threads WHERE thread_id IN ({ph_t})",
            all_threads,
        )
        counts["email_threads"] = cur.rowcount
        conn.commit()
        return counts
    finally:
        conn.close()


def _truncate_logs() -> list[str]:
    cleared: list[str] = []
    logs_dir = ROOT / "logs"
    if not logs_dir.is_dir():
        return cleared
    for name in LOG_FILES:
        path = logs_dir / name
        if path.is_file():
            path.write_text("", encoding="utf-8")
            cleared.append(name)
    for name in PID_FILES:
        path = logs_dir / name
        if path.is_file():
            path.unlink()
            cleared.append(f"removed {name}")
    return cleared


def main() -> int:
    print("=== Clear UAT state ===\n")
    log_result = _truncate_logs()
    if log_result:
        print("Logs:", ", ".join(log_result))
    else:
        print("Logs: (none cleared)")

    dbs = [ROOT / "data" / "lexi.db", ROOT / "data" / "lexi_local.db"]
    for db in dbs:
        counts = _clear_test_rows(db)
        if not counts:
            print(f"{db.name}: no TEST rows")
            continue
        print(f"{db.name}: {counts}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

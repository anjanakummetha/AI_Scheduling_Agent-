#!/usr/bin/env python3
"""Verify Lexi local stack: Composio read access, DB, FastAPI health."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.config import settings
from app.integrations.composio_client import get_composio, require_composio_connection_id
from app.integrations.outlook_calendar import get_calendar_events
from scripts.init_lexi_db import init_lexi_db


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def main() -> int:
    print("\n=== Lexi Stack Verification ===\n")
    all_ok = True

    init_lexi_db()
    all_ok &= _check("SQLite DB", settings.lexi_database_path.exists(), str(settings.lexi_database_path))

    api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
    all_ok &= _check("COMPOSIO_API_KEY set", bool(api_key))

    try:
        connection_id = require_composio_connection_id()
        all_ok &= _check("KORY_COMPOSIO_CONNECTION_ID", True, connection_id)
        composio = get_composio()
        account = composio.connected_accounts.get(connection_id)
        account_id = getattr(account, "id", None) or getattr(account, "nanoid", None) or connection_id
        all_ok &= _check("Composio connected account", True, str(account_id))
    except Exception as exc:
        all_ok &= _check("Composio connected account", False, str(exc))

    dry_run = settings.lexi_dry_run
    _check("LEXI_DRY_RUN (no Outlook writes)", dry_run, "enabled" if dry_run else "DISABLED — will send/create")

    llm_ok = bool(settings.llm_api_key) and "11434" not in settings.llm_base_url
    all_ok &= _check(
        "Anthropic LLM",
        llm_ok,
        f"model={settings.llm_model} base={settings.llm_base_url}"
        if llm_ok
        else "set ANTHROPIC_API_KEY (or LLM_API_KEY); do not use Ollama",
    )

    _check(
        "Lexi write mode",
        settings.lexi_write_mode in {"sandbox", "kory"},
        f"{settings.lexi_write_mode} → {settings.sandbox_composio_connection_id or settings.kory_composio_connection_id}",
    )
    _check(
        "Sandbox mailbox",
        bool(settings.sandbox_mailbox_email) or settings.lexi_write_mode == "kory",
        settings.sandbox_mailbox_email or "n/a (kory write mode)",
    )

    asana_gid = settings.asana_project_gid or ""
    asana_conn = settings.asana_composio_connection_id or ""
    _check(
        "Asana board (Lexi Booking reminders)",
        bool(asana_gid and asana_conn),
        "set ASANA_PROJECT_GID + ASANA_COMPOSIO_CONNECTION_ID when ready"
        if not (asana_gid and asana_conn)
        else f"project={asana_gid[:8]}... connection={asana_conn[:8]}...",
    )

    if api_key and all_ok:
        try:
            start = datetime.now(timezone.utc)
            end = start + timedelta(days=7)
            events, log_id = get_calendar_events(start.isoformat(), end.isoformat())
            all_ok &= _check(
                "Outlook calendar READ",
                True,
                f"{len(events)} blocking/busy events in next 7 days (log={log_id})",
            )
        except Exception as exc:
            all_ok &= _check("Outlook calendar READ", False, str(exc))

    teams_id = os.getenv("TEAMS_CLIENT_ID", "").strip()
    teams_secret = os.getenv("TEAMS_CLIENT_SECRET", "").strip()
    allowed = os.getenv("TEAMS_ALLOWED_USERS", "").strip()
    all_ok &= _check("Teams bot credentials", bool(teams_id and teams_secret), f"app_id={teams_id[:8]}...")
    _check("Teams allowlist", bool(allowed), allowed or "(empty — all senders blocked)")

    from app.worker.runner import is_worker_running

    _check(
        "Lexi worker running",
        is_worker_running(),
        "start Hermes gateway (embeds worker) or: python -m app.worker",
    )

    print("\n  Azure Bot → Hermes :3978 /api/messages (Hermes-only Teams)")
    print("  Composio webhook (optional) → :8780/webhooks/composio")
    print("  Debug dashboard: LEXI_DASHBOARD_ENABLED=true uvicorn app.main:create_app --factory --port 8080\n")

    if all_ok:
        print("=== All critical checks passed ===\n")
        return 0
    print("=== Some checks failed — fix .env / Composio connect before live test ===\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

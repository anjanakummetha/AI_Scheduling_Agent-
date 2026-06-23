#!/usr/bin/env python3
"""Quick gate before local Mac testing (Kory inbox — approval required for sends)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    return ok


def main() -> int:
    from app.config import settings
    from app.safety.approval_gate import kory_approves_all, require_kory_approval_env

    print("\n=== Local Mac testing gate ===\n")

    results = [
        check("LEXI_LOCAL_MODE", os.getenv("LEXI_LOCAL_MODE", "").lower() in {"1", "true", "yes"}),
        check(
            "Local database (not production lexi.db)",
            "lexi_local" in str(settings.lexi_database_path),
            str(settings.lexi_database_path),
        ),
        check("Kory read connection", bool(settings.kory_composio_connection_id)),
        check("Lexi mailbox connection", bool(settings.lexi_composio_connection_id)),
        check("LEXI_REQUIRE_KORY_APPROVAL", require_kory_approval_env()),
        check("kory_approves_all", kory_approves_all()),
        check(
            "Approval before live sends",
            require_kory_approval_env() and kory_approves_all(),
            "sends/holds need Teams approval even when dry_run=false",
        ),
        check("Teams credentials", bool(os.getenv("TEAMS_CLIENT_ID", "").strip())),
        check("Anthropic API key", bool(settings.llm_api_key)),
        check(
            "Teams conversation registered",
            (ROOT / "data" / "teams_conversation.json").exists()
            or bool(os.getenv("TEAMS_CONVERSATION_ID", "").strip()),
        ),
    ]

    # auto_execute check
    auto = os.getenv("LEXI_AUTO_EXECUTE_ENABLED", "false").lower() in {"1", "true", "yes"}
    results.append(check("LEXI_AUTO_EXECUTE_ENABLED off", not auto, os.getenv("LEXI_AUTO_EXECUTE_ENABLED", "false")))

    if settings.lexi_dry_run:
        print("\n  Note: LEXI_DRY_RUN=true — previews only, no real sends/holds.")
    else:
        print("\n  Note: LEXI_DRY_RUN=false — real sends/holds AFTER Kory approves in Teams.")

    print("\n  Before starting:")
    print("    1) Stop VPS: sudo systemctl stop lexi-hermes  (avoid double-processing mail)")
    print("    2) Terminal A: hermes gateway run --replace")
    print("    3) Terminal B: ngrok http 3978  → update Azure Bot messaging URL")
    print("    4) Terminal C: .venv/bin/python scripts/listen_outlook_local.py")
    print("    5) Send TEST emails from anjana.kummetha@iconicfounders.com → Kory\n")

    failed = sum(1 for ok in results if not ok)
    if failed:
        print(f"{failed} check(s) failed.\n")
        return 1
    print("ALL PASS — safe to start local Mac testing.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

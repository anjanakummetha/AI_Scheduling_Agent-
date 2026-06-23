#!/usr/bin/env python3
"""Verify Teams bot credentials + conversation for Phase B live chat.

Usage:
    .venv/bin/python scripts/verify_teams_connection.py
    .venv/bin/python scripts/verify_teams_connection.py --live-ping   # posts test DM to Teams
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

REPORT = ROOT / "docs" / "TEAMS_CONNECTION_REPORT.json"


def _check(name: str, ok: bool, detail: str = "") -> dict:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return {"name": name, "ok": ok, "detail": detail}


async def _test_bot_token() -> tuple[bool, str]:
    import os

    from botframework.connector.auth import MicrosoftAppCredentials

    app_id = os.getenv("TEAMS_CLIENT_ID", "").strip()
    secret = os.getenv("TEAMS_CLIENT_SECRET", "").strip()
    tenant = os.getenv("TEAMS_TENANT_ID", "").strip() or None
    if not app_id or not secret:
        return False, "missing credentials"
    try:
        creds = MicrosoftAppCredentials(app_id, secret, channel_auth_tenant=tenant)
        token_result = creds.get_access_token()
        if asyncio.iscoroutine(token_result):
            token = await token_result
        else:
            token = token_result
        return bool(token), f"token_len={len(str(token or ''))}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _live_ping() -> tuple[bool, str]:
    from app.bot.teams_publisher import push_approval_text_to_teams

    text = (
        "**Lexi — Phase B connection test**\n\n"
        "If you see this in Teams, proactive delivery is working.\n"
        "Outlook send/write remain OFF for UAT.\n\n"
        "Reply in Hermes chat: `help`"
    )
    try:
        await push_approval_text_to_teams(text, proposal_id="phase-b-ping")
        return True, "message sent to registered conversation"
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    import os

    from app.bot.teams_conversation_store import (
        STORE_PATH,
        load_conversation_reference,
        teams_delivery_ready,
    )
    from app.config import settings

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live-ping",
        action="store_true",
        help="Send a test message to the registered Teams conversation",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Production cutover: expect live writes with approval gates (not read-only UAT)",
    )
    args = parser.parse_args()
    production = args.production

    title = "Teams connection verification (production)" if production else "Teams connection verification (Phase B)"
    print(f"\n=== {title} ===\n")
    results: list[dict] = []

    results.append(
        _check(
            "LEXI_TEAMS_ENABLED (proactive cards from worker)",
            settings.lexi_teams_enabled,
            "set LEXI_TEAMS_ENABLED=true in .env for inbound email cards",
        )
    )
    results.append(
        _check(
            "LEXI_TEAMS_TEXT_ONLY=false (Adaptive Cards)",
            not settings.lexi_teams_text_only,
            str(settings.lexi_teams_text_only),
        )
    )
    results.append(
        _check(
            "TEAMS_CLIENT_ID",
            bool(os.getenv("TEAMS_CLIENT_ID", "").strip()),
            (os.getenv("TEAMS_CLIENT_ID", "")[:8] + "...") if os.getenv("TEAMS_CLIENT_ID") else "",
        )
    )
    results.append(
        _check("TEAMS_CLIENT_SECRET", bool(os.getenv("TEAMS_CLIENT_SECRET", "").strip()), "set")
    )
    results.append(
        _check("TEAMS_TENANT_ID", bool(os.getenv("TEAMS_TENANT_ID", "").strip()), "set")
    )
    allowed = os.getenv("TEAMS_ALLOWED_USERS", "").strip()
    results.append(
        _check("TEAMS_ALLOWED_USERS", bool(allowed), f"{len(allowed.split(','))} user(s)" if allowed else "")
    )

    ref = load_conversation_reference()
    cid = (ref or {}).get("conversation_id", "")
    results.append(
        _check(
            "Teams conversation registered",
            bool(cid),
            f"{cid[:28]}..." if cid else f"no ref — DM Hermes once or set {STORE_PATH.name}",
        )
    )
    results.append(_check("teams_cards_ready", teams_delivery_ready()))

    hermes_cfg = Path.home() / ".hermes" / "config.yaml"
    hermes_env = Path.home() / ".hermes" / ".env"
    results.append(_check("~/.hermes/.env exists", hermes_env.exists()))
    if hermes_cfg.exists():
        text = hermes_cfg.read_text(encoding="utf-8")
        results.append(
            _check(
                "Lexi MCP in ~/.hermes/config.yaml",
                "hermes_mcp_server.py" in text or "lexi-scheduling" in text,
            )
        )
    else:
        results.append(_check("~/.hermes/config.yaml exists", False, "run setup_hermes_mcp.py"))

    results.append(_check("agent_instructions.txt", (ROOT / "agent_instructions.txt").exists()))
    if production:
        from app.safety.approval_gate import (
            auto_execute_allowed,
            immediate_send_allowed,
            require_kory_approval_env,
        )

        results.append(_check("Production: LEXI_DRY_RUN off", not settings.lexi_dry_run))
        results.append(
            _check(
                "Production: Kory writes unlocked",
                not settings.lexi_kory_space_read_only and not settings.lexi_kory_outbound_blocked,
            )
        )
        results.append(_check("Production: require Kory approval", require_kory_approval_env()))
        results.append(_check("Production: auto_execute off", not auto_execute_allowed()))
        results.append(_check("Production: immediate_send off", not immediate_send_allowed()))
    else:
        results.append(_check("Safety: LEXI_DRY_RUN", settings.lexi_dry_run))
        results.append(_check("Safety: Kory read-only", settings.lexi_kory_space_read_only))

    print("\n--- Bot Framework auth (live) ---")
    token_ok, token_detail = asyncio.run(_test_bot_token())
    results.append(_check("Bot Framework token", token_ok, token_detail))

    if args.live_ping:
        print("\n--- Live Teams ping ---")
        if not teams_delivery_ready():
            results.append(_check("Live ping", False, "teams_cards_ready=false"))
        else:
            ping_ok, ping_detail = asyncio.run(_live_ping())
            results.append(_check("Live ping to Teams DM", ping_ok, ping_detail))

    failed = [r for r in results if not r.get("ok")]
    report = {
        "teams_cards_ready": teams_delivery_ready(),
        "conversation_id_prefix": cid[:28] if cid else None,
        "store_path": str(STORE_PATH),
        "failed_count": len(failed),
        "checks": results,
        "phase_b_chat_ready": len(failed) == 0,
        "note": (
            "Hermes gateway must be running with Azure Bot endpoint pointed at "
            ":3978/api/messages for inbound Teams chat."
        ),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    if failed:
        print(f"TEAMS NOT FULLY READY — {len(failed)} check(s) failed")
        for r in failed:
            print(f"  • {r['name']}: {r.get('detail', '')}")
    else:
        print("TEAMS CONNECTION READY for Phase B chat testing")
        print("Start: hermes gateway run --replace  (+ ngrok → Azure Bot if local)")
    print(f"Report: {REPORT}")
    print("=" * 60 + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

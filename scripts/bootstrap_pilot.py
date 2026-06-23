#!/usr/bin/env python3
"""Run automated pilot bootstrap checks (Phases 1–3, 6). User actions needed for Azure/ngrok."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.bot.teams_conversation_store import load_conversation_reference, teams_delivery_ready
from app.config import settings


def _run(cmd: list[str], label: str) -> bool:
    print(f"\n── {label} ──")
    result = subprocess.run(cmd, cwd=ROOT)
    ok = result.returncode == 0
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
    return ok


def _sync_teams_conversation() -> bool:
    store = ROOT / "data" / "teams_conversation.json"
    if not store.exists():
        print("  [skip] no data/teams_conversation.json")
        return False
    data = json.loads(store.read_text(encoding="utf-8"))
    cid = data.get("conversation_id", "")
    if not cid:
        return False
    print(f"  [ok] Teams conversation on file (id starts {cid[:24]}…)")
    return True


def main() -> int:
    print("\n=== Lexi pilot bootstrap (automated phases) ===\n")
    failures = 0

    # Phase 1 — config
    print("Phase 1 — Config")
    write_ok = (
        settings.lexi_write_mode == "kory" and settings.kory_composio_connection_id
    ) or (
        settings.lexi_write_mode == "sandbox" and settings.sandbox_composio_connection_id
    )
    checks = [
        ("Kory read connection", bool(settings.kory_composio_connection_id)),
        ("Write connection", write_ok),
        (
            f"LEXI_WRITE_MODE={settings.lexi_write_mode}",
            settings.lexi_write_mode in {"kory", "sandbox"},
        ),
        ("LEXI_REQUIRE_KORY_APPROVAL", os.getenv("LEXI_REQUIRE_KORY_APPROVAL", "").lower() in {"1", "true", "yes"}),
        ("LEXI_TEAMS_ENABLED", settings.lexi_teams_enabled),
        ("Poll Kory inbox", os.getenv("LEXI_ORCHESTRATOR_POLL_OUTLOOK", "").lower() in {"1", "true", "yes"}),
        ("LEXI_EMBED_WORKER", os.getenv("LEXI_EMBED_WORKER", "true").lower() in {"1", "true", "yes"}),
        ("ASANA_ENABLED + project GID", settings.asana_enabled and bool(settings.asana_project_gid)),
    ]

    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures += 1

    # Phase 5 partial — conversation
    print("\nPhase 5 — Teams conversation (cards)")
    ref = load_conversation_reference()
    cards = teams_delivery_ready()
    print(f"  [{'PASS' if ref else 'FAIL'}] conversation reference loaded")
    print(f"  [{'PASS' if cards else 'FAIL'}] teams_cards_ready")
    if not ref:
        failures += 1
    if not cards:
        failures += 1
    _sync_teams_conversation()

    # Phase 2 — Composio trigger (attempt)
    print("\nPhase 2 — Composio Kory inbox trigger")
    if not _run([sys.executable, str(ROOT / "setup.py")], "Register OUTLOOK_MESSAGE_TRIGGER on Kory"):
        print("  (If trigger already exists, this may be OK — check Composio dashboard)")

    # Phase 3 — Hermes MCP
    print("\nPhase 3 — Hermes MCP")
    hermes_cfg = Path.home() / ".hermes" / "config.yaml"
    if hermes_cfg.exists() and "hermes_mcp_server.py" in hermes_cfg.read_text(encoding="utf-8"):
        print("  [PASS] Lexi MCP registered in ~/.hermes/config.yaml")
    else:
        print("  [FAIL] Run: .venv/bin/python scripts/setup_hermes_mcp.py and merge into config")
        failures += 1
    prefill = ROOT / "agent_prefill_messages.json"
    instructions = ROOT / "agent_instructions.txt"
    print(f"  [{'PASS' if instructions.exists() else 'FAIL'}] agent_instructions.txt")
    print(f"  [{'PASS' if prefill.exists() else 'FAIL'}] agent_prefill_messages.json (Hermes prefill)")

    # Phase 6 — verify scripts
    print("\nPhase 6 — Automated tests")
    for script in (
        "scripts/verify_pre_kory_switch.py",
        "scripts/test_approval_safety.py",
        "scripts/test_mcp_tools.py",
    ):
        if not _run([sys.executable, str(ROOT / script)], script):
            failures += 1

    # User-required phases
    print("\n" + "=" * 60)
    print("YOU NEED TO DO (cannot automate from here):")
    print("=" * 60)
    print("""
Phase 4 — Teams tunnel
  1. Terminal A:  hermes gateway run --replace
  2. Terminal B:  ngrok http 3978
  3. Azure Bot → Configuration → Messaging endpoint:
     https://<ngrok-host>/api/messages

Phase 6 — Live test (with Hermes running)
  1. Kory DMs the bot in Teams (refreshes conversation if needed)
  2. Send a scheduling email to Kory's inbox
  3. Wait ~30s → Adaptive Card in Teams DM
  4. draft <id> yes  →  approve <id> option 1

If ngrok URL changes, update Azure Bot endpoint each time.
""")

    if failures:
        print(f"\nBootstrap finished with {failures} automated failure(s).\n")
        return 1
    print("\nAll automated phases passed. Start Hermes + ngrok to finish.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

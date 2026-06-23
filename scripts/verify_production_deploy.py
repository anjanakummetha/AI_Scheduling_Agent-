#!/usr/bin/env python3
"""Production deploy gate — no sends; validates config, safety, and integrations."""

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

PY = sys.executable
REPORT = ROOT / "docs" / "PRODUCTION_DEPLOY_REPORT.json"


def _run(script: str, *args: str) -> tuple[bool, str]:
    r = subprocess.run(
        [PY, str(ROOT / script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    tail = (r.stdout + r.stderr).strip().splitlines()
    detail = tail[-1] if tail else f"exit {r.returncode}"
    return r.returncode == 0, detail


def main() -> int:
    from app.config import settings
    from app.safety.approval_gate import (
        auto_execute_allowed,
        immediate_send_allowed,
        kory_approves_all,
        require_kory_approval_env,
    )

    print("\n=== Production deploy verification (no sends) ===\n")
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        line = f"  [{status}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
        checks.append({"name": name, "ok": ok, "detail": detail})

    # Config
    check("LEXI_DRY_RUN off", not settings.lexi_dry_run)
    check("LEXI_WRITE_MODE=kory", settings.lexi_write_mode == "kory", settings.lexi_write_mode)
    check("Kory outbound enabled", not settings.lexi_kory_outbound_blocked)
    check("Kory space writes enabled", not settings.lexi_kory_space_read_only)
    check("kory_approves_all", kory_approves_all())
    check("LEXI_REQUIRE_KORY_APPROVAL", require_kory_approval_env())
    check("auto_execute off", not auto_execute_allowed())
    check("immediate_send off", not immediate_send_allowed())
    check("Lexi + Kory Composio IDs", bool(settings.lexi_composio_connection_id and settings.kory_composio_connection_id))
    check("Teams enabled", settings.lexi_teams_enabled)
    check("delegation_only inbound", settings.lexi_teams_inbound_notify_mode == "delegation_only")
    public = (os.getenv("LEXI_WEBHOOK_PUBLIC_URL") or "").strip()
    check(
        "LEXI_WEBHOOK_PUBLIC_URL (HTTPS)",
        public.startswith("https://"),
        public or "set https://lexi.iconicfounders.com on VPS before Composio webhook",
    )
    webhook_on = os.getenv("LEXI_WEBHOOK_ENABLED", "false").lower() in {"1", "true", "yes"}
    poll_on = os.getenv("LEXI_ORCHESTRATOR_POLL_OUTLOOK", "true").lower() in {"1", "true", "yes"}
    check("Webhook ingress enabled", webhook_on)
    check("Frequent poll off", not poll_on)

    suites = [
        ("Approval safety", "scripts/test_approval_safety.py"),
        ("Production cutover", "scripts/verify_pre_kory_switch.py", "--production-cutover"),
        ("Teams connection", "scripts/verify_teams_connection.py", "--production"),
        ("MCP tools", "scripts/test_mcp_tools.py"),
        ("Phase suite (CI, no live send)", "scripts/test_kory_phase_suite.py", "--ci", "--skip-live-llm"),
        ("Mock pipeline", "scripts/test_lexi_pipeline.py"),
    ]
    if settings.lexi_write_mode == "kory":
        check(
            "E2E staging (skipped — kory write mode sends real mail)",
            True,
            "run manually with LEXI_DRY_RUN=true if needed",
        )
    else:
        suites.append(
            ("E2E staging (no approval send)", "scripts/test_live_e2e.py", "--skip-approval"),
        )
    for item in suites:
        label = item[0]
        ok, detail = _run(*item[1:])
        check(label, ok, detail)

    failed = sum(1 for c in checks if not c["ok"])
    infra_blockers = [
        c for c in checks
        if not c["ok"] and c["name"] in {"LEXI_WEBHOOK_PUBLIC_URL (HTTPS)"}
    ]
    report = {
        "failed": failed,
        "checks": checks,
        "code_ready": failed == len(infra_blockers),
        "infra_blockers": [c["name"] for c in infra_blockers],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nReport: {REPORT}")
    if failed == 0:
        print("\nALL PASS — code + config ready for production deploy.\n")
        return 0
    if report["code_ready"]:
        print(
            f"\n{failed} check(s) failed — mostly infra/DNS on VPS. "
            "Code and safety gates look ready.\n"
        )
        return 0
    print(f"\n{failed} check(s) failed — fix before deploy.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

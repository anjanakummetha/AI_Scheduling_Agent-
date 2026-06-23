#!/usr/bin/env python3
"""Verify webhook-first ingress is configured before production cutover."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.orchestrator import describe_ingress_mode


def _check(name: str, ok: bool, detail: str = "") -> dict:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {name}" + (f" — {detail}" if detail else "")
    print(line)
    return {"name": name, "ok": ok, "detail": detail}


def main() -> int:
    load_dotenv(ROOT / ".env")
    failed = 0
    ingress = describe_ingress_mode(
        interval_seconds=int(os.getenv("LEXI_ORCHESTRATOR_INTERVAL", "30"))
    )

    print("\n=== Webhook ingress verification ===\n")

    webhook_on = ingress["webhook_enabled"]
    poll_on = ingress["poll_outlook"]
    backup = ingress["backup_poll_minutes"]
    public = (os.getenv("LEXI_WEBHOOK_PUBLIC_URL") or "").strip()

    for item in [
        _check("LEXI_WEBHOOK_ENABLED or LEXI_WEBHOOK_PORT", webhook_on, str(ingress.get("detail"))),
        _check("Frequent poll OFF (saves Composio budget)", not poll_on, f"poll={poll_on}"),
        _check(
            "Backup poll configured (optional safety net)",
            backup > 0 or webhook_on,
            f"backup_poll_minutes={backup}",
        ),
        _check(
            "LEXI_WEBHOOK_PUBLIC_URL set for Composio",
            bool(public.startswith("https://")),
            public[:60] + ("..." if len(public) > 60 else "") if public else "unset",
        ),
        _check("KORY_COMPOSIO_CONNECTION_ID", bool(os.getenv("KORY_COMPOSIO_CONNECTION_ID")), ""),
        _check("COMPOSIO_API_KEY", bool(os.getenv("COMPOSIO_API_KEY")), ""),
    ]:
        if not item["ok"]:
            failed += 1

    if public.startswith("https://"):
        health_url = public.rstrip("/")
        if not health_url.endswith("/webhooks/composio"):
            health_url = health_url.replace("/webhooks/composio", "")
        health_url = health_url.rstrip("/") + "/api/health"
        try:
            resp = requests.get(health_url, timeout=10)
            item = _check(
                "Public /api/health reachable",
                resp.status_code == 200,
                f"{health_url} → HTTP {resp.status_code}",
            )
        except Exception as exc:
            item = _check("Public /api/health reachable", False, f"{type(exc).__name__}: {exc}")
        if not item["ok"]:
            failed += 1

    report = {
        "ingress": ingress,
        "checks_passed": 6 - failed if failed <= 6 else "see output",
        "failed": failed,
    }
    out = ROOT / "docs" / "WEBHOOK_INGRESS_REPORT.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {out}")
    print(f"\n{'ALL PASS' if failed == 0 else f'{failed} check(s) need attention'}\n")
    if failed:
        print("Deploy steps:")
        print("  1. Expose :8780 (or reverse-proxy) with stable HTTPS URL")
        print("  2. Set LEXI_WEBHOOK_PUBLIC_URL=https://your-host")
        print("  3. .venv/bin/python scripts/register_composio_webhook.py")
        print("  4. .venv/bin/python scripts/ensure_outlook_trigger.py")
        print("  5. Restart Hermes / worker\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

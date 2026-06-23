#!/usr/bin/env python3
"""Register Lexi's public webhook URL with Composio (one-time per deploy URL)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WEBHOOK_PATH = "/webhooks/composio"
COMPOSIO_WEBHOOK_API = "https://backend.composio.dev/api/v3.1/webhook_subscriptions"


def _normalize_public_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        raise SystemExit("Webhook URL is required.")
    if not url.startswith("https://"):
        raise SystemExit("Webhook URL must be HTTPS (Composio requires a public endpoint).")
    if not url.endswith(WEBHOOK_PATH):
        url = f"{url}{WEBHOOK_PATH}"
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Register Composio → Lexi webhook subscription")
    parser.add_argument(
        "--url",
        help="Public base or full URL (e.g. https://api.example.com or .../webhooks/composio)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print payload only; do not POST")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("COMPOSIO_API_KEY is missing in .env")

    public = args.url or os.getenv("LEXI_WEBHOOK_PUBLIC_URL", "").strip()
    webhook_url = _normalize_public_url(public)

    payload = {
        "webhook_url": webhook_url,
        "enabled_events": ["composio.trigger.message"],
    }

    print("\n=== Composio webhook subscription ===\n")
    print(f"Target: {webhook_url}")
    print(f"Events: {payload['enabled_events']}")

    if args.dry_run:
        print("\n(dry-run — not posting)\n")
        return 0

    response = requests.post(
        COMPOSIO_WEBHOOK_API,
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    print(f"\nHTTP {response.status_code}")
    try:
        print(response.json())
    except Exception:
        print(response.text[:500])

    if response.status_code >= 400:
        print(
            "\nIf subscription already exists, update it in the Composio dashboard "
            "or delete the old subscription and re-run this script."
        )
        return 1

    print(
        "\nNext: ensure OUTLOOK_MESSAGE_TRIGGER exists on Kory's connection:\n"
        "  .venv/bin/python scripts/ensure_outlook_trigger.py\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Optional live smoke test for Composio Search (costs API calls).

Usage:
    .venv/bin/python scripts/test_composio_search_live.py
    .venv/bin/python scripts/test_composio_search_live.py --query "best steakhouses Denver"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.integrations.composio_search import search_enabled, web_search


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="Denver to New York flights next Friday")
    args = parser.parse_args()

    if not search_enabled():
        print("FAIL: Composio Search not enabled (COMPOSIO_API_KEY / LEXI_COMPOSIO_SEARCH_ENABLED)")
        return 1

    print(f"Searching: {args.query}")
    try:
        result = web_search(args.query)
        print(json.dumps(result, indent=2, default=str)[:4000])
        print("\nPASS: Composio Search returned data.")
        return 0
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

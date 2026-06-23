#!/usr/bin/env python3
"""Run Lexi headless worker: python -m app.worker [--webhook] [--no-poll]."""

from __future__ import annotations

import argparse
import signal
import sys
import time

from app.worker.runner import is_worker_running, start_lexi_worker, stop_lexi_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Lexi headless worker (no FastAPI :8000)")
    parser.add_argument(
        "--webhook",
        action="store_true",
        help="Enable Composio webhook HTTP server (LEXI_WEBHOOK_PORT, default 8780)",
    )
    parser.add_argument(
        "--no-poll",
        action="store_true",
        help="Disable Kory inbox polling (webhook-only ingress)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Orchestrator cycle interval in seconds (default: env or 30)",
    )
    args = parser.parse_args()

    status = start_lexi_worker(
        webhook=True if args.webhook else None,
        poll_outlook=False if args.no_poll else None,
        interval_seconds=args.interval,
    )
    print(status, flush=True)

    if not is_worker_running():
        print("Lexi worker failed to start.", file=sys.stderr)
        return 1

    def _shutdown(_signum: int, _frame: object) -> None:
        print("\n[lexi-worker] shutting down...", flush=True)
        stop_lexi_worker()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("[lexi-worker] running — Ctrl+C to stop", flush=True)
    while is_worker_running():
        time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

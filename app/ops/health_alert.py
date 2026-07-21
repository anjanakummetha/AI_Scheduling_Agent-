"""Ops alerting (plan Phase 4) — push a health/incident alert to Kory in Teams.

Called by the watchdog when /api/health is unhealthy. Best-effort: if Teams isn't
reachable, print to stderr so the journal still captures it.
"""

from __future__ import annotations

import sys


def send_ops_alert(text: str) -> bool:
    """Deliver an ops alert to the registered Teams conversation. Returns delivered?"""
    message = f"⚠️ Lexi ops alert: {text}"
    try:
        import asyncio

        from app.bot.teams_conversation_store import teams_delivery_ready
        from app.bot.teams_publisher import push_approval_text_to_teams

        if teams_delivery_ready():
            asyncio.run(push_approval_text_to_teams(message))
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"[ops-alert] Teams delivery failed: {exc}", file=sys.stderr, flush=True)
    print(f"[ops-alert] {message}", file=sys.stderr, flush=True)
    return False


if __name__ == "__main__":  # python -m app.ops.health_alert "message"
    send_ops_alert(" ".join(sys.argv[1:]) or "unspecified alert")

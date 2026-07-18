"""Run a Teams Adaptive Card submit in Lexi's own venv (stdin JSON → stdout JSON).

Hermes gateway calls this via subprocess so card Send/Discard/Save uses Lexi deps
(composio, botbuilder, etc.) instead of the slimmer Hermes Python environment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# Hermes subprocess inherits ~/.hermes/.env — override so Lexi connection IDs match this API key.
_LEXI_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_LEXI_ENV, override=True)
load_dotenv(override=True)


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        payload = data.get("payload") or {}
        authorized_by = str(data.get("authorized_by") or "kory")
        from app.teams.commands import handle_teams_card_submit

        result = handle_teams_card_submit(payload, authorized_by=authorized_by)
        message = str(result.get("message") or "Done.")
        if not result.get("ok"):
            message = f"⚠️ {message}"
        sys.stdout.write(json.dumps({"ok": bool(result.get("ok")), "message": message, "result": result}))
        return 0
    except Exception as exc:
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "message": f"⚠️ Lexi could not process that card action: {exc}",
                    "error": str(exc),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

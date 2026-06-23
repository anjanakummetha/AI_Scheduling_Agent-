"""Create or confirm the Outlook new-message trigger on Kory's inbox."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from composio import Composio
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings

TRIGGER_SLUG = "OUTLOOK_MESSAGE_TRIGGER"
WEBHOOK_PATH = "/webhooks/composio"


def main() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("COMPOSIO_API_KEY")
    if not api_key:
        raise SystemExit("COMPOSIO_API_KEY is missing.")

    connection_id = (settings.kory_composio_connection_id or "").strip()
    if not connection_id:
        raise SystemExit("KORY_COMPOSIO_CONNECTION_ID is missing — trigger must watch Kory's inbox.")

    composio = Composio(api_key=api_key)
    trigger = composio.triggers.create(
        slug=TRIGGER_SLUG,
        connected_account_id=connection_id,
        trigger_config={},
    )
    trigger_id = getattr(trigger, "trigger_id", None) or getattr(trigger, "id", None)
    print(f"{TRIGGER_SLUG} ready for connection_id={connection_id}. trigger_id={trigger_id}")

    public = (os.getenv("LEXI_WEBHOOK_PUBLIC_URL") or "").strip().rstrip("/")
    print("\n--- Webhook ingress (production) ---")
    if public:
        target = public if public.endswith(WEBHOOK_PATH) else f"{public}{WEBHOOK_PATH}"
        print(f"Lexi endpoint: {target}")
        print("Register with Composio (once per stable URL):")
        print(f"  .venv/bin/python scripts/register_composio_webhook.py --url {public}")
    else:
        print("Set LEXI_WEBHOOK_PUBLIC_URL=https://your-stable-host")
        print("Then: .venv/bin/python scripts/register_composio_webhook.py")
    print("Verify: .venv/bin/python scripts/verify_webhook_ingress.py\n")


if __name__ == "__main__":
    main()

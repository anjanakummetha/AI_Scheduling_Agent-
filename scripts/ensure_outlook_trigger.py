"""Create or confirm the Outlook new-message trigger for the demo account."""

from __future__ import annotations

import os

from composio import Composio
from dotenv import load_dotenv


TRIGGER_SLUG = "OUTLOOK_MESSAGE_TRIGGER"


def main() -> None:
    load_dotenv(".env")
    api_key = os.getenv("COMPOSIO_API_KEY")
    user_id = os.getenv("COMPOSIO_USER_ID", "kory")
    if not api_key:
        raise SystemExit("COMPOSIO_API_KEY is missing.")

    composio = Composio(api_key=api_key)
    trigger = composio.triggers.create(
        slug=TRIGGER_SLUG,
        user_id=user_id,
        trigger_config={},
    )
    trigger_id = getattr(trigger, "trigger_id", None) or getattr(trigger, "id", None)
    print(f"{TRIGGER_SLUG} ready for user_id={user_id}. trigger_id={trigger_id}")


if __name__ == "__main__":
    main()

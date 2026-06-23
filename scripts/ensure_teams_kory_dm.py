#!/usr/bin/env python3
"""Open (or refresh) Kory's 1:1 Teams DM with Lexi and send a visible ping.

Use when proactive cards return HTTP 201 but nothing appears in Teams —
usually a stale conversation_id. This calls Bot Framework createConversation
for Kory's AAD object id, saves data/teams_conversation.json, and posts a ping.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(Path.home() / ".hermes" / ".env", override=False)


async def _create_conversation(
    *,
    app_id: str,
    app_secret: str,
    tenant_id: str,
    user_aad_id: str,
    service_url: str,
) -> tuple[str, str]:
    import aiohttp
    from botframework.connector.auth import MicrosoftAppCredentials

    creds = MicrosoftAppCredentials(app_id, app_secret, channel_auth_tenant=tenant_id)
    token_result = creds.get_access_token()
    if asyncio.iscoroutine(token_result):
        token = await token_result
    else:
        token = token_result
    if not token:
        raise RuntimeError("Bot Framework token request failed")

    if not service_url.endswith("/"):
        service_url += "/"

    payload = {
        "channelData": {"tenant": {"id": tenant_id}},
        "members": [{"id": f"29:{user_aad_id}"}],
        "bot": {"id": f"28:{app_id}", "name": "Lexi"},
        "isGroup": False,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{service_url}v3/conversations",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"createConversation failed ({resp.status}): {body[:500]}")
            data = json.loads(body)
    conversation_id = str(data.get("id") or "").strip()
    if not conversation_id:
        raise RuntimeError(f"createConversation missing id: {data}")
    return conversation_id, service_url


async def _send_ping(
    *,
    app_id: str,
    app_secret: str,
    tenant_id: str,
    conversation_id: str,
    service_url: str,
    text: str,
) -> None:
    from botbuilder.core import MessageFactory
    from botbuilder.schema import Activity, ActivityTypes
    from botframework.connector.aio import ConnectorClient
    from botframework.connector.auth import MicrosoftAppCredentials

    creds = MicrosoftAppCredentials(app_id, app_secret, channel_auth_tenant=tenant_id)
    activity = Activity(
        type=ActivityTypes.message,
        text=text,
        text_format="markdown",
    )
    async with ConnectorClient(creds, service_url) as client:
        await client.conversations.send_to_conversation(conversation_id, activity)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user-aad-id",
        default=os.getenv("TEAMS_ALLOWED_USERS", "").split(",")[0].strip(),
        help="Kory's Azure AD object id (default: first TEAMS_ALLOWED_USERS)",
    )
    parser.add_argument("--ping-only", action="store_true", help="Skip create; ping stored ref")
    args = parser.parse_args()

    app_id = os.getenv("TEAMS_CLIENT_ID", "").strip()
    app_secret = os.getenv("TEAMS_CLIENT_SECRET", "").strip()
    tenant_id = os.getenv("TEAMS_TENANT_ID", "").strip()
    user_aad = (args.user_aad_id or "").strip()
    service_url = (
        os.getenv("TEAMS_SERVICE_URL", "").strip()
        or f"https://smba.trafficmanager.net/amer/{tenant_id}/"
        if tenant_id
        else "https://smba.trafficmanager.net/amer/"
    )

    if not all([app_id, app_secret, tenant_id, user_aad]):
        print("Missing TEAMS_CLIENT_ID/SECRET/TENANT_ID or user AAD id.", file=sys.stderr)
        return 1

    from app.bot.teams_conversation_store import load_conversation_reference, save_conversation_reference

    ping_text = (
        "**Lexi is connected** (local Mac test)\n\n"
        "If you see this in your **Lexi** 1:1 chat, proactive cards will land here.\n"
        "Reply `help` to list commands.\n\n"
        "_Next: send your delegation email with lexi@ CC'd._"
    )

    async def run() -> None:
        if args.ping_only:
            ref = load_conversation_reference()
            if not ref:
                raise RuntimeError("No conversation reference — run without --ping-only")
            conversation_id = ref["conversation_id"]
            service_url_use = ref.get("service_url") or service_url
        else:
            conversation_id, service_url_use = await _create_conversation(
                app_id=app_id,
                app_secret=app_secret,
                tenant_id=tenant_id,
                user_aad_id=user_aad,
                service_url=service_url,
            )
            record = save_conversation_reference(
                conversation_id,
                service_url=service_url_use,
                tenant_id=tenant_id,
                bot_id=f"28:{app_id}",
            )
            print(json.dumps(record, indent=2))

        await _send_ping(
            app_id=app_id,
            app_secret=app_secret,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            service_url=service_url_use,
            text=ping_text,
        )
        print(f"\nPing sent to conversation {conversation_id[:40]}...")

    try:
        asyncio.run(run())
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
